"""The agent orchestrator (F2).

Each customer turn runs as a state machine of small steps:

    triage ─┬─> retrieve ─────────────> draft ─> supervise ─┬─> reply_rules ─> respond
            ├─> act (plan → tool) ─┬──> draft                ├─> draft (revise, at most twice)
            ├─> execute_pending ───┘                         ├─> blocked
            └─> escalate <───────────────────────────────────┘
                 (budgets, sensitive topics, supervisor timeouts, model outages)

State is checkpointed to Postgres after every step, together with that
step's trace record, so a killed process resumes at the last completed
step (``resume_turn``) and a turn can park while a human approves an
action and pick up where it left off (``continue_after_approval``).
"""

from __future__ import annotations

import asyncio
import copy
import json
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from psycopg import AsyncConnection

from cairn.channels.message import Message
from cairn.db.core import Jsonb, fetch_all, fetch_one, tenant_tx, vec
from cairn.engine import skills
from cairn.engine.config import load_config
from cairn.jobs.queue import enqueue
from cairn.knowledge.embed import embed
from cairn.knowledge.store import search
from cairn.llm.gateway import ModelCall, ModelGateway, ModelResult, ModelUnavailable
from cairn.rules.engine import Decision, Rule, evaluate, load_active_rules
from cairn.security.pii import Tokenizer, find_pii, mask_obj, mask_text
from cairn.supervisor import detectors
from cairn.supervisor.supervisor import ReviewInput, review
from cairn.tools import layer
from cairn.tools.layer import ToolSpec

Emit = Callable[[dict], Awaitable[None]]

ACT_INTENTS = {"order_status", "refund_request", "cancel_subscription", "change_address"}

STEP_LABELS = {
    "triage": "Understanding your request",
    "retrieve": "Checking our policies",
    "act": "Looking into your account",
    "execute_pending": "Taking care of it",
    "execute_approved": "Completing the approved request",
    "draft": "Writing a reply",
    "supervise": "Double-checking the reply",
    "reply_rules": "Applying business rules",
    "respond": "Sending",
    "escalate": "Connecting you with our team",
    "blocked": "Sending",
}

SAFE_DECLINE = ("I'm sorry, I can't help with that. I can help with orders, refunds, shipping and Trail Club "
                "membership. Is there something along those lines I can do for you?")
ESCALATION_MESSAGE = ("I'm bringing in a member of our team who can help with this. They'll see our whole "
                      "conversation, so you won't need to repeat anything.")


class SimulatedCrash(RuntimeError):
    """Raised by tests and the eval harness to kill a turn after a step."""


@dataclass
class TurnContext:
    tenant_id: uuid.UUID
    conversation_id: uuid.UUID
    turn_id: uuid.UUID
    config: dict
    config_version: int
    gateway: ModelGateway
    rules: list[Rule]
    tools: dict[str, ToolSpec]
    emit: Emit
    is_test: bool = False
    inject: dict = field(default_factory=dict)

    def tx(self):
        return tenant_tx(self.tenant_id)


@dataclass
class TurnResult:
    turn_id: str
    conversation_id: str
    status: str
    action: str
    reply: str
    verdict: str | None
    citations: list[dict]
    latency_ms: int
    cost_usd: float
    steps: int
    approval: dict | None = None


async def _noop(_: dict) -> None:
    return None


# ----------------------------------------------------------------- entry

_locks: dict[str, asyncio.Lock] = {}


def _lock(conversation_id) -> asyncio.Lock:
    key = str(conversation_id)
    if key not in _locks:
        _locks[key] = asyncio.Lock()
    return _locks[key]


async def handle_message(
    msg: Message, conversation_id: uuid.UUID, *, emit: Emit | None = None, config_override: dict | None = None,
    config_version: int | None = None, inject: dict | None = None, use_draft_config: bool = False,
) -> TurnResult:
    """Run one customer turn end to end."""
    tenant_id = uuid.UUID(msg.tenant_id)
    emit = emit or _noop
    async with _lock(conversation_id):
        async with tenant_tx(tenant_id) as conn:
            conv = await fetch_one(conn, "select * from conversations where id=%s for update", (conversation_id,))
            if conv is None:
                raise LookupError("conversation not found")
            seq = (await fetch_one(conn, "select coalesce(max(seq),0)+1 as n from turns where conversation_id=%s",
                                   (conversation_id,)))["n"]
            turn = await fetch_one(conn, """
                insert into turns (tenant_id, conversation_id, customer_id, seq, config_version)
                values (%s,%s,%s,%s,%s) returning id""",
                (tenant_id, conversation_id, conv["customer_id"], seq, config_version))
            mrow = await fetch_one(conn, """
                insert into messages (tenant_id, conversation_id, customer_id, turn_id, role, channel, content,
                  attachments, metadata)
                values (%s,%s,%s,%s,%s,%s,%s,%s,%s) returning id""",
                (tenant_id, conversation_id, conv["customer_id"], turn["id"],
                 "outside_agent" if msg.channel.type == "pap" else "customer", msg.channel.type, msg.content,
                 Jsonb([a.model_dump() for a in msg.attachments]), Jsonb({**msg.metadata, "channel": msg.channel.model_dump()})))
            await conn.execute("update turns set input_message_id=%s where id=%s", (mrow["id"], turn["id"]))
            await conn.execute("update conversations set last_activity_at=now() where id=%s", (conversation_id,))
            cfg, version = (config_override, config_version or 0) if config_override else await load_config(
                conn, draft=use_draft_config)
            await conn.execute("update turns set config_version=%s where id=%s", (version, turn["id"]))
            history = await _history(conn, conversation_id, exclude=mrow["id"])
            cstate = conv["state"] or {}

        state: dict[str, Any] = {
            "seq": seq, "steps": 0, "channel": msg.channel.type, "t0": time.time(),
            "cost_usd": float(cstate.get("cost_usd", 0.0)),
            "message": {"id": str(mrow["id"]), "content": msg.content},
            "history": history,
            "facts": cstate.get("facts", {}),
            "pending_action": cstate.get("pending_action"),
            "pending_approval": cstate.get("pending_approval"),
            "awaiting": cstate.get("awaiting"),
            "tok": cstate.get("tok", {}),
            "customer_id": str(conv["customer_id"]) if conv["customer_id"] else None,
            "untrusted_source": "outside_agent" if msg.channel.type == "pap" else "customer",
            "results": [], "attempts": 0, "verdicts": [], "act_iterations": 0,
            "next": "triage",
        }
        if msg.customer.verified and msg.customer.email:
            state["facts"]["verified"] = True
            state["facts"]["email"] = msg.customer.email
        ctx = await _context(tenant_id, conversation_id, turn["id"], cfg, version, emit, conv["is_test"], inject)
        await _checkpoint(ctx, state, "start", 0)
        return await _run(ctx, state)


