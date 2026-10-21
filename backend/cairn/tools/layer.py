"""The tool layer: how the agent acts in a customer's systems, safely (F5).

Every external action is an MCP tool with strict input and output schemas.
On each call, in order:

1. arguments are validated against the tool's input schema, whatever the
   model asked for;
2. the rule engine evaluates the call (no model on that path);
3. high-tier tools, and any call a rule marks ``require_approval``, wait
   for a named human approver;
4. write calls carry an idempotency key, so a retry never acts twice;
5. the call is recorded with input, output, status and approver.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx
import jsonschema
from psycopg import AsyncConnection

from cairn.db.core import Jsonb, fetch_all, fetch_one
from cairn.rules.engine import Decision, Rule, evaluate
from cairn.security.crypto import unseal
from cairn.tools import sandbox_commerce
from cairn.tools.sandbox_commerce import SANDBOX_URL


@dataclass
class ToolSpec:
    name: str
    title: str
    description: str
    input_schema: dict
    output_schema: dict
    risk_tier: str
    requires_approval: bool
    is_write: bool
    server_url: str
    pap_exposed: bool = False
    integration: str = ""
    credential: tuple[bytes, bytes] | None = None

    @classmethod
    def from_row(cls, r: dict) -> "ToolSpec":
        cred = None
        if r.get("credential_ciphertext"):
            cred = (bytes(r["credential_ciphertext"]), bytes(r["credential_wrapped_key"]))
        return cls(
            name=r["name"], title=r["title"], description=r["description"],
            input_schema=r["input_schema"], output_schema=r["output_schema"],
            risk_tier=r["risk_tier"], requires_approval=r["requires_approval"],
            is_write=r["is_write"], server_url=r["server_url"], pap_exposed=r["pap_exposed"],
            integration=r["integration"], credential=cred,
        )

    @property
    def needs_human(self) -> bool:
        return self.risk_tier == "high" or self.requires_approval

    def prompt_view(self) -> dict:
        return {"name": self.name, "description": self.description, "input_schema": self.input_schema,
                "writes": self.is_write, "risk_tier": self.risk_tier}


@dataclass
class ToolOutcome:
    status: str  # succeeded | failed | refused | pending_approval | denied
    call_id: str | None
    output: dict | None = None
    error: str | None = None
    decision: Decision | None = None
    reason: str = ""
    latency_ms: int = 0
    deduplicated: bool = False
    extra: dict = field(default_factory=dict)


async def load_tools(conn: AsyncConnection) -> dict[str, ToolSpec]:
    rows = await fetch_all(conn, "select * from tools where enabled order by name")
    return {r["name"]: ToolSpec.from_row(r) for r in rows}


def idempotency_key(scope: str, tool: str, args: dict) -> str:
    canon = json.dumps(args, sort_keys=True, separators=(",", ":"))
    return "idem_" + hashlib.sha256(f"{scope}|{tool}|{canon}".encode()).hexdigest()[:40]


class SchemaError(ValueError):
    pass


def validate_args(spec: ToolSpec, args: dict) -> None:
    try:
        jsonschema.validate(args, spec.input_schema)
    except jsonschema.ValidationError as e:
        raise SchemaError(f"{spec.name}: {e.message}") from e


async def _record_refusal(conn, tenant_id, spec: ToolSpec, args, key, ids: dict, reason: str, source: str):
    row = await fetch_one(conn, """
        insert into tool_calls (tenant_id, conversation_id, customer_id, turn_id, tool_name, risk_tier,
          input, idempotency_key, status, error, source, completed_at)
        values (%s,%s,%s,%s,%s,%s,%s,%s,'refused',%s,%s,now())
        on conflict (tenant_id, idempotency_key) do update set error = excluded.error
        returning id""",
        (tenant_id, ids.get("conversation_id"), ids.get("customer_id"), ids.get("turn_id"), spec.name,
         spec.risk_tier, Jsonb(args), key + ":refused:" + uuid.uuid4().hex[:6], reason, source))
    return str(row["id"]) if row else None


async def request_tool(
    conn: AsyncConnection, tenant_id: uuid.UUID, spec: ToolSpec, args: dict, *,
    rules: list[Rule], rule_context: dict, ids: dict, scope: str, source: str = "agent",
) -> ToolOutcome:
    """Validate, check rules and either run the call or park it for approval."""
    try:
        validate_args(spec, args)
    except SchemaError as e:
        cid = await _record_refusal(conn, tenant_id, spec, args, idempotency_key(scope, spec.name, args),
                                    ids, f"schema: {e}", source)
        return ToolOutcome("refused", cid, error=str(e), reason="schema_invalid")

    decision = evaluate(rules, "tool_call", {**rule_context, "tool": spec.name, "args": args}, tool=spec.name)
    key = idempotency_key(scope, spec.name, args)

    if decision.blocked:
        msg = "; ".join(f.message or f.name for f in decision.firings if f.outcome == "block")
        cid = await _record_refusal(conn, tenant_id, spec, args, key, ids, f"rule: {msg}", source)
        return ToolOutcome("refused", cid, error=msg, decision=decision, reason="rule_block")

    existing = await fetch_one(conn, "select * from tool_calls where idempotency_key=%s", (key,))
    if existing and existing["status"] == "succeeded":
        return ToolOutcome("succeeded", str(existing["id"]), output=existing["output"], decision=decision,
                           deduplicated=True)
    if existing and existing["status"] == "pending_approval":
        return ToolOutcome("pending_approval", str(existing["id"]), decision=decision, reason="awaiting_approval")
    if existing and existing["status"] == "denied":
        return ToolOutcome("denied", str(existing["id"]), decision=decision, reason=existing["decision_note"] or "")

    if spec.needs_human or decision.needs_approval:
        row = await fetch_one(conn, """
            insert into tool_calls (tenant_id, conversation_id, customer_id, turn_id, tool_name, risk_tier,
              input, idempotency_key, status, source)
            values (%s,%s,%s,%s,%s,%s,%s,%s,'pending_approval',%s)
            on conflict (tenant_id, idempotency_key) do update set status = 'pending_approval'
            returning id""",
            (tenant_id, ids.get("conversation_id"), ids.get("customer_id"), ids.get("turn_id"), spec.name,
             spec.risk_tier, Jsonb(args), key, source))
        reason = "high_risk_tool" if spec.needs_human else "rule_requires_approval"
        return ToolOutcome("pending_approval", str(row["id"]), decision=decision, reason=reason)

    return await execute(conn, tenant_id, spec, args, key=key, ids=ids, source=source, decision=decision)


async def execute(
    conn: AsyncConnection, tenant_id: uuid.UUID, spec: ToolSpec, args: dict, *, key: str, ids: dict,
    source: str = "agent", decision: Decision | None = None,
) -> ToolOutcome:
    """Run a call. Refuses a human-gated call that has no recorded approval."""
    row = await fetch_one(conn, "select * from tool_calls where idempotency_key=%s", (key,))
    if row and row["status"] == "succeeded":
        return ToolOutcome("succeeded", str(row["id"]), output=row["output"], decision=decision, deduplicated=True)
    gated = spec.needs_human or (decision is not None and decision.needs_approval)
    if gated and not (row and row["status"] == "approved" and row["approver_label"]):
        cid = await _record_refusal(conn, tenant_id, spec, args, key, ids,
                                    "approval required: no approver recorded", source)
        return ToolOutcome("refused", cid, error="approval required", reason="missing_approval")

    if row is None:
        row = await fetch_one(conn, """
            insert into tool_calls (tenant_id, conversation_id, customer_id, turn_id, tool_name, risk_tier,
              input, idempotency_key, status, source)
            values (%s,%s,%s,%s,%s,%s,%s,%s,'approved',%s) returning *""",
            (tenant_id, ids.get("conversation_id"), ids.get("customer_id"), ids.get("turn_id"), spec.name,
             spec.risk_tier, Jsonb(args), key, source))

    t0 = time.perf_counter()
    try:
        output, is_error = await call_mcp(spec, args, key, tenant_id)
        latency = int((time.perf_counter() - t0) * 1000)
        if not is_error:
            jsonschema.validate(output, spec.output_schema)
    except Exception as e:  # noqa: BLE001 - every failure is recorded, then surfaced
        latency = int((time.perf_counter() - t0) * 1000)
        await conn.execute(
            "update tool_calls set status='failed', error=%s, latency_ms=%s, completed_at=now() where id=%s",
            (f"{type(e).__name__}: {e}"[:500], latency, row["id"]))
        return ToolOutcome("failed", str(row["id"]), error=str(e), decision=decision, latency_ms=latency)

    status = "failed" if is_error else "succeeded"
    await conn.execute(
        "update tool_calls set status=%s, output=%s, error=%s, latency_ms=%s, completed_at=now() where id=%s",
        (status, Jsonb(output), output.get("error") if is_error else None, latency, row["id"]))
    return ToolOutcome(status, str(row["id"]), output=output, error=output.get("error") if is_error else None,
                       decision=decision, latency_ms=latency)


async def call_mcp(spec: ToolSpec, args: dict, key: str, tenant_id) -> tuple[dict, bool]:
    req = {"jsonrpc": "2.0", "id": uuid.uuid4().hex, "method": "tools/call",
           "params": {"name": spec.name, "arguments": args, "_meta": {"idempotency_key": key}}}
    if spec.server_url == SANDBOX_URL:
        resp = sandbox_commerce.current.get().handle(req)
    else:
        headers = {"content-type": "application/json", "accept": "application/json",
                   "idempotency-key": key}
        if spec.credential:
            token = unseal(spec.credential[0], spec.credential[1], tenant_id).decode()
            headers["authorization"] = f"Bearer {token}"
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(spec.server_url, json=req, headers=headers)
            r.raise_for_status()
            resp = r.json()
    if "error" in resp:
        raise RuntimeError(resp["error"].get("message", "MCP error"))
    result = resp["result"]
    out = result.get("structuredContent")
    if out is None:
        text = "".join(c.get("text", "") for c in result.get("content", []) if c.get("type") == "text")
        out = json.loads(text) if text.strip().startswith("{") else {"text": text}
    return out, bool(result.get("isError"))
