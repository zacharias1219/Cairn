-- Cairn foundation schema.
--
-- Principle 5, "tenants never touch": every table carries tenant_id and has
-- row-level security enabled and forced from this first migration. The
-- application connects as `cairn_app`, which owns nothing and cannot bypass
-- RLS. The tenant for a transaction is set with
--   select set_config('app.tenant_id', '<uuid>', true)
-- and an unset value matches no rows (fail closed).

create extension if not exists vector;

create or replace function cairn_tenant() returns uuid
language sql stable as $$
  select nullif(current_setting('app.tenant_id', true), '')::uuid
$$;

-- ---------------------------------------------------------------- tenancy

create table tenants (
  id            uuid primary key default gen_random_uuid(),
  tenant_id     uuid generated always as (id) stored,
  name          text not null,
  slug          text not null unique,
  plan          text not null default 'pilot' check (plan in ('pilot','growth','scale')),
  settings      jsonb not null default '{}'::jsonb,
  widget_key    text not null unique,
  identity_secret text not null,
  created_at    timestamptz not null default now()
);

create table users (
  id            uuid primary key default gen_random_uuid(),
  tenant_id     uuid not null references tenants(id) on delete cascade,
  email         text not null unique,
  name          text not null,
  password_hash text not null,
  role          text not null check (role in ('admin','builder','viewer')),
  created_at    timestamptz not null default now(),
  last_login_at timestamptz
);

create table api_keys (
  id            uuid primary key default gen_random_uuid(),
  tenant_id     uuid not null references tenants(id) on delete cascade,
  name          text not null,
  prefix        text not null,
  key_hash      text not null unique,
  scopes        text[] not null,
  created_by    uuid references users(id) on delete set null,
  created_at    timestamptz not null default now(),
  last_used_at  timestamptz,
  revoked_at    timestamptz
);

-- Admin actions: rule publishes, role changes, rollbacks, erasures.
create table admin_audit (
  id            bigserial primary key,
  tenant_id     uuid not null references tenants(id) on delete cascade,
  actor_id      uuid,
  actor_label   text not null,
  action        text not null,
  target        text,
  detail        jsonb not null default '{}'::jsonb,
  at            timestamptz not null default now()
);
create index on admin_audit (tenant_id, at desc);

-- ------------------------------------------------------- configuration

create table agent_configs (
  id            uuid primary key default gen_random_uuid(),
  tenant_id     uuid not null references tenants(id) on delete cascade,
  version       int not null,
  status        text not null check (status in ('draft','published','archived')),
  config        jsonb not null,
  note          text,
  created_by    uuid references users(id) on delete set null,
  published_by  uuid references users(id) on delete set null,
  published_at  timestamptz,
  eval_run_id   uuid,
  created_at    timestamptz not null default now(),
  unique (tenant_id, version)
);

create table rules (
  id            uuid primary key default gen_random_uuid(),
  tenant_id     uuid not null references tenants(id) on delete cascade,
  rule_key      text not null,
  version       int not null,
  status        text not null check (status in ('draft','published','archived')),
  enabled       boolean not null default true,
  name          text not null,
  description   text not null default '',
  event         text not null check (event in ('tool_call','reply')),
  tool          text,
  condition     jsonb not null,
  outcome       text not null check (outcome in ('allow','warn','block','require_approval')),
  message       text not null default '',
  severity      text not null default 'high' check (severity in ('low','medium','high','critical')),
  fixtures      jsonb not null default '[]'::jsonb,
  created_by    uuid references users(id) on delete set null,
  published_by  uuid references users(id) on delete set null,
  published_at  timestamptz,
  created_at    timestamptz not null default now(),
  unique (tenant_id, rule_key, version)
);

create table tools (
  id                uuid primary key default gen_random_uuid(),
  tenant_id         uuid not null references tenants(id) on delete cascade,
  name              text not null,
  title             text not null,
  description       text not null,
  integration       text not null,
  server_url        text not null,
  input_schema      jsonb not null,
  output_schema     jsonb not null,
  risk_tier         text not null check (risk_tier in ('low','medium','high')),
  requires_approval boolean not null default false,
  is_write          boolean not null default false,
  pap_exposed       boolean not null default false,
  enabled           boolean not null default true,
  credential_ciphertext bytea,
  credential_wrapped_key bytea,
  created_at        timestamptz not null default now(),
  unique (tenant_id, name)
);

-- -------------------------------------------- customers & conversations