async def resume_turn(tenant_id: uuid.UUID, turn_id: uuid.UUID, *, emit: Emit | None = None,
                      inject: dict | None = None) -> TurnResult:
    """Continue a turn from its last checkpoint (after a crash or restart)."""
    async with tenant_tx(tenant_id) as conn:
        cp = await fetch_one(conn, "select * from checkpoints where turn_id=%s order by step_index desc limit 1",
                             (turn_id,))
        turn = await fetch_one(conn, "select * from turns where id=%s", (turn_id,))
        if cp is None or turn is None:
            raise LookupError("no checkpoint for turn")
        conv = await fetch_one(conn, "select is_test from conversations where id=%s", (turn["conversation_id"],))
        cfg, version = await load_config(conn, version=turn["config_version"])
    state = cp["state"]
    if not state.get("next"):
        return _result_from_state(turn_id, turn["conversation_id"], state)
    ctx = await _context(tenant_id, turn["conversation_id"], turn_id, cfg, version, emit or _noop,
                         conv["is_test"], inject)
    async with _lock(turn["conversation_id"]):
        return await _run(ctx, state)


async def continue_after_approval(tenant_id: uuid.UUID, call_id: uuid.UUID, *, emit: Emit | None = None) -> TurnResult:
    """Resume a parked conversation once a human approved or denied its action."""
    async with tenant_tx(tenant_id) as conn:
        call = await fetch_one(conn, "select * from tool_calls where id=%s", (call_id,))
        if call is None or call["status"] not in ("approved", "denied"):
            raise ValueError("call is not decided")
        parked = await fetch_one(conn, "select * from checkpoints where turn_id=%s order by step_index desc limit 1",
                                 (call["turn_id"],))
        conv = await fetch_one(conn, "select * from conversations where id=%s", (call["conversation_id"],))
        seq = (await fetch_one(conn, "select coalesce(max(seq),0)+1 as n from turns where conversation_id=%s",
                               (conv["id"],)))["n"]
        prev_turn = await fetch_one(conn, "select config_version from turns where id=%s", (call["turn_id"],))
        turn = await fetch_one(conn, """
            insert into turns (tenant_id, conversation_id, customer_id, seq, config_version)
            values (%s,%s,%s,%s,%s) returning id""",
            (tenant_id, conv["id"], conv["customer_id"], seq, prev_turn["config_version"]))
        cfg, version = await load_config(conn, version=prev_turn["config_version"])
        history = await _history(conn, conv["id"])
    state = copy.deepcopy(parked["state"])
    state.update({
        "seq": seq, "steps": 0, "t0": time.time(), "history": history, "results": [], "attempts": 0,
        "verdicts": [], "act_iterations": 0, "draft": None, "feedback": None,
        "facts": (conv["state"] or {}).get("facts", state.get("facts", {})),
        "approval_call_id": str(call_id), "next": "execute_approved",
        "customer_id": str(conv["customer_id"]) if conv["customer_id"] else None, "final": None,
        "message": {"id": None, "content": ""},
    })
    ctx = await _context(tenant_id, conv["id"], turn["id"], cfg, version, emit or _noop, conv["is_test"], None)
    async with _lock(conv["id"]):
        await _checkpoint(ctx, state, "start", 0)
        return await _run(ctx, state)


async def _context(tenant_id, conversation_id, turn_id, cfg, version, emit, is_test, inject) -> TurnContext:
    async with tenant_tx(tenant_id) as conn:
        rules = await load_active_rules(conn)
        tools = await layer.load_tools(conn)
    if cfg.get("rules_override") is not None:
        rules = [Rule.from_row(r) for r in cfg["rules_override"]]
    return TurnContext(tenant_id, conversation_id, turn_id, cfg, version, ModelGateway(cfg.get("models")),
                       rules, tools, emit, is_test, inject or {})


async def _history(conn: AsyncConnection, conversation_id, exclude=None, limit: int = 12) -> list[dict]:
    rows = await fetch_all(conn, """
        select role, content from messages where conversation_id=%s and (%s::uuid is null or id <> %s::uuid)
        order by created_at desc limit %s""", (conversation_id, exclude, exclude, limit))
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


# ------------------------------------------------------------- the loop

