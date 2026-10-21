"use client";

import { Brain, Download, Eraser, FileCheck2, Search, ShieldCheck, UserRound } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { can, useMe } from "@/components/shell";
import { Avatar, Badge, Button, Card, CardHeader, Dialog, Drawer, Empty, Input, JsonView, LoadingRows, PageHeader, StatusBadge, Switch, Table, Tabs, Td, Th, useToast } from "@/components/ui";
import { api, useApi } from "@/lib/api";
import { ago, date, num, title } from "@/lib/format";

export default function Customers() {
  const [tab, setTab] = useState<"customers" | "erasures">("customers");
  const [q, setQ] = useState("");
  const [deb, setDeb] = useState("");
  useEffect(() => { const t = setTimeout(() => setDeb(q), 250); return () => clearTimeout(t); }, [q]);
  const { data, mutate } = useApi<{ items: any[] }>(`/api/customers${deb ? `?q=${encodeURIComponent(deb)}` : ""}`);
  const { data: er, mutate: mutateEr } = useApi<{ items: any[] }>("/api/erasures");
  const [open, setOpen] = useState<string | null>(null);
  return (
    <>
      <PageHeader eyebrow="Trust" title="Customers & privacy"
        description="Identity is resolved across channels on email, phone and CRM ID. Memory is used only with consent, can be exported as JSON, and can be erased completely, with a receipt." />
      <Tabs value={tab} onChange={setTab} tabs={[{ value: "customers", label: "Customers", count: data?.items.length }, { value: "erasures", label: "Erasure receipts", count: er?.items.length }]} />
      {tab === "customers" ? (
        <Card>
          <div className="p-3 border-b border-line"><div className="relative max-w-md"><Search className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-faint" /><Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search by name or email" className="pl-8" /></div></div>
          {!data ? <LoadingRows /> : data.items.length === 0 ? <Empty icon={<UserRound className="h-5 w-5" />} title="No customers found" /> : (
            <Table>
              <thead><tr><Th>Customer</Th><Th>Identity keys</Th><Th>Memory</Th><Th align="right">Conversations</Th><Th align="right">Last seen</Th></tr></thead>
              <tbody>{data.items.map((c) => (
                <tr key={c.id} onClick={() => setOpen(c.id)} className="cursor-pointer hover:bg-subtle/60">
                  <Td><div className="flex items-center gap-2.5"><Avatar name={c.display_name || c.email} /><div><div className="font-medium">{c.display_name || "—"}</div><div className="text-[11.5px] text-faint">{c.email}</div></div></div></Td>
                  <Td><div className="flex gap-1">{c.email && <Badge>email</Badge>}{c.phone && <Badge>phone</Badge>}{c.crm_id && <Badge>CRM</Badge>}</div></Td>
                  <Td>{c.memory_consent ? <Badge tone="accent">{c.memory_items} items</Badge> : <Badge>consent off</Badge>}</Td>
                  <Td align="right">{num(c.conversations)}</Td>
                  <Td align="right" className="text-muted">{ago(c.last_seen_at)}</Td>
                </tr>
              ))}</tbody>
            </Table>
          )}
        </Card>
      ) : <Receipts items={er?.items} />}
      {open && <CustomerDrawer id={open} onClose={() => setOpen(null)} onErased={() => { setOpen(null); mutate(); mutateEr(); setTab("erasures"); }} />}
    </>
  );
}

function Receipts({ items }: { items?: any[] }) {
  if (!items) return <Card><LoadingRows /></Card>;
  if (!items.length) return <Card><Empty icon={<FileCheck2 className="h-5 w-5" />} title="No erasure requests yet" /></Card>;
  return (
    <div className="grid gap-3 lg:grid-cols-2">
      {items.map((r) => <ReceiptCard key={r.id} r={r} />)}
    </div>
  );
}

function ReceiptCard({ r }: { r: any }) {
  const counts = r.receipt?.counts || {};
  return (
    <Card className="p-5 animate-rise">
      <div className="flex items-center gap-2 mb-1"><FileCheck2 className="h-4 w-4 text-approve" /><span className="font-semibold">Erasure receipt</span><StatusBadge value={r.status} /></div>
      <div className="text-[12px] text-faint font-mono mb-3">{r.id}</div>
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
        {Object.entries(counts).map(([k, v]) => (
          <div key={k} className="rounded-lg bg-subtle border border-line px-2.5 py-1.5"><div className="text-[11px] text-faint">{title(k)}</div><div className="num font-semibold">{String(v)}</div></div>
        ))}
      </div>
      <div className="text-[12px] text-muted mt-3 space-y-0.5">
        <div>Requested {date(r.requested_at, true)} by {r.requested_by} · completed {r.completed_at ? date(r.completed_at, true) : "—"}</div>
        {r.receipt && <div>Backups expire by <b className="text-ink">{r.receipt.backups_expire_by}</b> ({r.receipt.backup_retention_days}-day window). The erasure log is replayed after any restore.</div>}
      </div>
    </Card>
  );
}

