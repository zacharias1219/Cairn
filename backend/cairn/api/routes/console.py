"""Operator console API (F11)."""

from __future__ import annotations

import csv
import datetime as dt
import io
import json
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field

from cairn.api.deps import Principal, SESSION_COOKIE, audit, current_principal, role
from cairn.channels.message import ChannelInfo, CustomerRef, Message
from cairn.channels.service import start_conversation
from cairn.config import get_settings
from cairn.db.core import Jsonb, anon_tx, fetch_all, fetch_one, tenant_tx
from cairn.engine import approvals
from cairn.engine.config import DEFAULT_CONFIG, load_config, merged
from cairn.engine.orchestrator import handle_message
from cairn.evals.harness import run_suite
from cairn.insights.queries import run as run_insights
from cairn.jobs.queue import enqueue
from cairn.knowledge.store import search, upsert_source
from cairn.memory.store import erase_customer, export_customer
from cairn.outcomes.engine import PLAN_FEES, PLAN_RATES, close_conversation
from cairn.pap.gateway import revoke
from cairn.rules import jsonlogic
from cairn.rules.engine import Rule, evaluate, run_fixtures
from cairn.security.crypto import hash_password, issue_session, random_token, seal, sha256, verify_password

router = APIRouter(prefix="/api")
viewer, builder, admin = role("viewer"), role("builder"), role("admin")


def _tx(p: Principal):
    return tenant_tx(p.tenant_id)


# ------------------------------------------------------------------ auth

class Login(BaseModel):
    email: str
    password: str


@router.post("/auth/login")
async def login(body: Login, response: Response):
    async with anon_tx() as conn:
        u = await fetch_one(conn, "select * from auth_user_by_email(%s)", (body.email,))
    if u is None or not verify_password(body.password, u["password_hash"]):
        raise HTTPException(401, "Email or password is incorrect")
    token = issue_session(u["id"], u["tenant_id"], u["role"], body.email.lower())
    s = get_settings()
    response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax", secure=s.cookie_secure,
                        max_age=s.session_ttl_hours * 3600, path="/")
    async with tenant_tx(u["tenant_id"]) as conn:
        await conn.execute("update users set last_login_at=now() where id=%s", (u["id"],))
    return {"ok": True, "role": u["role"]}


@router.post("/auth/logout")
async def logout(response: Response):
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@router.get("/auth/me")
async def me(p: Principal = Depends(current_principal)):
    async with _tx(p) as conn:
        t = await fetch_one(conn, "select id, name, slug, plan, widget_key, settings from tenants where id=%s",
                            (p.tenant_id,))
        u = await fetch_one(conn, "select id, email, name, role from users where id=%s", (p.user_id,)) if p.user_id else None
        pending = await fetch_one(conn, """select count(*) as n from tool_calls tc
            left join conversations c on c.id = tc.conversation_id
            where tc.status='pending_approval' and not coalesce(c.is_test, false)""")
        esc = await fetch_one(conn, "select count(*) as n from conversations where status='escalated' and not is_test")
    return {"tenant": t, "user": u or {"name": p.label, "role": p.role}, "role": p.role,
            "counts": {"approvals": pending["n"], "escalations": esc["n"]},
            "model_mode": "claude" if get_settings().use_claude else "sandbox"}


# -------------------------------------------------------------- overview

@router.get("/overview")
async def overview(days: int = 30, p: Principal = Depends(viewer)):
    ins = await run_insights(p.tenant_id, days)
    m = ins["metrics"]
    async with _tx(p) as conn:
        live = await fetch_one(conn, """
            select
              (select count(*) from conversations where not is_test and ended_at is null) as active,
              (select count(*) from conversations where not is_test and started_at >= now() - interval '24 hours') as today,
              (select count(*) from tool_calls tc left join conversations c on c.id = tc.conversation_id
               where tc.status='pending_approval' and not coalesce(c.is_test, false)) as approvals,
              (select count(*) from knowledge_sources where reviewed_at + make_interval(days => review_interval_days) < now()) as stale_sources,
              (select count(*) from outcomes where status='pending' and not is_test) as pending_outcomes""")
        last_eval = await fetch_one(conn, "select id, status, summary, gates, finished_at, config_version from eval_runs "
                                          "where status <> 'running' order by started_at desc limit 1")
        recent = await fetch_all(conn, """
            select c.id, c.channel, c.status, c.intent, c.started_at, c.last_activity_at, cu.display_name, cu.email,
              (select content from messages m where m.conversation_id=c.id and m.role in ('customer','outside_agent')
               order by created_at limit 1) as first_message,
              (select final_verdict from turns t where t.conversation_id=c.id order by seq desc limit 1) as last_verdict,
              o.type as outcome, o.billable
            from conversations c left join customers cu on cu.id=c.customer_id
            left join outcomes o on o.conversation_id=c.id
            where not c.is_test order by c.last_activity_at desc limit 8""")
        cfg = await fetch_one(conn, "select version, published_at from agent_configs where status='published' "
                                    "order by published_at desc nulls last limit 1")
    return {"days": days, "metrics": m, "live": live, "last_eval": last_eval, "recent": recent, "config": cfg}


@router.get("/insights")
async def insights(days: int = 30, p: Principal = Depends(viewer)):
    return await run_insights(p.tenant_id, days)


# --------------------------------------------------------- conversations

