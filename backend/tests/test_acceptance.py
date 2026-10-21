"""One test (or more) per "Accept when" criterion in the PRD, section 8."""

from __future__ import annotations

import asyncio
import base64
import datetime as dt
import hashlib
import json
import uuid

import pytest

from cairn.channels import email as email_channel
from cairn.channels.message import ChannelInfo, CustomerRef, Message
from cairn.db.core import Jsonb, anon_tx, fetch_all, fetch_one, system_tx, tenant_tx
from cairn.engine import approvals
from cairn.engine.orchestrator import SimulatedCrash, resume_turn
from cairn.llm.gateway import ModelGateway
from cairn.rules.engine import Rule, evaluate, run_fixtures
from cairn.tools import layer

from .helpers import new_conversation, one, rows, say, uid

MAYA = "maya.chen@example.com"
SAM = "sam.patel@example.com"


# ------------------------------------------------------------------- F1

async def test_f1_chat_and_email_produce_identical_messages(acme):
    raw = (
        "From: Maya Chen <maya.chen@example.com>\r\nTo: support@acme.example\r\nSubject: Order question\r\n"
        "Message-ID: <abc123@mail.example>\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n"
        "Where is my order A1002?\r\n\r\nOn Mon, Oct 19, 2026 Acme wrote:\r\n> Thanks for shopping with us\r\n"
    )
    from_email = email_channel.parse_inbound(raw, str(acme))
    from_chat = Message(tenant_id=str(acme), channel=ChannelInfo(type="web"),
                        customer=CustomerRef(email=MAYA, name="Maya Chen"), content="Where is my order A1002?")
    a, b = from_email.model_dump(), from_chat.model_dump()
    assert a["channel"]["type"] == "email" and b["channel"]["type"] == "web"
    a.pop("channel"), b.pop("channel")
    assert a == b


async def test_f1_email_thread_is_preserved_and_reply_is_threaded(acme, sandbox):
    first = ("From: maya.chen@example.com\r\nTo: support@acme.example\r\nSubject: Shipping\r\n"
             "Message-ID: <t1@mail.example>\r\n\r\nIs shipping free?\r\n")
    m1 = email_channel.parse_inbound(first, str(acme))
    from cairn.channels.service import start_conversation
    from cairn.engine.orchestrator import handle_message

    cid, _ = await start_conversation(acme, "email", m1.customer, external_thread_id=m1.channel.envelope["thread_root"])
    r1 = await handle_message(m1, cid)
    out = await email_channel.queue_reply(acme, cid, m1, r1.reply, "support@acme.example")
    second = (f"From: maya.chen@example.com\r\nTo: support@acme.example\r\nSubject: Re: Shipping\r\n"
              f"Message-ID: <t2@mail.example>\r\nIn-Reply-To: {out['message_id']}\r\n"
              f"References: <t1@mail.example> {out['message_id']}\r\n\r\nAnd how long does express take?\r\n")
    m2 = email_channel.parse_inbound(second, str(acme))
    assert await email_channel.find_thread(acme, m2.channel.envelope) == cid
    ob = await one(acme, "select in_reply_to, subject from outbox_emails where id=%s", (out["id"],))
    assert ob["in_reply_to"] == "<t1@mail.example>" and ob["subject"].startswith("Re:")


# ------------------------------------------------------------------- F2

async def test_f2_killed_turn_resumes_at_last_completed_step(acme, sandbox):
    cid = await new_conversation(acme, MAYA)
    with pytest.raises(SimulatedCrash):
        await say(acme, cid, "Where is my order A1002?", MAYA, inject={"crash_after": "act"})
    turn = await one(acme, "select id, status from turns where conversation_id=%s order by seq desc limit 1", (cid,))
    assert turn["status"] == "running"
    steps_before = await one(acme, "select count(*) as n from checkpoints where turn_id=%s", (turn["id"],))
    res = await resume_turn(acme, turn["id"])
    assert res.action == "reply" and "1Z84A0F20398" in res.reply
    lookups = await one(acme, "select count(*) as n from tool_calls where conversation_id=%s and tool_name='lookup_order'",
                        (cid,))
    assert lookups["n"] == 1, "completed steps must not run again after a restart"
    first_steps = await rows(acme, "select step from checkpoints where turn_id=%s order by step_index", (turn["id"],))
    assert [s["step"] for s in first_steps].count("triage") == 1
    assert steps_before["n"] < len(first_steps)


