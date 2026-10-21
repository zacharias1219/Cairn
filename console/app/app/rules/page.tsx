"use client";

import { FlaskConical, Plus, Rocket, Save, Scale, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";

import { FailureList, GateList } from "@/components/gates";
import { can, useMe } from "@/components/shell";
import { Badge, Button, Card, Drawer, Field, Input, JsonView, LoadingRows, PageHeader, Select, StatusBadge, Switch, Table, Tabs, Td, Textarea, Th, cx, useToast } from "@/components/ui";
import { api, useApi } from "@/lib/api";
import { ago, date } from "@/lib/format";

const BLANK = {
  rule_key: "", name: "", description: "", event: "tool_call", tool: "issue_refund", outcome: "require_approval",
  severity: "high", message: "", condition: { ">": [{ var: "args.amount" }, 100] },
  fixtures: [{ name: "fires above the limit", context: { args: { amount: 150 } }, expect: true }],
};

export default function Rules() {
  const me = useMe();
  const { data, mutate, isLoading } = useApi<{ items: any[] }>("/api/rules");
  const [open, setOpen] = useState<any>(null);
  const items = data?.items || [];
  return (
    <>
      <PageHeader eyebrow="Build" title="Rules"
        description="Money limits, eligibility and consent, in deterministic code. Evaluated before any tool call runs and before any reply is sent. No model can override them."
        actions={can(me, "builder") && <Button variant="primary" icon={<Plus className="h-3.5 w-3.5" />} onClick={() => setOpen({ ...BLANK, isNew: true })}>New rule</Button>} />
      <div className="grid gap-3 sm:grid-cols-4 mb-4">
        {[["block", "Block"], ["require_approval", "Needs approval"], ["warn", "Warn"], ["allow", "Allow"]].map(([o, l]) => (
          <Card key={o} className="px-4 py-3 flex items-center justify-between">
            <span className="text-[12.5px] text-muted">{l}</span>
            <span className="text-[20px] font-semibold num">{items.filter((r) => r.outcome === o).length}</span>
          </Card>
        ))}
      </div>
      <Card>
        {isLoading && !data ? <LoadingRows /> : (
          <Table>
            <thead><tr><Th>Rule</Th><Th>Applies to</Th><Th>Outcome</Th><Th>Version</Th><Th align="right">Fired (30d)</Th><Th align="right">Fixtures</Th></tr></thead>
            <tbody>
              {items.map((r) => (
                <tr key={r.rule_key} onClick={() => setOpen(r)} className={cx("cursor-pointer hover:bg-subtle/60 transition-colors", !r.enabled && "opacity-50")}>
                  <Td>
                    <div className="font-medium">{r.name}</div>
                    <div className="text-[11.5px] text-faint font-mono">{r.rule_key}</div>
                  </Td>
                  <Td><Badge>{r.event === "reply" ? "every reply" : r.tool ? r.tool : "every tool call"}</Badge></Td>
                  <Td><StatusBadge value={r.outcome} /></Td>
                  <Td>
                    <span className="font-mono text-[12.5px]">v{r.published_version ?? "—"}</span>
                    {r.status === "draft" && <Badge tone="revise" className="ml-1.5">draft v{r.version}</Badge>}
                    {!r.enabled && <Badge className="ml-1.5">disabled</Badge>}
                  </Td>
                  <Td align="right">{r.firings_30d}</Td>
                  <Td align="right" className="text-muted">{r.fixtures.length}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
      {open && <RuleDrawer rule={open} onClose={() => setOpen(null)} onSaved={mutate} />}
    </>
  );
}

function RuleDrawer({ rule, onClose, onSaved }: { rule: any; onClose: () => void; onSaved: () => void }) {
  const me = useMe();
  const toast = useToast();
  const editable = can(me, "builder");
  const [r, setR] = useState<any>(() => structuredClone(rule));
  const [cond, setCond] = useState(JSON.stringify(rule.condition, null, 2));
  const [fix, setFix] = useState(JSON.stringify(rule.fixtures, null, 2));
  const [tab, setTab] = useState<"rule" | "test" | "history">("rule");
  const [ctx, setCtx] = useState(JSON.stringify(rule.fixtures?.[0]?.context || { args: { amount: 150 } }, null, 2));
  const [result, setResult] = useState<any>(null);
  const [fixtureFailures, setFixtureFailures] = useState<any[] | null>(null);
  const [report, setReport] = useState<any>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const { data: detail } = useApi<any>(rule.isNew ? null : `/api/rules/${rule.rule_key}`);

  function parsed() {
    try { return { condition: JSON.parse(cond), fixtures: JSON.parse(fix) }; }
    catch { toast({ title: "Invalid JSON", body: "Check the condition and fixtures.", tone: "block" }); return null; }
  }

  async function save() {
    const p = parsed(); if (!p) return;
    setBusy("save");
    try {
      const out = await api("/api/rules", { body: { ...r, ...p, tool: r.event === "reply" ? null : r.tool || null } });
      setFixtureFailures(out.fixture_failures);
      toast({ title: `Draft v${out.version} saved`, body: out.fixture_failures.length ? `${out.fixture_failures.length} fixture(s) failing — publishing will be refused.` : "All fixtures pass.", tone: out.fixture_failures.length ? "revise" : "approve" });
      onSaved();
    } catch (e: any) { toast({ title: "Save failed", body: e.message, tone: "block" }); }
    finally { setBusy(null); }
  }

  async function publish() {
    await save();
    setBusy("publish");
    setReport(null);
    try {
      const out = await api(`/api/rules/${r.rule_key}/publish`, { method: "POST" });
      setReport({ ...out.report, ok: true });
      toast({ title: `Published v${out.published}`, body: "Fixtures and every release gate passed." });
      onSaved();
    } catch (e: any) {
      const d = e.detail as any;
      if (d?.fixture_failures) { setFixtureFailures(d.fixture_failures); toast({ title: "Publish refused", body: "A fixture failed.", tone: "block" }); }
      else if (d?.report) setReport({ ...d.report, ok: false });
      else toast({ title: "Publish failed", body: e.message, tone: "block" });
    } finally { setBusy(null); }
  }

  async function test() {
    try {
      const out = await api(`/api/rules/${r.rule_key}/test`, { body: { context: JSON.parse(ctx) } });
      setResult(out);
    } catch (e: any) { toast({ title: "Test failed", body: e.message, tone: "block" }); }
  }

  async function toggle(enabled: boolean) {
    await api(`/api/rules/${r.rule_key}/toggle`, { body: { enabled } });
    setR({ ...r, enabled });
    onSaved();
  }

  return (
    <Drawer open onClose={onClose} width={720} title={r.isNew ? "New rule" : r.name} subtitle={!r.isNew && <span className="font-mono">{r.rule_key} · published v{r.published_version ?? "—"}</span>}
      footer={editable && <>
        {!r.isNew && me?.role === "admin" && <label className="mr-auto flex items-center gap-2 text-[12.5px] text-muted"><Switch checked={r.enabled} onChange={toggle} /> Enabled</label>}
        <Button icon={<Save className="h-3.5 w-3.5" />} onClick={save} loading={busy === "save"}>Save draft</Button>
        <Button variant="primary" icon={<Rocket className="h-3.5 w-3.5" />} onClick={publish} loading={busy === "publish"} disabled={!r.rule_key}>Publish</Button>
      </>}>
      <Tabs value={tab} onChange={setTab} tabs={[{ value: "rule", label: "Rule" }, { value: "test", label: "Test" }, ...(r.isNew ? [] : [{ value: "history" as const, label: "Versions & firings" }])]} />
      {tab === "rule" && (
        <fieldset disabled={!editable} className="space-y-4">
          <div className="grid sm:grid-cols-2 gap-3">
            <Field label="Name"><Input value={r.name} onChange={(e) => setR({ ...r, name: e.target.value })} /></Field>
            <Field label="Key" hint="Lowercase, underscores"><Input value={r.rule_key} disabled={!r.isNew} onChange={(e) => setR({ ...r, rule_key: e.target.value })} className="font-mono" /></Field>
          </div>
          <Field label="Description"><Input value={r.description} onChange={(e) => setR({ ...r, description: e.target.value })} /></Field>
          <div className="grid sm:grid-cols-3 gap-3">
            <Field label="When"><Select value={r.event} onChange={(e) => setR({ ...r, event: e.target.value })}><option value="tool_call">Before a tool call</option><option value="reply">Before a reply is sent</option></Select></Field>
            {r.event === "tool_call" && <Field label="Tool"><Select value={r.tool || ""} onChange={(e) => setR({ ...r, tool: e.target.value || null })}>
              <option value="">Any tool</option>{["issue_refund", "cancel_subscription", "update_shipping_address", "apply_goodwill_credit", "lookup_order", "lookup_subscription", "verify_customer"].map((t) => <option key={t}>{t}</option>)}
            </Select></Field>}
            <Field label="Outcome"><Select value={r.outcome} onChange={(e) => setR({ ...r, outcome: e.target.value })}>
              <option value="block">Block</option><option value="require_approval">Require approval</option><option value="warn">Warn</option><option value="allow">Allow</option>
            </Select></Field>
          </div>
          <Field label="Message" hint="Shown to the customer when the rule blocks an action, and to approvers."><Textarea rows={2} value={r.message} onChange={(e) => setR({ ...r, message: e.target.value })} /></Field>
          <Field label="Condition (JSON-logic)" hint={<>Reads <code className="font-mono">args</code>, <code className="font-mono">order</code>, <code className="font-mono">customer</code>, <code className="font-mono">subscription</code>, <code className="font-mono">conversation</code>, <code className="font-mono">reply</code>. Pure: no clock, no I/O, no model.</>}>
            <Textarea rows={7} value={cond} onChange={(e) => setCond(e.target.value)} className="font-mono text-[12.5px]" spellCheck={false} />
          </Field>
          <Field label="Fixtures" hint="Each: name, context, expect (true = the rule fires). A rule cannot be published until every fixture passes.">
            <Textarea rows={8} value={fix} onChange={(e) => setFix(e.target.value)} className="font-mono text-[12.5px]" spellCheck={false} />
          </Field>
          {fixtureFailures && (
            <div className={cx("rounded-lg border px-3 py-2 text-[12.5px]", fixtureFailures.length ? "border-block/30 bg-block/5 text-block" : "border-approve/30 bg-approve/5 text-approve")}>
              {fixtureFailures.length ? fixtureFailures.map((f, i) => <div key={i}><b>{f.fixture}:</b> {f.error}</div>) : "All fixtures pass."}
            </div>
          )}
          {report && <div className="pt-2"><div className="text-[13px] font-medium mb-2">{report.ok ? "Published — every gate passed" : "Publish refused by the release gates"}</div><GateList gates={report.gates} /><FailureList failures={report.failures} /></div>}
        </fieldset>
      )}
      {tab === "test" && (
        <div className="space-y-3">
          <Field label="Context"><Textarea rows={10} value={ctx} onChange={(e) => setCtx(e.target.value)} className="font-mono text-[12.5px]" spellCheck={false} /></Field>
          <Button icon={<FlaskConical className="h-3.5 w-3.5" />} onClick={test} disabled={r.isNew}>Evaluate</Button>
          {r.isNew && <div className="text-[12px] text-faint">Save the rule once to test it.</div>}
          {result && (
            <div className="rounded-xl border border-line p-4 animate-rise">
              <div className="flex items-center gap-2"><Scale className="h-4 w-4 text-faint" /><span className="text-[13px]">Outcome</span><StatusBadge value={result.outcome} />
                <span className="text-[12.5px] text-muted">{result.fires ? "The rule fires." : "The rule does not fire."}</span></div>
              <div className="text-[11.5px] text-faint mt-2">Same input, same result, every time.</div>
            </div>
          )}
        </div>
      )}
      {tab === "history" && detail && (
        <div className="space-y-5">
          <div>
            <div className="label mb-2">Versions</div>
            <div className="space-y-1.5">{detail.versions.map((v: any) => (
              <div key={v.version} className="flex items-center gap-3 rounded-lg border border-line px-3 py-2 text-[12.5px]">
                <span className="font-mono">v{v.version}</span><StatusBadge value={v.status === "published" ? "approve" : "pending"} label={v.status} />
                <span className="text-muted">{v.published_at ? `published ${date(v.published_at, true)}` : `created ${ago(v.created_at)}`}</span>
              </div>
            ))}</div>
          </div>
          <div>
            <div className="label mb-2">Recent firings</div>
            {detail.recent_firings.length === 0 ? <div className="text-[12.5px] text-muted">This rule has not fired yet.</div> : (
              <div className="space-y-1.5">{detail.recent_firings.map((f: any, i: number) => (
                <a key={i} href={`/app/conversations/${f.conversation_id}`} className="flex items-center gap-3 rounded-lg border border-line px-3 py-2 text-[12.5px] hover:bg-subtle">
                  <StatusBadge value={f.outcome} /><span className="text-muted truncate flex-1">{f.message}</span><span className="text-faint">{ago(f.created_at)}</span>
                </a>
              ))}</div>
            )}
          </div>
        </div>
      )}
    </Drawer>
  );
}
