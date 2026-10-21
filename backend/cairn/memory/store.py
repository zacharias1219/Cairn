"""Erasable memory (F7, section 10).

Memory holds structured facts and short conversation summaries, each
pointing back to its source conversation and customer. Live account data
is fetched when needed and never kept here. Memory is used only for the
workflows the tenant enabled and only with the customer's consent.

Erasure is complete by construction: ``ERASURE_REGISTRY`` lists every table
that can hold a customer's data, a CI test fails if a table with a
customer_id column is missing from it, and one job deletes across every
store and returns a receipt with counts per store.
"""

from __future__ import annotations

import datetime as dt
import uuid

from psycopg import AsyncConnection

from cairn.db.core import Jsonb, fetch_all, fetch_one, tenant_tx, vec
from cairn.engine import skills
from cairn.engine.config import load_config
from cairn.knowledge.embed import embed
from cairn.llm.gateway import ModelCall, ModelGateway

BACKUP_RETENTION_DAYS = 30

# table -> how the erasure job handles it. "delete": rows removed;
# "anonymize": the customer reference and content are stripped but counts and
# timestamps stay (billing must remain auditable); "log": the erasure log itself.
ERASURE_REGISTRY: dict[str, str] = {
    "customers": "delete",
    "conversations": "delete",
    "messages": "delete",
    "chat_sessions": "delete",
    "customer_signals": "delete",
    "turns": "delete",
    "checkpoints": "delete",
    "turn_traces": "delete",
    "supervisor_verdicts": "delete",
    "rule_decisions": "delete",
    "tool_calls": "delete",
    "handoffs": "delete",
    "outbox_emails": "delete",
    "memory_items": "delete",
    "pap_sessions": "delete",
    "pap_actions": "delete",
    "outcomes": "anonymize",
    "erasure_requests": "log",
}

# In-process caches that may hold session data; erasure clears them too.
CACHE_HOOKS: list = []


async def remember(tenant_id: uuid.UUID, conversation_id: uuid.UUID) -> int:
    """Summarize a closed conversation into memory, if consent and config allow."""
    async with tenant_tx(tenant_id) as conn:
        conv = await fetch_one(conn, "select * from conversations where id=%s", (conversation_id,))
        if not conv or not conv["customer_id"] or conv["is_test"]:
            return 0
        cust = await fetch_one(conn, "select memory_consent from customers where id=%s", (conv["customer_id"],))
        cfg, _ = await load_config(conn)
        if not cust or not cust["memory_consent"] or not cfg.get("memory", {}).get("enabled", True):
            return 0
        if conv["intent"] not in set(cfg["memory"].get("workflows", [])):
            return 0
        msgs = await fetch_all(conn, "select role, content from messages where conversation_id=%s order by created_at",
                               (conversation_id,))
        calls = await fetch_all(conn, "select tool_name as tool, input as args, output, status from tool_calls "
                                      "where conversation_id=%s", (conversation_id,))
        outcome = await fetch_one(conn, "select type from outcomes where conversation_id=%s", (conversation_id,))
    facts = (conv["state"] or {}).get("facts", {})
    gw = ModelGateway(cfg.get("models"))
    res = await gw.run(ModelCall(
        step="summarize", system=skills.SUMMARY_SYSTEM,
        prompt=f"<untrusted kind=\"transcript\">{[{'role': m['role'], 'content': m['content']} for m in msgs]}</untrusted>",
        schema=skills.SUMMARY_SCHEMA,
        sandbox=lambda: skills.sandbox_summary(conv["intent"], facts, (outcome or {}).get("type", "open"),
                                               [dict(c) for c in calls]),
        max_tokens=1024))
    items = [("summary", res.data["summary"])] + [("fact", f) for f in res.data["facts"]]
    async with tenant_tx(tenant_id) as conn:
        for kind, content in items:
            await conn.execute("""
                insert into memory_items (tenant_id, customer_id, kind, content, embedding, source_conversation_id)
                values (%s,%s,%s,%s,%s::vector,%s)""",
                (tenant_id, conv["customer_id"], kind, content, vec(embed(content)), conversation_id))
    return len(items)


async def export_customer(tenant_id: uuid.UUID, customer_id: uuid.UUID) -> dict:
    async with tenant_tx(tenant_id) as conn:
        cust = await fetch_one(conn, "select * from customers where id=%s", (customer_id,))
        if cust is None:
            raise LookupError("customer not found")
        convs = await fetch_all(conn, "select id, channel, status, intent, started_at, ended_at from conversations "
                                      "where customer_id=%s order by started_at", (customer_id,))
        for c in convs:
            c["messages"] = await fetch_all(conn, "select role, content, created_at from messages "
                                                  "where conversation_id=%s order by created_at", (c["id"],))
        memory = await fetch_all(conn, "select kind, content, source_conversation_id, created_at from memory_items "
                                       "where customer_id=%s order by created_at", (customer_id,))
        actions = await fetch_all(conn, "select tool_name, input, output, status, created_at from tool_calls "
                                        "where customer_id=%s order by created_at", (customer_id,))
        signals = await fetch_all(conn, "select kind, value, comment, created_at from customer_signals "
                                        "where customer_id=%s", (customer_id,))
        pap = await fetch_all(conn, "select agent_identity, mode, scopes, consent, created_at, revoked_at "
                                    "from pap_sessions where customer_id=%s", (customer_id,))
    return {
        "exported_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "customer": {k: cust[k] for k in ("id", "display_name", "email", "phone", "crm_id", "memory_consent",
                                          "created_at", "last_seen_at")},
        "conversations": convs, "memory": memory, "actions": actions, "signals": signals,
        "outside_agent_sessions": pap,
    }


