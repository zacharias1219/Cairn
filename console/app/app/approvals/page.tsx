"use client";

import { Check, ClipboardCheck, MessageSquareText, Scale, ShieldAlert, X } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { can, useMe } from "@/components/shell";
import { Avatar, Badge, Button, Card, Empty, JsonView, LoadingRows, PageHeader, StatusBadge, Tabs, Textarea, cx, useToast } from "@/components/ui";
import { api, refresh, useApi } from "@/lib/api";
import { ago, money, title } from "@/lib/format";

export default function Approvals() {
  const [tab, setTab] = useState<"pending_approval" | "all">("pending_approval");
  const { data, mutate, isLoading } = useApi<{ items: any[] }>(`/api/approvals?status=${tab}`, { refreshInterval: 8000 });
  return (
    <>
      <PageHeader eyebrow="Monitor" title="Approvals"
        description="High-risk actions and anything a rule marked for review wait here, with the full context of the request. Nothing runs until a named person decides." />
      <Tabs value={tab} onChange={setTab} tabs={[{ value: "pending_approval", label: "Waiting", count: tab === "pending_approval" ? data?.items.length : undefined }, { value: "all", label: "History" }]} />
      {isLoading && !data ? <Card><LoadingRows rows={4} /></Card> : !data?.items.length ? (
        <Card><Empty icon={<ClipboardCheck className="h-5 w-5" />} title={tab === "pending_approval" ? "Nothing is waiting" : "No decisions yet"}>
          {tab === "pending_approval" ? "When the agent proposes a refund over the approval threshold or a high-risk action, it appears here." : ""}
        </Empty></Card>
      ) : (
        <div className="grid gap-4 xl:grid-cols-2">
          {data.items.map((a) => <ApprovalCard key={a.id} a={a} onDone={() => { mutate(); refresh("/api/auth/me"); }} />)}
        </div>
      )}
    </>
  );
}

function ApprovalCard({ a, onDone }: { a: any; onDone: () => void }) {
  const me = useMe();
  const toast = useToast();
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState<"approve" | "deny" | null>(null);
  const pending = a.status === "pending_approval";
  const amount = a.input?.amount;

  async function decide(approve: boolean) {
    setBusy(approve ? "approve" : "deny");
    try {
      const r = await api(`/api/approvals/${a.id}`, { body: { approve, note: note || null } });
      toast({ title: approve ? "Approved and executed" : "Denied", body: `The customer was told: “${r.reply.slice(0, 120)}${r.reply.length > 120 ? "…" : ""}”`, tone: approve ? "approve" : "block" });
      onDone();
    } catch (e: any) {
      toast({ title: "Could not record the decision", body: e.message, tone: "block" });
    } finally { setBusy(null); }
  }

  return (
    <Card className="flex flex-col animate-rise">
      <div className="p-5 flex items-start gap-4">
        <div className={cx("h-11 w-11 rounded-xl grid place-items-center shrink-0", a.risk_tier === "high" ? "bg-block/10 text-block" : "bg-revise/10 text-revise")}>
          <ShieldAlert className="h-5 w-5" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-semibold text-[15px]">{title(a.tool_name)}</span>
            {amount != null && <span className="font-semibold text-[15px] num">{money(amount)}</span>}
            <Badge tone={a.risk_tier === "high" ? "block" : "revise"}>{a.risk_tier} risk</Badge>
            <StatusBadge value={a.status} />
          </div>
          <div className="text-[12.5px] text-muted mt-0.5">{a.tool_description}</div>
          <div className="flex items-center gap-2 mt-2 text-[12.5px]">
            <Avatar name={a.display_name || a.email} className="!h-5 !w-5 !text-[9px]" />
            <span>{a.display_name || a.email || "Unknown customer"}</span>
            <span className="text-faint">· {a.source === "pap" ? "via personal agent" : a.channel} · requested {ago(a.created_at)}</span>
          </div>
        </div>
      </div>
      <div className="px-5 space-y-3">
        {(a.rules || []).length > 0 && (
          <div className="rounded-lg border border-line divide-y divide-line">
            {a.rules.map((r: any) => (
              <div key={r.rule_key} className="flex items-center gap-2 px-3 py-2 text-[12.5px]">
                <Scale className="h-3.5 w-3.5 text-faint" /><span className="font-mono text-[12px]">{r.rule_key}</span>
                <StatusBadge value={r.outcome} /><span className="text-muted truncate">{r.message}</span>
              </div>
            ))}
          </div>
        )}
        {a.risk_tier === "high" && !(a.rules || []).length && <div className="text-[12.5px] text-muted">High-risk tools always wait for a person.</div>}
        <JsonView value={a.input} maxHeight={140} />
        {a.transcript && (
          <details className="group">
            <summary className="cursor-pointer text-[12.5px] text-muted flex items-center gap-1.5"><MessageSquareText className="h-3.5 w-3.5" /> Conversation ({a.transcript.length} messages)</summary>
            <div className="mt-2 space-y-1.5 max-h-56 overflow-y-auto rounded-lg bg-subtle p-3">
              {a.transcript.map((m: any, i: number) => (
                <div key={i} className="text-[12.5px]"><span className={cx("font-medium", m.role === "agent" ? "text-accent" : "text-ink")}>{m.role === "agent" ? "Agent" : "Customer"}:</span> <span className="text-muted">{m.content}</span></div>
              ))}
            </div>
          </details>
        )}
      </div>
      <div className="mt-auto p-5 pt-4">
        {pending ? (
          can(me, "builder") ? (
            <div className="space-y-2.5">
              <Textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2} placeholder="Note for the record (shown to the customer if you deny)" />
              <div className="flex gap-2">
                <Button variant="primary" className="flex-1" loading={busy === "approve"} onClick={() => decide(true)} icon={<Check className="h-4 w-4" />}>Approve and run</Button>
                <Button className="flex-1" loading={busy === "deny"} onClick={() => decide(false)} icon={<X className="h-4 w-4" />}>Deny</Button>
              </div>
            </div>
          ) : <div className="text-[12.5px] text-muted">Viewers can see approvals but not decide them.</div>
        ) : (
          <div className="flex items-center justify-between text-[12.5px] text-muted">
            <span>Decided by <b className="text-ink">{a.approver_label}</b> {ago(a.decided_at)}{a.decision_note ? ` · “${a.decision_note}”` : ""}</span>
            {a.conversation_id && <Link className="link" href={`/app/conversations/${a.conversation_id}`}>Open conversation</Link>}
          </div>
        )}
        {pending && a.conversation_id && <Link className="link text-[12.5px] mt-3 inline-block" href={`/app/conversations/${a.conversation_id}`}>Open the full trail</Link>}
      </div>
    </Card>
  );
}
