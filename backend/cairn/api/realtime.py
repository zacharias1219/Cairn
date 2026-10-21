"""Live connections from the chat widget, keyed by conversation.

One API instance holds these in memory (principle 8). A second instance
would move this to Redis, as section 9 anticipates.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict

from fastapi import WebSocket

from cairn.memory import store as memory_store


class Hub:
    def __init__(self) -> None:
        self.sockets: dict[str, set[WebSocket]] = defaultdict(set)
        self.customers: dict[str, str] = {}

    def add(self, conversation_id: str, ws: WebSocket, customer_id: str | None) -> None:
        self.sockets[conversation_id].add(ws)
        if customer_id:
            self.customers[conversation_id] = customer_id

    def remove(self, conversation_id: str, ws: WebSocket) -> None:
        self.sockets[conversation_id].discard(ws)
        if not self.sockets[conversation_id]:
            self.sockets.pop(conversation_id, None)

    async def send(self, conversation_id: str, event: dict) -> None:
        dead = []
        for ws in list(self.sockets.get(conversation_id, ())):
            try:
                await ws.send_json(event)
            except Exception:  # noqa: BLE001 - a closed socket is simply dropped
                dead.append(ws)
        for ws in dead:
            self.remove(conversation_id, ws)

    def emitter(self, conversation_id: str):
        async def emit(event: dict) -> None:
            if event.get("type") == "reply":
                await stream_reply(self, conversation_id, event)
            else:
                await self.send(conversation_id, event)
        return emit

    def forget(self, customer_id: str, conversation_ids) -> int:
        """Erasure hook: drop live sessions held for this customer."""
        n = 0
        conv_ids = {str(c) for c in conversation_ids}
        for cid, cust in list(self.customers.items()):
            if cust == customer_id or cid in conv_ids:
                for ws in list(self.sockets.get(cid, ())):
                    asyncio.ensure_future(ws.close(code=4001))
                    n += 1
                self.sockets.pop(cid, None)
                self.customers.pop(cid, None)
        return n


async def stream_reply(hub: Hub, conversation_id: str, event: dict) -> None:
    """The reply is approved before it streams; streaming is presentation only."""
    text = event.get("text", "")
    await hub.send(conversation_id, {"type": "reply.start", "message_id": event.get("message_id")})
    words = text.split(" ")
    chunk = []
    for i, w in enumerate(words):
        chunk.append(w)
        if len(chunk) >= 3 or i == len(words) - 1:
            await hub.send(conversation_id, {"type": "reply.delta", "text": " ".join(chunk) + (" " if i < len(words) - 1 else "")})
            chunk = []
            await asyncio.sleep(0.018)
    await hub.send(conversation_id, {**event, "type": "reply.done"})


hub = Hub()
memory_store.CACHE_HOOKS.append(hub.forget)
