"use client";

import { ArrowUpRight, ClipboardCheck, FlaskConical, MessagesSquare, TriangleAlert, Radio } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Spark, VolumeChart } from "@/components/charts";
import { useMe } from "@/components/shell";
import { Badge, Button, Card, CardHeader, Progress, Segmented, Skeleton, StatusBadge, cx } from "@/components/ui";
import { useApi } from "@/lib/api";
import { ago, money, ms, pct, title } from "@/lib/format";

const first = (m: any, k: string) => m?.[k]?.rows?.[0] || {};

export default function Overview() {
  const me = useMe();
  const [days, setDays] = useState<"7" | "30">("30");
  const { data } = useApi<any>(`/api/overview?days=${days}`, { refreshInterval: 20000 });
  const m = data?.metrics;
  const series = m?.daily_volume?.rows || [];
  const vr = first(m, "verified_resolution_rate");
  const esc = first(m, "escalation_rate");
  const cost = first(m, "cost_per_resolution");
  const csat = first(m, "csat");
  const lat = first(m, "latency");
  const hour = new Date().getHours();
  const greet = hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4 animate-rise">
        <div>
          <div className="label mb-1.5">{me?.tenant.name} · Overview</div>
          <h1 className="font-display text-[36px] leading-[1.05]">{greet}, {me?.user.name.split(" ")[0]}.</h1>
          <p className="text-muted mt-1.5">
            {data ? <>Your agent handled <b className="text-ink num">{data.live.today}</b> conversations in the last day.
              {data.live.approvals > 0 && <> <Link className="link" href="/app/approvals">{data.live.approvals} actions</Link> are waiting for a person.</>}</> : "Loading the latest activity…"}
          </p>
        </div>
        <Segmented value={days} onChange={setDays} options={[{ value: "7", label: "7 days" }, { value: "30", label: "30 days" }]} />
      </div>

      <LiveStrip live={data?.live} />

      <div className="grid gap-4 grid-cols-2 xl:grid-cols-5">
        <Kpi label="Verified resolution rate" value={vr.rate_pct != null ? pct(vr.rate_pct) : "—"} loading={!data}
          hint={<>{vr.resolved ?? 0} of {vr.finalized ?? 0} finalized · target 60%</>}>
          <TargetBar value={Number(vr.rate_pct || 0)} target={60} />
        </Kpi>
        <Kpi label="Escalation rate" value={esc.rate_pct != null ? pct(esc.rate_pct) : "—"} loading={!data}
          hint={`${esc.escalated ?? 0} of ${esc.conversations ?? 0} conversations`}>
          <Spark values={series.map((r: any) => r.escalated)} color="escalate" />
        </Kpi>
        <Kpi label="Model cost / resolution" value={cost.cost_per_resolution_usd != null ? money(cost.cost_per_resolution_usd, 3) : "—"} loading={!data}
          hint={`${money(cost.model_cost_usd || 0)} model spend`}>
          <Spark values={series.map((r: any) => r.conversations)} />
        </Kpi>
        <Kpi label="Customer satisfaction" value={csat.avg_csat ? `${Number(csat.avg_csat).toFixed(2)}` : "—"} loading={!data}
          hint={`${csat.responses ?? 0} ratings · out of 5`}>
          <div className="flex gap-0.5 mt-2">{[1, 2, 3, 4, 5].map((i) => <span key={i} className={cx("h-1.5 flex-1 rounded-full", i <= Math.round(Number(csat.avg_csat || 0)) ? "bg-approve" : "bg-sunken")} />)}</div>
        </Kpi>
        <Kpi label="Reply latency p95" value={lat.p95_ms != null ? ms(lat.p95_ms) : "—"} loading={!data}
          hint={`p50 ${ms(lat.p50_ms || 0)} · budget 4 s, supervisor included`} className="col-span-2 xl:col-span-1">
          <TargetBar value={Math.min(100, (Number(lat.p95_ms || 0) / 4000) * 100)} target={100} inverse />
        </Kpi>
      </div>

      <div className="grid gap-4 xl:grid-cols-[1fr_380px]">
        <Card>
          <CardHeader title="Conversations and verified resolutions" subtitle="A resolution is verified only after the 72-hour re-contact window closes."
            action={<Link href="/app/insights" className="text-[12.5px] link">See queries</Link>} />
          <div className="px-3 pb-3">{data ? <VolumeChart rows={series} /> : <Skeleton className="h-[240px] mx-2" />}</div>
        </Card>
        <GateCard run={data?.last_eval} config={data?.config} />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader title="Supervisor interventions" subtitle="Drafts stopped or sent back before they reached a customer" />
          <div className="px-5 pb-5 space-y-3">
            {(m?.supervisor_interventions?.rows || []).slice(0, 6).map((r: any) => {
              const max = Math.max(...m.supervisor_interventions.rows.map((x: any) => x.n));
              return (
                <div key={r.verdict + r.reason_code} className="grid grid-cols-[150px_1fr_36px] items-center gap-3">
                  <div className="flex items-center gap-2 min-w-0"><StatusBadge value={r.verdict} /><span className="text-[12.5px] text-muted truncate">{title(r.reason_code)}</span></div>
                  <Progress value={(r.n / max) * 100} tone={r.verdict === "block" ? "block" : r.verdict === "escalate" ? "escalate" : "revise"} />
                  <span className="text-right num text-[13px] font-medium">{r.n}</span>
                </div>
              );
            })}
            {m && !m.supervisor_interventions.rows.length && <div className="text-muted text-[13px]">No interventions in this period.</div>}
            {!m && <Skeleton className="h-32" />}
          </div>
        </Card>
        <Card>
          <CardHeader title="Top contact reasons" subtitle="Ranked by volume, with the share that ended poorly" />
          <div className="px-5 pb-5">
            {(m?.contact_reasons?.rows || []).slice(0, 7).map((r: any) => (
              <div key={r.reason} className="grid grid-cols-[1fr_60px_110px] items-center gap-3 py-1.5 border-b border-line last:border-0">
                <span className="text-[13px] truncate">{title(r.reason)}</span>
                <span className="text-right num text-[13px] font-medium">{r.conversations}</span>
                <div className="flex items-center gap-2">
                  <Progress value={Number(r.poor_outcome_pct || 0)} tone={Number(r.poor_outcome_pct) > 50 ? "block" : "revise"} />
                  <span className="num text-[11.5px] text-muted w-9 text-right">{r.poor_outcome_pct != null ? `${Math.round(r.poor_outcome_pct)}%` : "—"}</span>
                </div>
              </div>
            ))}
            {!m && <Skeleton className="h-40" />}
          </div>
        </Card>
      </div>

      <Card>
        <CardHeader title="Latest conversations" action={<Link href="/app/conversations"><Button size="sm" variant="ghost">View all <ArrowUpRight className="h-3.5 w-3.5" /></Button></Link>} />
        <ul className="divide-y divide-line">
          {(data?.recent || []).map((c: any) => (
            <li key={c.id}>
              <Link href={`/app/conversations/${c.id}`} className="flex items-center gap-4 px-5 py-3 hover:bg-subtle/60 transition-colors">
                <MessagesSquare className="h-4 w-4 text-faint shrink-0" />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-[13.5px]">{c.first_message || "—"}</div>
                  <div className="text-[12px] text-faint">{c.display_name || c.email || "Anonymous visitor"} · {title(c.intent)} · {c.channel}</div>
                </div>
                {c.last_verdict && <StatusBadge value={c.last_verdict} />}
                <StatusBadge value={c.outcome || c.status} />
                <span className="text-[12px] text-faint w-16 text-right">{ago(c.last_activity_at)}</span>
              </Link>
            </li>
          ))}
          {!data && <li className="p-5"><Skeleton className="h-24" /></li>}
        </ul>
      </Card>
    </div>
  );
}