async def test_f2_model_per_step_is_configuration(acme):
    gw = ModelGateway({"draft": {"primary": "claude-sonnet-5-5"}}, use_claude=True)
    assert gw.label("draft") == "claude-sonnet-5-5"
    assert ModelGateway(None, use_claude=True).label("draft") == "claude-opus-5-5"
    assert ModelGateway(None, use_claude=True).label("supervisor") == "claude-haiku-5-5"


async def test_f2_step_limit_escalates(acme, sandbox):
    from cairn.engine.config import merged

    cid = await new_conversation(acme, MAYA)
    cfg = merged({"limits": {"max_steps_per_turn": 2, "cost_budget_per_conversation_usd": 1}})
    from cairn.engine.orchestrator import handle_message

    res = await handle_message(Message(tenant_id=str(acme), channel=ChannelInfo(type="web"),
                                       customer=CustomerRef(email=MAYA, verified=True), content="Where is A1002?"),
                               cid, config_override=cfg, config_version=1)
    assert res.action == "escalate"
    h = await one(acme, "select reason_code from handoffs where conversation_id=%s", (cid,))
    assert h["reason_code"] == "step_limit"


# ------------------------------------------------------------------- F3

async def test_f3_seeded_suite_stops_every_critical_case(acme):
    from cairn.evals.harness import run_suite

    report = await run_suite(acme, suites=["critical", "adversarial"], include_judge=False, trigger="test")
    s = report["summary"]
    assert s["critical_total"] >= 200, "the PRD asks for a seeded suite of at least 200 cases"
    assert s["critical_passed"] == s["critical_total"], report["failures"][:3]
    missing = await one(acme, "select count(*) as n from supervisor_verdicts where reason_code is null or reason_code=''")
    assert missing["n"] == 0, "every verdict is stored with its reason"


async def test_f3_supervisor_timeout_fails_closed(acme, sandbox):
    cid = await new_conversation(acme)
    res = await say(acme, cid, "Is shipping free?", inject={"supervisor_timeout": True})
    assert res.action == "escalate"
    v = await one(acme, "select verdict, reason_code from supervisor_verdicts where conversation_id=%s", (cid,))
    assert v["verdict"] == "escalate" and v["reason_code"] == "supervisor_timeout"


async def test_f3_revise_feedback_then_escalate_after_two_revisions(acme, sandbox):
    cid = await new_conversation(acme)
    res = await say(acme, cid, "What's your return window?", inject={"drafts": ["Returns within 120 days."] * 3})
    verdicts = await rows(acme, "select verdict from supervisor_verdicts where conversation_id=%s order by attempt", (cid,))
    assert [v["verdict"] for v in verdicts] == ["revise", "revise", "revise"]
    assert res.action == "escalate" and "120" not in res.reply


# ------------------------------------------------------------------- F4

RULE = Rule("t", 1, "t", "tool_call", {">": [{"var": "args.amount"}, 100]}, "require_approval", tool="issue_refund",
            fixtures=[{"name": "big", "context": {"args": {"amount": 101}}, "expect": True}])


def test_f4_same_input_same_result_and_no_model_on_path():
    import sys

    results = {evaluate([RULE], "tool_call", {"args": {"amount": 150}}, tool="issue_refund").outcome
               for _ in range(200)}
    assert results == {"require_approval"}
    import cairn.rules.engine as eng
    import cairn.rules.jsonlogic as jl

    for mod in (eng, jl):
        src = open(mod.__file__).read()
        assert "llm" not in src and "anthropic" not in src and "gateway" not in src
    assert "cairn.llm.gateway" not in getattr(sys.modules[eng.__name__], "__dict__", {})


def test_f4_failing_fixture_is_detected():
    bad = Rule("t", 1, "t", "tool_call", {">": [{"var": "args.amount"}, 500]}, "block", tool="issue_refund",
               fixtures=[{"name": "should fire at 200", "context": {"args": {"amount": 200}}, "expect": True}])
    assert run_fixtures(bad) and not run_fixtures(RULE)


