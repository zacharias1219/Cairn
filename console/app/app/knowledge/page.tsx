"use client";

import { BookOpenText, CheckCheck, FileText, Plus, Search, Trash2 } from "lucide-react";
import { useState } from "react";

import { can, useMe } from "@/components/shell";
import { Badge, Button, Card, CardHeader, Dialog, Drawer, Field, Input, LoadingRows, PageHeader, Select, Table, Td, Textarea, Th, cx, useToast } from "@/components/ui";
import { api, useApi } from "@/lib/api";
import { ago, date, until } from "@/lib/format";

export default function Knowledge() {
  const me = useMe();
  const { data, mutate } = useApi<{ items: any[] }>("/api/knowledge");
  const [edit, setEdit] = useState<any>(null);
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<any[] | null>(null);
  const [searching, setSearching] = useState(false);
  const stale = data?.items.filter((s) => s.stale).length || 0;

  async function ask(e: React.FormEvent) {
    e.preventDefault();
    if (!q.trim()) return;
    setSearching(true);
    try { setHits((await api(`/api/knowledge/search?q=${encodeURIComponent(q)}`)).items); } finally { setSearching(false); }
  }

  return (
    <>
      <PageHeader eyebrow="Build" title="Knowledge"
        description="Policies, FAQs and docs, chunked and indexed for hybrid keyword and vector search. Every answer cites the chunks it used; stale sources are flagged for their owner."
        actions={can(me, "builder") && <Button variant="primary" icon={<Plus className="h-3.5 w-3.5" />} onClick={() => setEdit({ title: "", content: "", owner: me?.user.name || "", kind: "policy", review_interval_days: 90 })}>Add source</Button>} />
      <div className="grid gap-4 xl:grid-cols-[1fr_420px]">
        <Card>
          <CardHeader title={`${data?.items.length ?? "—"} sources`} subtitle={stale ? `${stale} past its review date` : "All sources reviewed on schedule"} />
          {!data ? <LoadingRows /> : (
            <Table>
              <thead><tr><Th>Source</Th><Th>Owner</Th><Th>Review</Th><Th align="right">Chunks</Th></tr></thead>
              <tbody>
                {data.items.map((s) => (
                  <tr key={s.id} onClick={async () => setEdit(await api(`/api/knowledge/${s.id}`))} className="cursor-pointer hover:bg-subtle/60">
                    <Td>
                      <div className="flex items-center gap-2.5"><FileText className="h-4 w-4 text-faint shrink-0" />
                        <div className="min-w-0"><div className="font-medium truncate">{s.title}</div><div className="text-[11.5px] text-faint">{s.kind} · updated {ago(s.updated_at)}</div></div>
                      </div>
                    </Td>
                    <Td className="text-muted">{s.owner}</Td>
                    <Td>{s.stale ? <Badge tone="revise" dot>review overdue</Badge> : <span className="text-[12.5px] text-muted">due in {until(s.review_due)}</span>}</Td>
                    <Td align="right" className="text-muted">{s.chunks}</Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </Card>
        <Card className="self-start">
          <CardHeader title="Ask the knowledge base" subtitle="See exactly which chunks the agent would retrieve, and why." />
          <form onSubmit={ask} className="px-5 flex gap-2">
            <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="e.g. how long do refunds take?" />
            <Button loading={searching} icon={<Search className="h-3.5 w-3.5" />}>Search</Button>
          </form>
          <div className="p-5 space-y-2.5">
            {hits === null && <div className="text-[12.5px] text-faint">Results are ranked by reciprocal-rank fusion of keyword and vector search, then reranked on term coverage.</div>}
            {hits?.length === 0 && <div className="text-[12.5px] text-muted">No source covers that. The agent would say it isn't sure and offer a teammate.</div>}
            {hits?.map((h, i) => (
              <div key={h.chunk_id} className="rounded-lg border border-line p-3 animate-rise" style={{ animationDelay: `${i * 50}ms` }}>
                <div className="flex items-center gap-2 text-[12.5px]"><span className="font-medium">{h.title}</span>{h.heading && <span className="text-faint truncate">› {h.heading}</span>}
                  <span className="ml-auto num text-faint text-[11.5px]">{Number(h.score).toFixed(2)}</span></div>
                <p className="text-[12.5px] text-muted mt-1 line-clamp-4">{h.content}</p>
              </div>
            ))}
          </div>
        </Card>
      </div>
      {edit && <SourceDrawer source={edit} onClose={() => setEdit(null)} onSaved={() => { mutate(); setEdit(null); }} />}
    </>
  );
}

function SourceDrawer({ source, onClose, onSaved }: { source: any; onClose: () => void; onSaved: () => void }) {
  const me = useMe();
  const toast = useToast();
  const [s, setS] = useState({ ...source });
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const editable = can(me, "builder");
  const isNew = !source.id;

  async function save() {
    setBusy(true);
    try {
      const body = { title: s.title, content: s.content, owner: s.owner, kind: s.kind, url: s.url || null, review_interval_days: +s.review_interval_days };
      await api(isNew ? "/api/knowledge" : `/api/knowledge/${s.id}`, { method: isNew ? "POST" : "PUT", body });
      toast({ title: isNew ? "Source added" : "Source updated", body: "Re-chunked and re-indexed. It is live for retrieval now." });
      onSaved();
    } catch (e: any) { toast({ title: "Save failed", body: e.message, tone: "block" }); }
    finally { setBusy(false); }
  }
  async function reviewed() { await api(`/api/knowledge/${s.id}/review`, { method: "POST" }); toast({ title: "Marked as reviewed" }); onSaved(); }
  async function del() { await api(`/api/knowledge/${s.id}`, { method: "DELETE" }); toast({ title: "Source deleted", body: "Its chunks were removed from retrieval immediately." }); onSaved(); }

  return (
    <Drawer open onClose={onClose} width={760} title={isNew ? "New source" : s.title}
      subtitle={!isNew && `${s.chunks?.length ?? 0} chunks · reviewed ${date(s.reviewed_at)} by ${s.owner}`}
      footer={editable && <>
        {!isNew && <Button variant="ghost" className="mr-auto text-block" icon={<Trash2 className="h-3.5 w-3.5" />} onClick={() => setConfirm(true)}>Delete</Button>}
        {!isNew && <Button icon={<CheckCheck className="h-3.5 w-3.5" />} onClick={reviewed}>Mark reviewed</Button>}
        <Button variant="primary" onClick={save} loading={busy}>Save & index</Button>
      </>}>
      <fieldset disabled={!editable} className="space-y-4">
        <div className="grid sm:grid-cols-2 gap-3">
          <Field label="Title"><Input value={s.title} onChange={(e) => setS({ ...s, title: e.target.value })} /></Field>
          <Field label="Owner" hint="Responsible for keeping it current"><Input value={s.owner} onChange={(e) => setS({ ...s, owner: e.target.value })} /></Field>
        </div>
        <div className="grid sm:grid-cols-3 gap-3">
          <Field label="Kind"><Select value={s.kind} onChange={(e) => setS({ ...s, kind: e.target.value })}><option value="policy">Policy</option><option value="faq">FAQ</option><option value="doc">Doc</option></Select></Field>
          <Field label="Review every (days)"><Input type="number" value={s.review_interval_days} onChange={(e) => setS({ ...s, review_interval_days: e.target.value })} /></Field>
          <Field label="URL"><Input value={s.url || ""} onChange={(e) => setS({ ...s, url: e.target.value })} /></Field>
        </div>
        <Field label="Content (Markdown)" hint="Headings become chunk boundaries."><Textarea rows={16} value={s.content} onChange={(e) => setS({ ...s, content: e.target.value })} className="font-mono text-[12.5px]" /></Field>
      </fieldset>
      {!isNew && s.chunks?.length > 0 && (
        <div className="mt-6">
          <div className="label mb-2">Indexed chunks</div>
          <div className="space-y-2">{s.chunks.map((c: any) => (
            <div key={c.id} className="rounded-lg border border-line p-3">
              <div className="text-[12px] font-medium">{c.heading || "Introduction"} <span className="text-faint font-mono font-normal">#{c.ord}</span></div>
              <p className="text-[12.5px] text-muted mt-1">{c.content}</p>
            </div>
          ))}</div>
        </div>
      )}
      <Dialog open={confirm} onClose={() => setConfirm(false)} title="Delete this source?"
        footer={<><Button onClick={() => setConfirm(false)}>Cancel</Button><Button variant="danger" onClick={del}>Delete</Button></>}>
        Its chunks are removed from retrieval immediately. Answers that cited it stay on the trail.
      </Dialog>
    </Drawer>
  );
}
