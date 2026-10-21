"use client";

import { Bot, BookOpen, ShieldCheck, User } from "lucide-react";

import { Badge, StatusBadge, cx } from "@/components/ui";
import { time } from "@/lib/format";

export type Msg = { id?: string; turn_id?: string; role: string; content: string; metadata?: any; created_at?: string; pending?: boolean };

export function Transcript({ messages, selectedTurn, onSelect, typing }: {
  messages: Msg[]; selectedTurn?: string | null; onSelect?: (turnId: string) => void; typing?: string | null;
}) {
  return (
    <div className="space-y-3">
      {messages.map((m, i) => <Bubble key={m.id || i} m={m} selected={!!m.turn_id && m.turn_id === selectedTurn} onSelect={onSelect} />)}
      {typing && (
        <div className="flex items-end gap-2 animate-fade-in">
          <span className="h-7 w-7 rounded-full bg-accent grid place-items-center text-accent-ink shrink-0"><Bot className="h-3.5 w-3.5" /></span>
          <div className="rounded-2xl rounded-bl-md bg-surface border border-line px-3.5 py-2.5 text-[12.5px] text-muted flex items-center gap-2">
            <span className="flex gap-1">{[0, 1, 2].map((d) => <span key={d} className="h-1.5 w-1.5 rounded-full bg-faint animate-pulse-dot" style={{ animationDelay: `${d * 160}ms` }} />)}</span>
            {typing}
          </div>
        </div>
      )}
    </div>
  );
}

function Bubble({ m, selected, onSelect }: { m: Msg; selected: boolean; onSelect?: (t: string) => void }) {
  const customer = m.role === "customer" || m.role === "outside_agent";
  const meta = m.metadata || {};
  if (m.role === "system") return <div className="text-center text-[11.5px] text-faint">{m.content}</div>;
  return (
    <div className={cx("flex items-end gap-2 animate-rise", customer ? "flex-row-reverse" : "")}>
      <span className={cx("h-7 w-7 rounded-full grid place-items-center shrink-0",
        customer ? "bg-sunken text-muted" : "bg-accent text-accent-ink")}>
        {customer ? (m.role === "outside_agent" ? <Bot className="h-3.5 w-3.5" /> : <User className="h-3.5 w-3.5" />) : <Bot className="h-3.5 w-3.5" />}
      </span>
      <div className={cx("max-w-[80%] min-w-0", customer && "items-end flex flex-col")}>
        <button
          disabled={!onSelect || !m.turn_id || customer}
          onClick={() => m.turn_id && onSelect?.(m.turn_id)}
          className={cx("text-left rounded-2xl px-3.5 py-2.5 text-[13.5px] leading-relaxed whitespace-pre-wrap transition-all",
            customer ? "bg-ink text-bg rounded-br-md" : "bg-surface border border-line rounded-bl-md hover:border-line-strong",
            selected && "ring-2 ring-accent/50 border-accent/40", m.pending && "opacity-60")}>
          {m.content}
        </button>
        <div className={cx("flex flex-wrap items-center gap-1.5 mt-1 px-1", customer && "justify-end")}>
          {m.role === "outside_agent" && <Badge tone="info">personal agent</Badge>}
          {!customer && meta.verdict && (
            <span className="inline-flex items-center gap-1 text-[11px] text-faint"><ShieldCheck className="h-3 w-3 text-approve" />checked</span>
          )}
          {!customer && meta.action && meta.action !== "reply" && <StatusBadge value={meta.action} />}
          {(meta.citations || []).map((c: any) => (
            <span key={c.chunk_id} className="inline-flex items-center gap-1 rounded-full bg-subtle border border-line px-1.5 text-[10.5px] text-muted">
              <BookOpen className="h-2.5 w-2.5" />{c.title}{c.heading ? ` › ${c.heading}` : ""}
            </span>
          ))}
          {m.created_at && <span className="text-[10.5px] text-faint">{time(m.created_at)}</span>}
        </div>
      </div>
    </div>
  );
}