async def test_f4_publishing_a_rule_with_a_failing_fixture_is_refused(client):
    body = {"rule_key": "refund_hard_cap_500", "name": "Hard cap", "event": "tool_call", "tool": "issue_refund",
            "condition": {">": [{"var": "args.amount"}, 900]}, "outcome": "block", "message": "x",
            "fixtures": [{"name": "750 must be blocked", "context": {"args": {"amount": 750}}, "expect": True}]}
    r = await client.post("/api/rules", json=body)
    assert r.status_code == 200 and r.json()["fixture_failures"]
    r = await client.post("/api/rules/refund_hard_cap_500/publish")
    assert r.status_code == 409
    assert "fixture" in json.dumps(r.json()).lower()
    # clean up the draft so other tests see the published rule only
    async with system_tx() as conn:
        await conn.execute("delete from rules where rule_key='refund_hard_cap_500' and status='draft'")


# ------------------------------------------------------------------- F5

async def test_f5_same_refund_twice_with_one_key_refunds_once(acme, sandbox):
    async with tenant_tx(acme) as conn:
        tools = await layer.load_tools(conn)
        spec = tools["issue_refund"]
        args = {"order_id": "A1001", "amount": 84.0, "reason": "damaged on arrival"}
        key = layer.idempotency_key("test-idem", spec.name, args)
        a = await layer.execute(conn, acme, spec, args, key=key, ids={})
        b = await layer.execute(conn, acme, spec, args, key=key, ids={})
    assert a.status == b.status == "succeeded" and b.deduplicated
    assert len(sandbox.refunds) == 1
    n = await one(acme, "select count(*) as n from tool_calls where idempotency_key=%s", (key,))
    assert n["n"] == 1


async def test_f5_high_tier_call_without_approval_is_refused_and_logged(acme, sandbox):
    async with tenant_tx(acme) as conn:
        spec = (await layer.load_tools(conn))["apply_goodwill_credit"]
        assert spec.risk_tier == "high"
        args = {"email": MAYA, "amount": 10, "reason": "late delivery"}
        out = await layer.execute(conn, acme, spec, args, key=layer.idempotency_key("hi", spec.name, args), ids={})
    assert out.status == "refused"
    assert not sandbox.credits
    row = await one(acme, "select status, error from tool_calls where id=%s", (out.call_id,))
    assert row["status"] == "refused" and "approval" in row["error"]


async def test_f5_schema_is_enforced_whatever_the_model_asked(acme, sandbox):
    async with tenant_tx(acme) as conn:
        spec = (await layer.load_tools(conn))["issue_refund"]
        out = await layer.request_tool(conn, acme, spec, {"order_id": "A1001", "amount": "all of it"}, rules=[],
                                       rule_context={}, ids={}, scope="schema-test")
    assert out.status == "refused" and out.reason == "schema_invalid"


async def test_f5_approval_flow_runs_the_call_once_approved(acme, sandbox):
    cid = await new_conversation(acme, SAM)
    await say(acme, cid, "I want a refund for order A1004", SAM)
    res = await say(acme, cid, "yes please", SAM)
    assert res.status == "awaiting_approval" and res.approval
    assert not sandbox.refunds
    done = await approvals.decide(acme, uid(res.approval["call_id"]), approve=True, approver_id=None,
                                  approver_label="tester")
    assert "refund of $249.00" in done.reply and len(sandbox.refunds) == 1
    call = await one(acme, "select status, approver_label from tool_calls where id=%s", (res.approval["call_id"],))
    assert call["status"] == "succeeded" and call["approver_label"] == "tester"


# ------------------------------------------------------------------- F6

async def test_f6_policy_answer_cites_its_source_and_deletion_removes_chunks(acme, sandbox):
    from cairn.knowledge.store import search, upsert_source

    async with tenant_tx(acme) as conn:
        src = await upsert_source(conn, acme, title="Bike rental policy", owner="QA",
                                  content="# Bike rentals\n\nWe rent mountain bikes for 45 dollars a day from our "
                                          "Boulder store. Helmets are included with every bike rental.")
    cid = await new_conversation(acme)
    res = await say(acme, cid, "Do you include helmets with bike rentals?")
    assert res.citations and res.citations[0]["title"] == "Bike rental policy"
    async with tenant_tx(acme) as conn:
        await conn.execute("delete from knowledge_sources where id=%s", (src["id"],))
        hits = await search(conn, "helmets bike rentals")
    assert all(h.source_id != str(src["id"]) for h in hits)


# ------------------------------------------------------------------- F7

def _tables_with_customer_id(conn_rows):
    return sorted({r["table_name"] for r in conn_rows})


