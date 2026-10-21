"""Tenant provisioning and seeding."""

from __future__ import annotations

import json
import secrets
import uuid
from importlib import resources

from cairn.db.core import Jsonb, fetch_one, system_tx, tenant_tx
from cairn.engine.config import DEFAULT_CONFIG
from cairn.knowledge.store import upsert_source
from cairn.security.crypto import hash_password
from cairn.tools.sandbox_commerce import SANDBOX_URL, TOOLS


async def create_tenant(name: str, slug: str, *, plan: str = "growth") -> uuid.UUID:
    tid = uuid.uuid4()
    async with system_tx() as conn:
        await conn.execute(
            "insert into tenants (id, name, slug, plan, widget_key, identity_secret, settings) "
            "values (%s,%s,%s,%s,%s,%s,%s)",
            (tid, name, slug, plan, f"pk_{slug}_{secrets.token_hex(6)}", secrets.token_hex(24),
             Jsonb({"retention_days": 365, "monthly_cap_usd": None, "region": "us-east"})))
    return tid


async def add_user(tenant_id: uuid.UUID, email: str, name: str, password: str, role: str) -> uuid.UUID:
    async with tenant_tx(tenant_id) as conn:
        row = await fetch_one(conn, "insert into users (tenant_id, email, name, password_hash, role) "
                                    "values (%s,%s,%s,%s,%s) returning id",
                              (tenant_id, email.lower(), name, hash_password(password), role))
    return row["id"]


def _seed_text(name: str) -> str:
    return (resources.files("cairn") / "seed" / name).read_text()


async def seed_commerce_tools(tenant_id: uuid.UUID) -> None:
    async with tenant_tx(tenant_id) as conn:
        for t in TOOLS:
            await conn.execute("""
                insert into tools (tenant_id, name, title, description, integration, server_url, input_schema,
                  output_schema, risk_tier, requires_approval, is_write, pap_exposed)
                values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                on conflict (tenant_id, name) do nothing""",
                (tenant_id, t["name"], t["title"], t["description"], "Acme Commerce (sandbox)", SANDBOX_URL,
                 Jsonb(t["inputSchema"]), Jsonb(t["outputSchema"]), t["risk_tier"], t["risk_tier"] == "high",
                 t["is_write"], t["pap_exposed"]))


async def seed_rules(tenant_id: uuid.UUID, published_by: uuid.UUID | None = None) -> None:
    rules = json.loads(_seed_text("rules.json"))
    async with tenant_tx(tenant_id) as conn:
        for r in rules:
            await conn.execute("""
                insert into rules (tenant_id, rule_key, version, status, name, description, event, tool, condition,
                  outcome, message, severity, fixtures, created_by, published_by, published_at)
                values (%s,%s,1,'published',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())""",
                (tenant_id, r["rule_key"], r["name"], r["description"], r["event"], r.get("tool"),
                 Jsonb(r["condition"]), r["outcome"], r["message"], r["severity"], Jsonb(r["fixtures"]),
                 published_by, published_by))


KNOWLEDGE = [
    ("Returns and refunds policy", "returns-and-refunds.md", "policy", "Dana Ortiz (CX Ops)", 20),
    ("Shipping policy", "shipping.md", "policy", "Dana Ortiz (CX Ops)", 35),
    ("Trail Club membership", "trail-club.md", "policy", "Kiran Shah (Membership)", 60),
    ("Warranty and repairs", "warranty.md", "policy", "Theo Brandt (Product)", 140),
    ("Exchanges and gift cards", "exchanges-and-gift-cards.md", "faq", "Dana Ortiz (CX Ops)", 12),
    ("International orders and privacy", "international-and-privacy.md", "faq", "Mina Park (Legal)", 45),
]


async def seed_knowledge(tenant_id: uuid.UUID) -> None:
    import datetime as dt

    async with tenant_tx(tenant_id) as conn:
        for title, fname, kind, owner, age in KNOWLEDGE:
            await upsert_source(conn, tenant_id, title=title, content=_seed_text(fname), owner=owner, kind=kind,
                                url=f"https://acme.example/help/{fname.removesuffix('.md')}",
                                reviewed_at=dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=age),
                                review_interval_days=90)


async def seed_config(tenant_id: uuid.UUID, user_id: uuid.UUID | None) -> None:
    async with tenant_tx(tenant_id) as conn:
        await conn.execute("""
            insert into agent_configs (tenant_id, version, status, config, note, created_by, published_by, published_at)
            values (%s,1,'published',%s,'Initial configuration',%s,%s,now())""",
            (tenant_id, Jsonb(DEFAULT_CONFIG), user_id, user_id))


async def seed_pap(tenant_id: uuid.UUID) -> None:
    async with tenant_tx(tenant_id) as conn:
        for ident, name, status, limit in [
            ("agent://meta.ai/personal", "Meta AI personal agent", "allow", 30),
            ("agent://reference.cairn.dev/pap-agent", "Cairn reference agent", "allow", 60),
            ("agent://scraper.example/bot", "Unknown scraper", "deny", 0),
        ]:
            await conn.execute("""
                insert into pap_agents (tenant_id, agent_identity, display_name, status, rate_limit_per_min)
                values (%s,%s,%s,%s,%s) on conflict do nothing""", (tenant_id, ident, name, status, limit))


async def provision_demo(slug: str = "acme", password: str = "cairn-demo") -> uuid.UUID:
    """Acme Outfitters: the sandbox tenant behind the demo and the eval suite."""
    from cairn.evals.packs import seed_eval_cases

    async with system_tx() as conn:
        existing = await fetch_one(conn, "select id from tenants where slug=%s", (slug,))
    if existing:
        await seed_eval_cases(existing["id"])  # keep the built-in packs current
        return existing["id"]
    tid = await create_tenant("Acme Outfitters", slug)
    domain = "acme.test" if slug == "acme" else f"{slug}.test"
    admin = await add_user(tid, f"admin@{domain}", "Riley Morgan", password, "admin")
    await add_user(tid, f"builder@{domain}", "Jesse Alvarez", password, "builder")
    await add_user(tid, f"viewer@{domain}", "Casey Nguyen", password, "viewer")
    await seed_config(tid, admin)
    await seed_commerce_tools(tid)
    await seed_rules(tid, admin)
    await seed_knowledge(tid)
    await seed_pap(tid)
    await seed_eval_cases(tid)
    return tid
