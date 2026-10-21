"use client";

import { Hourglass, Receipt, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Badge, Card, CardHeader, Drawer, JsonView, LoadingRows, PageHeader, Select, StatusBadge, Table, Td, Th, cx } from "@/components/ui";
import { useApi } from "@/lib/api";
import { ago, date, money, num, title, until } from "@/lib/format";

export default function Outcomes() {
  const [status, setStatus] = useState("");
  const { data: billing } = useApi<any>("/api/billing");
  const { data } = useApi<{ items: any[] }>(`/api/outcomes${status ? `?status=${status}` : ""}`);
  const [open, setOpen] = useState<any>(null);
  const m = billing?.month;
  return (
    <>
      <PageHeader eyebrow="Trust" title="Outcomes & billing"
        description="A published rate card and a hard definition of resolved. You pay only for verified resolutions: the re-contact window must pass with no repeat contact and no negative signal. Every charge opens to its evidence." />
      <div className="grid gap-4 lg:grid-cols-[1.2fr_1fr] mb-4">
        <Card className="p-5">
          <div className="flex items-start justify-between">
            <div><div className="label">This month · estimated invoice</div>
              <div className="font-display text-[48px] leading-none mt-2 num">{billing ? money(billing.estimated_invoice_usd) : "—"}</div>
              <div className="text-muted text-[13px] mt-2">{billing && <>{money(billing.platform_fee_usd, 0)} platform fee + {num(m.billable)} verified resolutions × {money(billing.rate_per_resolution_usd)}</>}</div>
            </div>
            <Badge tone="accent" className="capitalize">{billing?.plan} plan</Badge>
          </div>
          <div className="grid grid-cols-3 gap-3 mt-6">
            <Box icon={ShieldCheck} label="Billable" value={m?.billable} tone="approve" />
            <Box icon={Receipt} label="Free (not resolved, or not verified)" value={m?.free} />
            <Box icon={Hourglass} label="In re-contact window" value={m?.pending} tone="revise" />
          </div>
          {billing?.monthly_cap_usd && <div className="text-[12px] text-muted mt-3">Monthly spending cap: {money(billing.monthly_cap_usd)}</div>}
        </Card>
        <Card>
          <CardHeader title="Why conversations were not billed" subtitle="Escalated, abandoned and failed conversations are always free." />
          <div className="px-5 pb-5 space-y-2">
            {(billing?.nonbillable_reasons || []).map((r: any) => (
              <div key={r.reason} className="flex items-center justify-between text-[13px] border-b border-line last:border-0 py-1.5">
                <span className={cx("first-letter:uppercase", r.reason === "billable" && "font-medium text-approve")}>{r.reason === "billable" ? "Billed: verified resolution" : r.reason}</span><span className="num font-medium">{r.n}</span>
              </div>
            ))}
          </div>
        </Card>
      </div>
      <Card className="mb-4">
        <CardHeader title="Rate card" subtitle="Published, not quote-only." />
        <div className="grid md:grid-cols-3 gap-px bg-line border-t border-line">
          {(billing?.rate_card || []).map((p: any) => (
            <div key={p.plan} className={cx("bg-surface p-5", billing?.plan === p.plan.toLowerCase() && "bg-accent-soft/40")}>
              <div className="flex items-center gap-2"><span className="font-semibold">{p.plan}</span>{p.duration && <Badge>{p.duration}</Badge>}{billing?.plan === p.plan.toLowerCase() && <Badge tone="accent">current</Badge>}</div>
              <div className="mt-2 text-[22px] font-semibold num">{p.platform_fee != null ? `${money(p.platform_fee, 0)}` : "Custom"}<span className="text-[13px] text-muted font-normal">{p.platform_fee != null ? " / month" : ""}</span></div>
              <div className="text-[13px] text-muted">{p.per_resolution != null ? `+ ${money(p.per_resolution)} per verified resolution` : "Negotiated per resolution"}</div>
              <div className="text-[12.5px] text-muted mt-3">{p.includes}</div>
            </div>
          ))}
        </div>
      </Card>
      <Card>
        <CardHeader title="Outcomes" action={<Select value={status} onChange={(e) => setStatus(e.target.value)} className="w-[150px]"><option value="">All</option><option value="pending">Pending</option><option value="final">Final</option></Select>} />
        {!data ? <LoadingRows /> : (
          <Table>
            <thead><tr><Th>Conversation</Th><Th>Type</Th><Th>Status</Th><Th>Billing</Th><Th align="right">Amount</Th><Th align="right">Ended</Th></tr></thead>
            <tbody>{data.items.map((o) => (
              <tr key={o.id} onClick={() => setOpen(o)} className="cursor-pointer hover:bg-subtle/60">
                <Td><div className="font-medium">{title(o.intent)}</div><div className="font-mono text-[11px] text-faint">{o.conversation_id.slice(0, 8)} · {o.channel}</div></Td>
                <Td><StatusBadge value={o.type} /></Td>
                <Td>{o.status === "pending" ? <Badge tone="revise">window closes in {until(o.window_ends_at)}</Badge> : <Badge>final</Badge>}</Td>
                <Td className="text-[12.5px]">{o.status === "pending" ? <span className="text-faint">pending</span> : o.billable ? <span className="text-approve font-medium">billable</span> : <span className="text-muted">{o.nonbillable_reason}</span>}</Td>
                <Td align="right">{o.billable ? money(o.amount_usd) : "—"}</Td>
                <Td align="right" className="text-muted">{date(o.ended_at, true)}</Td>
              </tr>
            ))}</tbody>
          </Table>
        )}
      </Card>
      <Drawer open={!!open} onClose={() => setOpen(null)} title={`${title(open?.type)} · ${title(open?.intent)}`} subtitle="The evidence behind this outcome: tool results, supervisor state and customer signals.">
        {open && <div className="space-y-4">
          <div className="flex flex-wrap gap-2"><StatusBadge value={open.type} />{open.billable ? <Badge tone="approve">billed {money(open.amount_usd)}</Badge> : <Badge>{open.nonbillable_reason || "pending"}</Badge>}</div>
          <Link className="link text-[13px]" href={`/app/conversations/${open.conversation_id}`}>Open the conversation trail</Link>
          <JsonView value={open.evidence} maxHeight={600} />
        </div>}
      </Drawer>
    </>
  );
}

function Box({ icon: Icon, label, value, tone }: { icon: React.ElementType; label: string; value?: number; tone?: string }) {
  return (
    <div className="rounded-xl border border-line p-3">
      <Icon className={cx("h-4 w-4 mb-2", tone ? `text-${tone}` : "text-faint")} />
      <div className="text-[20px] font-semibold num leading-tight">{value ?? "·"}</div>
      <div className="text-[11.5px] text-muted">{label}</div>
    </div>
  );
}