async def test_f7_registry_covers_every_table_with_a_customer_id():
    from cairn.memory.store import ERASURE_REGISTRY

    async with system_tx() as conn:
        tables = await fetch_all(conn, "select table_name from information_schema.columns "
                                       "where table_schema='public' and column_name='customer_id'")
    missing = [t for t in _tables_with_customer_id(tables) if t not in ERASURE_REGISTRY]
    assert not missing, f"tables hold customer data but are not in the erasure registry: {missing}"


async def test_f7_erasure_leaves_zero_references(acme, sandbox):
    from cairn.api.realtime import hub
    from cairn.memory.store import erase_customer, remember
    from cairn.outcomes.engine import close_conversation
    from cairn.pap import gateway as pap

    email = "erase.me@example.com"
    sandbox.orders["A1001"]["customer_email"] = email  # give the test customer an order
    cid = await new_conversation(acme, email)
    await say(acme, cid, "I'd like a refund for order A1001", email)
    await say(acme, cid, "yes", email)
    await say(acme, cid, "I'm calling my lawyer about the last order", email)  # handoff with transcript
    cust = (await one(acme, "select id from customers where email=%s", (email,)))["id"]
    async with tenant_tx(acme) as conn:
        await conn.execute("insert into customer_signals (tenant_id, conversation_id, customer_id, kind, value) "
                           "values (%s,%s,%s,'csat',5)", (acme, cid, cust))
        await conn.execute("insert into chat_sessions (tenant_id, conversation_id, customer_id, token_hash, data, "
                           "expires_at) values (%s,%s,%s,%s,%s, now() + interval '1 day')",
                           (acme, cid, cust, "hash-" + uuid.uuid4().hex, Jsonb({"email": email})))
    await close_conversation(acme, cid)
    await remember(acme, cid)
    assert (await one(acme, "select count(*) as n from memory_items where customer_id=%s", (cust,)))["n"] > 0
    # an outside agent session and an email
    sid = await pap.authorize(acme, "agent://meta.ai/personal", "read", "https://a.example/cb", "c" * 43, None)
    await pap.consent(acme, sid, customer_id=cust, granted=["read"], method="test")
    m = email_channel.parse_inbound(f"From: {email}\r\nSubject: hi\r\nMessage-ID: <e1@x>\r\n\r\nhello\r\n", str(acme))
    await email_channel.queue_reply(acme, cid, m, "Hello!", "support@acme.example")
    hub.customers[str(cid)] = str(cust)

    receipt = await erase_customer(acme, cust, "test")
    assert receipt["counts"]["messages"] > 0 and receipt["counts"]["memory_items"] > 0
    assert receipt["backup_retention_days"] > 0 and "backups_expire_by" in receipt
    assert str(cid) not in hub.customers

    # Scan every table with a customer_id, every text and json column, and the vector index.
    async with system_tx() as conn:
        tables = await fetch_all(conn, "select table_name from information_schema.columns "
                                       "where table_schema='public' and column_name='customer_id'")
        for t in _tables_with_customer_id(tables):
            if t == "erasure_requests":
                continue  # the erasure log holds the id, never content
            n = await fetch_one(conn, f"select count(*) as n from {t} where customer_id=%s", (cust,))
            assert n["n"] == 0, f"{t} still references the customer"
        cols = await fetch_all(conn, """
            select table_name, column_name from information_schema.columns
            where table_schema='public' and data_type in ('text','jsonb','character varying')
              and table_name not in ('schema_migrations','erasure_requests')""")
        for c in cols:
            n = await fetch_one(conn, f'select count(*) as n from "{c["table_name"]}" '
                                      f'where "{c["column_name"]}"::text ilike %s', (f"%{email}%",))
            assert n["n"] == 0, f"{c['table_name']}.{c['column_name']} still contains the email"
        n = await fetch_one(conn, "select count(*) as n from memory_items where customer_id=%s", (cust,))
        assert n["n"] == 0
        o = await fetch_one(conn, "select customer_id, evidence from outcomes where conversation_id=%s", (cid,))
        assert o["customer_id"] is None and o["evidence"].get("erased") is True


async def test_f7_export_returns_json(acme, sandbox):
    from cairn.memory.store import export_customer

    cid = await new_conversation(acme, MAYA)
    await say(acme, cid, "Where is my order A1002?", MAYA)
    cust = (await one(acme, "select id from customers where email=%s", (MAYA,)))["id"]
    data = await export_customer(acme, cust)
    assert data["customer"]["email"] == MAYA and data["conversations"]
    json.dumps(data, default=str)


