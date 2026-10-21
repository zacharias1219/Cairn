# Cairn

**Every agent leaves a trail.**

Cairn is an AI agent platform that answers customers, takes real actions in a company's systems, and leaves an
audit trail for every decision it makes. It is the supervised, auditable front door for a business, ready for
customers and for the personal AI agents they send.

It is built around the three bets in the PRD, and nothing more:

1. **A supervised agent loop with a full audit trail.** A supervisor reviews every drafted reply and proposed action
   before anything reaches a customer. Money and policy rules run in deterministic code. Every step is written to an
   append-only trail that explains, on one page, why any reply was sent.
2. **PAP as a native channel.** Customers' personal agents reach the business through a permissioned route: guest
   sessions for questions, signed-in sessions only after the customer consents and picks read or write scope.
3. **Memory that is erasable by design.** One request deletes a customer from every store, including summaries and
   embeddings, and returns a receipt. CI fails if a table could leave personal data behind.

---

## What's in the repository

| Path | What it is |
| --- | --- |
| `backend/` | One Python service (FastAPI): orchestrator, supervisor, rule engine, tool layer, knowledge, memory, outcomes, PAP gateway, email, insights, job worker, CLI |
| `backend/cairn/db/migrations/` | Plain-SQL schema with row-level security on every table from the first migration |
| `backend/tests/` | Acceptance tests, one or more per "Accept when" criterion in the PRD |
| `console/` | Operator console (Next.js, TypeScript, Tailwind) and the public product site |
| `widget/` | The web chat widget: plain TypeScript, Shadow DOM, one script tag, 5 KB gzipped |
| `examples/pap_reference_agent.py` | A reference personal agent that runs the full PAP flow |
| `.github/workflows/ci.yml` | Tests, release gates, console build and widget size budget on every change |

## Quick start

With Docker:

```bash
scripts/gen-env.sh          # writes .env with random database passwords and keys (gitignored)
docker compose up --build
docker compose exec api cairn demo-traffic    # optional: a month of realistic history
# console  http://localhost:3000   (admin@acme.test / cairn-demo)
# demo     http://localhost:8000/demo/acme
```

Without Docker (PostgreSQL 16 with pgvector on localhost, Python 3.11+, Node 22), first put your database URLs
in `backend/.env` (see `.env.example`), then:

```bash
./scripts/dev.sh --demo     # migrate, seed Acme Outfitters, generate a month of history, start API + console
```

Or step by step:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e "backend[dev]"
cd backend
cairn db migrate            # schema, RLS policies, the cairn_app role
cairn seed                  # Acme Outfitters: policies, 12 rules with fixtures, 7 sandbox tools, 227 eval cases
cairn demo-traffic          # ~160 real conversations through the agent, back-dated over 30 days
cairn eval run              # every release gate; exits 1 if one fails
uvicorn cairn.api.app:app --port 8000
(cd ../widget && npm i && npm run build)
(cd ../console && npm i && npm run dev)
```

Sign in at `http://localhost:3000/login` as `admin@acme.test`, `builder@acme.test` or `viewer@acme.test`
(password `cairn-demo`).

### Models

Set `ANTHROPIC_API_KEY` and Cairn runs on Claude through one model gateway: Claude Opus 5.5 plans and drafts,
Claude Haiku 5.5 handles triage, supervision and memory summaries, each step with a fallback model (server-side
refusal fallbacks are enabled on Opus). Which model runs each step is configuration, editable in the console.

Without a key, Cairn runs on **sandbox models**: deterministic, code-only implementations of every step. They power
the demo, the tests and CI without network access, and make seeded failures reproducible. The console shows which
mode is active, and the trail labels every sandbox step. Sandbox costs are estimates priced as if Claude had run.

## A tour

| Console page | What to look at |
| --- | --- |
| **Overview** | Verified resolution rate against the 60% target, escalations, cost per resolution, CSAT, p95 latency, supervisor interventions, contact reasons, release-gate status |
| **Conversations → any conversation** | The transcript next to *the trail*: triage, retrieved sources with scores, plans, tool calls with idempotency keys and approvers, every supervisor check, every rule evaluated, latency and cost per step |
| **Approvals** | High-risk actions and rule-flagged refunds waiting for a named person, with full context. Approving runs the call and the customer is told in the same conversation |
| **Playground** | Talk to the draft configuration and watch the trail build. *Seed the next draft* with a known failure (invented policy, a refund that never ran, a leaked email) and watch the supervisor stop it |
| **Agent config** | Brand voice, competitors, sensitive topics, models per step, limits. Versioned JSON with diff; publishing runs the evaluation suite and is refused if a gate fails; rollback restores a version exactly |
| **Rules** | JSON-logic rules with fixtures and a live tester. A rule with a failing fixture cannot be published |
| **Tools** | MCP tools with strict schemas and risk tiers; credentials stored with envelope encryption |
| **Knowledge** | Sources with owners and review dates, stale flags, and a search tester showing exactly what the agent would retrieve |
| **Evaluations** | 227 cases (26 scenarios, 201 critical seeded and adversarial cases), the five release gates, per-category results |
| **Customers & privacy** | Memory, consent, export as JSON, and erasure with a receipt of counts per store |
| **Outside agents** | PAP agents with allow/deny and rate limits, sessions with consent records, the action log, the manifest |
| **Outcomes & billing** | The published rate card, the estimated invoice, why each conversation was or wasn't billed, and the evidence behind every charge |
| **Insights** | Every number with the SQL that produced it |

