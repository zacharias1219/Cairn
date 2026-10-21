"""Insights (F13).

Every dashboard number is produced by exactly the query shown next to it
in the console, run against the raw tables. Nothing is precomputed, so any
number can be reproduced by pasting its query into psql with the tenant set.
Test and evaluation conversations are always excluded.
"""

from __future__ import annotations

import datetime as dt
import uuid

from cairn.db.core import fetch_all, tenant_tx

QUERIES: dict[str, dict[str, str]] = {
    "verified_resolution_rate": {
        "title": "Verified resolution rate",
        "description": "Finalized outcomes that became billable resolutions, over all finalized outcomes.",
        "sql": """select count(*) filter (where billable) as resolved,
       count(*) as finalized,
       round(100.0 * count(*) filter (where billable) / nullif(count(*), 0), 1) as rate_pct
from outcomes
where status = 'final' and not is_test and ended_at >= %(since)s""",
    },
    "outcome_mix": {
        "title": "Outcome mix",
        "description": "How conversations ended, including outcomes still inside their re-contact window.",
        "sql": """select type, status, count(*) as n
from outcomes
where not is_test and ended_at >= %(since)s
group by type, status
order by n desc""",
    },
    "escalation_reasons": {
        "title": "Escalations by reason",
        "description": "Handoffs to the help desk, grouped by the reason code the orchestrator recorded.",
        "sql": """select h.reason_code, count(*) as n
from handoffs h join conversations c on c.id = h.conversation_id
where not c.is_test and h.created_at >= %(since)s
group by h.reason_code
order by n desc""",
    },
    "escalation_rate": {
        "title": "Escalation rate",
        "description": "Conversations that ended in a handoff, over all conversations started.",
        "sql": """select count(*) filter (where exists (select 1 from handoffs h where h.conversation_id = c.id)) as escalated,
       count(*) as conversations,
       round(100.0 * count(*) filter (where exists (select 1 from handoffs h where h.conversation_id = c.id))
             / nullif(count(*), 0), 1) as rate_pct
from conversations c
where not c.is_test and c.started_at >= %(since)s""",
    },
    "cost_per_resolution": {
        "title": "Model cost per verified resolution",
        "description": "Model spend on all conversations in the period, over billable resolutions.",
        "sql": """select round(sum(t.cost_usd)::numeric, 4) as model_cost_usd,
       (select count(*) from outcomes o where o.billable and not o.is_test and o.ended_at >= %(since)s) as resolutions,
       round(sum(t.cost_usd)::numeric / nullif((select count(*) from outcomes o
             where o.billable and not o.is_test and o.ended_at >= %(since)s), 0), 4) as cost_per_resolution_usd
from turns t join conversations c on c.id = t.conversation_id
where not c.is_test and t.started_at >= %(since)s""",
    },
    "supervisor_interventions": {
        "title": "Supervisor interventions by type",
        "description": "Every non-approve verdict, grouped by verdict and reason code.",
        "sql": """select v.verdict, v.reason_code, count(*) as n
from supervisor_verdicts v join conversations c on c.id = v.conversation_id
where not c.is_test and v.verdict <> 'approve' and v.created_at >= %(since)s
group by v.verdict, v.reason_code
order by n desc""",
    },
    "contact_reasons": {
        "title": "Top contact reasons",
        "description": "Conversations by intent, ranked by volume, with the share that ended poorly "
                       "(escalated, abandoned, failed, or resolved but not billable).",
        "sql": """select coalesce(c.intent, 'unclassified') as reason,
       count(*) as conversations,
       round(100.0 * count(*) filter (where o.type in ('escalated','abandoned','failed')
             or (o.status = 'final' and not o.billable)) / nullif(count(o.id), 0), 1) as poor_outcome_pct
from conversations c left join outcomes o on o.conversation_id = c.id
where not c.is_test and c.started_at >= %(since)s
group by 1
order by conversations desc""",
    },
    "csat": {
        "title": "Customer satisfaction",
        "description": "Average CSAT (1-5) where the tenant collects it.",
        "sql": """select round(avg(s.value)::numeric, 2) as avg_csat, count(*) as responses
from customer_signals s join conversations c on c.id = s.conversation_id
where s.kind = 'csat' and not c.is_test and s.created_at >= %(since)s""",
    },
    "daily_volume": {
        "title": "Daily conversations and resolutions",
        "description": "Conversations started per day, and how many became verified resolutions.",
        "sql": """select date_trunc('day', c.started_at)::date as day,
       count(*) as conversations,
       count(*) filter (where o.billable) as verified_resolutions,
       count(*) filter (where o.type = 'escalated') as escalated
from conversations c left join outcomes o on o.conversation_id = c.id
where not c.is_test and c.started_at >= %(since)s
group by 1
order by 1""",
    },
    "latency": {
        "title": "Reply latency",
        "description": "Turn latency from customer message to approved reply, supervisor included.",
        "sql": """select percentile_disc(0.5) within group (order by t.latency_ms) as p50_ms,
       percentile_disc(0.95) within group (order by t.latency_ms) as p95_ms,
       count(*) as turns
from turns t join conversations c on c.id = t.conversation_id
where not c.is_test and t.latency_ms is not null and t.started_at >= %(since)s""",
    },
    "rule_firings": {
        "title": "Rule firings",
        "description": "How often each rule changed the outcome of an action or reply.",
        "sql": """select d.rule_key, d.outcome, count(*) as n
from rule_decisions d join conversations c on c.id = d.conversation_id
where not c.is_test and d.outcome <> 'allow' and d.created_at >= %(since)s
group by d.rule_key, d.outcome
order by n desc""",
    },
}


async def run(tenant_id: uuid.UUID, days: int = 30, keys: list[str] | None = None) -> dict:
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    out = {}
    async with tenant_tx(tenant_id) as conn:
        for key, q in QUERIES.items():
            if keys and key not in keys:
                continue
            rows = await fetch_all(conn, q["sql"], {"since": since})
            out[key] = {"title": q["title"], "description": q["description"], "sql": q["sql"], "rows": rows}
    return {"since": since, "days": days, "metrics": out}