create table customers (
  id              uuid primary key default gen_random_uuid(),
  tenant_id       uuid not null references tenants(id) on delete cascade,
  display_name    text,
  email           text,
  phone           text,
  crm_id          text,
  memory_consent  boolean not null default true,
  attributes      jsonb not null default '{}'::jsonb,
  created_at      timestamptz not null default now(),
  last_seen_at    timestamptz not null default now(),
  unique (tenant_id, email),
  unique (tenant_id, phone),
  unique (tenant_id, crm_id)
);

create table conversations (
  id                uuid primary key default gen_random_uuid(),
  tenant_id         uuid not null references tenants(id) on delete cascade,
  customer_id       uuid references customers(id) on delete cascade,
  channel           text not null check (channel in ('web','email','pap','playground','eval')),
  status            text not null default 'active'
                    check (status in ('active','awaiting_approval','escalated','closed')),
  intent            text,
  issue_key         text,
  subject           text,
  external_thread_id text,
  config_version    int,
  is_test           boolean not null default false,
  state             jsonb not null default '{}'::jsonb,
  started_at        timestamptz not null default now(),
  last_activity_at  timestamptz not null default now(),
  ended_at          timestamptz,
  end_reason        text
);
create index on conversations (tenant_id, started_at desc);
create index on conversations (tenant_id, customer_id);
create index on conversations (tenant_id, external_thread_id);

create table messages (
  id              uuid primary key default gen_random_uuid(),
  tenant_id       uuid not null references tenants(id) on delete cascade,
  conversation_id uuid not null references conversations(id) on delete cascade,
  customer_id     uuid references customers(id) on delete cascade,
  turn_id         uuid,
  role            text not null check (role in ('customer','agent','human','system','outside_agent')),
  channel         text not null,
  content         text not null,
  attachments     jsonb not null default '[]'::jsonb,
  metadata        jsonb not null default '{}'::jsonb,
  external_id     text,
  created_at      timestamptz not null default now()
);
create index on messages (tenant_id, conversation_id, created_at);

-- Cached widget/session data (erasable).
create table chat_sessions (
  id              uuid primary key default gen_random_uuid(),
  tenant_id       uuid not null references tenants(id) on delete cascade,
  conversation_id uuid not null references conversations(id) on delete cascade,
  customer_id     uuid references customers(id) on delete cascade,
  token_hash      text not null unique,
  data            jsonb not null default '{}'::jsonb,
  created_at      timestamptz not null default now(),
  expires_at      timestamptz not null
);

create table customer_signals (
  id              uuid primary key default gen_random_uuid(),
  tenant_id       uuid not null references tenants(id) on delete cascade,
  conversation_id uuid references conversations(id) on delete cascade,
  customer_id     uuid references customers(id) on delete cascade,
  kind            text not null check (kind in ('csat','negative','positive')),
  value           int,
  comment         text,
  created_at      timestamptz not null default now()
);

-- ---------------------------------------------------- the trail (F10)

create table turns (
  id               uuid primary key default gen_random_uuid(),
  tenant_id        uuid not null references tenants(id) on delete cascade,
  conversation_id  uuid not null references conversations(id) on delete cascade,
  customer_id      uuid references customers(id) on delete cascade,
  seq              int not null,
  status           text not null default 'running'
                   check (status in ('running','awaiting_approval','completed','escalated','failed')),
  input_message_id uuid,
  reply_message_id uuid,
  final_action     text,
  final_verdict    text,
  config_version   int,
  steps            int not null default 0,
  cost_usd         numeric(12,6) not null default 0,
  latency_ms       int,
  started_at       timestamptz not null default now(),
  completed_at     timestamptz
);
create index on turns (tenant_id, conversation_id, seq);

-- Checkpoint after every orchestrator step (F2).
create table checkpoints (
  id               bigserial primary key,
  tenant_id        uuid not null references tenants(id) on delete cascade,
  conversation_id  uuid not null references conversations(id) on delete cascade,
  customer_id      uuid references customers(id) on delete cascade,
  turn_id          uuid not null references turns(id) on delete cascade,
  step_index       int not null,
  step             text not null,
  next_step        text,
  state            jsonb not null,
  created_at       timestamptz not null default now()
);
create index on checkpoints (tenant_id, turn_id, step_index desc);

