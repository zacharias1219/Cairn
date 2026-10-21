"use client";

import { GitCompare, History, Plus, Rocket, RotateCcw, Save, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { Diff, FailureList, GateList } from "@/components/gates";
import { can, useMe } from "@/components/shell";
import { Badge, Button, Card, CardHeader, Dialog, Drawer, Field, Input, JsonView, PageHeader, Select, Skeleton, StatusBadge, Switch, Tabs, Textarea, cx, useToast } from "@/components/ui";
import { api, useApi } from "@/lib/api";
import { ago } from "@/lib/format";

const MODELS = ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5", "claude-fable-5-1"];
const STEPS = [
  { key: "triage", label: "Triage", hint: "Classifies the request. Fast and cheap." },
  { key: "plan", label: "Planner", hint: "Chooses the next tool call." },
  { key: "draft", label: "Drafter", hint: "Writes the reply. The main reasoning model." },
  { key: "supervisor", label: "Supervisor judge", hint: "Reviews every draft in parallel with deterministic checks." },
  { key: "summarize", label: "Memory summaries", hint: "Background job after a conversation ends." },
];

export default function ConfigPage() {
  const me = useMe();
  const toast = useToast();
  const { data, mutate } = useApi<any>("/api/config");
  const [cfg, setCfg] = useState<any>(null);
  const [note, setNote] = useState("");
  const [tab, setTab] = useState<"voice" | "policy" | "models" | "safety" | "json">("voice");
  const [saving, setSaving] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [report, setReport] = useState<any>(null);
  const [history, setHistory] = useState(false);
  const [diffOpen, setDiffOpen] = useState(false);
  const editable = can(me, "builder");

  useEffect(() => { if (data && !cfg) setCfg(structuredClone(data.draft.config)); }, [data, cfg]);
  const published = data?.published;
  const dirty = useMemo(() => cfg && data && JSON.stringify(cfg) !== JSON.stringify(data.draft.config), [cfg, data]);
  const hasDraft = data && data.draft.version !== data.published.version;

  const set = (path: string, value: any) => setCfg((c: any) => {
    const n = structuredClone(c);
    const keys = path.split(".");
    let o = n;
    keys.slice(0, -1).forEach((k) => (o = o[k] ??= {}));
    o[keys[keys.length - 1]] = value;
    return n;
  });

  async function save() {
    setSaving(true);
    try { const r = await api("/api/config/draft", { method: "PUT", body: { config: cfg, note: note || null } }); toast({ title: `Draft v${r.version} saved`, body: "Test it in the playground, then publish." }); await mutate(); }
    catch (e: any) { toast({ title: "Save failed", body: e.message, tone: "block" }); }
    finally { setSaving(false); }
  }

  async function publish() {
    if (dirty) await save();
    setPublishing(true);
    setReport(null);
    try {
      const r = await api("/api/config/publish", { body: {} });
      setReport({ ...r.report, published: r.published });
      toast({ title: `Published v${r.published}`, body: "Every release gate passed." });
      await mutate();
    } catch (e: any) {
      const rep = (e.detail as any)?.report;
      if (rep) setReport({ ...rep, refused: true });
      else toast({ title: "Publish failed", body: e.message, tone: "block" });
    } finally { setPublishing(false); }
  }

  async function rollback(v: number) {
    try { const r = await api("/api/config/rollback", { body: { version: v } }); toast({ title: `Rolled back`, body: `v${r.restored_from} is live again as v${r.published}.` }); setCfg(null); await mutate(); setHistory(false); }
    catch (e: any) { toast({ title: "Rollback failed", body: e.message, tone: "block" }); }
  }

  if (!data || !cfg) return <div className="space-y-4"><Skeleton className="h-16" /><Skeleton className="h-[480px]" /></div>;

  return (
    <>
      <PageHeader eyebrow="Build" title="Agent configuration"
        description="Forms in front, versioned JSON behind. Every publish runs the full evaluation suite; a change that fails a critical case does not ship."
        actions={<>
          <Button icon={<History className="h-3.5 w-3.5" />} onClick={() => setHistory(true)}>Versions</Button>
          <Button icon={<GitCompare className="h-3.5 w-3.5" />} onClick={() => setDiffOpen(true)}>Diff vs live</Button>
          {editable && <Button icon={<Save className="h-3.5 w-3.5" />} onClick={save} loading={saving} disabled={!dirty}>Save draft</Button>}
          {editable && <Button variant="primary" icon={<Rocket className="h-3.5 w-3.5" />} onClick={publish} loading={publishing} disabled={!dirty && !hasDraft}>Publish</Button>}
        </>} />

      <div className="flex flex-wrap items-center gap-2 mb-4 text-[12.5px] text-muted">
        <Badge tone="approve" dot>Live v{published.version}</Badge>
        {hasDraft && <Badge tone="revise" dot>Draft v{data.draft.version}</Badge>}
        {dirty && <Badge tone="info" dot>Unsaved changes</Badge>}
      </div>

      <div className="grid gap-4 xl:grid-cols-[1fr_340px]">
        <Card className="p-5">
          <Tabs value={tab} onChange={setTab} tabs={[{ value: "voice", label: "Brand & voice" }, { value: "policy", label: "Policy" }, { value: "models", label: "Models" }, { value: "safety", label: "Limits & safety" }, { value: "json", label: "JSON" }]} />
          <fieldset disabled={!editable} className="space-y-5">
            {tab === "voice" && <>
              <div className="grid sm:grid-cols-2 gap-4">
                <Field label="Business name"><Input value={cfg.brand.name} onChange={(e) => set("brand.name", e.target.value)} /></Field>
                <Field label="Agent name"><Input value={cfg.brand.agent_name} onChange={(e) => set("brand.agent_name", e.target.value)} /></Field>
              </div>
              <Field label="Voice" hint="How replies should sound. The drafter reads this on every turn."><Textarea rows={3} value={cfg.tone.voice} onChange={(e) => set("tone.voice", e.target.value)} /></Field>
              <Field label="Phrases to avoid" hint="The supervisor sends back any draft that uses them.">
                <Chips values={cfg.tone.avoid_phrases || []} onChange={(v) => set("tone.avoid_phrases", v)} placeholder="Add a phrase" />
              </Field>
              <Field label="Maximum exclamation marks per reply"><Input type="number" min={0} max={5} value={cfg.tone.max_exclamations} onChange={(e) => set("tone.max_exclamations", +e.target.value)} className="w-28" /></Field>
            </>}
            {tab === "policy" && <>
              <Field label="Competitors" hint="Replies that mention these are revised before sending."><Chips values={cfg.policy.competitors} onChange={(v) => set("policy.competitors", v)} placeholder="Add a competitor" /></Field>
              <div>
                <div className="text-[12.5px] font-medium mb-1">Sensitive topics</div>
                <div className="text-[12px] text-muted mb-2">If a customer or a draft touches one of these, the conversation goes to a person.</div>
                <div className="space-y-2">
                  {cfg.policy.sensitive_topics.map((t: any, i: number) => (
                    <div key={i} className="rounded-lg border border-line p-3">
                      <div className="flex items-center gap-2 mb-2">
                        <Input value={t.name} onChange={(e) => { const n = [...cfg.policy.sensitive_topics]; n[i] = { ...t, name: e.target.value }; set("policy.sensitive_topics", n); }} className="max-w-[220px]" />
                        <Badge tone="escalate">escalate</Badge>
                        <Button variant="ghost" size="icon" className="ml-auto" onClick={() => set("policy.sensitive_topics", cfg.policy.sensitive_topics.filter((_: any, j: number) => j !== i))}><X className="h-4 w-4" /></Button>
                      </div>
                      <Chips values={t.keywords} onChange={(v) => { const n = [...cfg.policy.sensitive_topics]; n[i] = { ...t, keywords: v }; set("policy.sensitive_topics", n); }} placeholder="Add a keyword" />
                    </div>
                  ))}
                  <Button size="sm" icon={<Plus className="h-3.5 w-3.5" />} onClick={() => set("policy.sensitive_topics", [...cfg.policy.sensitive_topics, { name: "New topic", keywords: [], action: "escalate" }])}>Add topic</Button>
                </div>
              </div>
              <div className="grid sm:grid-cols-2 gap-4">
                <Field label="Re-contact window (hours)" hint="A resolution is billable only after this passes with no repeat contact."><Input type="number" value={cfg.outcomes.recontact_window_hours} onChange={(e) => set("outcomes.recontact_window_hours", +e.target.value)} /></Field>
                <Field label="Human handoff destination"><Input value={cfg.handoff.destination} onChange={(e) => set("handoff.destination", e.target.value)} /></Field>
              </div>
              <div className="flex items-center justify-between rounded-lg border border-line p-3">
                <div><div className="text-[13px] font-medium">Confirm write actions with the customer</div><div className="text-[12px] text-muted">Refunds, cancellations and address changes are proposed first and run only after a yes.</div></div>
                <Switch checked={cfg.confirm_writes} onChange={(v) => set("confirm_writes", v)} />
              </div>
              <div className="flex items-center justify-between rounded-lg border border-line p-3">
                <div><div className="text-[13px] font-medium">Cross-conversation memory</div><div className="text-[12px] text-muted">Only for customers who consent. Every item is erasable.</div></div>
                <Switch checked={cfg.memory.enabled} onChange={(v) => set("memory.enabled", v)} />
              </div>
            </>}
            {tab === "models" && <>
              <p className="text-[12.5px] text-muted -mt-1">Which model runs each step is configuration. Models sit behind one gateway, so changing one needs no code change. If the primary fails, the fallback runs; if both fail, the conversation escalates.</p>
              <div className="rounded-xl border border-line divide-y divide-line">
                {STEPS.map((s) => (
                  <div key={s.key} className="grid sm:grid-cols-[1fr_190px_190px_110px] gap-3 items-center p-3">
                    <div><div className="text-[13px] font-medium">{s.label}</div><div className="text-[12px] text-muted">{s.hint}</div></div>
                    <Select value={cfg.models[s.key]?.primary} onChange={(e) => set(`models.${s.key}.primary`, e.target.value)}>{MODELS.map((m) => <option key={m}>{m}</option>)}</Select>
                    <Select value={cfg.models[s.key]?.fallback} onChange={(e) => set(`models.${s.key}.fallback`, e.target.value)}>{MODELS.map((m) => <option key={m}>{m}</option>)}</Select>
                    <Select value={cfg.models[s.key]?.effort} onChange={(e) => set(`models.${s.key}.effort`, e.target.value)}>{["low", "medium", "high", "xhigh"].map((m) => <option key={m}>{m}</option>)}</Select>
                  </div>
                ))}
              </div>
              <div className="text-[11.5px] text-faint">Columns: primary · fallback · effort</div>
            </>}
            {tab === "safety" && <div className="grid sm:grid-cols-2 gap-4">
              <Field label="Supervisor time budget (ms)" hint="If the judge doesn't answer in time, the reply is held and the conversation escalates."><Input type="number" value={cfg.supervisor.timeout_ms} onChange={(e) => set("supervisor.timeout_ms", +e.target.value)} /></Field>
              <Field label="Maximum revisions" hint="After this many rejected drafts, a person takes over."><Input type="number" min={0} max={4} value={cfg.supervisor.max_revisions} onChange={(e) => set("supervisor.max_revisions", +e.target.value)} /></Field>
              <Field label="Step limit per turn"><Input type="number" value={cfg.limits.max_steps_per_turn} onChange={(e) => set("limits.max_steps_per_turn", +e.target.value)} /></Field>
              <Field label="Cost budget per conversation (USD)"><Input type="number" step="0.05" value={cfg.limits.cost_budget_per_conversation_usd} onChange={(e) => set("limits.cost_budget_per_conversation_usd", +e.target.value)} /></Field>
              <Field label="Knowledge sources per answer"><Input type="number" min={1} max={8} value={cfg.retrieval.top_k} onChange={(e) => set("retrieval.top_k", +e.target.value)} /></Field>
            </div>}
            {tab === "json" && <JsonView value={cfg} maxHeight={560} />}
          </fieldset>
          {editable && tab !== "json" && <div className="mt-5 pt-4 border-t border-line"><Field label="Change note"><Input value={note} onChange={(e) => setNote(e.target.value)} placeholder="What changed and why" /></Field></div>}
        </Card>

        <div className="space-y-4">
          <Card>
            <CardHeader title="How publishing works" />
            <ol className="px-5 pb-5 space-y-3 text-[12.5px] text-muted">
              {["Save a draft. Nothing changes for customers.", "Try it in the playground with draft config switched on.",
                "Publish runs 220+ evaluation cases against the draft.", "Any critical failure refuses the publish. Rollback restores a previous version exactly."]
                .map((s, i) => <li key={i} className="flex gap-3"><span className="h-5 w-5 rounded-full bg-accent-soft text-accent text-[11px] font-semibold grid place-items-center shrink-0">{i + 1}</span>{s}</li>)}
            </ol>
          </Card>
          {publishing && <Card className="p-5"><div className="text-[13px] font-medium mb-2">Running release gates…</div><Skeleton className="h-40" /></Card>}
          {report && (
            <Card className={cx("p-5 animate-rise", report.refused && "border-block/40")}>
              <div className="flex items-center gap-2 mb-3">
                <StatusBadge value={report.refused ? "failed" : "passed"} label={report.refused ? "Publish refused" : `Published v${report.published}`} />
                <span className="text-[12px] text-faint">{report.summary.cases} cases · {report.summary.duration_s}s</span>
              </div>
              <GateList gates={report.gates} />
              <FailureList failures={report.failures} />
            </Card>
          )}
        </div>
      </div>

      <Drawer open={history} onClose={() => setHistory(false)} title="Configuration versions" subtitle="Rollback creates a new version identical to the one you pick.">
        <ul className="space-y-2">
          {data.versions.map((v: any) => (
            <li key={v.version} className="rounded-lg border border-line p-3 flex items-center gap-3">
              <span className="font-mono text-[13px] w-10">v{v.version}</span>
              <div className="min-w-0 flex-1">
                <div className="text-[13px]">{v.note || "—"}</div>
                <div className="text-[11.5px] text-faint">{v.status === "published" ? `published ${ago(v.published_at)} by ${v.published_by || "—"}` : `${v.status} · ${ago(v.created_at)}`}</div>
              </div>
              <StatusBadge value={v.status === "published" ? "approve" : v.status === "draft" ? "pending" : undefined} label={v.status} />
              {editable && v.status !== "published" && v.status !== "draft" && <Button size="sm" icon={<RotateCcw className="h-3.5 w-3.5" />} onClick={() => rollback(v.version)}>Restore</Button>}
            </li>
          ))}
        </ul>
      </Drawer>
      <Drawer open={diffOpen} onClose={() => setDiffOpen(false)} title={`Changes vs live v${published.version}`} subtitle="Red is live, green is what you would publish.">
        <Diff a={published.config} b={cfg} />
      </Drawer>
    </>
  );
}

function Chips({ values, onChange, placeholder }: { values: string[]; onChange: (v: string[]) => void; placeholder: string }) {
  const [t, setT] = useState("");
  return (
    <div className="flex flex-wrap items-center gap-1.5 rounded-lg border border-line bg-surface p-1.5 focus-within:border-accent/60 focus-within:shadow-ring transition-shadow">
      {values.map((v) => (
        <span key={v} className="inline-flex items-center gap-1 rounded-md bg-subtle border border-line px-2 py-0.5 text-[12.5px]">
          {v}<button type="button" onClick={() => onChange(values.filter((x) => x !== v))} className="text-faint hover:text-block"><X className="h-3 w-3" /></button>
        </span>
      ))}
      <input value={t} onChange={(e) => setT(e.target.value)} placeholder={placeholder}
        onKeyDown={(e) => { if ((e.key === "Enter" || e.key === ",") && t.trim()) { e.preventDefault(); if (!values.includes(t.trim())) onChange([...values, t.trim()]); setT(""); } }}
        className="flex-1 min-w-[120px] bg-transparent outline-none text-[13px] px-1 py-0.5 placeholder:text-faint" />
    </div>
  );
}
