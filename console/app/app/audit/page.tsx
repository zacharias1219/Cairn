"use client";

import { Download, Search } from "lucide-react";
import Link from "next/link";
import { Fragment, useState } from "react";

import { Badge, Button, Card, Field, Input, JsonView, LoadingRows, PageHeader, Select, Table, Tabs, Td, Th } from "@/components/ui";
import { useApi } from "@/lib/api";
import { ago, date, money, ms, title } from "@/lib/format";

export default function Audit() {
  const [tab, setTab] = useState<"admin" | "trail">("admin");
  return (
    <>
      <PageHeader eyebrow="Trust" title="Audit log"
        description="Two append-only records: every admin action (publishes, role changes, approvals, erasures), and the per-step trail behind every reply, searchable by customer, conversation, rule and tool."
        actions={<><a href="/api/audit/export?format=json"><Button icon={<Download className="h-3.5 w-3.5" />}>Trail JSON</Button></a><a href="/api/audit/export?format=csv"><Button icon={<Download className="h-3.5 w-3.5" />}>Trail CSV</Button></a></>} />
      <Tabs value={tab} onChange={setTab} tabs={[{ value: "admin", label: "Admin actions" }, { value: "trail", label: "Search the trail" }]} />
      {tab === "admin" ? <AdminLog /> : <TrailSearch />}
    </>
  );
}

function AdminLog() {
  const { data } = useApi<{ items: any[] }>("/api/audit-log");
  const [open, setOpen] = useState<number | null>(null);
  if (!data) return <Card><LoadingRows /></Card>;
  return (
    <Card>
      <Table>
        <thead><tr><Th>When</Th><Th>Actor</Th><Th>Action</Th><Th>Target</Th></tr></thead>
        <tbody>{data.items.map((a) => (
          <Fragment key={a.id}>
            <tr onClick={() => setOpen(open === a.id ? null : a.id)} className="cursor-pointer hover:bg-subtle/60">
              <Td className="text-muted whitespace-nowrap">{date(a.at, true)}</Td>
              <Td>{a.actor_label}</Td>
              <Td><Badge tone={a.action.includes("refused") || a.action.includes("erase") || a.action.includes("deny") ? "block" : a.action.includes("publish") || a.action.includes("approve") ? "approve" : "neutral"}>{a.action}</Badge></Td>
              <Td className="font-mono text-[12px] text-muted truncate max-w-[280px]">{a.target}</Td>
            </tr>
            {open === a.id && <tr><td colSpan={4} className="px-4 py-3 bg-subtle/40 border-b border-line"><JsonView value={a.detail} maxHeight={240} /></td></tr>}
          </Fragment>
        ))}</tbody>
      </Table>
    </Card>
  );
}

function TrailSearch() {
  const [f, setF] = useState({ customer: "", rule: "", tool: "", conversation: "" });
  const [q, setQ] = useState("");
  const { data } = useApi<{ items: any[] }>(`/api/audit/search?${q}`);
  const { data: rules } = useApi<{ items: any[] }>("/api/rules");
  function go(e: React.FormEvent) {
    e.preventDefault();
    setQ(new URLSearchParams(Object.fromEntries(Object.entries(f).filter(([, v]) => v))).toString());
  }
  return (
    <div className="space-y-4">
      <Card className="p-4">
        <form onSubmit={go} className="grid gap-3 md:grid-cols-[1fr_1fr_1fr_1fr_auto] items-end">
          <Field label="Customer email"><Input value={f.customer} onChange={(e) => setF({ ...f, customer: e.target.value })} placeholder="maya.chen@…" /></Field>
          <Field label="Rule"><Select value={f.rule} onChange={(e) => setF({ ...f, rule: e.target.value })}><option value="">Any</option>{rules?.items.map((r) => <option key={r.rule_key} value={r.rule_key}>{r.rule_key}</option>)}</Select></Field>
          <Field label="Tool"><Select value={f.tool} onChange={(e) => setF({ ...f, tool: e.target.value })}><option value="">Any</option>{["lookup_order", "verify_customer", "issue_refund", "lookup_subscription", "cancel_subscription", "update_shipping_address", "apply_goodwill_credit"].map((t) => <option key={t}>{t}</option>)}</Select></Field>
          <Field label="Conversation ID"><Input value={f.conversation} onChange={(e) => setF({ ...f, conversation: e.target.value })} placeholder="uuid" /></Field>
          <Button variant="primary" icon={<Search className="h-3.5 w-3.5" />}>Search</Button>
        </form>
      </Card>
      <Card>
        {!data ? <LoadingRows /> : (
          <Table>
            <thead><tr><Th>When</Th><Th>Step</Th><Th>Summary</Th><Th>Model</Th><Th>Customer</Th><Th align="right">Latency</Th><Th align="right">Cost</Th></tr></thead>
            <tbody>{data.items.map((t) => (
              <tr key={t.trace_id} className="hover:bg-subtle/60">
                <Td className="text-muted whitespace-nowrap">{ago(t.created_at)}</Td>
                <Td><Badge>{title(t.step)}</Badge></Td>
                <Td className="max-w-[340px]"><Link className="truncate block hover:underline" href={`/app/conversations/${t.conversation_id}`}>{t.summary}</Link></Td>
                <Td className="font-mono text-[11.5px] text-faint whitespace-nowrap">{t.model || "—"}</Td>
                <Td className="text-muted">{t.email || "—"}</Td>
                <Td align="right" className="text-muted">{ms(t.latency_ms)}</Td>
                <Td align="right" className="text-muted">{money(t.cost_usd, 4)}</Td>
              </tr>
            ))}</tbody>
          </Table>
        )}
      </Card>
    </div>
  );
}