async def _run(ctx: TurnContext, state: dict) -> TurnResult:
    limits = ctx.config.get("limits", {})
    max_steps = int(limits.get("max_steps_per_turn", 16))
    budget = float(limits.get("cost_budget_per_conversation_usd", 0.75))
    while state.get("next"):
        step = state["next"]
        if step not in ("escalate", "respond", "blocked"):
            if state["steps"] >= max_steps:
                state["escalation"] = {"code": "step_limit", "reason": f"step limit of {max_steps} reached"}
                step = "escalate"
            elif state["cost_usd"] >= budget:
                state["escalation"] = {"code": "cost_budget", "reason": f"cost budget of ${budget:.2f} reached"}
                step = "escalate"
        await ctx.emit({"type": "status", "step": step, "label": STEP_LABELS.get(step, step)})
        t0 = time.perf_counter()
        trace: dict[str, Any] = {"kind": "step", "summary": "", "model": None, "input": {}, "output": {},
                                 "tokens": (0, 0), "cost": 0.0}
        try:
            nxt = await STEPS[step](ctx, state, trace)
        except ModelUnavailable as e:
            state["escalation"] = {"code": "model_unavailable", "reason": str(e)[:300]}
            trace.update(kind="error", summary="Every configured model failed; failing closed")
            nxt = "escalate"
        state["steps"] += 1
        state["next"] = nxt
        latency = int((time.perf_counter() - t0) * 1000)
        await _checkpoint(ctx, state, step, state["steps"], trace=trace, latency=latency)
        if ctx.inject.get("crash_after") == step:
            raise SimulatedCrash(f"simulated crash after {step}")
    return _result_from_state(ctx.turn_id, ctx.conversation_id, state)


def _result_from_state(turn_id, conversation_id, state: dict) -> TurnResult:
    final = state.get("final") or {}
    return TurnResult(
        turn_id=str(turn_id), conversation_id=str(conversation_id), status=final.get("status", "completed"),
        action=final.get("action", "reply"), reply=final.get("text", ""), verdict=final.get("verdict"),
        citations=final.get("citations", []), latency_ms=final.get("latency_ms", 0),
        cost_usd=round(state.get("turn_cost", 0.0), 6), steps=state.get("steps", 0),
        approval=state.get("pending_approval"),
    )