# ------------------------------------------------------------------- F8

def _pkce():
    verifier = "v" * 50
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


async def test_f8_reference_agent_flow(client, acme, sandbox):
    agent = "agent://reference.cairn.dev/pap-agent"
    m = (await client.get("/pap/v1/acme/.well-known/pap.json")).json()
    assert m["protocol"] == "pap" and any(c["name"] == "issue_refund" and c["scope"] == "write" for c in m["capabilities"])

    guest = (await client.post("/pap/v1/acme/sessions", json={"agent": agent})).json()
    gh = {"authorization": f"Bearer {guest['access_token']}"}
    r = await client.post("/pap/v1/acme/actions/lookup_order", json={"arguments": {"order_id": "A1002"}}, headers=gh)
    assert r.status_code == 200 and r.json()["result"]["status"] == "shipped"
    assert "customer_email" not in r.json()["result"], "guests never see personal data"
    r = await client.post("/pap/v1/acme/actions/issue_refund",
                          json={"arguments": {"order_id": "A1001", "amount": 84, "reason": "broken"}}, headers=gh)
    assert r.status_code == 403 and r.json()["error"] == "insufficient_scope"

    verifier, challenge = _pkce()
    r = await client.get("/pap/v1/acme/authorize", params={
        "agent": agent, "redirect_uri": "https://agent.example/cb", "code_challenge": challenge,
        "scope": "read write", "state": "xyz"})
    assert r.status_code == 200 and "Allow an assistant" in r.text
    sid = r.text.split("/authorize/")[1].split('"')[0]
    r = await client.post(f"/pap/v1/acme/authorize/{sid}", data={"email": MAYA, "order_id": "A1001",
                                                                 "allow_write": "1", "decision": "allow"})
    assert r.status_code == 303
    loc = r.headers["location"]
    code = loc.split("code=")[1].split("&")[0]
    assert "state=xyz" in loc
    tok = (await client.post("/pap/v1/acme/token", json={"code": code, "code_verifier": verifier, "agent": agent})).json()
    assert tok["mode"] == "signed_in" and "write" in tok["scope"]
    sh = {"authorization": f"Bearer {tok['access_token']}"}
    r = await client.post("/pap/v1/acme/actions/issue_refund",
                          json={"arguments": {"order_id": "A1001", "amount": 84, "reason": "Arrived damaged"}},
                          headers=sh)
    assert r.status_code == 200 and r.json()["status"] == "succeeded"
    # Someone else's order is refused by the ownership rule, even with write scope.
    r = await client.post("/pap/v1/acme/actions/issue_refund",
                          json={"arguments": {"order_id": "A1007", "amount": 20, "reason": "not mine"}}, headers=sh)
    assert r.status_code == 403
    r = await client.post("/pap/v1/acme/messages", json={"content": "Where is order A1002?"}, headers=sh)
    assert r.status_code == 200 and "shipped" in r.json()["reply"]
    log = await rows(acme, "select action, allowed, outcome, scope_required from pap_actions where agent_identity=%s",
                     (agent,))
    assert any(a["outcome"] == "refused_scope" and not a["allowed"] for a in log)
    assert any(a["action"] == "action:issue_refund" and a["outcome"] == "succeeded" for a in log)


async def test_f8_read_only_session_cannot_write_and_denied_agents_are_refused(client, acme):
    agent = "agent://meta.ai/personal"
    verifier, challenge = _pkce()
    r = await client.get("/pap/v1/acme/authorize", params={
        "agent": agent, "redirect_uri": "https://agent.example/cb", "code_challenge": challenge, "scope": "read write"})
    sid = r.text.split("/authorize/")[1].split('"')[0]
    r = await client.post(f"/pap/v1/acme/authorize/{sid}", data={"email": MAYA, "order_id": "A1001", "decision": "allow"})
    code = r.headers["location"].split("code=")[1].split("&")[0]
    tok = (await client.post("/pap/v1/acme/token", json={"code": code, "code_verifier": verifier, "agent": agent})).json()
    assert tok["scope"] == "read"
    r = await client.post("/pap/v1/acme/actions/cancel_subscription",
                          json={"arguments": {"subscription_id": "SUB-2003", "reason": "moving"}},
                          headers={"authorization": f"Bearer {tok['access_token']}"})
    assert r.status_code == 403
    r = await client.post("/pap/v1/acme/sessions", json={"agent": "agent://scraper.example/bot"})
    assert r.status_code == 403 and r.json()["error"] == "agent_denied"