function Kpi({ label, value, hint, children, loading, className }: { label: string; value: React.ReactNode; hint?: React.ReactNode; children?: React.ReactNode; loading?: boolean; className?: string }) {
  return (
    <Card className={cx("p-4 flex flex-col animate-rise", className)}>
      <div className="label">{label}</div>
      {loading ? <Skeleton className="h-8 w-24 mt-2" /> : <div className="text-[28px] font-semibold num tracking-tight leading-tight mt-1">{value}</div>}
      <div className="text-[12px] text-muted mt-0.5 min-h-[18px]">{hint}</div>
      <div className="mt-auto">{children}</div>
    </Card>
  );
}

function TargetBar({ value, target, inverse }: { value: number; target: number; inverse?: boolean }) {
  const good = inverse ? value <= target : value >= target;
  return (
    <div className="relative mt-3">
      <Progress value={value} tone={good ? "approve" : "revise"} />
      {!inverse && <span className="absolute -top-1 h-3.5 w-px bg-ink/50" style={{ left: `${target}%` }} />}
    </div>
  );
}

function LiveStrip({ live }: { live?: any }) {
  const items = [
    { icon: Radio, label: "Live conversations", value: live?.active, href: "/app/conversations?status=active" },
    { icon: ClipboardCheck, label: "Awaiting approval", value: live?.approvals, href: "/app/approvals", tone: live?.approvals ? "revise" : undefined },
    { icon: TriangleAlert, label: "Stale knowledge sources", value: live?.stale_sources, href: "/app/knowledge", tone: live?.stale_sources ? "revise" : undefined },
    { icon: FlaskConical, label: "Outcomes in re-contact window", value: live?.pending_outcomes, href: "/app/outcomes" },
  ];
  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
      {items.map((it) => (
        <Link key={it.label} href={it.href} className="group card px-4 py-3 flex items-center gap-3 hover:border-line-strong transition-colors">
          <span className={cx("h-8 w-8 rounded-lg grid place-items-center", it.tone ? "bg-revise/10 text-revise" : "bg-subtle text-muted")}>
            <it.icon className="h-4 w-4" />
          </span>
          <div className="min-w-0">
            <div className="text-[18px] font-semibold num leading-tight">{live ? it.value ?? 0 : "·"}</div>
            <div className="text-[12px] text-muted truncate">{it.label}</div>
          </div>
          <ArrowUpRight className="ml-auto h-3.5 w-3.5 text-faint opacity-0 group-hover:opacity-100 transition-opacity" />
        </Link>
      ))}
    </div>
  );
}