async def _checkpoint(ctx: TurnContext, state: dict, step: str, index: int, *, trace: dict | None = None,
                      latency: int = 0) -> None:
    async with ctx.tx() as conn:
        await conn.execute("""
            insert into checkpoints (tenant_id, conversation_id, customer_id, turn_id, step_index, step, next_step, state)
            values (%s,%s,%s,%s,%s,%s,%s,%s)""",
            (ctx.tenant_id, ctx.conversation_id, state.get("customer_id"), ctx.turn_id, index, step,
             state.get("next"), Jsonb(state)))
        if trace is not None:
            tin, tout = trace["tokens"]
            await conn.execute("""
                insert into turn_traces (tenant_id, conversation_id, customer_id, turn_id, seq, step, kind, summary,
                  model, input, output, latency_ms, input_tokens, output_tokens, cost_usd)
                values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (ctx.tenant_id, ctx.conversation_id, state.get("customer_id"), ctx.turn_id, index, step,
                 trace["kind"], trace["summary"], trace["model"], Jsonb(mask_obj(trace["input"])),
                 Jsonb(mask_obj(trace["output"])), latency, tin, tout, trace["cost"]))
            await conn.execute("update turns set steps=%s, cost_usd=cost_usd+%s where id=%s",
                               (index, trace["cost"], ctx.turn_id))


def _account(state: dict, trace: dict, res: ModelResult) -> None:
    state["cost_usd"] = state.get("cost_usd", 0.0) + res.cost_usd
    state["turn_cost"] = state.get("turn_cost", 0.0) + res.cost_usd
    tin, tout = trace["tokens"]
    trace["tokens"] = (tin + res.input_tokens, tout + res.output_tokens)
    trace["cost"] = round(trace["cost"] + res.cost_usd, 6)
    trace["model"] = res.model + (" (fallback)" if res.fallback_used else "")


def _brand(ctx: TurnContext) -> str:
    return ctx.config.get("brand", {}).get("name", "Acme Outfitters")


# ------------------------------------------------------------------ steps

async def step_triage(ctx: TurnContext, state: dict, trace: dict) -> str:
    tok = Tokenizer.from_state(state["tok"])
    text = state["message"]["content"]
    safe_text = tok.protect(text)
    state["tok"] = tok.to_state()
    policy = ctx.config.get("policy", {})

    async def screen() -> dict:
        # Input screening runs in parallel with triage (supervisor, F3).
        return {"injection": detectors.detect_injection(text),
                "sensitive": detectors.detect_sensitive(text, policy.get("sensitive_topics", []))}

    pending = state.get("pending_action")
    awaiting = state.get("awaiting")
    call = ModelCall(
        step="triage", system=skills.TRIAGE_SYSTEM.format(brand=_brand(ctx)),
        prompt=(f"<pending_action>{json.dumps(pending) if pending else 'none'}</pending_action>\n"
                f"<awaiting_answer_for>{awaiting or 'none'}</awaiting_answer_for>\n"
                f"<untrusted kind=\"history\">{json.dumps([{'role': h['role'], 'content': tok.protect(h['content'])} for h in state['history'][-6:]])}</untrusted>\n"
                f"<untrusted kind=\"{state['untrusted_source']}_message\">{safe_text}</untrusted>"),
        schema=skills.TRIAGE_SCHEMA,
        sandbox=lambda: skills.sandbox_triage(safe_text, pending_action=pending, awaiting=awaiting),
        max_tokens=1024,
    )
    res, scr = await asyncio.gather(ctx.gateway.run(call), screen())
    _account(state, trace, res)
    tri = res.data
    state["intent"] = tri["intent"]
    state["triage"] = tri
    state["injection"] = scr["injection"]
    state["sensitive"] = scr["sensitive"]
    facts = state["facts"]
    for k in ("order_id", "amount", "address"):
        if tri.get(k):
            facts[k] = tri[k]
    if tri.get("email") and not (facts.get("verified") and facts.get("email")):
        facts["email"] = tok.reveal(tri["email"])
    trace.update(kind="model", summary=f"Intent {tri['intent']} ({tri['confidence']:.0%})"
                 + (f" · injection signals: {len(scr['injection'])}" if scr["injection"] else ""),
                 input={"message": text, "pending_action": pending},
                 output={**tri, "injection": scr["injection"], "sensitive": scr["sensitive"]})

    intent = tri["intent"]
    if pending and intent not in ("confirm_yes", "confirm_no"):
        state["pending_action"] = None
    if any(s["action"] == "escalate" for s in scr["sensitive"]):
        state["escalation"] = {"code": "sensitive_topic",
                               "reason": "Sensitive topic: " + ", ".join(s["topic"] for s in scr["sensitive"])}
        return "escalate"
    if intent == "human_request":
        state["escalation"] = {"code": "customer_request", "reason": "Customer asked for a person"}
        return "escalate"
    if intent == "confirm_yes" and pending:
        return "execute_pending"
    if intent == "confirm_no" and pending:
        state["pending_action"] = None
        state["draft_kind"] = "declined_confirmation"
        return "draft"
    if intent in ACT_INTENTS:
        return "act"
    return "retrieve"


async def step_retrieve(ctx: TurnContext, state: dict, trace: dict) -> str:
    q = f"{state['triage'].get('search_query', '')} {state['message']['content']}".strip()
    for _, value in find_pii(q):
        q = q.replace(value, " ")  # personal data is never a search term
    q = re.sub(r"<[A-Z]+_\d+>", " ", q)
    async with ctx.tx() as conn:
        hits = await search(conn, q, k=int(ctx.config.get("retrieval", {}).get("top_k", 3)))
        memory = await _recall(ctx, conn, state, q)
    if state.get("intent") == "out_of_scope" and not state.get("injection") and hits and hits[0].coverage >= 0.6:
        # Knowledge-aware triage: the tenant's own sources answer it, so it is in scope.
        state["intent"] = "policy_question"
    elif state.get("intent") == "out_of_scope":
        hits = []
    state["sources"] = [h.as_dict() for h in hits]
    state["memory"] = memory
    state.setdefault("draft_kind", "answer")
    trace.update(kind="retrieval", summary=f"{len(hits)} source chunk(s), {len(memory)} memory item(s)",
                 input={"query": q},
                 output={"sources": [{"chunk_id": h.chunk_id, "title": h.title, "heading": h.heading,
                                      "score": h.score, "stale": h.stale, "content": h.content[:400]} for h in hits],
                         "memory": memory})
    return "draft"


async def _recall(ctx: TurnContext, conn: AsyncConnection, state: dict, q: str) -> list[str]:
    mem_cfg = ctx.config.get("memory", {})
    cid = state.get("customer_id")
    if not cid or not mem_cfg.get("enabled", True):
        return []
    if state.get("intent") not in set(mem_cfg.get("workflows", list(ACT_INTENTS) + ["policy_question", "complaint"])):
        return []
    cust = await fetch_one(conn, "select memory_consent from customers where id=%s", (cid,))
    if not cust or not cust["memory_consent"]:
        return []
    rows = await fetch_all(conn, """
        select content from memory_items where customer_id=%s and (source_conversation_id is distinct from %s)
        order by embedding <=> %s::vector limit 3""", (cid, ctx.conversation_id, vec(embed(q))))
    return [r["content"] for r in rows]


def _rule_context(ctx: TurnContext, state: dict) -> dict:
    f = state["facts"]
    return {
        "customer": {"verified": bool(f.get("verified")), "email": f.get("email")},
        "order": f.get("order") or {},
        "subscription": f.get("subscription") or {},
        "conversation": {"channel": state["channel"], "turn": state["seq"],
                         "outside_agent": state["untrusted_source"] == "outside_agent"},
        "intent": state.get("intent"),
    }


async def _log_decision(ctx: TurnContext, state: dict, decision: Decision, event: str, tool: str | None,
                        context: dict) -> None:
    fired = {f.rule_key: f for f in decision.firings}
    async with ctx.tx() as conn:
        for key in decision.evaluated:
            rule = next(r for r in ctx.rules if r.rule_key == key)
            f = fired.get(key)
            await conn.execute("""
                insert into rule_decisions (tenant_id, conversation_id, customer_id, turn_id, rule_key, rule_version,
                  event, tool, outcome, message, context)
                values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (ctx.tenant_id, ctx.conversation_id, state.get("customer_id"), ctx.turn_id, key, rule.version, event,
                 tool, f.outcome if f else "allow", f.message if f else "", Jsonb(mask_obj(context))))


def _absorb(state: dict, tool: str, args: dict, out: dict | None, status: str) -> None:
    f = state["facts"]
    if status != "succeeded" or out is None:
        return
    if tool == "lookup_order":
        f["order"] = out
        f["order_id"] = out.get("order_id")
    elif tool == "verify_customer":
        if out.get("verified"):
            f["verified"] = True
            f["email"] = args["email"]
            f.pop("verify_failed", None)
        else:
            f["verify_failed"] = True
    elif tool == "lookup_subscription":
        f["subscription"] = out


