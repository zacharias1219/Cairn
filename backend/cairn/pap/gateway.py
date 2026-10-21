"""PAP gateway (F8): a permissioned route for customers' personal agents.

PAP (the Personal Agent Protocol) is a draft standard, so this is a thin
adapter behind one interface: the endpoints below map onto the OAuth-based
flow described in the protocol's announcement (guest sessions for read-only
questions; signed-in sessions after the customer consents and chooses read
or write scope). When the v0.1 specification is mapped, only this module
and its routes change.

Everything an outside agent sends is untrusted input: it goes through the
same supervisor and rule engine as any customer, every action is logged
with the agent's identity, the scope granted, the consent record and the
outcome, and each agent has its own rate limit and allow/deny status.
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import secrets
import time
import uuid
from dataclasses import dataclass

from psycopg import AsyncConnection

from cairn.db.core import Jsonb, fetch_all, fetch_one, tenant_tx
from cairn.security.crypto import sha256

PAP_VERSION = "0.1-draft"
GUEST_TTL = dt.timedelta(hours=1)
SIGNED_IN_TTL = dt.timedelta(days=30)
DEFAULT_RATE = 10


class PapError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


# ----------------------------------------------------------- rate limits

class TokenBucket:
    def __init__(self) -> None:
        self.buckets: dict[str, tuple[float, float]] = {}

    def take(self, key: str, per_minute: int) -> bool:
        if per_minute <= 0:
            return False
        now = time.monotonic()
        tokens, last = self.buckets.get(key, (float(per_minute), now))
        tokens = min(float(per_minute), tokens + (now - last) * per_minute / 60.0)
        if tokens < 1:
            self.buckets[key] = (tokens, now)
            return False
        self.buckets[key] = (tokens - 1, now)
        return True


BUCKETS = TokenBucket()


async def check_agent(conn: AsyncConnection, tenant_id: uuid.UUID, identity: str) -> dict:
    if not identity or not identity.startswith("agent://"):
        raise PapError(400, "invalid_agent", "agent identity must be an agent:// URI")
    row = await fetch_one(conn, "select * from pap_agents where agent_identity=%s", (identity,))
    if row and row["status"] == "deny":
        await _log_refusal(tenant_id, identity, "session.denied", "denied_agent")
        raise PapError(403, "agent_denied", "this agent is not allowed to act on this business")
    limit = row["rate_limit_per_min"] if row else DEFAULT_RATE
    if not BUCKETS.take(f"{tenant_id}:{identity}", limit):
        await _log_refusal(tenant_id, identity, "rate_limited", "rate_limited")
        raise PapError(429, "rate_limited", f"rate limit of {limit} requests per minute exceeded")
    return row or {"agent_identity": identity, "display_name": identity, "status": "allow", "rate_limit_per_min": limit}


async def _log_refusal(tenant_id, identity: str, action: str, outcome: str) -> None:
    # Its own transaction: the caller's rolls back when the refusal is raised.
    async with tenant_tx(tenant_id) as c:
        await log_action(c, tenant_id, None, None, identity, action, "none", False, outcome, {})


async def log_action(conn, tenant_id, session_id, customer_id, identity, action, scope, allowed, outcome, detail):
    await conn.execute("""
        insert into pap_actions (tenant_id, session_id, customer_id, agent_identity, action, scope_required, allowed,
          outcome, detail)
        values (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (tenant_id, session_id, customer_id, identity, action, scope, allowed, outcome, Jsonb(detail)))


# ---------------------------------------------------------- manifest

async def manifest(tenant_id: uuid.UUID, slug: str, base_url: str) -> dict:
    async with tenant_tx(tenant_id) as conn:
        tenant = await fetch_one(conn, "select name from tenants where id=%s", (tenant_id,))
        tools = await fetch_all(conn, "select name, title, description, input_schema, is_write, risk_tier "
                                      "from tools where enabled and pap_exposed order by name")
    root = f"{base_url}/pap/v1/{slug}"
    return {
        "protocol": "pap", "version": PAP_VERSION,
        "business": {"name": tenant["name"], "id": slug},
        "authentication": {
            "type": "oauth2", "flow": "authorization_code", "pkce": "S256",
            "authorization_endpoint": f"{root}/authorize", "token_endpoint": f"{root}/token",
            "scopes": {"read": "Ask questions and read your orders and membership",
                       "write": "Make changes you ask for, such as refunds and cancellations"},
        },
        "guest_access": {"endpoint": f"{root}/sessions", "scopes": ["read"]},
        "routes": {
            "agent": {"endpoint": f"{root}/messages", "description": "Talk to the business's own supervised agent"},
            "actions": {"endpoint": f"{root}/actions/{{capability}}", "transport": "MCP-compatible JSON"},
            "website": base_url,
        },
        "capabilities": [
            {"name": t["name"], "title": t["title"], "description": t["description"],
             "scope": "write" if t["is_write"] else "read", "input_schema": t["input_schema"],
             "may_require_approval": t["is_write"]}
            for t in tools
        ],
        "policies": {"untrusted_input": True, "every_action_logged": True,
                     "rate_limit_default_per_minute": DEFAULT_RATE},
    }


# ---------------------------------------------------------- sessions

@dataclass
class Session:
    id: uuid.UUID
    tenant_id: uuid.UUID
    agent_identity: str
    customer_id: uuid.UUID | None
    mode: str
    scopes: list[str]
    conversation_id: uuid.UUID | None
    customer_email: str | None


