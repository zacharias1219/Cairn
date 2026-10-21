"use client";

import { CheckCircle2, CircleX, FlaskConical, Play, Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { FailureList, GateList } from "@/components/gates";
import { can, useMe } from "@/components/shell";
import { Badge, Button, Card, CardHeader, Drawer, Empty, Input, JsonView, LoadingRows, PageHeader, Progress, Select, Skeleton, StatusBadge, Table, Tabs, Td, Th, cx, useToast } from "@/components/ui";
import { api, useApi } from "@/lib/api";
import { ago, ms, title } from "@/lib/format";

export default function Evals() {
  const me = useMe();
  const toast = useToast();
  const { data: runs, mutate } = useApi<{ items: any[] }>("/api/evals/runs", { refreshInterval: 20000 });
  const [runId, setRunId] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [tab, setTab] = useState<"results" | "cases">("results");
  useEffect(() => { if (!runId && runs?.items.length) setRunId(runs.items[0].id); }, [runs, runId]);
  const { data: run } = useApi<any>(runId ? `/api/evals/runs/${runId}` : null);

  async function start() {
    setRunning(true);
    try {
      const r = await api("/api/evals/run", { body: { use_draft: true } });
      toast({ title: r.passed ? "All release gates passed" : "A release gate failed", body: `${r.summary.passed}/${r.summary.cases} cases in ${r.summary.duration_s}s`, tone: r.passed ? "approve" : "block" });
      await mutate(); setRunId(r.run_id);
    } catch (e: any) { toast({ title: "Run failed", body: e.message, tone: "block" }); }
    finally { setRunning(false); }
  }

  return (
    <>
      <PageHeader eyebrow="Build" title="Evaluations"
        description="Proof that a change is safe before it ships. Scripted workflows, seeded failures and an adversarial pack run on every publish and in CI. One critical failure blocks the release."
        actions={can(me, "builder") && <Button variant="primary" loading={running} icon={<Play className="h-3.5 w-3.5" />} onClick={start}>Run full suite</Button>} />
      <Tabs value={tab} onChange={setTab} tabs={[{ value: "results", label: "Runs" }, { value: "cases", label: "Test cases" }]} />
      {tab === "results" ? (
        <div className="grid gap-4 xl:grid-cols-[300px_1fr]">
          <Card className="self-start overflow-hidden">
            <CardHeader title="History" />
            <ul className="max-h-[640px] overflow-y-auto">
              {runs?.items.map((r) => (
                <li key={r.id}>
                  <button onClick={() => setRunId(r.id)} className={cx("w-full text-left px-5 py-3 border-t border-line hover:bg-subtle/60 transition-colors", r.id === runId && "bg-accent-soft/60")}>
                    <div className="flex items-center gap-2">
                      {r.status === "passed" ? <CheckCircle2 className="h-4 w-4 text-approve" /> : r.status === "running" ? <FlaskConical className="h-4 w-4 text-info animate-pulse" /> : <CircleX className="h-4 w-4 text-block" />}
                      <span className="text-[13px] font-medium truncate">{r.trigger}</span>
                    </div>
                    <div className="text-[11.5px] text-faint mt-0.5 pl-6">{ago(r.started_at)} · {r.summary?.passed ?? "—"}/{r.summary?.cases ?? "—"} · config v{r.config_version ?? "—"}</div>
                  </button>
                </li>
              ))}
              {!runs && <li className="p-4"><Skeleton className="h-40" /></li>}
            </ul>
          </Card>
          {run ? <RunDetail run={run} /> : <Card><LoadingRows /></Card>}
        </div>
      ) : <CaseBrowser />}
    </>
  );
}

function RunDetail({ run }: { run: any }) {
  const [filter, setFilter] = useState<"failed" | "all">(run.results?.some((r: any) => !r.passed) ? "failed" : "all");
  const [open, setOpen] = useState<any>(null);
  const s = run.summary || {};
  const cats = Object.entries(s.by_category || {}) as [string, any][];
  const rows = (run.results || []).filter((r: any) => filter === "all" || !r.passed);
  return (
    <div className="space-y-4 min-w-0">
      <div className="grid gap-3 grid-cols-2 lg:grid-cols-4">
        <Card className="p-4"><div className="label">Cases</div><div className="text-[24px] font-semibold num">{s.passed}/{s.cases}</div></Card>
        <Card className="p-4"><div className="label">Critical</div><div className={cx("text-[24px] font-semibold num", s.critical_passed === s.critical_total ? "text-approve" : "text-block")}>{s.critical_passed}/{s.critical_total}</div></Card>
        <Card className="p-4"><div className="label">p95 latency</div><div className="text-[24px] font-semibold num">{ms(s.p95_latency_ms)}</div></Card>
        <Card className="p-4"><div className="label">Duration</div><div className="text-[24px] font-semibold num">{s.duration_s}s</div></Card>
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="p-5"><div className="flex items-center gap-2 mb-3"><span className="font-semibold text-[14px]">Release gates</span><StatusBadge value={run.status} /></div><GateList gates={run.gates || []} /></Card>
        <Card className="p-5">
          <div className="font-semibold text-[14px] mb-3">By category</div>
          <div className="space-y-2">
            {cats.sort((a, b) => b[1].total - a[1].total).map(([k, v]) => (
              <div key={k} className="grid grid-cols-[150px_1fr_52px] items-center gap-3">
                <span className="text-[12.5px] truncate">{title(k)}</span>
                <Progress value={(v.passed / v.total) * 100} tone={v.passed === v.total ? "approve" : "block"} />
                <span className="text-right num text-[12px] text-muted">{v.passed}/{v.total}</span>
              </div>
            ))}
          </div>
        </Card>
      </div>
      <Card>
        <CardHeader title="Cases" action={<Select value={filter} onChange={(e) => setFilter(e.target.value as any)} className="w-[140px]"><option value="failed">Failed only</option><option value="all">All cases</option></Select>} />
        {rows.length === 0 ? <Empty icon={<CheckCircle2 className="h-5 w-5" />} title="Every case passed" /> : (
          <Table>
            <thead><tr><Th>Case</Th><Th>Category</Th><Th>Result</Th><Th align="right">Latency</Th></tr></thead>
            <tbody>{rows.slice(0, 300).map((r: any) => (
              <tr key={r.id} onClick={() => setOpen(r)} className="cursor-pointer hover:bg-subtle/60">
                <Td><div className="text-[13px] truncate max-w-[420px]">{r.name || r.case_key}</div><div className="font-mono text-[11px] text-faint">{r.case_key}</div></Td>
                <Td><div className="flex gap-1.5"><Badge>{title(r.category)}</Badge>{r.critical && <Badge tone="block">critical</Badge>}</div></Td>
                <Td><StatusBadge value={r.passed ? "passed" : "failed"} /></Td>
                <Td align="right" className="text-muted">{ms(r.latency_ms)}</Td>
              </tr>
            ))}</tbody>
          </Table>
        )}
      </Card>
      <Drawer open={!!open} onClose={() => setOpen(null)} title={open?.name || open?.case_key} subtitle={open && <span className="font-mono">{open.case_key}</span>}>
        {open && (
          <div className="space-y-4">
            {open.failures?.length > 0 && <div className="rounded-lg border border-block/30 bg-block/5 p-3 text-[12.5px] text-block space-y-1">{open.failures.map((f: string, i: number) => <div key={i}>{f}</div>)}</div>}
            {(open.observed?.turns || []).map((t: any, i: number) => (
              <div key={i} className="rounded-xl border border-line p-3 space-y-2">
                <div className="text-[12.5px]"><span className="label mr-2">Customer</span>{t.say}</div>
                <div className="text-[12.5px] rounded-lg bg-subtle px-3 py-2">{t.reply}</div>
                <div className="flex flex-wrap gap-1.5">
                  {t.action && <StatusBadge value={t.action} />}{t.intent && <Badge tone="info">{title(t.intent)}</Badge>}
                  {(t.verdicts || []).map((v: any, j: number) => <Badge key={j} tone={v.verdict === "approve" ? "approve" : v.verdict === "revise" ? "revise" : "block"}>#{v.attempt} {v.verdict} · {v.reason_code}</Badge>)}
                  {Object.entries(t.rules || {}).map(([k, v]) => <Badge key={k} tone="escalate">{k} → {String(v)}</Badge>)}
                </div>
              </div>
            ))}
          </div>
        )}
      </Drawer>
    </div>
  );
}

function CaseBrowser() {
  const { data } = useApi<{ items: any[] }>("/api/evals/cases");
  const [q, setQ] = useState("");
  const [suite, setSuite] = useState("");
  const [open, setOpen] = useState<any>(null);
  const items = useMemo(() => (data?.items || []).filter((c) => (!suite || c.suite === suite) && (!q || (c.name + c.key).toLowerCase().includes(q.toLowerCase()))), [data, q, suite]);
  const counts = useMemo(() => (data?.items || []).reduce((a: any, c) => ({ ...a, [c.suite]: (a[c.suite] || 0) + 1 }), {}), [data]);
  return (
    <Card>
      <div className="flex flex-wrap items-center gap-2 p-3 border-b border-line">
        <div className="relative flex-1 min-w-[220px]"><Search className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-faint" /><Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search cases" className="pl-8" /></div>
        <Select value={suite} onChange={(e) => setSuite(e.target.value)} className="w-[200px]">
          <option value="">All suites ({data?.items.length ?? 0})</option>
          {Object.entries(counts).map(([k, v]) => <option key={k} value={k}>{title(k)} ({String(v)})</option>)}
        </Select>
      </div>
      {!data ? <LoadingRows /> : (
        <Table>
          <thead><tr><Th>Case</Th><Th>Suite</Th><Th>Category</Th><Th align="right">Turns</Th></tr></thead>
          <tbody>{items.slice(0, 400).map((c) => (
            <tr key={c.key} onClick={() => setOpen(c)} className="cursor-pointer hover:bg-subtle/60">
              <Td><div className="truncate max-w-[520px]">{c.name}</div><div className="font-mono text-[11px] text-faint">{c.key}</div></Td>
              <Td><Badge tone={c.critical ? "block" : "info"}>{c.suite}</Badge></Td>
              <Td className="text-muted">{title(c.category)}</Td>
              <Td align="right" className="text-muted">{c.spec.turns.length}</Td>
            </tr>
          ))}</tbody>
        </Table>
      )}
      <Drawer open={!!open} onClose={() => setOpen(null)} title={open?.name} subtitle="Test cases are data: a scripted conversation plus the expected rule, supervisor and tool outcomes.">
        {open && <JsonView value={open.spec} maxHeight={700} />}
      </Drawer>
    </Card>
  );
}