# ------------------------------------------------------------------- F9

async def test_f9_outcomes_pending_then_repeat_contact_is_not_billable(acme, sandbox):
    from cairn.outcomes.engine import close_conversation, finalize_due

    email = "outcome.test@example.com"
    sandbox.orders["A1008"]["customer_email"] = email
    c1 = await new_conversation(acme, email)
    await say(acme, c1, "Where is my order A1008?", email)
    o1 = await close_conversation(acme, c1)
    assert o1["type"] == "resolved" and o1["status"] == "pending" and not o1["billable"]
    assert o1["evidence"]["tool_results"] and o1["evidence"]["supervisor"]["final"] == "approve"

    c2 = await new_conversation(acme, email)
    await say(acme, c2, "Where is my order A1008? Still nothing", email)
    await close_conversation(acme, c2)
    later = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=80)
    await finalize_due(acme, now=later)
    f1 = await one(acme, "select * from outcomes where conversation_id=%s", (c1,))
    assert f1["status"] == "final" and not f1["billable"] and "repeat" in f1["nonbillable_reason"]
    f2 = await one(acme, "select * from outcomes where conversation_id=%s", (c2,))
    assert f2["status"] == "final" and f2["billable"] and float(f2["amount_usd"]) > 0


async def test_f9_escalations_are_free(acme, sandbox):
    from cairn.outcomes.engine import close_conversation

    cid = await new_conversation(acme)
    await say(acme, cid, "Let me talk to a human")
    o = await close_conversation(acme, cid)
    assert o["type"] == "escalated"


# ------------------------------------------------------------------ F10

async def test_f10_one_page_reconstructs_why_a_reply_was_sent(client, acme, sandbox):
    cid = await new_conversation(acme, MAYA)
    res = await say(acme, cid, "How long does a refund take to show up on my card? My email is maya.chen@example.com", MAYA)
    t = (await client.get(f"/api/turns/{res.turn_id}")).json()
    steps = {s["step"] for s in t["trail"]["steps"]}
    assert {"triage", "retrieve", "draft", "supervise", "reply_rules", "respond"} <= steps
    retrieval = next(s for s in t["trail"]["steps"] if s["step"] == "retrieve")
    assert retrieval["output"]["sources"], "retrieved sources are on the trail"
    assert all(s["model"] for s in t["trail"]["steps"] if s["kind"] in ("model", "supervisor"))
    assert t["trail"]["verdicts"] and t["trail"]["verdicts"][0]["reason_code"]
    assert t["trail"]["rules"], "reply rules evaluated are recorded"
    assert t["latency_ms"] is not None and t["cost_usd"] is not None
    assert any(m["role"] == "agent" for m in t["messages"])
    raw = json.dumps(t["trail"]["steps"])
    assert MAYA not in raw, "personal data is masked in traces"


async def test_f10_trail_is_append_only(acme):
    async with tenant_tx(acme) as conn:
        row = await fetch_one(conn, "select id from turn_traces limit 1")
    with pytest.raises(Exception, match="append-only"):
        async with tenant_tx(acme) as conn:
            await conn.execute("update turn_traces set summary='tampered' where id=%s", (row["id"],))


async def test_f10_export_json_and_csv(client):
    r = await client.get("/api/audit/export?format=csv")
    assert r.status_code == 200 and r.text.splitlines()[0].startswith("created_at")
    r = await client.get("/api/audit/export?format=json")
    assert isinstance(r.json(), list)


# ------------------------------------------------------------------ F11

async def test_f11_failing_config_is_refused_and_rollback_is_exact(client, acme):
    cfg = (await client.get("/api/config")).json()
    v_pub = cfg["published"]["version"]
    original = cfg["published"]["config"]

    bad = json.loads(json.dumps(original))
    bad["policy"]["competitors"] = []  # the supervisor would let competitor mentions through
    assert (await client.put("/api/config/draft", json={"config": bad, "note": "drop competitors"})).status_code == 200
    r = await client.post("/api/config/publish", json={})
    assert r.status_code == 409
    assert (await client.get("/api/config")).json()["published"]["version"] == v_pub

    good = json.loads(json.dumps(original))
    good["tone"]["voice"] = "Friendly and brief."
    await client.put("/api/config/draft", json={"config": good, "note": "voice tweak"})
    r = await client.post("/api/config/publish", json={})
    assert r.status_code == 200, r.text
    assert (await client.get("/api/config")).json()["published"]["config"]["tone"]["voice"] == "Friendly and brief."

    r = await client.post("/api/config/rollback", json={"version": v_pub})
    assert r.status_code == 200
    now = (await client.get("/api/config")).json()["published"]
    assert now["config"] == original and now["version"] == r.json()["published"]