function CustomerDrawer({ id, onClose, onErased }: { id: string; onClose: () => void; onErased: () => void }) {
  const me = useMe();
  const toast = useToast();
  const { data: c, mutate } = useApi<any>(`/api/customers/${id}`);
  const [confirm, setConfirm] = useState(false);
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [receipt, setReceipt] = useState<any>(null);

  async function consent(v: boolean) {
    await api(`/api/customers/${id}`, { method: "PATCH", body: { memory_consent: v } });
    toast({ title: v ? "Memory enabled" : "Memory disabled", body: v ? "Memory will be used in eligible workflows." : "Memory will not be read or written for this customer." });
    mutate();
  }
  async function erase() {
    setBusy(true);
    try { const r = await api(`/api/customers/${id}/erase`, { method: "POST" }); setReceipt(r); toast({ title: "Customer erased", body: "Every store was cleared. A receipt was issued." }); }
    catch (e: any) { toast({ title: "Erasure failed", body: e.message, tone: "block" }); }
    finally { setBusy(false); setConfirm(false); }
  }

  if (receipt) return (
    <Drawer open onClose={onErased} title="Erasure complete" subtitle="Raw messages, summaries, facts, embeddings, traces, tool payloads, outside-agent sessions and cached session data were deleted.">
      <ReceiptCard r={{ id: receipt.request_id, status: "completed", requested_at: receipt.requested_at, completed_at: receipt.completed_at, requested_by: me?.user.name, receipt }} />
      <JsonView value={receipt} className="mt-4" />
    </Drawer>
  );

  return (
    <Drawer open onClose={onClose} width={680} title={c?.display_name || c?.email || "Customer"} subtitle={c?.email}
      footer={c && me?.role === "admin" && <>
        <a href={`/api/customers/${id}/export`} className="mr-auto"><Button icon={<Download className="h-3.5 w-3.5" />}>Export JSON</Button></a>
        <Button variant="danger" icon={<Eraser className="h-3.5 w-3.5" />} onClick={() => setConfirm(true)}>Erase customer</Button>
      </>}>
      {!c ? <LoadingRows /> : (
        <div className="space-y-5">
          <div className="flex items-center justify-between rounded-xl border border-line p-4">
            <div className="flex items-center gap-3"><ShieldCheck className="h-5 w-5 text-accent" /><div><div className="text-[13px] font-medium">Memory consent</div><div className="text-[12px] text-muted">Gates whether memory is read or written at all.</div></div></div>
            <Switch checked={c.memory_consent} disabled={!can(me, "builder")} onChange={consent} />
          </div>
          <div>
            <div className="label mb-2 flex items-center gap-1.5"><Brain className="h-3.5 w-3.5" /> Memory ({c.memory.length})</div>
            {c.memory.length === 0 ? <div className="text-[12.5px] text-muted">Nothing remembered.</div> : (
              <ul className="space-y-1.5">{c.memory.map((m: any) => (
                <li key={m.id} className="rounded-lg border border-line px-3 py-2 text-[12.5px] flex gap-2">
                  <Badge tone={m.kind === "fact" ? "info" : "neutral"}>{m.kind}</Badge>
                  <span className="flex-1">{m.content}</span>
                  {m.source_conversation_id && <Link href={`/app/conversations/${m.source_conversation_id}`} className="link text-[11.5px] shrink-0">source</Link>}
                </li>
              ))}</ul>
            )}
          </div>
          <div>
            <div className="label mb-2">Conversations ({c.conversations.length})</div>
            <div className="space-y-1.5">{c.conversations.slice(0, 12).map((x: any) => (
              <Link key={x.id} href={`/app/conversations/${x.id}`} className="flex items-center gap-2 rounded-lg border border-line px-3 py-2 text-[12.5px] hover:bg-subtle">
                <span className="flex-1">{title(x.intent)}</span><Badge>{x.channel}</Badge><StatusBadge value={x.outcome || x.status} /><span className="text-faint">{ago(x.started_at)}</span>
              </Link>
            ))}</div>
          </div>
          {c.pap_sessions.length > 0 && (
            <div>
              <div className="label mb-2">Outside-agent access</div>
              {c.pap_sessions.map((s: any) => <div key={s.id} className="rounded-lg border border-line px-3 py-2 text-[12.5px] flex gap-2 mb-1.5"><span className="font-mono flex-1 truncate">{s.agent_identity}</span><Badge>{s.scopes.join(" + ")}</Badge>{s.revoked_at ? <Badge>revoked</Badge> : <Badge tone="approve">active</Badge>}</div>)}
            </div>
          )}
        </div>
      )}
      <Dialog open={confirm} onClose={() => setConfirm(false)} title="Erase this customer completely?"
        footer={<><Button onClick={() => setConfirm(false)}>Cancel</Button><Button variant="danger" loading={busy} disabled={typed !== "ERASE"} onClick={erase}>Erase everything</Button></>}>
        <p>This deletes their conversations, messages, memory and embeddings, trace content, tool payloads, outside-agent sessions and cached session data. Outcomes keep counts and timestamps only, so invoices stay auditable. This cannot be undone.</p>
        <Input className="mt-3" value={typed} onChange={(e) => setTyped(e.target.value)} placeholder="Type ERASE to confirm" />
      </Dialog>
    </Drawer>
  );
}
