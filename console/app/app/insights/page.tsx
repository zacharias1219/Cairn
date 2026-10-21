"use client";

import { Code2, Database } from "lucide-react";
import { useState } from "react";

import { VolumeChart } from "@/components/charts";
import { Card, CardHeader, CopyButton, LoadingRows, PageHeader, Segmented, Table, Td, Th, cx } from "@/components/ui";
import { useApi } from "@/lib/api";
import { title } from "@/lib/format";

const ORDER = ["verified_resolution_rate", "escalation_rate", "cost_per_resolution", "csat", "latency", "outcome_mix",
  "escalation_reasons", "supervisor_interventions", "contact_reasons", "rule_firings", "daily_volume"];

export default function Insights() {
  const [days, setDays] = useState<"7" | "30" | "90">("30");
  const { data } = useApi<any>(`/api/insights?days=${days}`);
  return (
    <>
      <PageHeader eyebrow="Monitor" title="Insights"
        description="Where the agent wins and where it struggles. Every number on this page is produced by exactly the query shown under it, run live against the raw tables. Test and evaluation traffic is excluded."
        actions={<Segmented value={days} onChange={setDays} options={[{ value: "7", label: "7d" }, { value: "30", label: "30d" }, { value: "90", label: "90d" }]} />} />
      {!data ? <Card><LoadingRows rows={8} /></Card> : (
        <div className="space-y-4">
          <Card>
            <CardHeader title="Daily volume" subtitle={data.metrics.daily_volume.description} />
            <div className="px-3"><VolumeChart rows={data.metrics.daily_volume.rows} /></div>
            <QueryPeek sql={data.metrics.daily_volume.sql} />
          </Card>
          <div className="grid gap-4 lg:grid-cols-2">
            {ORDER.filter((k) => k !== "daily_volume").map((k) => <Metric key={k} m={data.metrics[k]} />)}
          </div>
        </div>
      )}
    </>
  );
}

function Metric({ m }: { m: any }) {
  const rows: any[] = m.rows || [];
  const cols = rows[0] ? Object.keys(rows[0]) : [];
  const single = rows.length === 1 && cols.length <= 3;
  return (
    <Card className="flex flex-col">
      <CardHeader title={m.title} subtitle={m.description} />
      <div className="flex-1">
        {rows.length === 0 ? <div className="px-5 pb-4 text-[13px] text-muted">No data in this period.</div> : single ? (
          <div className="px-5 pb-4 flex flex-wrap gap-6">
            {cols.map((c) => (
              <div key={c}><div className="label">{title(c)}</div><div className="text-[24px] font-semibold num">{rows[0][c] ?? "—"}</div></div>
            ))}
          </div>
        ) : (
          <Table className="max-h-[300px] overflow-y-auto">
            <thead><tr>{cols.map((c) => <Th key={c} align={typeof rows[0][c] === "number" ? "right" : undefined}>{title(c)}</Th>)}</tr></thead>
            <tbody>{rows.map((r, i) => <tr key={i}>{cols.map((c) => <Td key={c} align={typeof r[c] === "number" ? "right" : undefined}>{typeof r[c] === "string" ? title(r[c]) : r[c] ?? "—"}</Td>)}</tr>)}</tbody>
          </Table>
        )}
      </div>
      <QueryPeek sql={m.sql} />
    </Card>
  );
}

function QueryPeek({ sql }: { sql: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="border-t border-line">
      <button onClick={() => setOpen((o) => !o)} className="w-full flex items-center gap-2 px-5 py-2.5 text-[12px] text-muted hover:text-ink">
        <Code2 className="h-3.5 w-3.5" /> {open ? "Hide" : "Show"} the query behind this number
        <Database className="h-3.5 w-3.5 ml-auto text-faint" />
      </button>
      {open && (
        <div className="relative mx-5 mb-4 rounded-lg bg-subtle border border-line">
          <CopyButton value={sql} className="absolute right-2 top-2" />
          <pre className={cx("code p-3 overflow-x-auto text-ink/85")}>{sql}</pre>
        </div>
      )}
    </div>
  );
}
