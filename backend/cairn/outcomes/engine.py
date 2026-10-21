"""The outcome engine (F9): a hard, auditable definition of "resolved".

Every conversation ends as resolved, escalated, abandoned or failed. A
resolution becomes billable only after the re-contact window passes with
no repeat contact on the same issue and no negative customer signal. A
background job finalizes outcomes after the window closes, never at the
moment a chat ends. Each outcome stores the evidence behind it.
"""

from __future__ import annotations

import datetime as dt
import uuid

from psycopg import AsyncConnection

from cairn.db.core import Jsonb, fetch_all, fetch_one, tenant_tx
from cairn.engine.config import load_config

PLAN_RATES = {"pilot": 1.25, "growth": 1.00, "scale": 0.85}
PLAN_FEES = {"pilot": 1000.0, "growth": 2000.0, "scale": 0.0}
SUBSTANTIVE = {"order_status", "refund_request", "cancel_subscription", "change_address", "policy_question",
               "complaint"}


async def _classify(conn: AsyncConnection, conv: dict) -> tuple[str, dict]:
    turns = await fetch_all(conn, "select status, final_action, final_verdict from turns where conversation_id=%s "
                                  "order by seq", (conv["id"],))
    calls = await fetch_all(conn, "select tool_name, status, output, approver_label, created_at from tool_calls "
                                  "where conversation_id=%s order by created_at", (conv["id"],))
    verdicts = await fetch_all(conn, "select verdict, reason_code, attempt, created_at from supervisor_verdicts "
                                     "where conversation_id=%s order by created_at", (conv["id"],))
    signals = await fetch_all(conn, "select kind, value, created_at from customer_signals where conversation_id=%s",
                              (conv["id"],))
    state = conv["state"] or {}
    evidence = {
        "turns": len(turns),
        "intent": conv["intent"],
        "tool_results": [{"tool": c["tool_name"], "status": c["status"], "output": c["output"],
                          "approver": c["approver_label"], "at": c["created_at"]} for c in calls],
        "supervisor": {
            "verdicts": len(verdicts),
            "final": verdicts[-1]["verdict"] if verdicts else None,
            "interventions": [{"verdict": v["verdict"], "reason": v["reason_code"]} for v in verdicts
                              if v["verdict"] != "approve"],
        },
        "signals": [{"kind": s["kind"], "value": s["value"], "at": s["created_at"]} for s in signals],
    }
    if conv["status"] == "escalated" or any(t["final_action"] == "escalate" for t in turns):
        return "escalated", evidence
    if any(t["status"] == "failed" for t in turns) or any(c["status"] == "failed" for c in calls):
        return "failed", evidence
    if state.get("pending_action") or state.get("pending_approval") or state.get("awaiting"):
        return "abandoned", evidence
    if conv["intent"] in SUBSTANTIVE and any(t["final_verdict"] == "approve" for t in turns):
        return "resolved", evidence
    return "abandoned", evidence


async def close_conversation(tenant_id: uuid.UUID, conversation_id: uuid.UUID, reason: str = "ended") -> dict | None:
    async with tenant_tx(tenant_id) as conn:
        conv = await fetch_one(conn, "select * from conversations where id=%s for update", (conversation_id,))
        if conv is None:
            return None
        existing = await fetch_one(conn, "select * from outcomes where conversation_id=%s", (conversation_id,))
        if existing:
            return existing
        cfg, _ = await load_config(conn)
        window_h = int(cfg.get("outcomes", {}).get("recontact_window_hours", 72))
        typ, evidence = await _classify(conn, conv)
        ended = conv["last_activity_at"] or dt.datetime.now(dt.timezone.utc)
        await conn.execute("update conversations set ended_at=coalesce(ended_at, %s), end_reason=%s, "
                           "status = case when status='escalated' then status else 'closed' end where id=%s",
                           (ended, reason, conversation_id))
        row = await fetch_one(conn, """
            insert into outcomes (tenant_id, conversation_id, customer_id, channel, type, intent, issue_key, evidence,
              is_test, ended_at, window_ends_at)
            values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) returning *""",
            (tenant_id, conversation_id, conv["customer_id"], conv["channel"], typ, conv["intent"], conv["issue_key"],
             Jsonb(evidence), conv["is_test"], ended, ended + dt.timedelta(hours=window_h)))
    return row


async def finalize_due(tenant_id: uuid.UUID, now: dt.datetime | None = None) -> int:
    """Finalize every pending outcome whose re-contact window has closed."""
    now = now or dt.datetime.now(dt.timezone.utc)
    n = 0
    async with tenant_tx(tenant_id) as conn:
        tenant = await fetch_one(conn, "select plan, settings from tenants where id=%s", (tenant_id,))
        rate = PLAN_RATES.get(tenant["plan"], 1.0)
        cap = (tenant["settings"] or {}).get("monthly_cap_usd")
        due = await fetch_all(conn, "select * from outcomes where status='pending' and window_ends_at <= %s "
                                    "order by ended_at for update skip locked", (now,))
        for o in due:
            billable, reason = False, None
            if o["type"] != "resolved":
                reason = f"{o['type']} conversations are free"
            elif o["is_test"]:
                reason = "test conversation"
            else:
                repeat = None
                if o["customer_id"] and o["issue_key"]:
                    repeat = await fetch_one(conn, """
                        select id, started_at from conversations
                        where customer_id=%s and issue_key=%s and id<>%s and started_at > %s and started_at <= %s
                        order by started_at limit 1""",
                        (o["customer_id"], o["issue_key"], o["conversation_id"], o["ended_at"], o["window_ends_at"]))
                neg = await fetch_one(conn, """
                    select kind, value from customer_signals
                    where conversation_id=%s and (kind='negative' or (kind='csat' and value <= 2)) limit 1""",
                    (o["conversation_id"],))
                if repeat:
                    reason = "repeat contact on the same issue inside the window"
                    o["evidence"]["repeat_contact"] = {"conversation_id": repeat["id"], "at": repeat["started_at"]}
                elif neg:
                    reason = "negative customer signal"
                else:
                    billable = True
            amount = rate if billable else 0.0
            if billable and cap:
                spent = (await fetch_one(conn, """
                    select coalesce(sum(amount_usd),0) as s from outcomes
                    where billable and date_trunc('month', finalized_at) = date_trunc('month', %s::timestamptz)""",
                    (now,)))["s"]
                if float(spent) + amount > float(cap):
                    amount, reason = 0.0, "monthly spending cap reached"
            await conn.execute("""
                update outcomes set status='final', billable=%s, amount_usd=%s, nonbillable_reason=%s, evidence=%s,
                  finalized_at=%s where id=%s""",
                (billable, amount, reason, Jsonb(o["evidence"]), now, o["id"]))
            n += 1
    return n


async def close_idle(tenant_id: uuid.UUID, idle_minutes: int = 30) -> int:
    async with tenant_tx(tenant_id) as conn:
        rows = await fetch_all(conn, """
            select id from conversations
            where ended_at is null and status in ('active','escalated')
              and last_activity_at < now() - make_interval(mins => %s)""", (idle_minutes,))
    for r in rows:
        await close_conversation(tenant_id, r["id"], "inactivity")
    return len(rows)