async def _link_customer(ctx: TurnContext, state: dict) -> None:
    """Identity resolution: attach a verified email to a customer record."""
    email = state["facts"].get("email")
    if not (state["facts"].get("verified") and email) or state.get("customer_id"):
        return
    async with ctx.tx() as conn:
        row = await fetch_one(conn, """
            insert into customers (tenant_id, email) values (%s, lower(%s))
            on conflict (tenant_id, email) do update set last_seen_at = now() returning id""", (ctx.tenant_id, email))
        cid = row["id"]
        for table in ("conversations",):
            await conn.execute(f"update {table} set customer_id=%s where id=%s", (cid, ctx.conversation_id))
        for table in ("messages", "turns", "checkpoints", "chat_sessions", "tool_calls"):
            await conn.execute(f"update {table} set customer_id=%s where conversation_id=%s and customer_id is null",
                               (cid, ctx.conversation_id))
    state["customer_id"] = str(cid)


async def step_act(ctx: TurnContext, state: dict, trace: dict) -> str:
    state["act_iterations"] += 1
    if state["act_iterations"] > 6:
        state["escalation"] = {"code": "plan_loop", "reason": "Too many planning iterations"}
        return "escalate"
    tok = Tokenizer.from_state(state["tok"])
    facts = state["facts"]
    tools = [t.prompt_view() for t in ctx.tools.values()]
    model_facts = {k: v for k, v in facts.items() if k != "order"}
    if facts.get("order"):
        model_facts["order"] = facts["order"]
    call = ModelCall(
        step="plan", system=skills.PLAN_SYSTEM.format(brand=_brand(ctx)),
        prompt=(f"<intent>{state['intent']}</intent>\n<tools>{json.dumps(tools)}</tools>\n"
                f"<facts>{tok.protect(json.dumps(model_facts))}</facts>\n"
                f"<untrusted kind=\"tool_results\">{tok.protect(json.dumps(state['results']))}</untrusted>\n"
                f"<untrusted kind=\"{state['untrusted_source']}_message\">{tok.protect(state['message']['content'])}</untrusted>\n"
                "Choose the next action."),
        schema=skills.PLAN_SCHEMA, sandbox=lambda: skills.sandbox_plan(state["intent"], facts, state["results"]),
        max_tokens=2048,
    )
    res = await ctx.gateway.run(call)
    _account(state, trace, res)
    plan = res.data
    trace.update(kind="plan", summary=f"Plan: {plan['action']}" + (f" {plan['tool']}" if plan.get("tool") else ""),
                 input={"intent": state["intent"], "facts": facts}, output=plan)

    if plan["action"] == "ask":
        state["draft_kind"] = "ask"
        state["question"] = tok.reveal(plan.get("question") or "Could you tell me a bit more?")
        return "draft"
    if plan["action"] == "escalate":
        state["escalation"] = {"code": "planner", "reason": plan.get("reason", "Planner escalated")}
        return "escalate"
    if plan["action"] == "respond":
        state["draft_kind"] = "answer"
        return "retrieve" if not state.get("sources") and state["intent"] != "order_status" else "draft"

    spec = ctx.tools.get(plan.get("tool") or "")
    try:
        args = tok.reveal(json.loads(plan.get("arguments_json") or "{}"))
    except json.JSONDecodeError:
        args = None
    if spec is None or not isinstance(args, dict):
        state["results"].append({"tool": plan.get("tool"), "args": args, "status": "refused",
                                 "error": "unknown tool or malformed arguments"})
        trace["summary"] += " · refused (unknown tool or malformed arguments)"
        return "act"

    rctx = _rule_context(ctx, state)
    ids = {"conversation_id": ctx.conversation_id, "customer_id": state.get("customer_id"), "turn_id": ctx.turn_id}
    if spec.is_write and ctx.config.get("confirm_writes", True):
        # Check rules before asking: never ask a customer to confirm something policy forbids.
        decision = evaluate(ctx.rules, "tool_call", {**rctx, "tool": spec.name, "args": args}, tool=spec.name)
        await _log_decision(ctx, state, decision, "tool_call", spec.name, {**rctx, "args": args})
        trace["output"] = {**plan, "rules": decision.as_dict()}
        if decision.blocked:
            async with ctx.tx() as conn:
                out = await layer.request_tool(conn, ctx.tenant_id, spec, args, rules=ctx.rules, rule_context=rctx,
                                               ids=ids, scope=str(ctx.conversation_id),
                                               source=state["untrusted_source"])
            msg = " ".join(f.message for f in decision.firings if f.outcome == "block" and f.message)
            state["results"].append({"tool": spec.name, "args": args, "status": "refused", "call_id": out.call_id,
                                     "error": msg, "customer_message": msg})
            state["action_result"] = state["results"][-1]
            state["draft_kind"] = "action_result"
            trace["summary"] += " · blocked by rule"
            return "draft"
        state["pending_action"] = {"tool": spec.name, "args": args, "requires_approval":
                                   spec.needs_human or decision.needs_approval}
        state["draft_kind"] = "confirm"
        trace["summary"] += " · awaiting customer confirmation"
        return "draft"

    async with ctx.tx() as conn:
        out = await layer.request_tool(conn, ctx.tenant_id, spec, args, rules=ctx.rules, rule_context=rctx, ids=ids,
                                       scope=f"{ctx.conversation_id}:{ctx.turn_id}", source=state["untrusted_source"])
    if out.decision:
        await _log_decision(ctx, state, out.decision, "tool_call", spec.name, {**rctx, "args": args})
    state["results"].append({"tool": spec.name, "args": args, "status": out.status, "call_id": out.call_id,
                             "output": out.output, "error": out.error})
    _absorb(state, spec.name, args, out.output, out.status)
    await _link_customer(ctx, state)
    trace["output"] = {**plan, "tool_status": out.status, "tool_output": out.output, "error": out.error}
    trace["summary"] += f" → {out.status}"
    return "act"