async def test_f11_roles_are_enforced(acme):
    import httpx

    from cairn.api.app import app

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        await c.post("/api/auth/login", json={"email": "viewer@acme.test", "password": "cairn-demo"})
        assert (await c.get("/api/conversations")).status_code == 200
        assert (await c.post("/api/rules/refund_hard_cap_500/publish")).status_code == 403
        assert (await c.post("/api/config/rollback", json={"version": 1})).status_code == 403


async def test_f11_admin_actions_are_logged(client):
    await client.post("/api/rules/refund_hard_cap_500/toggle", json={"enabled": True})
    log = (await client.get("/api/audit-log")).json()["items"]
    assert any(a["action"] == "rule.enable" for a in log)


# ------------------------------------------------------------------ F12

def test_f12_full_suite_runs_with_one_command():
    import os
    import subprocess
    import sys

    p = subprocess.run([sys.executable, "-m", "cairn.cli", "eval", "run", "--suite", "critical"],
                       capture_output=True, text=True, env=os.environ.copy(), timeout=300)
    assert p.returncode == 0, p.stdout + p.stderr
    assert "Release gate: PASSED" in p.stdout


# ------------------------------------------------------------------ F13

async def test_f13_every_dashboard_number_reproduces_from_its_query(acme):
    from cairn.insights.queries import QUERIES, run

    report = await run(acme, days=30)
    since = report["since"]
    async with system_tx() as conn:
        for key, q in QUERIES.items():
            await conn.execute("select set_config('app.tenant_id', %s, true)", (str(acme),))
            # Raw table access, with the tenant filter applied explicitly rather than by RLS.
            raw = await fetch_all(conn, f"with x as ({q['sql']}) select * from x", {"since": since})
            assert json.dumps(raw, default=str) != "" and len(raw) == len(report["metrics"][key]["rows"]), key


# ------------------------------------------------------------------ F16

async def test_f16_another_tenants_credentials_read_zero_rows_from_every_table(acme, globex, sandbox):
    cid = await new_conversation(globex, "maya.chen@example.com")
    await say(globex, cid, "Where is my order A1002?", "maya.chen@example.com")
    async with system_tx() as conn:
        tables = [r["relname"] for r in await fetch_all(conn, """
            select c.relname from pg_class c join pg_namespace n on n.oid=c.relnamespace
            where n.nspname='public' and c.relkind='r' and c.relname <> 'schema_migrations'""")]
        acme_rows = {}
        for t in tables:
            acme_rows[t] = (await fetch_one(conn, f"select count(*) as n from {t} where tenant_id=%s", (acme,)))["n"]
    assert sum(acme_rows.values()) > 0
    async with tenant_tx(globex) as conn:
        for t in tables:
            n = await fetch_one(conn, f"select count(*) as n from {t} where tenant_id=%s", (acme,))
            assert n["n"] == 0, f"{t}: globex can read acme rows"
    async with anon_tx() as conn:
        for t in tables:
            n = await fetch_one(conn, f"select count(*) as n from {t}")
            assert n["n"] == 0, f"{t}: rows visible without a tenant"
    with pytest.raises(Exception):
        async with tenant_tx(globex) as conn:
            await conn.execute("insert into knowledge_sources (tenant_id, title, owner, content) values (%s,'x','x','x')",
                               (acme,))


async def test_f7_concurrent_first_contacts_resolve_to_one_customer(acme):
    """A chat and an email from a new person at the same moment must not race the customer insert."""
    from cairn.channels.service import start_conversation

    for _ in range(5):  # the race needs warm pool connections to show up reliably
        email = f"race-{uuid.uuid4().hex[:8]}@example.com"
        results = await asyncio.gather(*[start_conversation(acme, "web", CustomerRef(email=email, verified=True))
                                         for _ in range(12)])
        assert len({cust for _, cust in results}) == 1
        n = await one(acme, "select count(*) as n from customers where email=%s", (email,))
        assert n["n"] == 1
