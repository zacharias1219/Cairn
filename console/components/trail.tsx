"use client";

import {
  AlertOctagon, ArrowRightLeft, BookOpen, Brain, CheckCircle2, ChevronRight, CircleX, Compass, Flag, Scale,
  ShieldCheck, Send, Sparkles, Wrench,
} from "lucide-react";
import { useState } from "react";

import { Badge, JsonView, StatusBadge, cx } from "@/components/ui";
import { money, ms, title } from "@/lib/format";

const KIND: Record<string, { icon: React.ElementType; tone: string }> = {
  triage: { icon: Compass, tone: "info" },
  retrieve: { icon: BookOpen, tone: "info" },
  act: { icon: Brain, tone: "accent" },
  execute_pending: { icon: Wrench, tone: "accent" },
  execute_approved: { icon: Wrench, tone: "accent" },
  draft: { icon: Sparkles, tone: "accent" },
  supervise: { icon: ShieldCheck, tone: "approve" },
  reply_rules: { icon: Scale, tone: "info" },
  respond: { icon: Send, tone: "approve" },
  blocked: { icon: CircleX, tone: "block" },
  escalate: { icon: Flag, tone: "escalate" },
};

const STEP_NAME: Record<string, string> = {
  triage: "Triage", retrieve: "Knowledge retrieval", act: "Plan", execute_pending: "Tool call", execute_approved: "Approved tool call",
  draft: "Draft", supervise: "Supervisor", reply_rules: "Reply rules", respond: "Sent", blocked: "Blocked", escalate: "Escalated",
};

export function whySummary(turn: any): string {
  const steps = turn.trail?.steps || [];
  const tri = steps.find((s: any) => s.step === "triage");
  const ret = steps.find((s: any) => s.step === "retrieve");
  const verdicts = turn.trail?.verdicts || [];
  const tools = (turn.trail?.tool_calls || []).filter((c: any) => c.status === "succeeded").map((c: any) => c.tool_name);
  const fired = (turn.trail?.rules || []).filter((r: any) => r.outcome !== "allow");
  const parts: string[] = [];
  if (tri) parts.push(`Classified as ${title(tri.output?.intent).toLowerCase()}`);
  if (ret) parts.push(`${ret.output?.sources?.length || 0} source(s) retrieved`);
  if (tools.length) parts.push(`${tools.join(", ")} succeeded`);
  const approved = steps.find((s: any) => s.step === "execute_approved");
  if (approved) parts.push(approved.summary);
  if (fired.length) parts.push(`rules fired: ${fired.map((r: any) => `${r.rule_key} → ${r.outcome}`).join(", ")}`);
  if (verdicts.length) {
    const last = verdicts[verdicts.length - 1];
    parts.push(`supervisor ${last.verdict === "approve" ? "approved" : last.verdict + "d"} on attempt ${last.attempt}${verdicts.length > 1 ? ` after ${verdicts.length - 1} intervention(s)` : ""}`);
  }
  if (turn.final_action === "escalate") parts.push("handed off to a person");
  if (turn.final_action === "blocked") parts.push("draft blocked, safe reply sent instead");
  return parts.join(" · ") + ".";
}

export function TurnTrail({ turn, compact }: { turn: any; compact?: boolean }) {
  const steps = turn.trail?.steps || [];
  return (
    <div>
      <div className="flex flex-wrap items-center gap-2 mb-3">
        <span className="text-[13px] font-semibold">Turn {turn.seq}</span>
        <StatusBadge value={turn.status} />
        {turn.final_verdict && <StatusBadge value={turn.final_verdict} />}
        <span className="ml-auto text-[12px] text-faint num">{ms(turn.latency_ms)} · {money(turn.cost_usd, 4)} · config v{turn.config_version}</span>
      </div>
      <div className="rounded-lg bg-accent-soft/60 border border-accent/15 px-3 py-2 text-[12.5px] text-ink/80 mb-4">
        <span className="font-medium text-accent">Why this reply: </span>{whySummary(turn)}
      </div>
      <ol className="relative">
        <span className="absolute left-[13px] top-2 bottom-2 w-px bg-line" />
        {steps.map((s: any, i: number) => <Step key={s.id || i} s={s} turn={turn} defaultOpen={!compact && ["supervise"].includes(s.step) && s.output?.verdict !== "approve"} />)}
      </ol>
    </div>
  );
}