async def step_execute_pending(ctx: TurnContext, state: dict, trace: dict) -> str:
    p = state.get("pending_action")
    state["pending_action"] = None
    spec = ctx.tools.get(p["tool"]) if p else None
    if spec is None:
        state["draft_kind"] = "answer"
        return "draft"
    rctx = _rule_context(ctx, state)
    ids = {"conversation_id": ctx.conversation_id, "customer_id": state.get("customer_id"), "turn_id": ctx.turn_id}
    async with ctx.tx() as conn:
        out = await layer.request_tool(conn, ctx.tenant_id, spec, p["args"], rules=ctx.rules, rule_context=rctx,
                                       ids=ids, scope=str(ctx.conversation_id), source=state["untrusted_source"])
    if out.decision:
        await _log_decision(ctx, state, out.decision, "tool_call", spec.name, {**rctx, "args": p["args"]})
    result = {"tool": spec.name, "args": p["args"], "status": out.status, "call_id": out.call_id,
              "output": out.output, "error": out.error}
    if out.status == "refused" and out.decision:
        result["customer_message"] = " ".join(f.message for f in out.decision.firings if f.outcome == "block")
    state["results"].append(result)
    state["action_result"] = result
    if out.status == "pending_approval":
        state["pending_approval"] = {"call_id": out.call_id, "tool": spec.name, "args": p["args"],
                                     "reason": out.reason}
    _absorb(state, spec.name, p["args"], out.output, out.status)
    state["draft_kind"] = "action_result"
    trace.update(kind="tool", summary=f"{spec.name} → {out.status}" + (" (deduplicated)" if out.deduplicated else ""),
                 input={"tool": spec.name, "args": p["args"], "risk_tier": spec.risk_tier},
                 output={"status": out.status, "output": out.output, "error": out.error,
                         "rules": out.decision.as_dict() if out.decision else None, "reason": out.reason})
    return "draft"


async def step_execute_approved(ctx: TurnContext, state: dict, trace: dict) -> str:
    call_id = state["approval_call_id"]
    async with ctx.tx() as conn:
        call = await fetch_one(conn, "select * from tool_calls where id=%s", (call_id,))
        spec = ctx.tools.get(call["tool_name"])
        if call["status"] == "approved" and spec is not None:
            ids = {"conversation_id": ctx.conversation_id, "customer_id": state.get("customer_id"),
                   "turn_id": ctx.turn_id}
            out = await layer.execute(conn, ctx.tenant_id, spec, call["input"], key=call["idempotency_key"], ids=ids,
                                      decision=None)
            result = {"tool": call["tool_name"], "args": call["input"], "status": out.status, "call_id": call_id,
                      "output": out.output, "error": out.error, "approver": call["approver_label"]}
        else:
            result = {"tool": call["tool_name"], "args": call["input"], "status": "denied", "call_id": call_id,
                      "note": call["decision_note"] or "", "approver": call["approver_label"]}
    state["pending_approval"] = None
    state["results"].append(result)
    state["action_result"] = result
    _absorb(state, result["tool"], result["args"], result.get("output"), result["status"])
    state["draft_kind"] = "action_result"
    trace.update(kind="tool", summary=f"{result['tool']} {result['status']} after review by {call['approver_label']}",
                 input={"call_id": call_id, "decision": call["status"], "approver": call["approver_label"]},
                 output=result)
    return "draft"


def _draft_ctx(ctx: TurnContext, state: dict) -> dict:
    return {
        "brand": _brand(ctx), "intent": state.get("intent") or "", "kind": state.get("draft_kind", "answer"),
        "customer_message": state["message"]["content"], "history": state["history"],
        "sources": state.get("sources") or [], "tool_results": state.get("results") or [],
        "facts": state["facts"], "pending_action": state.get("pending_action") if state.get("draft_kind") == "confirm" else None,
        "action_result": state.get("action_result") if state.get("draft_kind") == "action_result" else None,
        "question": state.get("question") if state.get("draft_kind") == "ask" else None,
        "memory": state.get("memory") or [], "feedback": state.get("feedback"),
    }


async def step_draft(ctx: TurnContext, state: dict, trace: dict) -> str:
    dctx = _draft_ctx(ctx, state)
    attempt = state["attempts"]
    seeded = (ctx.inject.get("drafts") or [])
    tok = Tokenizer.from_state(state["tok"])
    if attempt < len(seeded) and seeded[attempt] is not None:
        draft = {"reply": seeded[attempt], "citations": []}
        trace.update(kind="model", model="seeded failure (eval harness)",
                     summary=f"Draft attempt {attempt + 1} (seeded failure)")
    else:
        voice = ctx.config.get("tone", {}).get("voice", "Warm, concise and plain-spoken.")
        safe_ctx = json.loads(tok.protect(json.dumps(dctx)))
        res = await ctx.gateway.run(ModelCall(
            step="draft", system=skills.DRAFT_SYSTEM.format(brand=_brand(ctx), voice=voice),
            prompt=skills.draft_prompt(safe_ctx), schema=skills.DRAFT_SCHEMA,
            sandbox=lambda: skills.sandbox_draft(dctx), max_tokens=2048))
        _account(state, trace, res)
        draft = {"reply": tok.reveal(res.data["reply"]).strip(), "citations": res.data["citations"]}
        trace.update(kind="model", summary=f"Draft attempt {attempt + 1} ({dctx['kind']})")
    state["draft"] = draft
    state["attempts"] = attempt + 1
    trace["input"] = {"kind": dctx["kind"], "feedback": dctx["feedback"],
                      "sources": [s["chunk_id"] for s in dctx["sources"]]}
    trace["output"] = draft
    return "supervise"


