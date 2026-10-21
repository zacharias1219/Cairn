"use client";

import { ArrowLeft, Download, Flag, Lock, Receipt } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { can, useMe } from "@/components/shell";
import { ToolCallList, TurnTrail } from "@/components/trail";
import { Transcript } from "@/components/transcript";
import { Avatar, Badge, Button, Card, CardHeader, JsonView, Skeleton, StatusBadge, useToast } from "@/components/ui";
import { api, useApi } from "@/lib/api";
import { ago, date, money, title, until } from "@/lib/format";

export default function ConversationPage() {
  const { id } = useParams<{ id: string }>();
  const me = useMe();
  const toast = useToast();
  const { data, mutate } = useApi<any>(`/api/conversations/${id}`, { refreshInterval: 10000 });
  const [turnId, setTurnId] = useState<string | null>(null);
  const turns = data?.turns || [];
  useEffect(() => {
    if (!turnId && turns.length) setTurnId(turns[turns.length - 1].id);
  }, [turns, turnId]);
  const turn = useMemo(() => turns.find((t: any) => t.id === turnId), [turns, turnId]);
  const c = data?.conversation;
  const cost = turns.reduce((a: number, t: any) => a + Number(t.cost_usd || 0), 0);

  async function close() {
    try { await api(`/api/conversations/${id}/close`, { method: "POST" }); toast({ title: "Conversation closed", body: "Its outcome is now pending until the re-contact window ends." }); mutate(); }
    catch (e: any) { toast({ title: "Could not close", body: e.message, tone: "block" }); }
  }

  if (!data) return <div className="space-y-4"><Skeleton className="h-16" /><div className="grid lg:grid-cols-2 gap-4"><Skeleton className="h-[520px]" /><Skeleton className="h-[520px]" /></div></div>;

  return (
    <div className="animate-fade-in">
      <Link href="/app/conversations" className="inline-flex items-center gap-1.5 text-[12.5px] text-muted hover:text-ink mb-3"><ArrowLeft className="h-3.5 w-3.5" /> Conversations</Link>
      <div className="flex flex-wrap items-start gap-4 mb-5">
        <Avatar name={c.display_name || c.email || "Visitor"} className="!h-10 !w-10 !text-[13px]" />
        <div className="min-w-0 flex-1">
          <h1 className="font-display text-[28px] leading-tight truncate">{c.display_name || c.email || "Anonymous visitor"}</h1>
          <div className="flex flex-wrap items-center gap-2 mt-1 text-[12.5px] text-muted">
            <StatusBadge value={c.status} />
            <Badge>{c.channel === "pap" ? "outside agent" : c.channel}</Badge>
            {c.intent && <Badge tone="info">{title(c.intent)}</Badge>}
            {c.is_test && <Badge>test</Badge>}
            <span>Started {date(c.started_at, true)}</span><span>·</span><span>{turns.length} turns</span><span>·</span><span>{money(cost, 4)} model cost</span>
            {c.email && <span className="inline-flex items-center gap-1"><Lock className="h-3 w-3" />{c.memory_consent ? "memory on" : "memory off"}</span>}
          </div>
        </div>
        <div className="flex gap-2">
          <a href={`/api/audit/export?format=json&conversation=${id}`}><Button icon={<Download className="h-3.5 w-3.5" />}>Export trail</Button></a>
          {can(me, "builder") && !c.ended_at && <Button onClick={close}>Close conversation</Button>}
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
        <div className="space-y-4 min-w-0">
          <Card className="p-5 bg-subtle/40">
            <Transcript messages={data.messages} selectedTurn={turnId} onSelect={setTurnId} />
            <div className="text-center text-[11.5px] text-faint mt-5">Select any reply to open its trail</div>
          </Card>
          {data.handoffs.map((h: any) => (
            <Card key={h.id} className="p-4 border-escalate/30">
              <div className="flex items-center gap-2 text-[13px] font-medium"><Flag className="h-4 w-4 text-escalate" /> Handed off to {h.destination}</div>
              <div className="text-[12.5px] text-muted mt-1">{title(h.reason_code)}: {h.reason}</div>
              <div className="text-[11.5px] text-faint mt-1">{ago(h.created_at)} · {h.delivery_status} · full transcript attached</div>
            </Card>
          ))}
          <OutcomeCard outcome={data.outcome} signals={data.signals} />
        </div>
        <div className="min-w-0">
          <Card className="lg:sticky lg:top-[72px]">
            <CardHeader title="The trail" subtitle="Everything that happened between the message and the reply, in order."
              action={turns.length > 1 && (
                <div className="flex gap-1">{turns.map((t: any) => (
                  <button key={t.id} onClick={() => setTurnId(t.id)} className={`h-6 min-w-6 px-1.5 rounded-md text-[11.5px] num border ${t.id === turnId ? "bg-accent text-accent-ink border-accent" : "border-line text-muted hover:text-ink"}`}>{t.seq}</button>
                ))}</div>
              )} />
            <div className="px-5 pb-5 max-h-[calc(100vh-180px)] overflow-y-auto">
              {turn ? (
                <>
                  <TurnTrail turn={turn} />
                  {turn.trail.tool_calls.length > 0 && <><div className="label mt-4 mb-2">Tool calls</div><ToolCallList calls={turn.trail.tool_calls} /></>}
                </>
              ) : <div className="text-muted text-[13px]">No turns yet.</div>}
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}

function OutcomeCard({ outcome, signals }: { outcome: any; signals: any[] }) {
  if (!outcome) return (
    <Card className="p-4 text-[13px] text-muted flex items-center gap-2"><Receipt className="h-4 w-4 text-faint" /> No outcome yet. It is recorded when the conversation ends.</Card>
  );
  return (
    <Card>
      <CardHeader title="Outcome" subtitle={outcome.status === "pending" ? `Re-contact window closes in ${until(outcome.window_ends_at)}` : `Finalized ${ago(outcome.finalized_at)}`}
        action={<div className="flex gap-1.5"><StatusBadge value={outcome.type} />{outcome.status === "final" && (outcome.billable ? <Badge tone="approve">billable {money(outcome.amount_usd)}</Badge> : <Badge>not billed</Badge>)}</div>} />
      <div className="px-5 pb-5 space-y-2">
        {outcome.nonbillable_reason && <div className="text-[12.5px] text-muted">Why not billed: {outcome.nonbillable_reason}</div>}
        {signals.map((s, i) => <Badge key={i} tone={s.value >= 4 ? "approve" : s.value <= 2 ? "block" : "neutral"}>CSAT {s.value}/5</Badge>)}
        <details><summary className="text-[12.5px] text-faint cursor-pointer">Evidence behind this outcome</summary><JsonView value={outcome.evidence} className="mt-2" /></details>
      </div>
    </Card>
  );
}
