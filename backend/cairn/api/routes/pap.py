"""PAP gateway HTTP routes (F8)."""

from __future__ import annotations

import html
import urllib.parse
import uuid

from fastapi import APIRouter, Form, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from cairn.channels.message import ChannelInfo, CustomerRef, Message
from cairn.channels.service import resolve_customer, start_conversation
from cairn.config import get_settings
from cairn.db.core import anon_tx, fetch_one, tenant_tx
from cairn.engine.orchestrator import handle_message
from cairn.pap import gateway as g
from cairn.rules.engine import load_active_rules
from cairn.tools import layer

router = APIRouter()


async def _tenant(slug: str) -> dict:
    async with anon_tx() as conn:
        t = await fetch_one(conn, "select * from auth_tenant_by_slug(%s)", (slug,))
    if t is None:
        raise HTTPException(404, "unknown business")
    return t


def _err(e: g.PapError) -> JSONResponse:
    return JSONResponse({"error": e.code, "message": e.message}, status_code=e.status)


@router.get("/pap/v1/{slug}/.well-known/pap.json")
async def well_known(slug: str):
    t = await _tenant(slug)
    return await g.manifest(t["id"], slug, get_settings().public_url)


@router.get("/.well-known/pap.json")
async def well_known_root(tenant: str):
    return await well_known(tenant)


class GuestBody(BaseModel):
    agent: str = Field(description="agent:// identity of the outside agent")


@router.post("/pap/v1/{slug}/sessions")
async def guest(slug: str, body: GuestBody):
    t = await _tenant(slug)
    try:
        return await g.create_guest(t["id"], body.agent)
    except g.PapError as e:
        return _err(e)


@router.get("/pap/v1/{slug}/authorize", response_class=HTMLResponse)
async def authorize(slug: str, agent: str, redirect_uri: str, code_challenge: str, scope: str = "read",
                    state: str | None = None, code_challenge_method: str = "S256"):
    t = await _tenant(slug)
    if code_challenge_method != "S256":
        return _err(g.PapError(400, "pkce_required", "only S256 is supported"))
    try:
        sid = await g.authorize(t["id"], agent, scope, redirect_uri, code_challenge, state)
    except g.PapError as e:
        return _err(e)
    async with tenant_tx(t["id"]) as conn:
        a = await fetch_one(conn, "select display_name from pap_agents where agent_identity=%s", (agent,))
    return _consent_page(t["name"], slug, sid, (a or {}).get("display_name") or agent, scope.split(), None)


@router.post("/pap/v1/{slug}/authorize/{sid}", response_class=HTMLResponse)
async def authorize_submit(slug: str, sid: uuid.UUID, email: str = Form(...), order_id: str = Form(...),
                           allow_write: str | None = Form(None), decision: str = Form("allow")):
    t = await _tenant(slug)
    async with tenant_tx(t["id"]) as conn:
        s = await fetch_one(conn, "select * from pap_sessions where id=%s and mode='pending_consent'", (sid,))
        if s is None:
            raise HTTPException(400, "consent request expired")
        tools = await layer.load_tools(conn)
    if decision != "allow":
        q = urllib.parse.urlencode({"error": "access_denied", "state": (s["consent"] or {}).get("state") or ""})
        return RedirectResponse(f"{s['redirect_uri']}?{q}", status_code=303)
    # Sandbox sign-in: the business's own login would sit here. We verify the
    # customer owns an order, through the same tool layer the agent uses.
    async with tenant_tx(t["id"]) as conn:
        out = await layer.request_tool(conn, t["id"], tools["verify_customer"],
                                       {"email": email.strip().lower(), "order_id": order_id.strip().upper()},
                                       rules=[], rule_context={}, ids={}, scope=f"pap-consent:{sid}", source="pap")
    if out.status != "succeeded" or not (out.output or {}).get("verified"):
        a = s["agent_identity"]
        return _consent_page(t["name"], slug, sid, a, list(s["scopes"]),
                             "We couldn't match that email and order number. Please try again.")
    async with tenant_tx(t["id"]) as conn:
        cust = await resolve_customer(conn, t["id"], CustomerRef(email=email.strip().lower(), verified=True))
    granted = ["read"] + (["write"] if allow_write and "write" in s["scopes"] else [])
    code, info = await g.consent(t["id"], sid, customer_id=cust, granted=granted, method="email+order verification")
    q = urllib.parse.urlencode({"code": code, **({"state": info["state"]} if info.get("state") else {})})
    return RedirectResponse(f"{info['redirect_uri']}?{q}", status_code=303)


class TokenBody(BaseModel):
    grant_type: str = "authorization_code"
    code: str
    code_verifier: str
    agent: str


@router.post("/pap/v1/{slug}/token")
async def token(slug: str, body: TokenBody):
    t = await _tenant(slug)
    try:
        return await g.exchange(t["id"], body.code, body.code_verifier, body.agent)
    except g.PapError as e:
        return _err(e)