async def create_guest(tenant_id: uuid.UUID, identity: str) -> dict:
    token = "pap_" + secrets.token_urlsafe(32)
    async with tenant_tx(tenant_id) as conn:
        await check_agent(conn, tenant_id, identity)
        row = await fetch_one(conn, """
            insert into pap_sessions (tenant_id, agent_identity, mode, scopes, token_hash, expires_at)
            values (%s,%s,'guest',%s,%s,%s) returning id, expires_at""",
            (tenant_id, identity, ["read"], sha256(token), dt.datetime.now(dt.timezone.utc) + GUEST_TTL))
        await log_action(conn, tenant_id, row["id"], None, identity, "session.guest", "read", True, "created", {})
    return {"access_token": token, "token_type": "bearer", "mode": "guest", "scope": "read",
            "expires_at": row["expires_at"], "session_id": str(row["id"])}


async def authorize(tenant_id: uuid.UUID, identity: str, scope: str, redirect_uri: str, code_challenge: str,
                    state: str | None) -> uuid.UUID:
    scopes = sorted({s for s in scope.split() if s in ("read", "write")} or {"read"})
    if not redirect_uri.startswith(("https://", "http://localhost", "http://127.0.0.1")):
        raise PapError(400, "invalid_redirect", "redirect_uri must be https")
    if not code_challenge:
        raise PapError(400, "pkce_required", "code_challenge (S256) is required")
    async with tenant_tx(tenant_id) as conn:
        await check_agent(conn, tenant_id, identity)
        row = await fetch_one(conn, """
            insert into pap_sessions (tenant_id, agent_identity, mode, scopes, code_challenge, redirect_uri,
              consent, expires_at)
            values (%s,%s,'pending_consent',%s,%s,%s,%s,%s) returning id""",
            (tenant_id, identity, scopes, code_challenge, redirect_uri, Jsonb({"state": state, "requested": scopes}),
             dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=15)))
    return row["id"]


async def consent(tenant_id: uuid.UUID, session_id: uuid.UUID, *, customer_id: uuid.UUID, granted: list[str],
                  method: str) -> tuple[str, dict]:
    """Record the customer's consent and issue a one-time authorization code."""
    code = "papc_" + secrets.token_urlsafe(24)
    granted = sorted(set(granted) & {"read", "write"}) or ["read"]
    async with tenant_tx(tenant_id) as conn:
        s = await fetch_one(conn, "select * from pap_sessions where id=%s and mode='pending_consent'", (session_id,))
        if s is None or s["expires_at"] < dt.datetime.now(dt.timezone.utc):
            raise PapError(400, "invalid_request", "consent request expired or not found")
        granted = [g for g in granted if g in s["scopes"]] or ["read"]
        record = {**(s["consent"] or {}), "granted": granted, "granted_at": dt.datetime.now(dt.timezone.utc),
                  "method": method}
        await conn.execute("""
            update pap_sessions set customer_id=%s, scopes=%s, consent=%s, code_hash=%s,
              expires_at = now() + interval '5 minutes' where id=%s""",
            (customer_id, granted, Jsonb(record), sha256(code), session_id))
        await log_action(conn, tenant_id, session_id, customer_id, s["agent_identity"], "consent.granted",
                         " ".join(granted), True, "granted", {"scopes": granted, "method": method})
    return code, {"redirect_uri": s["redirect_uri"], "state": (s["consent"] or {}).get("state")}


def _s256(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


async def exchange(tenant_id: uuid.UUID, code: str, verifier: str, identity: str) -> dict:
    token = "pap_" + secrets.token_urlsafe(32)
    async with tenant_tx(tenant_id) as conn:
        s = await fetch_one(conn, "select * from pap_sessions where code_hash=%s", (sha256(code),))
        if s is None or s["expires_at"] < dt.datetime.now(dt.timezone.utc) or s["agent_identity"] != identity:
            raise PapError(400, "invalid_grant", "authorization code is invalid or expired")
        if _s256(verifier) != s["code_challenge"]:
            raise PapError(400, "invalid_grant", "PKCE verification failed")
        exp = dt.datetime.now(dt.timezone.utc) + SIGNED_IN_TTL
        await conn.execute("""
            update pap_sessions set mode='signed_in', token_hash=%s, code_hash=null, expires_at=%s where id=%s""",
            (sha256(token), exp, s["id"]))
        await log_action(conn, tenant_id, s["id"], s["customer_id"], identity, "session.signed_in",
                         " ".join(s["scopes"]), True, "created", {})
    return {"access_token": token, "token_type": "bearer", "mode": "signed_in", "scope": " ".join(s["scopes"]),
            "expires_at": exp, "session_id": str(s["id"])}


async def session_from_token(tenant_id: uuid.UUID, token: str) -> Session:
    async with tenant_tx(tenant_id) as conn:
        s = await fetch_one(conn, """
            select p.*, c.email as customer_email from pap_sessions p left join customers c on c.id = p.customer_id
            where p.token_hash=%s""", (sha256(token or ""),))
        if s is None or s["revoked_at"] or s["expires_at"] < dt.datetime.now(dt.timezone.utc) or s["mode"] == "pending_consent":
            raise PapError(401, "invalid_token", "session token is invalid, expired or revoked")
        await check_agent(conn, tenant_id, s["agent_identity"])
    return Session(s["id"], tenant_id, s["agent_identity"], s["customer_id"], s["mode"], list(s["scopes"]),
                   s["conversation_id"], s["customer_email"])


async def revoke(tenant_id: uuid.UUID, session_id: uuid.UUID, by: str) -> None:
    async with tenant_tx(tenant_id) as conn:
        s = await fetch_one(conn, "update pap_sessions set revoked_at=now() where id=%s returning *", (session_id,))
        if s:
            await log_action(conn, tenant_id, session_id, s["customer_id"], s["agent_identity"], "session.revoked",
                             "none", True, "revoked", {"by": by})
