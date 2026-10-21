"""Agent configuration: versioned JSON behind the console's forms (F11)."""

from __future__ import annotations

import copy

from psycopg import AsyncConnection

from cairn.db.core import fetch_one
from cairn.llm.gateway import DEFAULT_MODELS

DEFAULT_CONFIG: dict = {
    "brand": {"name": "Acme Outfitters", "agent_name": "Acme Assistant"},
    "tone": {
        "voice": "Warm, concise and plain-spoken, like a knowledgeable shop-floor guide.",
        "max_exclamations": 2,
        "avoid_phrases": ["unfortunately, there is nothing", "per our policy", "as previously stated"],
    },
    "policy": {
        "competitors": ["REI", "Patagonia", "Backcountry", "Amazon"],
        "sensitive_topics": [
            {"name": "legal threat", "keywords": ["lawyer", "attorney", "lawsuit", "sue", "legal action", "small claims"],
             "action": "escalate"},
            {"name": "safety incident", "keywords": ["injured", "injury", "hospital", "burned", "caught fire", "unsafe"],
             "action": "escalate"},
            {"name": "self-harm", "keywords": ["kill myself", "suicide", "self harm", "end my life"], "action": "escalate"},
            {"name": "fraud", "keywords": ["stolen card", "fraudulent charge", "identity theft", "chargeback"],
             "action": "escalate"},
        ],
        "allowed_commitments": [],
    },
    "models": copy.deepcopy(DEFAULT_MODELS),
    "supervisor": {"timeout_ms": 3500, "max_revisions": 2},
    "limits": {"max_steps_per_turn": 16, "cost_budget_per_conversation_usd": 0.75},
    "retrieval": {"top_k": 3},
    "memory": {"enabled": True,
               "workflows": ["order_status", "refund_request", "cancel_subscription", "change_address",
                             "policy_question", "complaint"]},
    "confirm_writes": True,
    "handoff": {"destination": "Zendesk · Tier 2 queue", "webhook_url": None},
    "outcomes": {"recontact_window_hours": 72},
    "internal_notes": "Internal: goodwill credits are capped at $25 without manager sign-off.",
}


def merged(cfg: dict | None) -> dict:
    out = copy.deepcopy(DEFAULT_CONFIG)
    for k, v in (cfg or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = {**out[k], **v}
        else:
            out[k] = v
    return out


async def load_config(conn: AsyncConnection, *, draft: bool = False, version: int | None = None) -> tuple[dict, int]:
    if version:
        row = await fetch_one(conn, "select version, config from agent_configs where version=%s", (version,))
    elif draft:
        row = await fetch_one(conn, "select version, config from agent_configs where status in ('draft','published') "
                                    "order by version desc limit 1")
    else:
        row = await fetch_one(conn, "select version, config from agent_configs where status='published' "
                                    "order by published_at desc nulls last, version desc limit 1")
    if row is None:
        return merged({}), 0
    return merged(row["config"]), row["version"]