-- One record per step of a turn. Append-only; personal data masked.
create table turn_traces (
  id               bigserial primary key,
  tenant_id        uuid not null references tenants(id) on delete cascade,
  conversation_id  uuid not null references conversations(id) on delete cascade,
  customer_id      uuid references customers(id) on delete cascade,
  turn_id          uuid not null references turns(id) on delete cascade,
  seq              int not null,
  step             text not null,
  kind             text not null,
  summary          text not null default '',
  model            text,
  input            jsonb not null default '{}'::jsonb,
  output           jsonb not null default '{}'::jsonb,
  latency_ms       int not null default 0,
  input_tokens     int not null default 0,
  output_tokens    int not null default 0,
  cost_usd         numeric(12,6) not null default 0,
  created_at       timestamptz not null default now()
);
create index on turn_traces (tenant_id, turn_id, seq);

create table supervisor_verdicts (
  id               uuid primary key default gen_random_uuid(),
  tenant_id        uuid not null references tenants(id) on delete cascade,
  conversation_id  uuid not null references conversations(id) on delete cascade,
  customer_id      uuid references customers(id) on delete cascade,
  turn_id          uuid not null references turns(id) on delete cascade,
  attempt          int not null,
  verdict          text not null check (verdict in ('approve','revise','block','escalate')),
  reason_code      text not null,
  reasons          jsonb not null default '[]'::jsonb,
  checks           jsonb not null default '[]'::jsonb,
  model            text,
  latency_ms       int not null default 0,
  created_at       timestamptz not null default now()
);
create index on supervisor_verdicts (tenant_id, created_at desc);

create table rule_decisions (
  id               uuid primary key default gen_random_uuid(),
  tenant_id        uuid not null references tenants(id) on delete cascade,
  conversation_id  uuid references conversations(id) on delete cascade,
  customer_id      uuid references customers(id) on delete cascade,
  turn_id          uuid references turns(id) on delete cascade,
  rule_key         text not null,
  rule_version     int not null,
  event            text not null,
  tool             text,
  outcome          text not null,
  message          text not null default '',
  context          jsonb not null default '{}'::jsonb,
  created_at       timestamptz not null default now()
);
create index on rule_decisions (tenant_id, rule_key, created_at desc);

create table tool_calls (
  id               uuid primary key default gen_random_uuid(),
  tenant_id        uuid not null references tenants(id) on delete cascade,
  conversation_id  uuid references conversations(id) on delete cascade,
  customer_id      uuid references customers(id) on delete cascade,
  turn_id          uuid references turns(id) on delete cascade,
  tool_name        text not null,
  risk_tier        text not null,
  input            jsonb not null,
  output           jsonb,
  idempotency_key  text not null,
  status           text not null check (status in
                   ('pending_approval','approved','denied','succeeded','failed','refused')),
  source           text not null default 'agent',
  approver_id      uuid references users(id) on delete set null,
  approver_label   text,
  decided_at       timestamptz,
  decision_note    text,
  error            text,
  latency_ms       int,
  created_at       timestamptz not null default now(),
  completed_at     timestamptz,
  unique (tenant_id, idempotency_key)
);
create index on tool_calls (tenant_id, status, created_at desc);

create table handoffs (
  id               uuid primary key default gen_random_uuid(),
  tenant_id        uuid not null references tenants(id) on delete cascade,
  conversation_id  uuid not null references conversations(id) on delete cascade,
  customer_id      uuid references customers(id) on delete cascade,
  reason_code      text not null,
  reason           text not null,
  transcript       jsonb not null,
  destination      text not null,
  delivery_status  text not null default 'queued',
  created_at       timestamptz not null default now()
);

create table outbox_emails (
  id               uuid primary key default gen_random_uuid(),
  tenant_id        uuid not null references tenants(id) on delete cascade,
  conversation_id  uuid references conversations(id) on delete cascade,
  customer_id      uuid references customers(id) on delete cascade,
  to_addr          text not null,
  from_addr        text not null,
  subject          text not null,
  body             text not null,
  message_id       text not null,
  in_reply_to      text,
  references_hdr   text,
  raw              text not null,
  dkim_signed      boolean not null default false,
  created_at       timestamptz not null default now(),
  sent_at          timestamptz
);

-- ---------------------------------------------------- knowledge (F6)

create table knowledge_sources (
  id                   uuid primary key default gen_random_uuid(),
  tenant_id            uuid not null references tenants(id) on delete cascade,
  title                text not null,
  kind                 text not null default 'policy' check (kind in ('policy','faq','doc')),
  owner                text not null,
  url                  text,
  content              text not null,
  reviewed_at          timestamptz not null default now(),
  review_interval_days int not null default 90,
  created_at           timestamptz not null default now(),
  updated_at           timestamptz not null default now()
);