@router.get("/conversations")
async def conversations(status: str | None = None, channel: str | None = None, outcome: str | None = None,
                        q: str | None = None, include_test: bool = False, limit: int = Query(50, le=200),
                        offset: int = 0, p: Principal = Depends(viewer)):
    async with _tx(p) as conn:
        rows = await fetch_all(conn, """
            select c.id, c.channel, c.status, c.intent, c.subject, c.started_at, c.last_activity_at, c.ended_at,
              c.is_test, cu.display_name, cu.email, o.type as outcome, o.status as outcome_status, o.billable,
              (select count(*) from messages m where m.conversation_id=c.id) as message_count,
              (select content from messages m where m.conversation_id=c.id and m.role in ('customer','outside_agent')
               order by created_at limit 1) as first_message,
              (select count(*) from supervisor_verdicts v where v.conversation_id=c.id and v.verdict<>'approve') as interventions,
              (select coalesce(sum(cost_usd),0) from turns t where t.conversation_id=c.id) as cost_usd
            from conversations c left join customers cu on cu.id=c.customer_id
            left join outcomes o on o.conversation_id=c.id
            where (%(test)s or not c.is_test)
              and (%(status)s::text is null or c.status=%(status)s)
              and (%(channel)s::text is null or c.channel=%(channel)s)
              and (%(outcome)s::text is null or o.type=%(outcome)s)
              and (%(q)s::text is null or cu.email ilike '%%'||%(q)s||'%%' or c.intent ilike '%%'||%(q)s||'%%'
                   or exists (select 1 from messages m where m.conversation_id=c.id and m.content ilike '%%'||%(q)s||'%%'))
            order by c.last_activity_at desc limit %(limit)s offset %(offset)s""",
            {"test": include_test, "status": status, "channel": channel, "outcome": outcome, "q": q or None,
             "limit": limit, "offset": offset})
        total = await fetch_one(conn, "select count(*) as n from conversations where (%s or not is_test)", (include_test,))
    return {"items": rows, "total": total["n"]}


async def _trail(conn, turn_ids: list) -> dict[str, dict]:
    traces = await fetch_all(conn, "select * from turn_traces where turn_id = any(%s) order by turn_id, seq", (turn_ids,))
    verdicts = await fetch_all(conn, "select * from supervisor_verdicts where turn_id = any(%s) order by created_at",
                               (turn_ids,))
    rules = await fetch_all(conn, "select * from rule_decisions where turn_id = any(%s) order by created_at", (turn_ids,))
    calls = await fetch_all(conn, "select id, turn_id, tool_name, risk_tier, input, output, status, idempotency_key, "
                                  "approver_label, decided_at, decision_note, error, latency_ms, created_at "
                                  "from tool_calls where turn_id = any(%s) order by created_at", (turn_ids,))
    out: dict[str, dict] = {str(t): {"steps": [], "verdicts": [], "rules": [], "tool_calls": []} for t in turn_ids}
    for k, rows in (("steps", traces), ("verdicts", verdicts), ("rules", rules), ("tool_calls", calls)):
        for r in rows:
            out[str(r["turn_id"])][k].append(r)
    return out


@router.get("/conversations/{cid}")
async def conversation(cid: uuid.UUID, p: Principal = Depends(viewer)):
    async with _tx(p) as conn:
        c = await fetch_one(conn, """
            select c.*, cu.display_name, cu.email, cu.memory_consent from conversations c
            left join customers cu on cu.id=c.customer_id where c.id=%s""", (cid,))
        if c is None:
            raise HTTPException(404, "conversation not found")
        msgs = await fetch_all(conn, "select id, turn_id, role, channel, content, metadata, created_at from messages "
                                     "where conversation_id=%s order by created_at", (cid,))
        turns = await fetch_all(conn, "select * from turns where conversation_id=%s order by seq", (cid,))
        trail = await _trail(conn, [t["id"] for t in turns])
        outcome = await fetch_one(conn, "select * from outcomes where conversation_id=%s", (cid,))
        handoffs = await fetch_all(conn, "select id, reason_code, reason, destination, delivery_status, created_at "
                                         "from handoffs where conversation_id=%s", (cid,))
        signals = await fetch_all(conn, "select kind, value, comment, created_at from customer_signals "
                                        "where conversation_id=%s", (cid,))
    c.pop("state", None)
    for t in turns:
        t["trail"] = trail[str(t["id"])]
    return {"conversation": c, "messages": msgs, "turns": turns, "outcome": outcome, "handoffs": handoffs,
            "signals": signals}


@router.post("/conversations/{cid}/close")
async def close(cid: uuid.UUID, p: Principal = Depends(builder)):
    o = await close_conversation(p.tenant_id, cid, "closed by operator")
    async with _tx(p) as conn:
        await enqueue(conn, p.tenant_id, "remember", {"conversation_id": str(cid)})
        await audit(conn, p, "conversation.close", f"conversation:{cid}")
    return o


@router.get("/turns/{tid}")
async def turn(tid: uuid.UUID, p: Principal = Depends(viewer)):
    async with _tx(p) as conn:
        t = await fetch_one(conn, "select * from turns where id=%s", (tid,))
        if t is None:
            raise HTTPException(404, "turn not found")
        t["trail"] = (await _trail(conn, [tid]))[str(tid)]
        t["messages"] = await fetch_all(conn, "select role, content, metadata, created_at from messages "
                                              "where turn_id=%s order by created_at", (tid,))
    return t


# ------------------------------------------------------------- audit trail

@router.get("/audit/search")
async def audit_search(customer: str | None = None, conversation: uuid.UUID | None = None, rule: str | None = None,
                       tool: str | None = None, limit: int = Query(100, le=1000), p: Principal = Depends(viewer)):
    async with _tx(p) as conn:
        rows = await fetch_all(conn, """
            select t.id as trace_id, t.created_at, t.conversation_id, t.turn_id, t.step, t.kind, t.summary, t.model,
              t.latency_ms, t.cost_usd, cu.email
            from turn_traces t left join customers cu on cu.id = t.customer_id
            where (%(conv)s::uuid is null or t.conversation_id = %(conv)s)
              and (%(cust)s::text is null or cu.email ilike '%%'||%(cust)s||'%%' or t.customer_id::text = %(cust)s)
              and (%(rule)s::text is null or exists (select 1 from rule_decisions d where d.turn_id=t.turn_id
                   and d.rule_key=%(rule)s and d.outcome <> 'allow') and t.kind in ('rules','plan','tool'))
              and (%(tool)s::text is null or exists (select 1 from tool_calls c where c.turn_id=t.turn_id
                   and c.tool_name=%(tool)s) and t.kind in ('plan','tool'))
            order by t.created_at desc limit %(limit)s""",
            {"conv": conversation, "cust": customer, "rule": rule, "tool": tool, "limit": limit})
    return {"items": rows}


