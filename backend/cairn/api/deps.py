"""Authentication, roles and the admin audit log for the console API."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request
from psycopg import AsyncConnection

from cairn.db.core import Jsonb, anon_tx, fetch_one
from cairn.security.crypto import read_session, sha256

ROLE_RANK = {"viewer": 0, "builder": 1, "admin": 2}
SESSION_COOKIE = "cairn_session"


@dataclass
class Principal:
    tenant_id: uuid.UUID
    user_id: uuid.UUID | None
    role: str
    label: str
    kind: str  # "user" | "api_key"
    scopes: tuple[str, ...] = ()


async def current_principal(request: Request) -> Principal:
    token = request.cookies.get(SESSION_COOKIE)
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
    if not token:
        raise HTTPException(401, "not signed in")
    if token.startswith("ck_"):
        async with anon_tx() as conn:
            row = await fetch_one(conn, "select * from auth_api_key(%s)", (sha256(token),))
        if row is None:
            raise HTTPException(401, "invalid API key")
        scopes = tuple(row["scopes"])
        role = "admin" if "admin" in scopes else "builder" if "write" in scopes else "viewer"
        return Principal(row["tenant_id"], None, role, f"api-key:{token[:10]}", "api_key", scopes)
    claims = read_session(token)
    if not claims:
        raise HTTPException(401, "session expired")
    return Principal(uuid.UUID(claims["tid"]), uuid.UUID(claims["sub"]), claims["role"],
                     claims.get("email", claims["sub"]), "user")


def role(minimum: str):
    async def dep(p: Principal = Depends(current_principal)) -> Principal:
        if ROLE_RANK[p.role] < ROLE_RANK[minimum]:
            raise HTTPException(403, f"requires the {minimum} role")
        return p
    return dep


async def audit(conn: AsyncConnection, p: Principal, action: str, target: str | None = None,
                detail: dict | None = None) -> None:
    await conn.execute("""
        insert into admin_audit (tenant_id, actor_id, actor_label, action, target, detail)
        values (%s,%s,%s,%s,%s,%s)""", (p.tenant_id, p.user_id, p.label, action, target, Jsonb(detail or {})))
