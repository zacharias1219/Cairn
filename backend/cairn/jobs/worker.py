"""Background worker: outcome finalization, memory summaries, erasure, handoff delivery."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid

import httpx

from cairn.config import get_settings
from cairn.db.core import fetch_all, fetch_one, system_tx, tenant_tx
from cairn.jobs import queue
from cairn.memory.store import erase_customer, remember
from cairn.outcomes.engine import close_conversation, close_idle, finalize_due

log = logging.getLogger("cairn.worker")


async def _deliver_handoff(tenant_id: uuid.UUID, payload: dict) -> None:
    async with tenant_tx(tenant_id) as conn:
        h = await fetch_one(conn, "select * from handoffs where id=%s", (payload["handoff_id"],))
        url = (payload.get("webhook_url") or "")
    if not h:
        return
    status = "delivered (sandbox)"
    if url:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(url, json={"reason": h["reason"], "reason_code": h["reason_code"],
                                             "conversation_id": str(h["conversation_id"]),
                                             "transcript": h["transcript"]})
            status = f"delivered ({r.status_code})"
    async with tenant_tx(tenant_id) as conn:
        await conn.execute("update handoffs set delivery_status=%s where id=%s", (status, h["id"]))


async def handle(job: dict) -> None:
    tid = job["tenant_id"]
    p = job["payload"] or {}
    kind = job["kind"]
    if kind == "close_conversation":
        await close_conversation(tid, uuid.UUID(p["conversation_id"]), p.get("reason", "ended"))
        await remember(tid, uuid.UUID(p["conversation_id"]))
    elif kind == "remember":
        await remember(tid, uuid.UUID(p["conversation_id"]))
    elif kind == "erase_customer":
        await erase_customer(tid, uuid.UUID(p["customer_id"]), p.get("requested_by", "system"),
                             uuid.UUID(p["request_id"]) if p.get("request_id") else None)
    elif kind == "deliver_handoff":
        await _deliver_handoff(tid, p)
    else:
        raise ValueError(f"unknown job kind {kind}")


async def periodic() -> None:
    """Housekeeping across tenants: close idle chats, finalize outcomes."""
    async with system_tx() as conn:
        tenants = await fetch_all(conn, "select id from tenants")
    for t in tenants:
        closed_ids = []
        async with tenant_tx(t["id"]) as conn:
            closed_ids = [r["id"] for r in await fetch_all(conn, """
                select id from conversations where ended_at is null and status in ('active','escalated')
                  and last_activity_at < now() - interval '30 minutes'""")]
        await close_idle(t["id"])
        for cid in closed_ids:
            try:
                await remember(t["id"], cid)
            except Exception:  # noqa: BLE001 - memory is best effort; the outcome is already recorded
                log.exception("memory summary failed")
        await finalize_due(t["id"])


async def run_forever(stop: asyncio.Event | None = None) -> None:
    s = get_settings()
    last_periodic = 0.0
    while not (stop and stop.is_set()):
        try:
            if time.time() - last_periodic > 60:
                last_periodic = time.time()
                await periodic()
            job = await queue.claim()
            if job is None:
                await asyncio.sleep(s.worker_poll_seconds)
                continue
            try:
                await handle(job)
                await queue.complete(job["id"])
            except Exception as e:  # noqa: BLE001 - recorded on the job and retried
                log.exception("job %s failed", job["id"])
                await queue.fail(job, f"{type(e).__name__}: {e}"[:500])
        except Exception:  # noqa: BLE001 - keep the worker alive through transient DB errors
            log.exception("worker loop error")
            await asyncio.sleep(2)