create table knowledge_chunks (
  id          uuid primary key default gen_random_uuid(),
  tenant_id   uuid not null references tenants(id) on delete cascade,
  source_id   uuid not null references knowledge_sources(id) on delete cascade,
  ord         int not null,
  heading     text,
  content     text not null,
  tsv         tsvector generated always as (to_tsvector('english', coalesce(heading,'') || ' ' || content)) stored,
  embedding   vector(384) not null
);
create index on knowledge_chunks using gin (tsv);
create index on knowledge_chunks using hnsw (embedding vector_cosine_ops);

-- ------------------------------------------------------- memory (F7)

create table memory_items (
  id                     uuid primary key default gen_random_uuid(),
  tenant_id              uuid not null references tenants(id) on delete cascade,
  customer_id            uuid not null references customers(id) on delete cascade,
  kind                   text not null check (kind in ('fact','summary')),
  content                text not null,
  embedding              vector(384) not null,
  source_conversation_id uuid references conversations(id) on delete set null,
  created_at             timestamptz not null default now()
);
create index on memory_items (tenant_id, customer_id);

create table erasure_requests (
  id            uuid primary key default gen_random_uuid(),
  tenant_id     uuid not null references tenants(id) on delete cascade,
  customer_id   uuid not null,
  requested_by  text not null,
  requested_at  timestamptz not null default now(),
  completed_at  timestamptz,
  status        text not null default 'queued' check (status in ('queued','running','completed','failed')),
  receipt       jsonb
);

-- ------------------------------------------------------ outcomes (F9)

create table outcomes (
  id                 uuid primary key default gen_random_uuid(),
  tenant_id          uuid not null references tenants(id) on delete cascade,
  conversation_id    uuid not null unique,
  customer_id        uuid references customers(id) on delete set null,
  channel            text not null,
  type               text not null check (type in ('resolved','escalated','abandoned','failed')),
  status             text not null default 'pending' check (status in ('pending','final')),
  intent             text,
  issue_key          text,
  billable           boolean not null default false,
  amount_usd         numeric(10,4) not null default 0,
  nonbillable_reason text,
  evidence           jsonb not null default '{}'::jsonb,
  is_test            boolean not null default false,
  ended_at           timestamptz not null,
  window_ends_at     timestamptz not null,
  finalized_at       timestamptz,
  created_at         timestamptz not null default now()
);
create index on outcomes (tenant_id, status, window_ends_at);

-- ---------------------------------------------------- PAP gateway (F8)

create table pap_agents (
  id               uuid primary key default gen_random_uuid(),
  tenant_id        uuid not null references tenants(id) on delete cascade,
  agent_identity   text not null,
  display_name     text not null,
  status           text not null default 'allow' check (status in ('allow','deny')),
  rate_limit_per_min int not null default 30,
  created_at       timestamptz not null default now(),
  unique (tenant_id, agent_identity)
);

create table pap_sessions (
  id               uuid primary key default gen_random_uuid(),
  tenant_id        uuid not null references tenants(id) on delete cascade,
  agent_identity   text not null,
  customer_id      uuid references customers(id) on delete cascade,
  conversation_id  uuid references conversations(id) on delete set null,
  mode             text not null check (mode in ('guest','signed_in','pending_consent')),
  scopes           text[] not null default '{}',
  consent          jsonb,
  token_hash       text unique,
  code_hash        text unique,
  code_challenge   text,
  redirect_uri     text,
  created_at       timestamptz not null default now(),
  expires_at       timestamptz not null,
  revoked_at       timestamptz
);

create table pap_actions (
  id               uuid primary key default gen_random_uuid(),
  tenant_id        uuid not null references tenants(id) on delete cascade,
  session_id       uuid references pap_sessions(id) on delete cascade,
  customer_id      uuid references customers(id) on delete cascade,
  agent_identity   text not null,
  action           text not null,
  scope_required   text not null,
  allowed          boolean not null,
  outcome          text not null,
  detail           jsonb not null default '{}'::jsonb,
  created_at       timestamptz not null default now()
);
create index on pap_actions (tenant_id, created_at desc);

-- ---------------------------------------------------- evaluation (F12)

