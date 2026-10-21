"""Public channel endpoints: the web chat widget, inbound email, and the sandbox MCP server."""

from __future__ import annotations

import asyncio
import os
import datetime as dt
import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

from cairn.api.realtime import hub
from cairn.channels import email as email_channel
from cairn.channels.message import ChannelInfo, CustomerRef, Message
from cairn.channels.service import start_conversation
from cairn.db.core import Jsonb, anon_tx, fetch_all, fetch_one, tenant_tx
from cairn.engine.config import load_config
from cairn.engine.orchestrator import handle_message
from cairn.jobs.queue import enqueue
from cairn.security.crypto import random_token, sha256, verify_identity_signature
from cairn.tools.sandbox_commerce import SANDBOX

log = logging.getLogger("cairn.public")
router = APIRouter()
WIDGET_DIST = Path(os.environ.get("CAIRN_WIDGET_DIST") or Path(__file__).resolve().parents[4] / "widget" / "dist")


async def _tenant_by_key(key: str) -> dict:
    async with anon_tx() as conn:
        t = await fetch_one(conn, "select * from auth_tenant_by_widget_key(%s)", (key,))
    if t is None:
        raise HTTPException(401, "unknown widget key")
    return t


class IdentifyBody(BaseModel):
    email: str | None = None
    name: str | None = None
    signature: str | None = None


class SessionBody(BaseModel):
    key: str
    session_token: str | None = None
    customer: IdentifyBody | None = None


async def _session(tenant_id, token: str) -> dict | None:
    async with tenant_tx(tenant_id) as conn:
        return await fetch_one(conn, "select * from chat_sessions where token_hash=%s and expires_at > now()",
                               (sha256(token),))


@router.post("/v1/chat/sessions")
async def chat_session(body: SessionBody):
    t = await _tenant_by_key(body.key)
    tid = t["id"]
    if body.session_token:
        s = await _session(tid, body.session_token)
        if s:
            async with tenant_tx(tid) as conn:
                msgs = await fetch_all(conn, "select id, role, content, metadata, created_at from messages "
                                             "where conversation_id=%s order by created_at", (s["conversation_id"],))
                conv = await fetch_one(conn, "select status, ended_at from conversations where id=%s",
                                       (s["conversation_id"],))
            if conv and conv["ended_at"] is None:
                return {"session_token": body.session_token, "conversation_id": s["conversation_id"],
                        "messages": msgs, "resumed": True, "status": conv["status"]}
    ref = None
    verified = False
    if body.customer and body.customer.email:
        verified = verify_identity_signature(t["identity_secret"], body.customer.email.lower(),
                                             body.customer.signature or "")
        # Only a verified identity links the chat to a customer record and its memory.
        if verified:
            ref = CustomerRef(email=body.customer.email.lower(), name=body.customer.name, verified=True)
    cid, cust = await start_conversation(tid, "web", ref)
    token = random_token("cs", 24)
    async with tenant_tx(tid) as conn:
        await conn.execute("""
            insert into chat_sessions (tenant_id, conversation_id, customer_id, token_hash, data, expires_at)
            values (%s,%s,%s,%s,%s,%s)""",
            (tid, cid, cust, sha256(token), Jsonb({"verified": verified,
                                                   "name": body.customer.name if body.customer else None}),
             dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=7)))
    return {"session_token": token, "conversation_id": cid, "messages": [], "resumed": False, "status": "active",
            "verified": verified}


@router.get("/v1/widget/config")
async def widget_config(key: str):
    t = await _tenant_by_key(key)
    async with tenant_tx(t["id"]) as conn:
        cfg, _ = await load_config(conn)
        tenant = await fetch_one(conn, "select name, settings from tenants where id=%s", (t["id"],))
    brand = cfg.get("brand", {})
    return {"name": brand.get("name", tenant["name"]), "agent_name": brand.get("agent_name", "Assistant"),
            "accent": (tenant["settings"] or {}).get("accent", "#2f5d50"),
            "greeting": brand.get("greeting", f"Hi! I'm the {brand.get('name', tenant['name'])} assistant. "
                                              "Ask me about orders, refunds, shipping or your membership."),
            "suggestions": brand.get("suggestions", ["Where is my order?", "Start a return", "Is shipping free?"])}


async def _run_turn(tid, conv_id, content: str, verified_email: str | None):
    msg = Message(tenant_id=str(tid), channel=ChannelInfo(type="web"),
                  customer=CustomerRef(email=verified_email, verified=bool(verified_email)), content=content)
    return await handle_message(msg, conv_id, emit=hub.emitter(str(conv_id)))