@router.get("/audit/export")
async def audit_export(format: str = "json", conversation: uuid.UUID | None = None, customer: uuid.UUID | None = None,
                       p: Principal = Depends(viewer)):
    async with _tx(p) as conn:
        rows = await fetch_all(conn, """
            select t.created_at, t.conversation_id, t.turn_id, t.seq, t.step, t.kind, t.summary, t.model,
              t.latency_ms, t.input_tokens, t.output_tokens, t.cost_usd, t.input, t.output
            from turn_traces t
            where (%(conv)s::uuid is null or t.conversation_id=%(conv)s)
              and (%(cust)s::uuid is null or t.customer_id=%(cust)s)
            order by t.created_at, t.seq limit 20000""", {"conv": conversation, "cust": customer})
        await audit(conn, p, "audit.export", f"conversation:{conversation}" if conversation else "all",
                    {"format": format, "rows": len(rows)})
    if format == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        cols = list(rows[0].keys()) if rows else ["created_at"]
        w.writerow(cols)
        for r in rows:
            w.writerow([json.dumps(r[c], default=str) if isinstance(r[c], (dict, list)) else r[c] for c in cols])
        return Response(buf.getvalue(), media_type="text/csv",
                        headers={"content-disposition": "attachment; filename=cairn-trail.csv"})
    return Response(json.dumps(rows, default=str, indent=1), media_type="application/json",
                    headers={"content-disposition": "attachment; filename=cairn-trail.json"})


@router.get("/audit-log")
async def audit_log(limit: int = Query(200, le=1000), p: Principal = Depends(viewer)):
    async with _tx(p) as conn:
        return {"items": await fetch_all(conn, "select * from admin_audit order by at desc limit %s", (limit,))}


# ------------------------------------------------------------- approvals

@router.get("/approvals")
async def approvals_list(status: str = "pending_approval", p: Principal = Depends(viewer)):
    async with _tx(p) as conn:
        rows = await fetch_all(conn, """
            select tc.*, cu.email, cu.display_name, c.channel, c.intent,
              (select json_agg(json_build_object('role', m.role, 'content', m.content, 'at', m.created_at)
                               order by m.created_at)
               from messages m where m.conversation_id = tc.conversation_id) as transcript,
              (select json_agg(json_build_object('rule_key', d.rule_key, 'outcome', d.outcome, 'message', d.message))
               from rule_decisions d where d.turn_id = tc.turn_id and d.tool = tc.tool_name and d.outcome <> 'allow') as rules,
              (select t.description from tools t where t.name = tc.tool_name) as tool_description
            from tool_calls tc
            left join conversations c on c.id = tc.conversation_id
            left join customers cu on cu.id = tc.customer_id
            where not coalesce(c.is_test, false)
              and ((%(s)s = 'all' and tc.status in ('pending_approval','approved','denied','succeeded')
                    and (tc.approver_label is not null or tc.status='pending_approval'))
                   or tc.status = %(s)s)
            order by tc.created_at desc limit 200""", {"s": status})
    return {"items": rows}


class Decision(BaseModel):
    approve: bool
    note: str | None = None


@router.post("/approvals/{call_id}")
async def approvals_decide(call_id: uuid.UUID, body: Decision, p: Principal = Depends(builder)):
    from cairn.api.realtime import hub

    async with _tx(p) as conn:
        call = await fetch_one(conn, "select conversation_id from tool_calls where id=%s", (call_id,))
    if call is None:
        raise HTTPException(404, "not found")
    try:
        res = await approvals.decide(p.tenant_id, call_id, approve=body.approve, approver_id=p.user_id,
                                     approver_label=p.label, note=body.note,
                                     emit=hub.emitter(str(call["conversation_id"])))
    except approvals.ApprovalError as e:
        raise HTTPException(409, str(e)) from e
    return res.__dict__


# ------------------------------------------------------------ playground

class PlaygroundStart(BaseModel):
    email: str | None = None
    verified: bool = True


@router.post("/playground/sessions")
async def playground_start(body: PlaygroundStart, p: Principal = Depends(viewer)):
    ref = CustomerRef(email=body.email, verified=body.verified) if body.email else None
    cid, _ = await start_conversation(p.tenant_id, "playground", ref, is_test=True)
    return {"conversation_id": cid}


