"use client";

import { CheckCircle2, CircleX } from "lucide-react";

import { Badge, cx } from "@/components/ui";

export function GateList({ gates }: { gates: any[] }) {
  return (
    <div className="rounded-xl border border-line divide-y divide-line overflow-hidden">
      {gates.map((g) => (
        <div key={g.gate} className={cx("flex items-center gap-3 px-4 py-3", !g.passed && "bg-block/5")}>
          {g.passed ? <CheckCircle2 className="h-4.5 w-4.5 h-[18px] w-[18px] text-approve shrink-0" /> : <CircleX className="h-[18px] w-[18px] text-block shrink-0" />}
          <div className="min-w-0 flex-1">
            <div className="text-[13px] font-medium text-ink">{g.gate}</div>
            <div className="text-[12px] text-muted">{g.condition} <span className="text-faint">· {g.applies_to.toLowerCase()}</span></div>
          </div>
          <span className={cx("num text-[13px] font-medium", g.passed ? "text-ink" : "text-block")}>{g.value}</span>
        </div>
      ))}
    </div>
  );
}

export function FailureList({ failures }: { failures: any[] }) {
  if (!failures?.length) return null;
  return (
    <div className="mt-3 space-y-2 max-h-64 overflow-y-auto">
      {failures.slice(0, 20).map((f) => (
        <div key={f.key} className="rounded-lg border border-line px-3 py-2">
          <div className="flex items-center gap-2 text-[12.5px]"><span className="font-mono">{f.key}</span>{f.critical && <Badge tone="block">critical</Badge>}</div>
          <ul className="text-[12px] text-muted mt-1 list-disc pl-4">{f.failures.slice(0, 3).map((x: string, i: number) => <li key={i}>{x}</li>)}</ul>
        </div>
      ))}
    </div>
  );
}

export function flatten(o: any, prefix = ""): Record<string, string> {
  const out: Record<string, string> = {};
  if (o && typeof o === "object" && !Array.isArray(o)) {
    for (const k of Object.keys(o)) Object.assign(out, flatten(o[k], prefix ? `${prefix}.${k}` : k));
  } else out[prefix] = JSON.stringify(o);
  return out;
}

export function Diff({ a, b }: { a: any; b: any }) {
  const fa = flatten(a), fb = flatten(b);
  const keys = Array.from(new Set([...Object.keys(fa), ...Object.keys(fb)])).sort().filter((k) => fa[k] !== fb[k]);
  if (!keys.length) return <div className="text-[12.5px] text-muted">No differences.</div>;
  return (
    <div className="rounded-lg border border-line divide-y divide-line font-mono text-[12px]">
      {keys.map((k) => (
        <div key={k} className="px-3 py-2">
          <div className="text-faint mb-1">{k}</div>
          {fa[k] !== undefined && <div className="text-block bg-block/5 rounded px-1.5 py-0.5 break-all">− {fa[k]}</div>}
          {fb[k] !== undefined && <div className="text-approve bg-approve/5 rounded px-1.5 py-0.5 mt-0.5 break-all">+ {fb[k]}</div>}
        </div>
      ))}
    </div>
  );
}