@router.websocket("/v1/chat/ws")
async def chat_ws(ws: WebSocket, key: str, token: str):
    await ws.accept()
    try:
        t = await _tenant_by_key(key)
    except HTTPException:
        await ws.close(code=4401)
        return
    tid = t["id"]
    s = await _session(tid, token)
    if s is None:
        await ws.close(code=4401)
        return
    conv_id = str(s["conversation_id"])
    hub.add(conv_id, ws, str(s["customer_id"]) if s["customer_id"] else None)
    email = None
    if s["customer_id"] and (s["data"] or {}).get("verified"):
        async with tenant_tx(tid) as conn:
            email = (await fetch_one(conn, "select email from customers where id=%s", (s["customer_id"],)))["email"]
    running: asyncio.Task | None = None
    try:
        await ws.send_json({"type": "ready", "conversation_id": conv_id})
        while True:
            data = await ws.receive_json()
            kind = data.get("type")
            if kind == "message":
                content = str(data.get("content", "")).strip()[:4000]
                if not content:
                    continue
                if running and not running.done():
                    await ws.send_json({"type": "error", "message": "Still working on your last message"})
                    continue

                async def go(c=content):
                    try:
                        await _run_turn(tid, uuid.UUID(conv_id), c, email)
                    except Exception:  # noqa: BLE001 - the customer sees a calm error, the trail keeps the detail
                        log.exception("turn failed")
                        await hub.send(conv_id, {"type": "error", "message": "Something went wrong on our side. "
                                                                             "Please try again."})
                running = asyncio.create_task(go())
            elif kind == "feedback":
                value = int(data.get("value", 0))
                async with tenant_tx(tid) as conn:
                    await conn.execute("""
                        insert into customer_signals (tenant_id, conversation_id, customer_id, kind, value, comment)
                        values (%s,%s,%s,%s,%s,%s)""",
                        (tid, conv_id, s["customer_id"], "csat", max(1, min(5, value)), data.get("comment")))
                await ws.send_json({"type": "feedback.ok"})
            elif kind == "end":
                async with tenant_tx(tid) as conn:
                    await enqueue(conn, tid, "close_conversation", {"conversation_id": conv_id, "reason": "ended by customer"})
                await ws.send_json({"type": "ended"})
            elif kind == "ping":
                await ws.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    finally:
        hub.remove(conv_id, ws)


class ChatHttp(BaseModel):
    key: str
    token: str
    content: str = Field(min_length=1, max_length=4000)


@router.post("/v1/chat/messages")
async def chat_http(body: ChatHttp):
    """HTTP fallback for environments without WebSockets."""
    t = await _tenant_by_key(body.key)
    s = await _session(t["id"], body.token)
    if s is None:
        raise HTTPException(401, "session expired")
    res = await _run_turn(t["id"], s["conversation_id"], body.content, None)
    return {"reply": res.reply, "action": res.action, "citations": res.citations, "status": res.status}


# -------------------------------------------------------------- email

@router.post("/v1/email/inbound/{slug}")
async def email_inbound(slug: str, request: Request):
    key = request.headers.get("x-cairn-key", "")
    async with anon_tx() as conn:
        k = await fetch_one(conn, "select * from auth_api_key(%s)", (sha256(key),)) if key else None
        tenant = await fetch_one(conn, "select * from auth_tenant_by_slug(%s)", (slug,))
    if tenant is None or k is None or k["tenant_id"] != tenant["id"] or "email:inbound" not in k["scopes"]:
        raise HTTPException(401, "an API key with the email:inbound scope is required")
    tid = tenant["id"]
    raw = await request.body()
    msg = email_channel.parse_inbound(raw, str(tid))
    if not msg.content:
        raise HTTPException(422, "empty message after removing quoted text")
    conv_id = await email_channel.find_thread(tid, msg.channel.envelope)
    if conv_id is None:
        conv_id, _ = await start_conversation(tid, "email", msg.customer, subject=msg.channel.envelope.get("subject"),
                                              external_thread_id=msg.channel.envelope.get("thread_root"),
                                              verified=False)
    res = await handle_message(msg, conv_id)
    domain = slug + ".example"
    out = await email_channel.queue_reply(tid, conv_id, msg, res.reply, f"support@{domain}")
    return {"conversation_id": conv_id, "reply": res.reply, "action": res.action, "outbox": out}


# ------------------------------------------------------- sandbox + demo

@router.post("/sandbox/mcp/commerce")
async def sandbox_mcp(request: Request):
    return SANDBOX.handle(await request.json())


@router.get("/widget.js")
async def widget_js():
    f = WIDGET_DIST / "cairn-widget.js"
    if not f.exists():
        raise HTTPException(404, "widget not built: run `npm run build` in widget/")
    return FileResponse(f, media_type="application/javascript", headers={"cache-control": "public, max-age=300"})


@router.get("/demo/{slug}", response_class=HTMLResponse)
async def demo_store(slug: str, request: Request):
    async with anon_tx() as conn:
        t = await fetch_one(conn, "select * from auth_tenant_by_slug(%s)", (slug,))
    if t is None:
        raise HTTPException(404, "unknown tenant")
    async with tenant_tx(t["id"]) as conn:
        row = await fetch_one(conn, "select widget_key, identity_secret from tenants where id=%s", (t["id"],))
    base = str(request.base_url).rstrip("/")
    from cairn.api.demo_page import render

    # The demo signs its sample customers server-side, exactly as a real store would.
    return render(t["name"], row["widget_key"], base, row["identity_secret"])