class PlaygroundMessage(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    use_draft: bool = True
    simulate_failure: str | None = Field(default=None, max_length=2000,
                                         description="Replace the first draft with this text to watch the supervisor")


@router.post("/playground/sessions/{cid}/messages")
async def playground_message(cid: uuid.UUID, body: PlaygroundMessage, p: Principal = Depends(viewer)):
    async with _tx(p) as conn:
        c = await fetch_one(conn, "select is_test, channel, state from conversations where id=%s", (cid,))
    if c is None or not c["is_test"]:
        raise HTTPException(404, "playground session not found")
    facts = (c["state"] or {}).get("facts", {})
    msg = Message(tenant_id=str(p.tenant_id), channel=ChannelInfo(type="playground"),
                  customer=CustomerRef(email=facts.get("email"), verified=bool(facts.get("verified"))),
                  content=body.content)
    events: list[dict] = []

    async def emit(e: dict) -> None:
        events.append(e)

    inject = {"drafts": [body.simulate_failure]} if body.simulate_failure else None
    res = await handle_message(msg, cid, emit=emit, use_draft_config=body.use_draft, inject=inject)
    async with _tx(p) as conn:
        t = await fetch_one(conn, "select * from turns where id=%s", (res.turn_id,))
        t["trail"] = (await _trail(conn, [res.turn_id]))[res.turn_id]
    return {"result": res.__dict__, "turn": t, "events": events}


# ---------------------------------------------------------------- config

@router.get("/config")
async def config_get(p: Principal = Depends(viewer)):
    async with _tx(p) as conn:
        versions = await fetch_all(conn, """
            select a.version, a.status, a.note, a.created_at, a.published_at, a.eval_run_id,
              cu.name as created_by, pu.name as published_by
            from agent_configs a left join users cu on cu.id=a.created_by left join users pu on pu.id=a.published_by
            order by a.version desc""")
        published, pv = await load_config(conn)
        draft, dv = await load_config(conn, draft=True)
    return {"published": {"version": pv, "config": published}, "draft": {"version": dv, "config": draft},
            "versions": versions, "defaults": DEFAULT_CONFIG}


@router.get("/config/versions/{version}")
async def config_version(version: int, p: Principal = Depends(viewer)):
    async with _tx(p) as conn:
        row = await fetch_one(conn, "select * from agent_configs where version=%s", (version,))
    if row is None:
        raise HTTPException(404, "version not found")
    row["config"] = merged(row["config"])
    return row


class DraftBody(BaseModel):
    config: dict[str, Any]
    note: str | None = None


@router.put("/config/draft")
async def config_save_draft(body: DraftBody, p: Principal = Depends(builder)):
    cfg = merged(body.config)
    async with _tx(p) as conn:
        draft = await fetch_one(conn, "select id, version from agent_configs where status='draft' "
                                      "order by version desc limit 1")
        if draft:
            await conn.execute("update agent_configs set config=%s, note=%s, created_by=%s where id=%s",
                               (Jsonb(cfg), body.note, p.user_id, draft["id"]))
            v = draft["version"]
        else:
            v = (await fetch_one(conn, "select coalesce(max(version),0)+1 as v from agent_configs"))["v"]
            await conn.execute("insert into agent_configs (tenant_id, version, status, config, note, created_by) "
                               "values (%s,%s,'draft',%s,%s,%s)", (p.tenant_id, v, Jsonb(cfg), body.note, p.user_id))
        await audit(conn, p, "config.save_draft", f"config:v{v}", {"note": body.note})
    return {"version": v}


class PublishBody(BaseModel):
    cost_signoff: str | None = None


async def _gate(p: Principal, config: dict, version: int, trigger: str, cost_signoff: str | None) -> dict:
    return await run_suite(p.tenant_id, config=config, version=version, trigger=trigger, cost_signoff=cost_signoff)


@router.post("/config/publish")
async def config_publish(body: PublishBody, p: Principal = Depends(builder)):
    async with _tx(p) as conn:
        draft = await fetch_one(conn, "select * from agent_configs where status='draft' order by version desc limit 1")
    if draft is None:
        raise HTTPException(409, "there is no draft to publish")
    report = await _gate(p, merged(draft["config"]), draft["version"], f"publish config v{draft['version']}",
                         body.cost_signoff)
    async with _tx(p) as conn:
        await conn.execute("update agent_configs set eval_run_id=%s where id=%s", (report["run_id"], draft["id"]))
        if not report["passed"]:
            await audit(conn, p, "config.publish_refused", f"config:v{draft['version']}",
                        {"run_id": report["run_id"], "gates": [g for g in report["gates"] if not g["passed"]]})
            raise HTTPException(409, {"message": "Publishing refused: a release gate failed", "report": report})
        await conn.execute("update agent_configs set status='archived' where status='published'")
        await conn.execute("update agent_configs set status='published', published_by=%s, published_at=now() "
                           "where id=%s", (p.user_id, draft["id"]))
        await audit(conn, p, "config.publish", f"config:v{draft['version']}",
                    {"run_id": report["run_id"], "signoff": body.cost_signoff})
    return {"published": draft["version"], "report": report}


class Rollback(BaseModel):
    version: int


@router.post("/config/rollback")
async def config_rollback(body: Rollback, p: Principal = Depends(builder)):
    async with _tx(p) as conn:
        target = await fetch_one(conn, "select * from agent_configs where version=%s", (body.version,))
        if target is None:
            raise HTTPException(404, "version not found")
        v = (await fetch_one(conn, "select coalesce(max(version),0)+1 as v from agent_configs"))["v"]
        await conn.execute("update agent_configs set status='archived' where status in ('published','draft')")
        await conn.execute("""
            insert into agent_configs (tenant_id, version, status, config, note, created_by, published_by, published_at)
            values (%s,%s,'published',%s,%s,%s,%s,now())""",
            (p.tenant_id, v, Jsonb(target["config"]), f"Rollback to v{body.version}", p.user_id, p.user_id))
        await audit(conn, p, "config.rollback", f"config:v{body.version}", {"new_version": v})
    return {"published": v, "restored_from": body.version}


# ----------------------------------------------------------------- rules

@router.get("/rules")
async def rules_list(p: Principal = Depends(viewer)):
    async with _tx(p) as conn:
        rows = await fetch_all(conn, """
            select distinct on (rule_key) r.*, (select max(version) from rules x where x.rule_key=r.rule_key
              and x.status='published') as published_version,
              (select count(*) from rule_decisions d join conversations c on c.id = d.conversation_id
               where d.rule_key=r.rule_key and d.outcome<>'allow' and not c.is_test
               and d.created_at > now() - interval '30 days') as firings_30d
            from rules r order by rule_key, version desc""")
    for r in rows:
        r["variables"] = jsonlogic.variables(r["condition"])
    return {"items": rows}


@router.get("/rules/{key}")
async def rule_get(key: str, p: Principal = Depends(viewer)):
    async with _tx(p) as conn:
        versions = await fetch_all(conn, "select * from rules where rule_key=%s order by version desc", (key,))
        recent = await fetch_all(conn, """
            select d.conversation_id, d.turn_id, d.outcome, d.message, d.tool, d.context, d.created_at
            from rule_decisions d join conversations c on c.id = d.conversation_id
            where d.rule_key=%s and d.outcome<>'allow' and not c.is_test
            order by d.created_at desc limit 20""", (key,))
    if not versions:
        raise HTTPException(404, "rule not found")
    return {"versions": versions, "recent_firings": recent}


class RuleBody(BaseModel):
    rule_key: str = Field(pattern=r"^[a-z0-9_]{3,60}$")
    name: str
    description: str = ""
    event: str = Field(pattern="^(tool_call|reply)$")
    tool: str | None = None
    condition: Any
    outcome: str = Field(pattern="^(allow|warn|block|require_approval)$")
    message: str = ""
    severity: str = "high"
    fixtures: list[dict] = []


@router.post("/rules")
async def rule_save_draft(body: RuleBody, p: Principal = Depends(builder)):
    try:
        jsonlogic.validate(body.condition)
    except jsonlogic.RuleSyntaxError as e:
        raise HTTPException(422, str(e)) from e
    async with _tx(p) as conn:
        cur = await fetch_one(conn, "select id, version, status from rules where rule_key=%s order by version desc "
                                    "limit 1", (body.rule_key,))
        if cur and cur["status"] == "draft":
            await conn.execute("""
                update rules set name=%s, description=%s, event=%s, tool=%s, condition=%s, outcome=%s, message=%s,
                  severity=%s, fixtures=%s, created_by=%s where id=%s""",
                (body.name, body.description, body.event, body.tool, Jsonb(body.condition), body.outcome, body.message,
                 body.severity, Jsonb(body.fixtures), p.user_id, cur["id"]))
            v = cur["version"]
        else:
            v = (cur["version"] + 1) if cur else 1
            await conn.execute("""
                insert into rules (tenant_id, rule_key, version, status, name, description, event, tool, condition,
                  outcome, message, severity, fixtures, created_by)
                values (%s,%s,%s,'draft',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (p.tenant_id, body.rule_key, v, body.name, body.description, body.event, body.tool,
                 Jsonb(body.condition), body.outcome, body.message, body.severity, Jsonb(body.fixtures), p.user_id))
        await audit(conn, p, "rule.save_draft", f"rule:{body.rule_key}@v{v}")
    rule = Rule(body.rule_key, v, body.name, body.event, body.condition, body.outcome, body.message, body.tool,
                body.severity, body.fixtures)
    return {"version": v, "fixture_failures": run_fixtures(rule)}


class RuleTest(BaseModel):
    context: dict[str, Any]


@router.post("/rules/{key}/test")
async def rule_test(key: str, body: RuleTest, p: Principal = Depends(viewer)):
    async with _tx(p) as conn:
        r = await fetch_one(conn, "select * from rules where rule_key=%s order by version desc limit 1", (key,))
    if r is None:
        raise HTTPException(404, "rule not found")
    rule = Rule.from_row(r)
    d = evaluate([rule], rule.event, body.context, tool=body.context.get("tool") or rule.tool)
    return {"fires": bool(d.firings), "outcome": d.outcome, "decision": d.as_dict(),
            "fixture_failures": run_fixtures(rule)}


@router.post("/rules/{key}/publish")
async def rule_publish(key: str, p: Principal = Depends(builder)):
    async with _tx(p) as conn:
        r = await fetch_one(conn, "select * from rules where rule_key=%s and status='draft' "
                                  "order by version desc limit 1", (key,))
        active = await fetch_all(conn, "select distinct on (rule_key) * from rules where status='published' "
                                       "order by rule_key, version desc")
    if r is None:
        raise HTTPException(409, "no draft version of this rule")
    rule = Rule.from_row(r)
    failures = run_fixtures(rule)
    if failures:
        async with _tx(p) as conn:
            await audit(conn, p, "rule.publish_refused", f"rule:{key}@v{r['version']}", {"fixtures": failures})
        raise HTTPException(409, {"message": "Publishing refused: a fixture failed", "fixture_failures": failures})
    # The release gate runs with the candidate rule set before anything goes live.
    candidate = [a for a in active if a["rule_key"] != key] + [r]
    async with _tx(p) as conn:
        cfg, v = await load_config(conn)
    cfg = {**cfg, "rules_override": candidate}
    report = await run_suite(p.tenant_id, config=cfg, version=v, trigger=f"publish rule {key}@v{r['version']}",
                             suites=["critical", "adversarial", "scenario"], include_judge=False)
    async with _tx(p) as conn:
        if not report["passed"]:
            await audit(conn, p, "rule.publish_refused", f"rule:{key}@v{r['version']}", {"run_id": report["run_id"]})
            raise HTTPException(409, {"message": "Publishing refused: a release gate failed", "report": report})
        await conn.execute("update rules set status='published', published_by=%s, published_at=now() where id=%s",
                           (p.user_id, r["id"]))
        await audit(conn, p, "rule.publish", f"rule:{key}@v{r['version']}", {"run_id": report["run_id"]})
    return {"published": r["version"], "report": report}


class Toggle(BaseModel):
    enabled: bool


@router.post("/rules/{key}/toggle")
async def rule_toggle(key: str, body: Toggle, p: Principal = Depends(admin)):
    async with _tx(p) as conn:
        await conn.execute("update rules set enabled=%s where rule_key=%s", (body.enabled, key))
        await audit(conn, p, "rule.enable" if body.enabled else "rule.disable", f"rule:{key}")
    return {"ok": True}


# ----------------------------------------------------------------- tools

@router.get("/tools")
async def tools_list(p: Principal = Depends(viewer)):
    async with _tx(p) as conn:
        rows = await fetch_all(conn, """
            select t.id, t.name, t.title, t.description, t.integration, t.server_url, t.input_schema, t.output_schema,
              t.risk_tier, t.requires_approval, t.is_write, t.pap_exposed, t.enabled, t.created_at,
              (t.credential_ciphertext is not null) as has_credential,
              (select count(*) from tool_calls c join conversations v on v.id = c.conversation_id
               where c.tool_name=t.name and not v.is_test) as calls,
              (select count(*) from tool_calls c join conversations v on v.id = c.conversation_id
               where c.tool_name=t.name and c.status='succeeded' and not v.is_test) as succeeded,
              (select round(avg(c.latency_ms)) from tool_calls c join conversations v on v.id = c.conversation_id
               where c.tool_name=t.name and c.latency_ms is not null and not v.is_test) as avg_latency_ms
            from tools t order by t.is_write, t.name""")
        recent = await fetch_all(conn, """
            select tc.id, tc.tool_name, tc.status, tc.risk_tier, tc.approver_label, tc.latency_ms, tc.created_at,
              tc.conversation_id from tool_calls tc left join conversations c on c.id = tc.conversation_id
            where not coalesce(c.is_test, false) order by tc.created_at desc limit 25""")
    return {"items": rows, "recent": recent}


class ToolPatch(BaseModel):
    risk_tier: str | None = Field(default=None, pattern="^(low|medium|high)$")
    requires_approval: bool | None = None
    enabled: bool | None = None
    pap_exposed: bool | None = None


@router.patch("/tools/{name}")
async def tool_patch(name: str, body: ToolPatch, p: Principal = Depends(builder)):
    changes = body.model_dump(exclude_none=True)
    if not changes:
        return {"ok": True}
    sets = ", ".join(f"{k}=%s" for k in changes)
    async with _tx(p) as conn:
        await conn.execute(f"update tools set {sets} where name=%s", (*changes.values(), name))
        await audit(conn, p, "tool.update", f"tool:{name}", changes)
    return {"ok": True}


class Credential(BaseModel):
    secret: str = Field(min_length=4)


@router.put("/tools/{name}/credential")
async def tool_credential(name: str, body: Credential, p: Principal = Depends(admin)):
    ct, wrapped = seal(body.secret.encode(), p.tenant_id)
    async with _tx(p) as conn:
        await conn.execute("update tools set credential_ciphertext=%s, credential_wrapped_key=%s where name=%s",
                           (ct, wrapped, name))
        await audit(conn, p, "tool.credential_set", f"tool:{name}")
    return {"ok": True}


# ------------------------------------------------------------- knowledge

@router.get("/knowledge")
async def knowledge_list(p: Principal = Depends(viewer)):
    async with _tx(p) as conn:
        rows = await fetch_all(conn, """
            select s.id, s.title, s.kind, s.owner, s.url, s.reviewed_at, s.review_interval_days, s.updated_at,
              length(s.content) as chars,
              (s.reviewed_at + make_interval(days => s.review_interval_days)) as review_due,
              (s.reviewed_at + make_interval(days => s.review_interval_days)) < now() as stale,
              (select count(*) from knowledge_chunks c where c.source_id = s.id) as chunks
            from knowledge_sources s order by s.title""")
    return {"items": rows}


@router.get("/knowledge/search")
async def knowledge_search(q: str, p: Principal = Depends(viewer)):
    async with _tx(p) as conn:
        return {"items": [h.as_dict() for h in await search(conn, q, k=5)]}


@router.get("/knowledge/{sid}")
async def knowledge_get(sid: uuid.UUID, p: Principal = Depends(viewer)):
    async with _tx(p) as conn:
        s = await fetch_one(conn, "select * from knowledge_sources where id=%s", (sid,))
        if s is None:
            raise HTTPException(404, "source not found")
        s["chunks"] = await fetch_all(conn, "select id, ord, heading, content from knowledge_chunks "
                                            "where source_id=%s order by ord", (sid,))
    return s


class SourceBody(BaseModel):
    title: str = Field(min_length=2)
    content: str = Field(min_length=10)
    owner: str = Field(min_length=2)
    kind: str = Field(default="policy", pattern="^(policy|faq|doc)$")
    url: str | None = None
    review_interval_days: int = 90


@router.post("/knowledge")
async def knowledge_create(body: SourceBody, p: Principal = Depends(builder)):
    async with _tx(p) as conn:
        s = await upsert_source(conn, p.tenant_id, **body.model_dump())
        await audit(conn, p, "knowledge.create", f"source:{s['id']}", {"title": body.title})
    return s


@router.put("/knowledge/{sid}")
async def knowledge_update(sid: uuid.UUID, body: SourceBody, p: Principal = Depends(builder)):
    async with _tx(p) as conn:
        s = await upsert_source(conn, p.tenant_id, source_id=sid, **body.model_dump())
        await audit(conn, p, "knowledge.update", f"source:{sid}", {"title": body.title})
    return s


@router.post("/knowledge/{sid}/review")
async def knowledge_review(sid: uuid.UUID, p: Principal = Depends(builder)):
    async with _tx(p) as conn:
        await conn.execute("update knowledge_sources set reviewed_at=now() where id=%s", (sid,))
        await audit(conn, p, "knowledge.review", f"source:{sid}")
    return {"ok": True}


@router.delete("/knowledge/{sid}")
async def knowledge_delete(sid: uuid.UUID, p: Principal = Depends(builder)):
    async with _tx(p) as conn:
        s = await fetch_one(conn, "delete from knowledge_sources where id=%s returning title", (sid,))
        await audit(conn, p, "knowledge.delete", f"source:{sid}", {"title": (s or {}).get("title")})
    return {"ok": True}


# ----------------------------------------------------------------- evals

@router.get("/evals/runs")
async def eval_runs(p: Principal = Depends(viewer)):
    async with _tx(p) as conn:
        return {"items": await fetch_all(conn, "select * from eval_runs order by started_at desc limit 50")}


@router.get("/evals/runs/{rid}")
async def eval_run(rid: uuid.UUID, p: Principal = Depends(viewer)):
    async with _tx(p) as conn:
        run = await fetch_one(conn, "select * from eval_runs where id=%s", (rid,))
        if run is None:
            raise HTTPException(404, "run not found")
        run["results"] = await fetch_all(conn, "select r.*, c.name from eval_results r left join eval_cases c "
                                               "on c.key = r.case_key where r.run_id=%s order by r.passed, r.case_key",
                                         (rid,))
    return run


class EvalRun(BaseModel):
    use_draft: bool = True
    suites: list[str] | None = None


@router.post("/evals/run")
async def eval_start(body: EvalRun, p: Principal = Depends(builder)):
    async with _tx(p) as conn:
        cfg, v = await load_config(conn, draft=body.use_draft)
    report = await run_suite(p.tenant_id, config=cfg, version=v, trigger=f"console ({p.label})", suites=body.suites)
    return report


@router.get("/evals/cases")
async def eval_cases(p: Principal = Depends(viewer)):
    async with _tx(p) as conn:
        rows = await fetch_all(conn, "select key, suite, name, category, critical, spec from eval_cases order by key")
    return {"items": rows}


class CaseBody(BaseModel):
    key: str = Field(pattern=r"^custom\.[a-z0-9_.-]{3,80}$")
    name: str
    category: str = "custom"
    critical: bool = False
    customer: dict | None = None
    turns: list[dict]


@router.post("/evals/cases")
async def eval_case_create(body: CaseBody, p: Principal = Depends(builder)):
    spec = {**body.model_dump(), "suite": "critical" if body.critical else "scenario"}
    async with _tx(p) as conn:
        await conn.execute("""
            insert into eval_cases (tenant_id, key, suite, name, category, critical, spec) values (%s,%s,%s,%s,%s,%s,%s)
            on conflict (tenant_id, key) do update set spec=excluded.spec, name=excluded.name""",
            (p.tenant_id, body.key, spec["suite"], body.name, body.category, body.critical, Jsonb(spec)))
        await audit(conn, p, "eval.case_save", f"case:{body.key}")
    return {"ok": True}


# ---------------------------------------------------- customers & privacy

@router.get("/customers")
async def customers(q: str | None = None, p: Principal = Depends(viewer)):
    async with _tx(p) as conn:
        rows = await fetch_all(conn, """
            select cu.*, (select count(*) from conversations c where c.customer_id=cu.id and not c.is_test) as conversations,
              (select count(*) from memory_items m where m.customer_id=cu.id) as memory_items
            from customers cu
            where %(q)s::text is null or cu.email ilike '%%'||%(q)s||'%%' or cu.display_name ilike '%%'||%(q)s||'%%'
            order by cu.last_seen_at desc limit 100""", {"q": q or None})
    return {"items": rows}


@router.get("/customers/{cid}")
async def customer(cid: uuid.UUID, p: Principal = Depends(viewer)):
    async with _tx(p) as conn:
        cu = await fetch_one(conn, "select * from customers where id=%s", (cid,))
        if cu is None:
            raise HTTPException(404, "customer not found")
        cu["memory"] = await fetch_all(conn, "select id, kind, content, source_conversation_id, created_at "
                                             "from memory_items where customer_id=%s order by created_at desc", (cid,))
        cu["conversations"] = await fetch_all(conn, """
            select c.id, c.channel, c.status, c.intent, c.started_at, o.type as outcome from conversations c
            left join outcomes o on o.conversation_id=c.id where c.customer_id=%s order by c.started_at desc""", (cid,))
        cu["pap_sessions"] = await fetch_all(conn, "select id, agent_identity, mode, scopes, created_at, revoked_at "
                                                   "from pap_sessions where customer_id=%s", (cid,))
    return cu


class Consent(BaseModel):
    memory_consent: bool


@router.patch("/customers/{cid}")
async def customer_consent(cid: uuid.UUID, body: Consent, p: Principal = Depends(builder)):
    async with _tx(p) as conn:
        await conn.execute("update customers set memory_consent=%s where id=%s", (body.memory_consent, cid))
        await audit(conn, p, "privacy.consent", f"customer:{cid}", body.model_dump())
    return {"ok": True}


@router.get("/customers/{cid}/export")
async def customer_export(cid: uuid.UUID, p: Principal = Depends(admin)):
    data = await export_customer(p.tenant_id, cid)
    async with _tx(p) as conn:
        await audit(conn, p, "privacy.export", f"customer:{cid}")
    return Response(json.dumps(data, default=str, indent=2), media_type="application/json",
                    headers={"content-disposition": f"attachment; filename=customer-{cid}.json"})


@router.post("/customers/{cid}/erase")
async def customer_erase(cid: uuid.UUID, p: Principal = Depends(admin)):
    async with _tx(p) as conn:
        exists = await fetch_one(conn, "select 1 from customers where id=%s", (cid,))
    if not exists:
        raise HTTPException(404, "customer not found")
    return await erase_customer(p.tenant_id, cid, p.label)


@router.get("/erasures")
async def erasures(p: Principal = Depends(viewer)):
    async with _tx(p) as conn:
        return {"items": await fetch_all(conn, "select * from erasure_requests order by requested_at desc")}


# --------------------------------------------------------------- outcomes

@router.get("/outcomes")
async def outcomes(status: str | None = None, billable: bool | None = None, limit: int = Query(100, le=500),
                   p: Principal = Depends(viewer)):
    async with _tx(p) as conn:
        rows = await fetch_all(conn, """
            select o.*, c.subject from outcomes o left join conversations c on c.id=o.conversation_id
            where not o.is_test and (%(s)s::text is null or o.status=%(s)s) and (%(b)s::bool is null or o.billable=%(b)s)
            order by o.ended_at desc limit %(l)s""", {"s": status, "b": billable, "l": limit})
    return {"items": rows}


@router.get("/outcomes/{oid}")
async def outcome(oid: uuid.UUID, p: Principal = Depends(viewer)):
    async with _tx(p) as conn:
        o = await fetch_one(conn, "select * from outcomes where id=%s", (oid,))
    if o is None:
        raise HTTPException(404, "outcome not found")
    return o


@router.get("/billing")
async def billing(p: Principal = Depends(viewer)):
    async with _tx(p) as conn:
        t = await fetch_one(conn, "select plan, settings from tenants where id=%s", (p.tenant_id,))
        month = await fetch_one(conn, """
            select count(*) filter (where billable) as billable, coalesce(sum(amount_usd),0) as usage_usd,
              count(*) filter (where status='final' and not billable) as free,
              count(*) filter (where status='pending') as pending
            from outcomes where not is_test and date_trunc('month', ended_at) = date_trunc('month', now())""")
        reasons = await fetch_all(conn, """
            select coalesce(nonbillable_reason, 'billable') as reason, count(*) as n from outcomes
            where not is_test and status='final' and date_trunc('month', ended_at) = date_trunc('month', now())
            group by 1 order by n desc""")
    plan = t["plan"]
    fee = PLAN_FEES.get(plan, 0)
    return {"plan": plan, "platform_fee_usd": fee, "rate_per_resolution_usd": PLAN_RATES.get(plan),
            "monthly_cap_usd": (t["settings"] or {}).get("monthly_cap_usd"), "month": month,
            "estimated_invoice_usd": round(fee + float(month["usage_usd"]), 2), "nonbillable_reasons": reasons,
            "rate_card": [
                {"plan": "Pilot", "duration": "90 days", "platform_fee": 1000, "per_resolution": 1.25,
                 "includes": "One workflow, one channel, one integration"},
                {"plan": "Growth", "platform_fee": 2000, "per_resolution": 1.00,
                 "includes": "Up to five workflows, chat and email, PAP gateway, three integrations"},
                {"plan": "Scale", "platform_fee": None, "per_resolution": None,
                 "includes": "SSO, data residency, support commitments"},
            ]}


# --------------------------------------------------------------------- PAP

@router.get("/pap")
async def pap_overview(p: Principal = Depends(viewer)):
    async with _tx(p) as conn:
        agents = await fetch_all(conn, """
            select a.*, (select count(*) from pap_actions x where x.agent_identity=a.agent_identity) as actions,
              (select max(created_at) from pap_actions x where x.agent_identity=a.agent_identity) as last_seen
            from pap_agents a order by a.created_at""")
        sessions = await fetch_all(conn, """
            select s.id, s.agent_identity, s.mode, s.scopes, s.consent, s.created_at, s.expires_at, s.revoked_at,
              cu.email from pap_sessions s left join customers cu on cu.id=s.customer_id
            where s.mode <> 'pending_consent' order by s.created_at desc limit 50""")
        actions = await fetch_all(conn, "select * from pap_actions order by created_at desc limit 100")
        slug = (await fetch_one(conn, "select slug from tenants where id=%s", (p.tenant_id,)))["slug"]
    from cairn.pap.gateway import manifest

    return {"agents": agents, "sessions": sessions, "actions": actions,
            "manifest": await manifest(p.tenant_id, slug, get_settings().public_url)}


class AgentBody(BaseModel):
    agent_identity: str = Field(pattern=r"^agent://.+")
    display_name: str
    status: str = Field(default="allow", pattern="^(allow|deny)$")
    rate_limit_per_min: int = Field(default=30, ge=0, le=6000)


@router.post("/pap/agents")
async def pap_agent_upsert(body: AgentBody, p: Principal = Depends(admin)):
    async with _tx(p) as conn:
        await conn.execute("""
            insert into pap_agents (tenant_id, agent_identity, display_name, status, rate_limit_per_min)
            values (%s,%s,%s,%s,%s)
            on conflict (tenant_id, agent_identity) do update set display_name=excluded.display_name,
              status=excluded.status, rate_limit_per_min=excluded.rate_limit_per_min""",
            (p.tenant_id, body.agent_identity, body.display_name, body.status, body.rate_limit_per_min))
        await audit(conn, p, "pap.agent_update", body.agent_identity, body.model_dump())
    return {"ok": True}


@router.post("/pap/sessions/{sid}/revoke")
async def pap_revoke(sid: uuid.UUID, p: Principal = Depends(builder)):
    await revoke(p.tenant_id, sid, p.label)
    async with _tx(p) as conn:
        await audit(conn, p, "pap.revoke", f"pap_session:{sid}")
    return {"ok": True}


# ---------------------------------------------------------------- settings

@router.get("/settings")
async def settings(p: Principal = Depends(viewer)):
    async with _tx(p) as conn:
        t = await fetch_one(conn, "select id, name, slug, plan, settings, widget_key, created_at from tenants "
                                  "where id=%s", (p.tenant_id,))
        users = await fetch_all(conn, "select id, email, name, role, created_at, last_login_at from users order by created_at")
        keys = await fetch_all(conn, "select id, name, prefix, scopes, created_at, last_used_at, revoked_at "
                                     "from api_keys order by created_at desc")
    return {"tenant": t, "users": users, "api_keys": keys}


class TenantSettings(BaseModel):
    retention_days: int | None = Field(default=None, ge=7, le=3650)
    monthly_cap_usd: float | None = None
    plan: str | None = Field(default=None, pattern="^(pilot|growth|scale)$")


@router.patch("/settings")
async def settings_patch(body: TenantSettings, p: Principal = Depends(admin)):
    changes = body.model_dump(exclude_none=True)
    async with _tx(p) as conn:
        if "plan" in changes:
            await conn.execute("update tenants set plan=%s where id=%s", (changes.pop("plan"), p.tenant_id))
        if changes:
            await conn.execute("update tenants set settings = settings || %s where id=%s", (Jsonb(changes), p.tenant_id))
        await audit(conn, p, "settings.update", "tenant", body.model_dump(exclude_none=True))
    return {"ok": True}


class UserBody(BaseModel):
    email: str
    name: str
    role: str = Field(pattern="^(admin|builder|viewer)$")
    password: str = Field(min_length=8)


@router.post("/users")
async def user_create(body: UserBody, p: Principal = Depends(admin)):
    async with _tx(p) as conn:
        row = await fetch_one(conn, "insert into users (tenant_id, email, name, password_hash, role) "
                                    "values (%s,lower(%s),%s,%s,%s) returning id",
                              (p.tenant_id, body.email, body.name, hash_password(body.password), body.role))
        await audit(conn, p, "user.create", f"user:{row['id']}", {"email": body.email, "role": body.role})
    return {"id": row["id"]}


class RoleBody(BaseModel):
    role: str = Field(pattern="^(admin|builder|viewer)$")


@router.patch("/users/{uid}")
async def user_role(uid: uuid.UUID, body: RoleBody, p: Principal = Depends(admin)):
    if uid == p.user_id:
        raise HTTPException(409, "you cannot change your own role")
    async with _tx(p) as conn:
        before = await fetch_one(conn, "select role from users where id=%s", (uid,))
        await conn.execute("update users set role=%s where id=%s", (body.role, uid))
        await audit(conn, p, "user.role_change", f"user:{uid}", {"from": (before or {}).get("role"), "to": body.role})
    return {"ok": True}


class KeyBody(BaseModel):
    name: str
    scopes: list[str] = ["read"]


@router.post("/api-keys")
async def key_create(body: KeyBody, p: Principal = Depends(admin)):
    allowed = {"read", "write", "admin", "email:inbound", "chat"}
    scopes = sorted(set(body.scopes) & allowed) or ["read"]
    token = random_token("ck")
    async with _tx(p) as conn:
        row = await fetch_one(conn, "insert into api_keys (tenant_id, name, prefix, key_hash, scopes, created_by) "
                                    "values (%s,%s,%s,%s,%s,%s) returning id",
                              (p.tenant_id, body.name, token[:10], sha256(token), scopes, p.user_id))
        await audit(conn, p, "api_key.create", f"api_key:{row['id']}", {"name": body.name, "scopes": scopes})
    return {"id": row["id"], "key": token, "scopes": scopes}


@router.delete("/api-keys/{kid}")
async def key_revoke(kid: uuid.UUID, p: Principal = Depends(admin)):
    async with _tx(p) as conn:
        await conn.execute("update api_keys set revoked_at=now() where id=%s", (kid,))
        await audit(conn, p, "api_key.revoke", f"api_key:{kid}")
    return {"ok": True}