async def _erase_in_tx(conn: AsyncConnection, customer_id: uuid.UUID) -> dict[str, int]:
    await conn.execute("select set_config('cairn.erasure', 'on', true)")
    cust = await fetch_one(conn, "select email, phone from customers where id=%s", (customer_id,))
    ident = [v for v in ((cust or {}).get("email"), (cust or {}).get("phone")) if v]
    conv_ids = [r["id"] for r in await fetch_all(conn, "select id from conversations where customer_id=%s",
                                                   (customer_id,))]
    # Anonymous conversations where this person identified themselves before being linked.
    for v in ident:
        rows = await fetch_all(conn, """
            select distinct m.conversation_id as id from messages m join conversations c on c.id = m.conversation_id
            where c.customer_id is null and m.content ilike %s""", (f"%{v}%",))
        conv_ids += [r["id"] for r in rows if r["id"] not in conv_ids]

    counts: dict[str, int] = {}

    async def count(table: str, where: str, params) -> None:
        r = await fetch_one(conn, f"select count(*) as n from {table} where {where}", params)
        counts[table] = counts.get(table, 0) + r["n"]

    by_conv = "conversation_id = any(%s) or customer_id = %s"
    for t in ("messages", "turns", "checkpoints", "turn_traces", "supervisor_verdicts", "rule_decisions",
              "tool_calls", "handoffs", "outbox_emails", "chat_sessions", "customer_signals"):
        await count(t, by_conv, (conv_ids, customer_id))
    await count("memory_items", "customer_id = %s", (customer_id,))
    await count("pap_sessions", "customer_id = %s", (customer_id,))
    await count("pap_actions", "customer_id = %s", (customer_id,))
    await count("conversations", "id = any(%s)", (conv_ids,))
    counts["memory_embeddings"] = counts["memory_items"]

    # Outcomes keep counts and timestamps but no content, so invoices stay auditable.
    r = await fetch_one(conn, """
        with u as (
          update outcomes set customer_id = null, issue_key = null,
            evidence = jsonb_build_object('erased', true, 'turns', evidence->'turns',
                                          'tool_calls', jsonb_array_length(coalesce(evidence->'tool_results','[]')))
          where customer_id = %s or conversation_id = any(%s) returning 1)
        select count(*) as n from u""", (customer_id, conv_ids))
    counts["outcomes_anonymized"] = r["n"]

    for t in ("pap_actions", "pap_sessions", "memory_items"):
        await conn.execute(f"delete from {t} where customer_id = %s", (customer_id,))
    for t in ("tool_calls", "customer_signals", "chat_sessions", "outbox_emails", "handoffs", "rule_decisions",
              "supervisor_verdicts", "turn_traces", "checkpoints", "turns", "messages"):
        await conn.execute(f"delete from {t} where conversation_id = any(%s) or customer_id = %s",
                           (conv_ids, customer_id))
    await conn.execute("delete from conversations where id = any(%s)", (conv_ids,))
    r = await fetch_one(conn, "with d as (delete from customers where id=%s returning 1) select count(*) as n from d",
                        (customer_id,))
    counts["customers"] = r["n"]
    for hook in CACHE_HOOKS:
        counts["session_cache"] = counts.get("session_cache", 0) + int(hook(str(customer_id), conv_ids) or 0)
    counts.setdefault("session_cache", 0)
    return counts


async def erase_customer(tenant_id: uuid.UUID, customer_id: uuid.UUID, requested_by: str,
                         request_id: uuid.UUID | None = None) -> dict:
    async with tenant_tx(tenant_id) as conn:
        if request_id is None:
            req = await fetch_one(conn, "insert into erasure_requests (tenant_id, customer_id, requested_by, status) "
                                        "values (%s,%s,%s,'running') returning *", (tenant_id, customer_id, requested_by))
        else:
            req = await fetch_one(conn, "update erasure_requests set status='running' where id=%s returning *",
                                  (request_id,))
        counts = await _erase_in_tx(conn, customer_id)
        now = dt.datetime.now(dt.timezone.utc)
        receipt = {
            "request_id": str(req["id"]), "customer_id": str(customer_id), "requested_at": req["requested_at"],
            "completed_at": now, "counts": counts,
            "backup_retention_days": BACKUP_RETENTION_DAYS,
            "backups_expire_by": (now + dt.timedelta(days=BACKUP_RETENTION_DAYS)).date().isoformat(),
            "note": "Backups expire on a fixed window. After any restore, the erasure log is replayed before the "
                    "system accepts traffic.",
        }
        await conn.execute("update erasure_requests set status='completed', completed_at=%s, receipt=%s where id=%s",
                           (now, Jsonb(receipt), req["id"]))
        await conn.execute("""insert into admin_audit (tenant_id, actor_label, action, target, detail)
                              values (%s,%s,'privacy.erase',%s,%s)""",
                           (tenant_id, requested_by, f"customer:{customer_id}", Jsonb({"counts": counts})))
    return receipt


async def replay_erasures(tenant_id: uuid.UUID) -> int:
    """After a restore from backup: re-apply every completed erasure."""
    async with tenant_tx(tenant_id) as conn:
        reqs = await fetch_all(conn, "select customer_id from erasure_requests where status='completed'")
        n = 0
        for r in reqs:
            exists = await fetch_one(conn, "select 1 from customers where id=%s", (r["customer_id"],))
            if exists:
                await _erase_in_tx(conn, r["customer_id"])
                n += 1
    return n
