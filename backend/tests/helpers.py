from __future__ import annotations

import uuid

from cairn.channels.message import ChannelInfo, CustomerRef, Message
from cairn.channels.service import start_conversation
from cairn.db.core import fetch_all, fetch_one, tenant_tx
from cairn.engine.orchestrator import handle_message


async def new_conversation(tid, email: str | None = None, verified: bool = True, channel: str = "web"):
    ref = CustomerRef(email=email, verified=verified) if email else None
    cid, _ = await start_conversation(tid, channel, ref)
    return cid


async def say(tid, cid, text: str, email: str | None = None, verified: bool = True, inject: dict | None = None):
    ref = CustomerRef(email=email, verified=verified) if email else CustomerRef()
    msg = Message(tenant_id=str(tid), channel=ChannelInfo(type="web"), customer=ref, content=text)
    return await handle_message(msg, cid, inject=inject)


async def rows(tid, sql: str, params=None) -> list[dict]:
    async with tenant_tx(tid) as conn:
        return await fetch_all(conn, sql, params)


async def one(tid, sql: str, params=None) -> dict | None:
    async with tenant_tx(tid) as conn:
        return await fetch_one(conn, sql, params)


def uid(x) -> uuid.UUID:
    return x if isinstance(x, uuid.UUID) else uuid.UUID(str(x))