def _allowed_pii(state: dict) -> set[str]:
    vals = set()
    f = state["facts"]
    if f.get("email") and f.get("verified"):
        vals.add(f["email"].lower())
    order = f.get("order") or {}
    if f.get("verified") and order.get("customer_email", "").lower() == (f.get("email") or "").lower():
        vals.add(order.get("customer_email", "").lower())
    for _, v in find_pii(state["message"]["content"]):
        vals.add(v.lower())
    return vals


async def step_supervise(ctx: TurnContext, state: dict, trace: dict) -> str:
    sup_cfg = ctx.config.get("supervisor", {})
    draft = state["draft"]
    results_for_review = []
    for r in state.get("results", []):
        rr = dict(r)
        if r.get("customer_message"):
            rr["output"] = {**(r.get("output") or {}), "rule_message": r["customer_message"]}
        results_for_review.append(rr)
    if state.get("pending_action") and state.get("draft_kind") == "confirm":
        results_for_review.append({"tool": state["pending_action"]["tool"], "args": state["pending_action"]["args"],
                                   "status": "proposed", "output": {
                                       "subscription": state["facts"].get("subscription"),
                                       "order": state["facts"].get("order")}})
    inp = ReviewInput(
        draft=draft["reply"], citations=draft.get("citations", []), intent=state.get("intent") or "",
        route=state.get("draft_kind", "answer"), customer_message=state["message"]["content"],
        history=state["history"], sources=state.get("sources") or [], tool_results=results_for_review,
        memory=state.get("memory") or [],
        succeeded_tools={r["tool"] for r in state.get("results", []) if r.get("status") == "succeeded"},
        allowed_pii=_allowed_pii(state),
        private_texts=[skills.DRAFT_SYSTEM, skills.PLAN_SYSTEM, skills.TRIAGE_SYSTEM]
        + [json.dumps(ctx.config.get("internal_notes", ""))],
        policy=ctx.config.get("policy", {}) | {"tone": ctx.config.get("tone", {}),
                                               "brand": _brand(ctx)},
        injection=state.get("injection", []), sensitive=[],
    )
    if state.get("draft_kind") == "answer" and state.get("intent") == "policy_question":
        inp.route = "answer"
    rv = await review(inp, ctx.gateway, timeout_ms=int(sup_cfg.get("timeout_ms", 3500)),
                      force_timeout=bool(ctx.inject.get("supervisor_timeout")))
    if rv.model_result:
        _account(state, trace, rv.model_result)
    trace["model"] = rv.model
    async with ctx.tx() as conn:
        await conn.execute("""
            insert into supervisor_verdicts (tenant_id, conversation_id, customer_id, turn_id, attempt, verdict,
              reason_code, reasons, checks, model, latency_ms)
            values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (ctx.tenant_id, ctx.conversation_id, state.get("customer_id"), ctx.turn_id, state["attempts"], rv.verdict,
             rv.reason_code, Jsonb(rv.reasons), Jsonb(rv.checks), rv.model, rv.latency_ms))
    state["verdicts"].append({"attempt": state["attempts"], "verdict": rv.verdict, "reason_code": rv.reason_code,
                              "reasons": rv.reasons})
    state["review"] = rv.as_dict()
    trace.update(kind="supervisor", summary=f"Verdict {rv.verdict} · {rv.reason_code}",
                 input={"draft": draft["reply"], "citations": draft.get("citations", [])}, output=rv.as_dict())

    if rv.verdict == "approve":
        return "reply_rules"
    if rv.verdict == "revise":
        if state["attempts"] > int(sup_cfg.get("max_revisions", 2)):
            state["escalation"] = {"code": "revision_limit",
                                   "reason": f"Draft rejected {state['attempts']} times: {rv.reason_code}"}
            return "escalate"
        state["feedback"] = rv.feedback or "Fix the issues the supervisor found."
        return "draft"
    if rv.verdict == "block":
        state["block"] = {"reason_code": rv.reason_code, "reasons": rv.reasons}
        if state.get("intent") in ACT_INTENTS:
            state["escalation"] = {"code": f"blocked_{rv.reason_code}", "reason": "; ".join(rv.reasons)}
            return "escalate"
        return "blocked"
    state["escalation"] = {"code": rv.reason_code, "reason": "; ".join(rv.reasons)}
    return "escalate"


async def step_reply_rules(ctx: TurnContext, state: dict, trace: dict) -> str:
    reply = state["draft"]["reply"]
    rctx = {**_rule_context(ctx, state), "reply": reply}
    decision = evaluate(ctx.rules, "reply", rctx)
    await _log_decision(ctx, state, decision, "reply", None, rctx)
    trace.update(kind="rules", summary=f"Reply rules: {decision.outcome} ({len(decision.evaluated)} evaluated)",
                 input={"reply": reply}, output=decision.as_dict())
    if decision.outcome == "block":
        state["block"] = {"reason_code": "reply_rule", "reasons": [f.message for f in decision.firings]}
        return "blocked"
    if decision.outcome == "require_approval":
        state["escalation"] = {"code": "reply_rule_approval",
                               "reason": "; ".join(f.message or f.name for f in decision.firings)}
        return "escalate"
    return "respond"


async def _finish(ctx: TurnContext, state: dict, *, text: str, action: str, verdict: str | None,
                  status: str, conv_status: str, citations: list[dict] | None = None,
                  extra_meta: dict | None = None) -> None:
    latency = int((time.time() - state["t0"]) * 1000)
    citations = citations or []
    async with ctx.tx() as conn:
        conv = await fetch_one(conn, "select customer_id from conversations where id=%s", (ctx.conversation_id,))
        cid = conv["customer_id"]
        m = await fetch_one(conn, """
            insert into messages (tenant_id, conversation_id, customer_id, turn_id, role, channel, content, metadata)
            values (%s,%s,%s,%s,'agent',%s,%s,%s) returning id""",
            (ctx.tenant_id, ctx.conversation_id, cid, ctx.turn_id, state["channel"], text,
             Jsonb({"citations": citations, "verdict": verdict, "action": action, **(extra_meta or {})})))
        await conn.execute("""
            update turns set status=%s, reply_message_id=%s, final_action=%s, final_verdict=%s, latency_ms=%s,
              completed_at=now() where id=%s""", (status, m["id"], action, verdict, latency, ctx.turn_id))
        cstate = {"facts": state["facts"], "pending_action": state.get("pending_action"),
                  "pending_approval": state.get("pending_approval"), "tok": state["tok"],
                  "cost_usd": state["cost_usd"], "last_intent": state.get("intent"),
                  "awaiting": state.get("intent") if state.get("draft_kind") == "ask" and action == "reply" else None}
        await conn.execute("""
            update conversations set status=%s, state=%s, last_activity_at=now(),
              intent=coalesce(case when %s in ('confirm_yes','confirm_no','thanks','greeting') then null else %s end, intent),
              issue_key=coalesce(%s, issue_key)
            where id=%s""",
            (conv_status, Jsonb(cstate), state.get("intent"), state.get("intent"), _issue_key(state),
             ctx.conversation_id))
    state["final"] = {"text": text, "action": action, "verdict": verdict, "status": status,
                      "citations": citations, "latency_ms": latency, "message_id": str(m["id"])}
    await ctx.emit({"type": "reply", "text": text, "action": action, "verdict": verdict, "citations": citations,
                    "status": status, "message_id": str(m["id"]),
                    "approval": state.get("pending_approval")})


def _issue_key(state: dict) -> str | None:
    intent = state.get("intent")
    if intent in (None, "confirm_yes", "confirm_no", "thanks", "greeting", "out_of_scope"):
        return None
    if intent == "policy_question":
        # Different questions are different issues: key on the policy section that answered it.
        src = (state.get("sources") or [{}])[0]
        topic = (src.get("heading") or src.get("title") or "").lower().replace(" ", "_")
        return f"{intent}:{topic}" if topic else None
    ref = state["facts"].get("order_id") or (state["facts"].get("subscription") or {}).get("subscription_id") or ""
    return f"{intent}:{ref}" if ref else intent


async def step_respond(ctx: TurnContext, state: dict, trace: dict) -> str | None:
    draft = state["draft"]
    srcs = {s["chunk_id"]: s for s in state.get("sources") or []}
    cites = [{"chunk_id": c, "title": srcs[c]["title"], "heading": srcs[c].get("heading")}
             for c in draft.get("citations", []) if c in srcs]
    parked = bool(state.get("pending_approval"))
    await _finish(ctx, state, text=draft["reply"], action="reply", verdict="approve",
                  status="awaiting_approval" if parked else "completed",
                  conv_status="awaiting_approval" if parked else "active", citations=cites)
    trace.update(kind="respond", summary="Reply sent" + (" · awaiting human approval" if parked else ""),
                 output={"reply": draft["reply"], "citations": cites})
    return None


async def step_blocked(ctx: TurnContext, state: dict, trace: dict) -> str | None:
    await _finish(ctx, state, text=SAFE_DECLINE, action="blocked", verdict="block", status="completed",
                  conv_status="active", extra_meta={"block": state.get("block")})
    trace.update(kind="respond", summary="Draft blocked; safe reply sent instead",
                 output={"reply": SAFE_DECLINE, "block": state.get("block")})
    return None


async def step_escalate(ctx: TurnContext, state: dict, trace: dict) -> str | None:
    esc = state.get("escalation") or {"code": "unknown", "reason": "Escalated"}
    dest = ctx.config.get("handoff", {}).get("destination", "help desk queue")
    async with ctx.tx() as conn:
        transcript = await fetch_all(conn, "select role, content, created_at from messages where conversation_id=%s "
                                           "order by created_at", (ctx.conversation_id,))
        conv = await fetch_one(conn, "select customer_id from conversations where id=%s", (ctx.conversation_id,))
        h = await fetch_one(conn, """
            insert into handoffs (tenant_id, conversation_id, customer_id, reason_code, reason, transcript, destination)
            values (%s,%s,%s,%s,%s,%s,%s) returning id""",
            (ctx.tenant_id, ctx.conversation_id, conv["customer_id"], esc["code"], esc["reason"],
             Jsonb(transcript), dest))
        if not ctx.is_test:
            await enqueue(conn, ctx.tenant_id, "deliver_handoff",
                          {"handoff_id": str(h["id"]), "webhook_url": ctx.config.get("handoff", {}).get("webhook_url")})
    state["pending_action"] = None
    await _finish(ctx, state, text=ESCALATION_MESSAGE, action="escalate", verdict=(state.get("review") or {}).get("verdict"),
                  status="escalated", conv_status="escalated", extra_meta={"escalation": esc})
    trace.update(kind="escalation", summary=f"Escalated to {dest}: {esc['code']}", output=esc)
    return None


STEPS: dict[str, Callable[[TurnContext, dict, dict], Awaitable[str | None]]] = {
    "triage": step_triage,
    "retrieve": step_retrieve,
    "act": step_act,
    "execute_pending": step_execute_pending,
    "execute_approved": step_execute_approved,
    "draft": step_draft,
    "supervise": step_supervise,
    "reply_rules": step_reply_rules,
    "respond": step_respond,
    "blocked": step_blocked,
    "escalate": step_escalate,
}
