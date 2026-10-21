"""The approvals queue for high-tier actions (F5, F11)."""

from __future__ import annotations

import uuid

from cairn.db.core import fetch_one, tenant_tx
from cairn.engine.orchestrator import Emit, TurnResult, continue_after_approval


class ApprovalError(ValueError):
    pass


async def decide(tenant_id: uuid.UUID, call_id: uuid.UUID, *, approve: bool, approver_id: uuid.UUID | None,
                 approver_label: str, note: str | None = None, emit: Emit | None = None) -> TurnResult:
    async with tenant_tx(tenant_id) as conn:
        call = await fetch_one(conn, "select * from tool_calls where id=%s for update", (call_id,))
        if call is None:
            raise ApprovalError("not found")
        if call["status"] != "pending_approval":
            raise ApprovalError(f"already {call['status']}")
        await conn.execute("""
            update tool_calls set status=%s, approver_id=%s, approver_label=%s, decided_at=now(), decision_note=%s
            where id=%s""",
            ("approved" if approve else "denied", approver_id, approver_label, note, call_id))
        await conn.execute("""
            insert into admin_audit (tenant_id, actor_id, actor_label, action, target, detail)
            values (%s,%s,%s,%s,%s,%s)""",
            (tenant_id, approver_id, approver_label, "approval.approve" if approve else "approval.deny",
             f"tool_call:{call_id}", {"tool": call["tool_name"], "risk_tier": call["risk_tier"], "note": note}))
    return await continue_after_approval(tenant_id, call_id, emit=emit)
