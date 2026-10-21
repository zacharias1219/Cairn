"""Conversation lifecycle shared by every channel."""

from __future__ import annotations

import uuid

from psycopg import AsyncConnection

from cairn.channels.message import CustomerRef
from cairn.db.core import Jsonb, fetch_one, tenant_tx


async def resolve_customer(conn: AsyncConnection, tenant_id: uuid.UUID, ref: CustomerRef | None) -> uuid.UUID | None:
    """Identity resolution across channels on the keys the tenant defines (email, phone, CRM ID)."""
    if ref is None or not ref.keys():
        return None
    keys = ref.keys()
    params = {"email": keys.get("email"), "phone": keys.get("phone"), "crm": keys.get("crm_id")}
    find = """
        select id from customers
        where (%(email)s::text is not null and email = lower(%(email)s))
           or (%(phone)s::text is not null and phone = %(phone)s)
           or (%(crm)s::text is not null and crm_id = %(crm)s)
        order by created_at limit 1"""
    row = await fetch_one(conn, find, params)
    if row:
        await conn.execute("""
            update customers set last_seen_at = now(),
              display_name = coalesce(display_name, %s), phone = coalesce(phone, %s), crm_id = coalesce(crm_id, %s)
            where id = %s""", (ref.name, keys.get("phone"), keys.get("crm_id"), row["id"]))
        return row["id"]
    # Two first contacts from the same person can race here (a chat and an email
    # at once): the loser of the insert reads back the winner's row.
    row = await fetch_one(conn, """
        insert into customers (tenant_id, display_name, email, phone, crm_id)
        values (%s,%s,lower(%s),%s,%s) on conflict do nothing returning id""",
        (tenant_id, ref.name, keys.get("email"), keys.get("phone"), keys.get("crm_id")))
    if row is None:
        row = await fetch_one(conn, find, params)
    return row["id"]


async def start_conversation(
    tenant_id: uuid.UUID, channel: str, customer: CustomerRef | None = None, *, is_test: bool = False,
    subject: str | None = None, external_thread_id: str | None = None, verified: bool | None = None,
) -> tuple[uuid.UUID, uuid.UUID | None]:
    async with tenant_tx(tenant_id) as conn:
        cid = await resolve_customer(conn, tenant_id, customer)
        state = {}
        if customer and (verified if verified is not None else customer.verified) and customer.email:
            state = {"facts": {"verified": True, "email": customer.email.lower()}}
        row = await fetch_one(conn, """
            insert into conversations (tenant_id, customer_id, channel, is_test, subject, external_thread_id, state)
            values (%s,%s,%s,%s,%s,%s,%s) returning id""",
            (tenant_id, cid, channel, is_test, subject, external_thread_id, Jsonb(state)))
    return row["id"], cid