Open `http://localhost:8000/demo/acme` for the storefront with the widget. Pick a signed-in customer to try
verified flows (Maya: refunds under $100; Sam: a $249 refund that waits for approval; Jordan: Trail Club
cancellation and a refund outside the 30-day window).

## How a turn works

```
customer message ─▶ channel gateway (one Message schema)
                     │
                     ▼
            ┌── triage ─────────────┐   input screening runs in parallel
            │   (intent, entities)  │   (prompt injection, sensitive topics)
            └──┬────────┬───────────┘
               │        └─▶ escalate (human asked, sensitive topic)
       retrieve│        act: plan → tool ─▶ rules ─▶ approval? ─▶ run (idempotent)
               ▼              │
             draft ◀──────────┘    writes are confirmed with the customer first
               │
           supervise ── revise (feedback, ≤2) ─┐
               │  └── block / escalate         │
               ▼                               │
          reply rules ◀────────────────────────┘
               │
            respond      state checkpointed to Postgres after every step
```

* **Fail closed.** A supervisor timeout or a model outage escalates; it never sends.
* **Rules in code.** `backend/cairn/rules/` evaluates JSON-logic with no model, clock or I/O on the path.
* **Untrusted input.** Customer text, documents, tool results and outside-agent content stay inside `<untrusted>`
  tags; personal data is swapped for reversible tokens before it reaches a model and revealed at the tool boundary.
* **Tenants never touch.** The app connects as a role that cannot bypass row-level security; an unset tenant sees zero
  rows. A test reads every table with another tenant's credentials and gets nothing.

## Acceptance criteria → tests

`cd backend && pytest` runs against a dedicated database and covers:

| PRD | Test |
| --- | --- |
| F1 | chat and email produce identical `Message` objects apart from `channel`; email threads and DKIM-ready replies |
| F2 | a turn killed after a step resumes at the last completed step without repeating tool calls; models per step are config; step limit escalates |
| F3 | ≥200 seeded policy and adversarial cases, 100% of critical ones stopped; every verdict stored with a reason; timeout fails closed; revise loop then escalate |
| F4 | same input, same result; no model on the path; a rule with a failing fixture cannot be published |
| F5 | the same refund twice with one idempotency key refunds once; a high-tier call without approval is refused and logged; schemas enforced; approval flow |
| F6 | a policy answer cites its source; deleting a source removes its chunks from retrieval immediately |
| F7 | erasure leaves zero references in every table, every text and JSON column, the vector index and the session cache; the registry covers every table with a `customer_id` |
| F8 | the reference agent completes a guest read and a consented write; writes without scope, to someone else's order, or from a denied agent are refused and logged |
| F9 | outcomes are pending until the window closes; a repeat contact makes a resolution non-billable; escalations are free |
| F10 | one page reconstructs why a reply was sent; personal data masked in traces; the trail is append-only; JSON and CSV export |
| F11 | a config that fails a critical evaluation is refused; rollback restores the previous version exactly; roles enforced; admin actions logged |
| F12 | the full suite runs with one command and gates the release |
| F13 | every dashboard number reproduces from its documented query |
| F16 | another tenant's credentials read zero rows from every table |

## Scope

Built: MVP and V1 from the PRD (F1–F13, F16), including the email channel, erasable memory, the outcome engine, the
operator console, the PAP gateway and basic insights.

Not built, as planned for V2: Slack teammate (F14), voice (F15), SMS and WhatsApp, SSO, SOC 2 preparation, and more
integrations. The PAP adapter follows the protocol's announcement; mapping it to the v0.1 specification's endpoints
is the open work item the PRD names. Compliance targets in the PRD need counsel review before any public claim.

## Configuration

| Variable | Default | |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | – | Enables Claude; otherwise sandbox models |
| `CAIRN_MODEL_MODE` | `auto` | `auto`, `sandbox` or `anthropic` |
| `CAIRN_DATABASE_URL` | required | App role (`cairn_app`), subject to RLS. Its password is set from this URL on migrate |
| `CAIRN_ADMIN_DATABASE_URL` | required | Migrations, provisioning, job claims |
| `CAIRN_ENV` | `development` | `production` refuses to start without the two keys below |
| `CAIRN_SECRET_KEY` | generated in dev | Signs console sessions |
| `CAIRN_MASTER_KEY` | generated in dev | Base64 of 32 bytes; wraps per-secret data keys (use your KMS in production) |
| `CAIRN_DKIM_PRIVATE_KEY_PATH` | – | Signs outbound email when set |
| `CAIRN_RUN_WORKER` | `true` | Runs the job worker inside the API process |

No credential has a default in code. In development, missing keys are generated once into
`backend/.cairn-dev-keys.json` (gitignored, mode 600). `scripts/gen-env.sh` creates a `.env` with random values
for Docker Compose, and CI uses a throwaway Postgres with trust auth, so no password is stored in the repository.
The demo users' password (`cairn-demo`) belongs to the seeded sandbox tenant only.