create table eval_cases (
  id          uuid primary key default gen_random_uuid(),
  tenant_id   uuid not null references tenants(id) on delete cascade,
  key         text not null,
  suite       text not null,
  name        text not null,
  category    text not null,
  critical    boolean not null default false,
  spec        jsonb not null,
  created_at  timestamptz not null default now(),
  unique (tenant_id, key)
);

create table eval_runs (
  id              uuid primary key default gen_random_uuid(),
  tenant_id       uuid not null references tenants(id) on delete cascade,
  config_version  int,
  trigger         text not null,
  status          text not null default 'running' check (status in ('running','passed','failed','error')),
  summary         jsonb not null default '{}'::jsonb,
  gates           jsonb not null default '[]'::jsonb,
  started_at      timestamptz not null default now(),
  finished_at     timestamptz
);

create table eval_results (
  id          uuid primary key default gen_random_uuid(),
  tenant_id   uuid not null references tenants(id) on delete cascade,
  run_id      uuid not null references eval_runs(id) on delete cascade,
  case_key    text not null,
  suite       text not null,
  category    text not null,
  critical    boolean not null,
  passed      boolean not null,
  failures    jsonb not null default '[]'::jsonb,
  observed    jsonb not null default '{}'::jsonb,
  latency_ms  int not null default 0,
  cost_usd    numeric(12,6) not null default 0
);
create index on eval_results (tenant_id, run_id);

-- --------------------------------------------------------------- jobs

create table jobs (
  id          bigserial primary key,
  tenant_id   uuid not null references tenants(id) on delete cascade,
  kind        text not null,
  payload     jsonb not null default '{}'::jsonb,
  status      text not null default 'queued' check (status in ('queued','running','done','failed')),
  attempts    int not null default 0,
  run_at      timestamptz not null default now(),
  locked_at   timestamptz,
  last_error  text,
  created_at  timestamptz not null default now()
);
create index on jobs (status, run_at);

-- ------------------------------------------------------ RLS everywhere

do $$
declare t text;
begin
  for t in
    select c.relname from pg_class c
    join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'public' and c.relkind = 'r'
      and c.relname <> 'schema_migrations'
  loop
    execute format('alter table %I enable row level security', t);
    execute format('alter table %I force row level security', t);
    execute format(
      'create policy tenant_isolation on %I using (tenant_id = cairn_tenant()) with check (tenant_id = cairn_tenant())', t);
  end loop;
end $$;

-- ------------------------------------------- append-only audit trail

create or replace function cairn_trail_guard() returns trigger
language plpgsql as $$
begin
  -- The trail is append-only. The single exception is erasure (F7),
  -- which runs with cairn.erasure = 'on' inside its own transaction.
  if coalesce(current_setting('cairn.erasure', true), '') = 'on' then
    return case when tg_op = 'DELETE' then old else new end;
  end if;
  raise exception 'trail tables are append-only (%.%)', tg_table_name, tg_op;
end $$;

create trigger turn_traces_append_only before update or delete on turn_traces
  for each row execute function cairn_trail_guard();
create trigger supervisor_verdicts_append_only before update or delete on supervisor_verdicts
  for each row execute function cairn_trail_guard();
create trigger rule_decisions_append_only before update or delete on rule_decisions
  for each row execute function cairn_trail_guard();
create trigger admin_audit_append_only before update or delete on admin_audit
  for each row execute function cairn_trail_guard();

-- ---------------------------- narrow cross-tenant lookups (definer fns)
-- The app role cannot see other tenants. These functions answer exactly
-- one question each, so login and key lookups work without opening RLS.

create or replace function auth_user_by_email(p_email text)
returns table (id uuid, tenant_id uuid, password_hash text, role text)
language sql security definer set search_path = public stable as $$
  select id, tenant_id, password_hash, role from users where lower(email) = lower(p_email)
$$;

create or replace function auth_api_key(p_hash text)
returns table (id uuid, tenant_id uuid, scopes text[])
language sql security definer set search_path = public stable as $$
  select id, tenant_id, scopes from api_keys where key_hash = p_hash and revoked_at is null
$$;

create or replace function auth_tenant_by_widget_key(p_key text)
returns table (id uuid, identity_secret text)
language sql security definer set search_path = public stable as $$
  select id, identity_secret from tenants where widget_key = p_key
$$;

create or replace function auth_tenant_by_slug(p_slug text)
returns table (id uuid, name text)
language sql security definer set search_path = public stable as $$
  select id, name from tenants where slug = p_slug
$$;