def _bearer(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise g.PapError(401, "invalid_token", "missing bearer token")
    return authorization[7:].strip()


class AgentMessage(BaseModel):
    content: str = Field(min_length=1, max_length=4000)


@router.post("/pap/v1/{slug}/messages")
async def message(slug: str, body: AgentMessage, authorization: str | None = Header(None)):
    t = await _tenant(slug)
    try:
        s = await g.session_from_token(t["id"], _bearer(authorization))
    except g.PapError as e:
        return _err(e)
    tid = t["id"]
    signed = s.mode == "signed_in"
    ref = CustomerRef(email=s.customer_email, verified=signed) if signed and s.customer_email else None
    conv_id = s.conversation_id
    if conv_id is None:
        conv_id, _ = await start_conversation(tid, "pap", ref, subject=f"Personal agent: {s.agent_identity}")
        async with tenant_tx(tid) as conn:
            await conn.execute("update pap_sessions set conversation_id=%s where id=%s", (conv_id, s.id))
    if "write" not in s.scopes:
        # A read-only session never gets to confirm a write, whatever it says.
        async with tenant_tx(tid) as conn:
            await conn.execute("update conversations set state = state - 'pending_action' where id=%s", (conv_id,))
    msg = Message(tenant_id=str(tid), channel=ChannelInfo(type="pap", envelope={"agent": s.agent_identity,
                                                                               "session": str(s.id)}),
                  customer=ref or CustomerRef(), content=body.content)
    res = await handle_message(msg, conv_id)
    async with tenant_tx(tid) as conn:
        calls = await fetch_one(conn, "select count(*) filter (where status='succeeded') as ok from tool_calls "
                                      "where turn_id=%s", (res.turn_id,))
        await g.log_action(conn, tid, s.id, s.customer_id, s.agent_identity, "message", "read", True, res.action,
                           {"turn_id": res.turn_id, "verdict": res.verdict, "tool_calls_succeeded": calls["ok"]})
    return {"reply": res.reply, "action": res.action, "verdict": res.verdict, "citations": res.citations,
            "conversation_id": str(conv_id), "awaiting_approval": res.status == "awaiting_approval"}


class ActionBody(BaseModel):
    arguments: dict


@router.post("/pap/v1/{slug}/actions/{capability}")
async def action(slug: str, capability: str, body: ActionBody, authorization: str | None = Header(None)):
    t = await _tenant(slug)
    tid = t["id"]
    try:
        s = await g.session_from_token(tid, _bearer(authorization))
    except g.PapError as e:
        return _err(e)
    async with tenant_tx(tid) as conn:
        tools = await layer.load_tools(conn)
        rules = await load_active_rules(conn)
        spec = tools.get(capability)
        if spec is None or not spec.pap_exposed:
            await g.log_action(conn, tid, s.id, s.customer_id, s.agent_identity, f"action:{capability}", "n/a",
                               False, "unknown_capability", {})
            return _err(g.PapError(404, "unknown_capability", f"{capability} is not offered to outside agents"))
        needed = "write" if spec.is_write else "read"
        if needed not in s.scopes:
            await g.log_action(conn, tid, s.id, s.customer_id, s.agent_identity, f"action:{capability}", needed,
                               False, "refused_scope", {"granted": s.scopes, "arguments": body.arguments})
            return _err(g.PapError(403, "insufficient_scope", f"{capability} needs the {needed} scope; this session "
                                                              f"has {' '.join(s.scopes)}"))
        args = dict(body.arguments)
        order = {}
        if "order_id" in args and "lookup_order" in tools:
            look = await layer.request_tool(conn, tid, tools["lookup_order"], {"order_id": args["order_id"]},
                                            rules=rules, rule_context={}, ids={"customer_id": s.customer_id},
                                            scope=f"pap:{s.id}:lookup", source="pap")
            order = look.output or {}  # full record for the rules; never returned to the agent
        ctx = {"customer": {"verified": s.mode == "signed_in", "email": s.customer_email}, "order": order,
               "conversation": {"channel": "pap", "outside_agent": True}, "intent": capability}
        out = await layer.request_tool(conn, tid, spec, args, rules=rules, rule_context=ctx,
                                       ids={"customer_id": s.customer_id}, scope=f"pap:{s.id}", source="pap")
        output = out.output
        owns = s.mode == "signed_in" and bool(s.customer_email) and \
            (output or {}).get("customer_email", "").lower() == (s.customer_email or "").lower()
        if capability == "lookup_order" and output and not owns:
            # Guests and other customers' orders: status only, never personal data.
            output = {k: v for k, v in output.items() if k not in ("customer_email", "shipping_address")}
        await g.log_action(conn, tid, s.id, s.customer_id, s.agent_identity, f"action:{capability}", needed,
                           out.status in ("succeeded", "pending_approval"), out.status,
                           {"arguments": args, "call_id": out.call_id, "reason": out.reason, "error": out.error,
                            "rules": out.decision.as_dict() if out.decision else None})
    status = {"succeeded": 200, "pending_approval": 202, "refused": 403, "denied": 403, "failed": 502}[out.status]
    return JSONResponse({"status": out.status, "result": output, "error": out.error, "call_id": out.call_id,
                         "reason": out.reason}, status_code=status)


@router.delete("/pap/v1/{slug}/session")
async def end_session(slug: str, authorization: str | None = Header(None)):
    t = await _tenant(slug)
    try:
        s = await g.session_from_token(t["id"], _bearer(authorization))
    except g.PapError as e:
        return _err(e)
    await g.revoke(t["id"], s.id, "agent")
    return {"ok": True}


def _consent_page(business: str, slug: str, sid, agent: str, scopes: list[str], error: str | None) -> HTMLResponse:
    e = html.escape
    write = "write" in scopes
    return HTMLResponse(f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Allow access · {e(business)}</title>
<style>
:root{{--bg:#f6f5f2;--card:#fff;--ink:#1c1b19;--muted:#6b6862;--line:#e6e3dd;--accent:#2f5d50}}
@media (prefers-color-scheme:dark){{:root{{--bg:#121211;--card:#1b1b19;--ink:#f1efe9;--muted:#a19d95;--line:#2c2b28;--accent:#7fb7a4}}}}
*{{box-sizing:border-box}}body{{margin:0;font:15px/1.55 ui-sans-serif,system-ui,-apple-system,Segoe UI,sans-serif;background:var(--bg);color:var(--ink);display:grid;place-items:center;min-height:100vh;padding:24px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:18px;max-width:440px;width:100%;padding:28px;box-shadow:0 20px 60px -30px rgba(0,0,0,.25)}}
.mark{{display:flex;gap:10px;align-items:center;color:var(--muted);font-size:13px;margin-bottom:18px}}
h1{{font:600 22px/1.25 Georgia,serif;margin:0 0 6px}}p{{margin:0 0 16px;color:var(--muted)}}
.agent{{display:flex;gap:12px;align-items:center;padding:12px;border:1px solid var(--line);border-radius:12px;margin-bottom:16px}}
.dot{{width:36px;height:36px;border-radius:10px;background:linear-gradient(135deg,var(--accent),#8fb9aa);flex:none}}
label{{display:block;font-size:13px;color:var(--muted);margin:10px 0 4px}}
input[type=email],input[type=text]{{width:100%;padding:11px 12px;border-radius:10px;border:1px solid var(--line);background:transparent;color:var(--ink);font:inherit}}
.scope{{display:flex;gap:10px;padding:10px 0;border-top:1px solid var(--line)}}.scope:first-of-type{{border-top:0}}
.btns{{display:flex;gap:10px;margin-top:20px}}button{{flex:1;padding:11px;border-radius:10px;border:1px solid var(--line);font:600 14px inherit;cursor:pointer;background:transparent;color:var(--ink)}}
button.primary{{background:var(--accent);border-color:var(--accent);color:#fff}}.err{{color:#b4402f;font-size:14px;margin:8px 0}}
small{{color:var(--muted);display:block;margin-top:14px;font-size:12px}}
</style></head><body><form class="card" method="post" action="/pap/v1/{e(slug)}/authorize/{sid}">
<div class="mark">◆ {e(business)} · secured by Cairn</div>
<h1>Allow an assistant to act for you?</h1>
<p>An AI agent is asking to work with your {e(business)} account.</p>
<div class="agent"><div class="dot"></div><div><b>{e(agent)}</b><br><span style="color:var(--muted);font-size:13px">Personal agent</span></div></div>
<div class="scope"><input type="checkbox" checked disabled><div><b>Read</b><br><span style="color:var(--muted);font-size:13px">Ask questions, see your orders and membership</span></div></div>
{f'<div class="scope"><input type="checkbox" name="allow_write" value="1" id="w"><label for="w" style="margin:0;color:var(--ink)"><b>Make changes</b><br><span style="color:var(--muted);font-size:13px">Refunds, cancellations and address changes you ask for. Larger refunds still need our team&#39;s approval.</span></label></div>' if write else ''}
{f'<div class="err">{e(error)}</div>' if error else ''}
<label>Email on your account</label><input type="email" name="email" required autocomplete="email">
<label>Any order number (to confirm it's you)</label><input type="text" name="order_id" required placeholder="A1234">
<div class="btns"><button name="decision" value="deny" formnovalidate>Deny</button><button class="primary" name="decision" value="allow">Allow</button></div>
<small>You can revoke access at any time. Every action the agent takes is logged.</small>
</form></body></html>""")
