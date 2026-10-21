"use client";

import { Ban, Bot, CheckCircle2, Globe, KeyRound, Plus, ShieldCheck, Timer } from "lucide-react";
import { useState } from "react";

import { can, useMe } from "@/components/shell";
import { Badge, Button, Card, CardHeader, Dialog, Field, Input, JsonView, LoadingRows, PageHeader, Select, StatusBadge, Table, Tabs, Td, Th, cx, useToast } from "@/components/ui";
import { api, useApi } from "@/lib/api";
import { ago, title } from "@/lib/format";

export default function Agents() {
  const me = useMe();
  const toast = useToast();
  const { data, mutate } = useApi<any>("/api/pap", { refreshInterval: 15000 });
  const [tab, setTab] = useState<"agents" | "sessions" | "log" | "manifest">("agents");
  const [edit, setEdit] = useState<any>(null);

  async function saveAgent() {
    try { await api("/api/pap/agents", { body: { ...edit, rate_limit_per_min: +edit.rate_limit_per_min } }); toast({ title: "Agent saved" }); setEdit(null); mutate(); }
    catch (e: any) { toast({ title: "Could not save", body: e.message, tone: "block" }); }
  }
  async function revoke(id: string) {
    await api(`/api/pap/sessions/${id}/revoke`, { method: "POST" }); toast({ title: "Access revoked", body: "The agent's token stops working immediately." }); mutate();
  }

  const actions = data?.actions || [];
  const refused = actions.filter((a: any) => !a.allowed).length;
  return (
    <>
      <PageHeader eyebrow="Trust" title="Outside agents"
        description="Customers' personal AI agents reach the business through a permissioned PAP route: guest sessions for read-only questions, signed-in sessions only after the customer consents and chooses read or write. Every action is logged with the agent, the scope and the consent behind it."
        actions={me?.role === "admin" && <Button variant="primary" icon={<Plus className="h-3.5 w-3.5" />} onClick={() => setEdit({ agent_identity: "agent://", display_name: "", status: "allow", rate_limit_per_min: 30 })}>Add agent</Button>} />
      <div className="grid gap-3 grid-cols-2 lg:grid-cols-4 mb-4">
        <Mini icon={Bot} label="Known agents" value={data?.agents.length} />
        <Mini icon={KeyRound} label="Active sessions" value={data?.sessions.filter((s: any) => !s.revoked_at).length} />
        <Mini icon={CheckCircle2} label="Actions logged" value={actions.length} />
        <Mini icon={Ban} label="Refused" value={refused} tone="block" />
      </div>
      <div className="rounded-xl border border-revise/30 bg-revise/5 px-4 py-3 text-[12.5px] text-muted mb-4">
        <b className="text-ink">PAP is a draft standard.</b> This gateway is a thin adapter mapped to the protocol's announced OAuth flow; it will be re-mapped against the v0.1 specification's endpoints.
      </div>
      <Tabs value={tab} onChange={setTab} tabs={[{ value: "agents", label: "Agents" }, { value: "sessions", label: "Sessions" }, { value: "log", label: "Action log" }, { value: "manifest", label: "Manifest" }]} />
      {!data ? <Card><LoadingRows /></Card> : tab === "agents" ? (
        <div className="grid gap-3 lg:grid-cols-3">
          {data.agents.map((a: any) => (
            <Card key={a.id} className="p-4">
              <div className="flex items-start gap-3">
                <span className={cx("h-10 w-10 rounded-xl grid place-items-center", a.status === "deny" ? "bg-block/10 text-block" : "bg-accent-soft text-accent")}><Bot className="h-5 w-5" /></span>
                <div className="min-w-0 flex-1"><div className="font-medium">{a.display_name}</div><div className="font-mono text-[11.5px] text-faint truncate">{a.agent_identity}</div></div>
                <Badge tone={a.status === "deny" ? "block" : "approve"} dot>{a.status === "deny" ? "denied" : "allowed"}</Badge>
              </div>
              <div className="flex items-center gap-4 mt-4 text-[12px] text-muted">
                <span className="inline-flex items-center gap-1"><Timer className="h-3.5 w-3.5" />{a.rate_limit_per_min}/min</span>
                <span>{a.actions} actions</span><span>{a.last_seen ? `seen ${ago(a.last_seen)}` : "never seen"}</span>
                {me?.role === "admin" && <Button size="sm" variant="ghost" className="ml-auto" onClick={() => setEdit({ ...a })}>Edit</Button>}
              </div>
            </Card>
          ))}
        </div>
      ) : tab === "sessions" ? (
        <Card><Table>
          <thead><tr><Th>Agent</Th><Th>Mode</Th><Th>Scopes</Th><Th>Customer</Th><Th>Consent</Th><Th align="right">Expires</Th><Th /></tr></thead>
          <tbody>{data.sessions.map((s: any) => (
            <tr key={s.id}>
              <Td className="font-mono text-[12px] max-w-[240px] truncate">{s.agent_identity}</Td>
              <Td><Badge tone={s.mode === "signed_in" ? "accent" : "neutral"}>{s.mode === "signed_in" ? "signed in" : "guest"}</Badge></Td>
              <Td><div className="flex gap-1">{s.scopes.map((x: string) => <Badge key={x} tone={x === "write" ? "revise" : "info"}>{x}</Badge>)}</div></Td>
              <Td className="text-muted">{s.email || "—"}</Td>
              <Td className="text-[12px] text-muted">{s.consent?.granted_at ? `${s.consent.method} · ${ago(s.consent.granted_at)}` : "—"}</Td>
              <Td align="right" className="text-muted">{s.revoked_at ? <Badge>revoked</Badge> : ago(s.expires_at)}</Td>
              <Td align="right">{!s.revoked_at && can(me, "builder") && <Button size="sm" variant="ghost" className="text-block" onClick={() => revoke(s.id)}>Revoke</Button>}</Td>
            </tr>
          ))}</tbody>
        </Table></Card>
      ) : tab === "log" ? (
        <Card><Table>
          <thead><tr><Th>When</Th><Th>Agent</Th><Th>Action</Th><Th>Scope</Th><Th>Result</Th></tr></thead>
          <tbody>{actions.map((a: any) => (
            <tr key={a.id}>
              <Td className="text-muted whitespace-nowrap">{ago(a.created_at)}</Td>
              <Td className="font-mono text-[12px] max-w-[220px] truncate">{a.agent_identity}</Td>
              <Td className="font-mono text-[12px]">{a.action}</Td>
              <Td><Badge>{a.scope_required}</Badge></Td>
              <Td><StatusBadge value={a.allowed ? "allow" : "refused"} label={title(a.outcome)} /></Td>
            </tr>
          ))}</tbody>
        </Table></Card>
      ) : (
        <Card className="p-5">
          <div className="flex items-center gap-2 mb-3 text-[13px]"><Globe className="h-4 w-4 text-faint" /> Published at <span className="font-mono text-[12px]">/pap/v1/{me?.tenant.slug}/.well-known/pap.json</span></div>
          <JsonView value={data.manifest} maxHeight={640} />
        </Card>
      )}
      <Dialog open={!!edit} onClose={() => setEdit(null)} title={edit?.id ? "Edit agent" : "Add agent"}
        footer={<><Button onClick={() => setEdit(null)}>Cancel</Button><Button variant="primary" onClick={saveAgent}>Save</Button></>}>
        {edit && <div className="space-y-3 text-ink">
          <Field label="Agent identity"><Input value={edit.agent_identity} disabled={!!edit.id} onChange={(e) => setEdit({ ...edit, agent_identity: e.target.value })} className="font-mono" /></Field>
          <Field label="Display name"><Input value={edit.display_name} onChange={(e) => setEdit({ ...edit, display_name: e.target.value })} /></Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Access"><Select value={edit.status} onChange={(e) => setEdit({ ...edit, status: e.target.value })}><option value="allow">Allow</option><option value="deny">Deny</option></Select></Field>
            <Field label="Rate limit / min"><Input type="number" value={edit.rate_limit_per_min} onChange={(e) => setEdit({ ...edit, rate_limit_per_min: e.target.value })} /></Field>
          </div>
        </div>}
      </Dialog>
    </>
  );
}

function Mini({ icon: Icon, label, value, tone }: { icon: React.ElementType; label: string; value?: number; tone?: string }) {
  return (
    <Card className="px-4 py-3 flex items-center gap-3">
      <span className={cx("h-8 w-8 rounded-lg grid place-items-center", tone ? `bg-${tone}/10 text-${tone}` : "bg-subtle text-muted")}><Icon className="h-4 w-4" /></span>
      <div><div className="text-[18px] font-semibold num leading-tight">{value ?? "·"}</div><div className="text-[12px] text-muted">{label}</div></div>
    </Card>
  );
}