function GateCard({ run, config }: { run?: any; config?: any }) {
  return (
    <Card className="flex flex-col">
      <CardHeader title="Release gates" subtitle={run ? `Last run ${ago(run.finished_at)} · config v${run.config_version ?? "—"}` : "No evaluation has run yet"}
        action={run && <StatusBadge value={run.status} />} />
      <div className="px-5 pb-4 space-y-2.5 flex-1">
        {(run?.gates || []).map((g: any) => (
          <div key={g.gate} className="flex items-center gap-3">
            <span className={cx("h-5 w-5 rounded-full grid place-items-center text-[11px] text-white", g.passed ? "bg-approve" : "bg-block")}>{g.passed ? "✓" : "✕"}</span>
            <div className="min-w-0 flex-1">
              <div className="text-[13px] font-medium">{g.gate}</div>
              <div className="text-[11.5px] text-faint truncate">{g.condition}</div>
            </div>
            <span className="text-[12.5px] num text-muted">{g.value}</span>
          </div>
        ))}
        {!run && <Skeleton className="h-40" />}
      </div>
      <div className="px-5 py-3 border-t border-line flex items-center justify-between text-[12.5px]">
        <span className="text-muted">Published config <b className="text-ink">v{config?.version ?? "—"}</b></span>
        <Link href="/app/evals" className="link">Open evaluations</Link>
      </div>
    </Card>
  );
}
