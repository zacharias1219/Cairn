"use client";

import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { date } from "@/lib/format";

const C = { accent: "rgb(var(--accent))", approve: "rgb(var(--approve))", escalate: "rgb(var(--escalate))" };

function ChartTip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="card shadow-pop px-3 py-2 text-[12px]">
      <div className="font-medium mb-1">{date(label)}</div>
      {payload.map((p: any) => (
        <div key={p.dataKey} className="flex items-center gap-2 text-muted">
          <span className="h-2 w-2 rounded-full" style={{ background: p.color }} />
          {p.name}<span className="ml-auto pl-4 text-ink num font-medium">{p.value}</span>
        </div>
      ))}
    </div>
  );
}

export function VolumeChart({ rows }: { rows: { day: string; conversations: number; verified_resolutions: number; escalated: number }[] }) {
  return (
    <ResponsiveContainer width="100%" height={240}>
      <AreaChart data={rows} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}>
        <defs>
          <linearGradient id="gConv" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={C.accent} stopOpacity={0.22} />
            <stop offset="100%" stopColor={C.accent} stopOpacity={0} />
          </linearGradient>
          <linearGradient id="gRes" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={C.approve} stopOpacity={0.25} />
            <stop offset="100%" stopColor={C.approve} stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid vertical={false} strokeDasharray="3 3" />
        <XAxis dataKey="day" tickFormatter={(d) => date(d)} tickLine={false} axisLine={false} minTickGap={28} />
        <YAxis allowDecimals={false} tickLine={false} axisLine={false} width={40} />
        <Tooltip content={<ChartTip />} cursor={{ stroke: "rgb(var(--line-strong))" }} />
        <Area type="monotone" dataKey="conversations" name="Conversations" stroke={C.accent} strokeWidth={2} fill="url(#gConv)" />
        <Area type="monotone" dataKey="verified_resolutions" name="Verified resolutions" stroke={C.approve} strokeWidth={2} fill="url(#gRes)" />
        <Area type="monotone" dataKey="escalated" name="Escalated" stroke={C.escalate} strokeWidth={1.5} fill="transparent" strokeDasharray="4 3" />
      </AreaChart>
    </ResponsiveContainer>
  );
}

export function Spark({ values, color = "accent" }: { values: number[]; color?: string }) {
  if (values.length < 2) return null;
  const max = Math.max(...values, 1);
  const pts = values.map((v, i) => `${(i / (values.length - 1)) * 100},${28 - (v / max) * 26}`).join(" ");
  return (
    <svg viewBox="0 0 100 30" preserveAspectRatio="none" className="h-8 w-full mt-1">
      <polyline points={pts} fill="none" stroke={`rgb(var(--${color}))`} strokeWidth="1.6" vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
    </svg>
  );
}