function Step({ s, turn, defaultOpen }: { s: any; turn: any; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(!!defaultOpen);
  const k = KIND[s.step] || { icon: ArrowRightLeft, tone: "neutral" };
  const failed = s.kind === "error" || (s.step === "supervise" && s.output?.verdict && s.output.verdict !== "approve");
  const Icon = s.kind === "error" ? AlertOctagon : k.icon;
  const tone = failed ? (s.output?.verdict === "revise" ? "revise" : s.output?.verdict === "escalate" ? "escalate" : "block") : k.tone;
  return (
    <li className="relative pl-9 pb-3">
      <span className={cx("absolute left-0 top-0.5 h-[27px] w-[27px] rounded-full grid place-items-center border bg-surface",
        `text-${tone}`, failed ? `border-${tone}` : "border-line")}>
        <Icon className="h-3.5 w-3.5" />
      </span>
      <button onClick={() => setOpen((o) => !o)} className="w-full text-left group">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-[13px] font-medium">{STEP_NAME[s.step] || s.step}</span>
          <ChevronRight className={cx("h-3.5 w-3.5 text-faint transition-transform", open && "rotate-90")} />
          <span className="ml-auto text-[11.5px] text-faint num shrink-0">{s.latency_ms ? ms(s.latency_ms) : ""}{Number(s.cost_usd) > 0 ? ` · ${money(s.cost_usd, 4)}` : ""}</span>
        </div>
        <div className="text-[12.5px] text-muted truncate group-hover:text-ink/80">{s.summary}</div>
        {s.model && <div className="text-[11px] text-faint font-mono mt-0.5">{s.model}</div>}
      </button>
      {open && <div className="mt-2.5 animate-fade-in"><StepDetail s={s} turn={turn} /></div>}
    </li>
  );
}

function StepDetail({ s, turn }: { s: any; turn: any }) {
  const o = s.output || {};
  if (s.step === "triage") {
    return (
      <div className="space-y-2">
        <div className="flex flex-wrap gap-1.5">
          <Badge tone="info">{title(o.intent)}</Badge>
          <Badge>confidence {Math.round((o.confidence || 0) * 100)}%</Badge>
          {o.order_id && <Badge>order {o.order_id}</Badge>}
          {(o.injection || []).length > 0 && <Badge tone="block">injection signals: {o.injection.length}</Badge>}
          {(o.sensitive || []).map((x: any) => <Badge key={x.topic} tone="escalate">{x.topic}</Badge>)}
        </div>
        {(o.injection || []).length > 0 && <div className="text-[12px] text-muted">Matched: {o.injection.map((x: string) => `“${x}”`).join(", ")} — treated as untrusted data.</div>}
        <JsonView value={s.input} maxHeight={160} />
      </div>
    );
  }
  if (s.step === "retrieve") {
    return (
      <div className="space-y-2">
        {(o.sources || []).map((src: any) => (
          <div key={src.chunk_id} className="rounded-lg border border-line p-2.5">
            <div className="flex items-center gap-2 text-[12.5px]">
              <BookOpen className="h-3.5 w-3.5 text-faint" />
              <span className="font-medium">{src.title}</span>
              {src.heading && <span className="text-faint">› {src.heading}</span>}
              {src.stale && <Badge tone="revise">stale</Badge>}
              <span className="ml-auto text-faint num text-[11.5px]">score {Number(src.score).toFixed(2)}</span>
            </div>
            <p className="text-[12.5px] text-muted mt-1 line-clamp-3">{src.content}</p>
            <div className="text-[10.5px] font-mono text-faint mt-1">{src.chunk_id}</div>
          </div>
        ))}
        {!o.sources?.length && <div className="text-[12.5px] text-muted">No source matched the question.</div>}
        {(o.memory || []).length > 0 && (
          <div className="rounded-lg border border-dashed border-line p-2.5">
            <div className="label mb-1">Memory used (with consent)</div>
            <ul className="text-[12.5px] text-muted list-disc pl-4">{o.memory.map((m: string, i: number) => <li key={i}>{m}</li>)}</ul>
          </div>
        )}
      </div>
    );
  }
  if (s.step === "supervise") {
    const checks = o.checks || [];
    return (
      <div className="space-y-2">
        <div className="flex items-center gap-2"><StatusBadge value={o.verdict} /><span className="text-[12.5px] text-muted">{title(o.reason_code)}</span></div>
        {o.feedback && <div className="text-[12.5px] rounded-md bg-revise/10 text-revise border border-revise/20 px-2.5 py-1.5">Feedback to drafter: {o.feedback}</div>}
        <div className="rounded-lg border border-line divide-y divide-line">
          {checks.map((c: any) => (
            <div key={c.name} className="flex items-start gap-2.5 px-2.5 py-1.5">
              {c.passed ? <CheckCircle2 className="h-3.5 w-3.5 text-approve mt-0.5 shrink-0" /> : <CircleX className={cx("h-3.5 w-3.5 mt-0.5 shrink-0", `text-${c.verdict === "revise" ? "revise" : c.verdict === "escalate" ? "escalate" : "block"}`)} />}
              <div className="min-w-0">
                <div className="text-[12.5px] font-medium">{title(c.name)}</div>
                <div className="text-[12px] text-muted">{c.detail}</div>
                {c.evidence?.length > 0 && <div className="text-[11px] text-faint font-mono mt-0.5 truncate">{c.evidence.join(" · ")}</div>}
              </div>
            </div>
          ))}
        </div>
        <details className="text-[12px]"><summary className="cursor-pointer text-faint">Draft under review</summary><p className="mt-1 text-muted">{s.input?.draft}</p></details>
      </div>
    );
  }
  if (s.step === "reply_rules" || (s.step === "act" && o.rules)) {
    const r = s.step === "reply_rules" ? o : o.rules;
    return (
      <div className="space-y-2">
        <div className="text-[12.5px] text-muted">Outcome <StatusBadge value={r.outcome} /> · evaluated {r.evaluated?.length || 0} rule(s) in code, no model on the path.</div>
        {(r.fired || []).map((f: any) => (
          <div key={f.rule_key} className="rounded-md border border-line px-2.5 py-1.5 text-[12.5px] flex items-center gap-2">
            <Scale className="h-3.5 w-3.5 text-faint" /><span className="font-mono text-[12px]">{f.rule_key}</span><StatusBadge value={f.outcome} />
            <span className="text-muted truncate">{f.message}</span>
          </div>
        ))}
        {s.step === "act" && <JsonView value={{ action: o.action, tool: o.tool, arguments: safeParse(o.arguments_json) }} maxHeight={160} />}
      </div>
    );
  }
  if (s.step === "draft") {
    return (
      <div className="space-y-2">
        {s.input?.feedback && <div className="text-[12px] text-revise">Revising per supervisor: {s.input.feedback}</div>}
        <div className="rounded-lg bg-subtle border border-line px-3 py-2 text-[13px]">{o.reply}</div>
        {o.citations?.length > 0 && <div className="text-[11.5px] text-faint font-mono">cites {o.citations.join(", ")}</div>}
      </div>
    );
  }
  return <div className="grid gap-2 lg:grid-cols-2"><JsonView value={s.input} maxHeight={220} /><JsonView value={s.output} maxHeight={220} /></div>;
}

function safeParse(t: string) {
  try { return JSON.parse(t); } catch { return t; }
}

export function ToolCallList({ calls }: { calls: any[] }) {
  if (!calls?.length) return null;
  return (
    <div className="space-y-2">
      {calls.map((c) => (
        <div key={c.id} className="rounded-lg border border-line p-3">
          <div className="flex items-center gap-2 text-[13px]">
            <Wrench className="h-3.5 w-3.5 text-faint" /><span className="font-mono">{c.tool_name}</span>
            <Badge tone={c.risk_tier === "high" ? "block" : c.risk_tier === "medium" ? "revise" : "neutral"}>{c.risk_tier} risk</Badge>
            <StatusBadge value={c.status} />
            <span className="ml-auto text-[11.5px] text-faint">{c.approver_label ? `approved by ${c.approver_label}` : ""}</span>
          </div>
          <div className="text-[11px] text-faint font-mono mt-1 truncate">idempotency {c.idempotency_key}</div>
        </div>
      ))}
    </div>
  );
}
