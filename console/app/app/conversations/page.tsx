"use client";

import { Download, Filter, MessagesSquare, Search } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { Avatar, Badge, Button, Card, Empty, Input, LoadingRows, PageHeader, Select, StatusBadge, Table, Td, Th } from "@/components/ui";
import { useApi } from "@/lib/api";
import { ago, money, title } from "@/lib/format";

function Conversations() {
  const params = useSearchParams();
  const router = useRouter();
  const [q, setQ] = useState(params.get("q") || "");
  const [debounced, setDebounced] = useState(q);
  const [status, setStatus] = useState(params.get("status") || "");
  const [channel, setChannel] = useState("");
  const [outcome, setOutcome] = useState("");
  const [testToo, setTestToo] = useState(false);
  useEffect(() => { const t = setTimeout(() => setDebounced(q), 250); return () => clearTimeout(t); }, [q]);
  const qs = new URLSearchParams({ limit: "100", ...(debounced && { q: debounced }), ...(status && { status }), ...(channel && { channel }), ...(outcome && { outcome }), ...(testToo && { include_test: "true" }) });
  const { data, isLoading } = useApi<{ items: any[]; total: number }>(`/api/conversations?${qs}`, { refreshInterval: 15000 });

  return (
    <>
      <PageHeader eyebrow="Monitor" title="Conversations" description="Every conversation, every channel. Open one to see the full trail behind each reply."
        actions={<a href="/api/audit/export?format=csv"><Button icon={<Download className="h-3.5 w-3.5" />}>Export trail</Button></a>} />
      <Card>
        <div className="flex flex-wrap items-center gap-2 p-3 border-b border-line">
          <div className="relative flex-1 min-w-[220px]">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-faint" />
            <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search messages, customers or intents" className="pl-8" />
          </div>
          <Select value={status} onChange={(e) => setStatus(e.target.value)} className="w-[160px]">
            <option value="">Any status</option><option value="active">Active</option><option value="awaiting_approval">Awaiting approval</option>
            <option value="escalated">Escalated</option><option value="closed">Closed</option>
          </Select>
          <Select value={channel} onChange={(e) => setChannel(e.target.value)} className="w-[140px]">
            <option value="">All channels</option><option value="web">Web chat</option><option value="email">Email</option><option value="pap">Outside agents</option>
          </Select>
          <Select value={outcome} onChange={(e) => setOutcome(e.target.value)} className="w-[150px]">
            <option value="">Any outcome</option><option value="resolved">Resolved</option><option value="escalated">Escalated</option>
            <option value="abandoned">Abandoned</option><option value="failed">Failed</option>
          </Select>
          <label className="flex items-center gap-1.5 text-[12.5px] text-muted px-1 cursor-pointer">
            <input type="checkbox" checked={testToo} onChange={(e) => setTestToo(e.target.checked)} className="accent-[rgb(var(--accent))]" /> Include tests
          </label>
        </div>
        {isLoading && !data ? <LoadingRows /> : data?.items.length === 0 ? (
          <Empty icon={<MessagesSquare className="h-5 w-5" />} title="No conversations match">Try a different filter or search term.</Empty>
        ) : (
          <Table>
            <thead><tr><Th>Conversation</Th><Th>Customer</Th><Th>Intent</Th><Th>Status</Th><Th>Outcome</Th><Th align="right">Checks</Th><Th align="right">Cost</Th><Th align="right">Last activity</Th></tr></thead>
            <tbody>
              {data?.items.map((c) => (
                <tr key={c.id} onClick={() => router.push(`/app/conversations/${c.id}`)} className="cursor-pointer hover:bg-subtle/60 transition-colors">
                  <Td className="max-w-[300px]">
                    <div className="truncate font-medium">{c.first_message || c.subject || "—"}</div>
                    <div className="text-[11.5px] text-faint flex items-center gap-1.5">{c.channel === "pap" ? "outside agent" : c.channel} · {c.message_count} messages {c.is_test && <Badge>test</Badge>}</div>
                  </Td>
                  <Td>
                    <div className="flex items-center gap-2 min-w-0">
                      <Avatar name={c.display_name || c.email || "Visitor"} className="!h-6 !w-6 !text-[10px]" />
                      <span className="truncate max-w-[160px]">{c.display_name || c.email || <span className="text-faint">Anonymous</span>}</span>
                    </div>
                  </Td>
                  <Td className="whitespace-nowrap">{title(c.intent)}</Td>
                  <Td><StatusBadge value={c.status} /></Td>
                  <Td>{c.outcome ? <StatusBadge value={c.outcome} label={`${title(c.outcome)}${c.outcome_status === "pending" ? " · pending" : c.billable ? " · billable" : ""}`} /> : <span className="text-faint">open</span>}</Td>
                  <Td align="right">{c.interventions > 0 ? <Badge tone="revise">{c.interventions} caught</Badge> : <span className="text-faint">clean</span>}</Td>
                  <Td align="right" className="text-muted">{money(c.cost_usd, 4)}</Td>
                  <Td align="right" className="text-muted whitespace-nowrap">{ago(c.last_activity_at)}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
        {data && <div className="px-4 py-2.5 text-[12px] text-faint border-t border-line flex items-center gap-1.5"><Filter className="h-3 w-3" /> Showing {data.items.length} of {data.total}</div>}
      </Card>
    </>
  );
}

export default function Page() {
  return <Suspense><Conversations /></Suspense>;
}
