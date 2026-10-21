"use client";

import { Eye, KeyRound, Lock, PenLine, Plug, Server } from "lucide-react";
import { useState } from "react";

import { can, useMe } from "@/components/shell";
import { Badge, Button, Card, CardHeader, Dialog, Drawer, Input, JsonView, LoadingRows, PageHeader, Segmented, StatusBadge, Switch, Table, Td, Th, cx, useToast } from "@/components/ui";
import { api, useApi } from "@/lib/api";
import { ago, ms } from "@/lib/format";

export default function Tools() {
  const me = useMe();
  const toast = useToast();
  const { data, mutate } = useApi<any>("/api/tools", { refreshInterval: 15000 });
  const [schema, setSchema] = useState<any>(null);
  const [cred, setCred] = useState<string | null>(null);
  const [secret, setSecret] = useState("");
  const editable = can(me, "builder");

  async function patch(name: string, body: any) {
    try { await api(`/api/tools/${name}`, { method: "PATCH", body }); mutate(); toast({ title: "Tool updated", body: name }); }
    catch (e: any) { toast({ title: "Update failed", body: e.message, tone: "block" }); }
  }
  async function saveCred() {
    try { await api(`/api/tools/${cred}/credential`, { method: "PUT", body: { secret } }); toast({ title: "Credential stored", body: "Encrypted with a per-tenant data key. It never appears in logs or traces." }); setCred(null); setSecret(""); mutate(); }
    catch (e: any) { toast({ title: "Could not store credential", body: e.message, tone: "block" }); }
  }

  return (
    <>
      <PageHeader eyebrow="Build" title="Tools"
        description="Every external action is an MCP tool with a strict schema and a risk tier. High-tier calls wait for a person. Every write carries an idempotency key, so a retry never acts twice." />
      <Card className="p-4 mb-4 flex flex-wrap items-center gap-4">
        <div className="h-10 w-10 rounded-xl bg-accent-soft text-accent grid place-items-center"><Server className="h-5 w-5" /></div>
        <div className="min-w-0 flex-1">
          <div className="font-medium">Acme Commerce <Badge tone="revise" className="ml-1">sandbox</Badge></div>
          <div className="text-[12.5px] text-muted">MCP server · <span className="font-mono">sandbox://commerce</span> · also reachable at <span className="font-mono">/sandbox/mcp/commerce</span> for demos and tests</div>
        </div>
        <Badge tone="approve" dot>connected</Badge>
      </Card>
      {!data ? <Card><LoadingRows /></Card> : (
        <div className="grid gap-3 lg:grid-cols-2">
          {data.items.map((t: any) => (
            <Card key={t.name} className={cx("p-4 flex flex-col gap-3", !t.enabled && "opacity-60")}>
              <div className="flex items-start gap-3">
                <span className={cx("h-9 w-9 rounded-lg grid place-items-center shrink-0", t.is_write ? "bg-revise/10 text-revise" : "bg-info/10 text-info")}>
                  {t.is_write ? <PenLine className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2"><span className="font-medium">{t.title}</span><span className="font-mono text-[11.5px] text-faint">{t.name}</span></div>
                  <div className="text-[12.5px] text-muted">{t.description}</div>
                </div>
                <Switch checked={t.enabled} disabled={!editable} onChange={(v) => patch(t.name, { enabled: v })} label="Enabled" />
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-[12px] text-muted">Risk</span>
                <Segmented size="sm" value={t.risk_tier} onChange={(v) => editable && patch(t.name, { risk_tier: v })}
                  options={[{ value: "low", label: "Low" }, { value: "medium", label: "Medium" }, { value: "high", label: "High" }]} />
                {t.risk_tier === "high" && <Badge tone="block"><Lock className="h-3 w-3" /> always needs approval</Badge>}
                <label className="ml-auto flex items-center gap-1.5 text-[12px] text-muted"><Switch checked={t.pap_exposed} disabled={!editable} onChange={(v) => patch(t.name, { pap_exposed: v })} label="Offer to outside agents" /> Outside agents</label>
              </div>
              <div className="flex items-center gap-4 text-[12px] text-muted border-t border-line pt-3">
                <span><b className="text-ink num">{t.calls}</b> calls</span>
                <span><b className="text-ink num">{t.calls ? Math.round((t.succeeded / t.calls) * 100) : 0}%</b> succeeded</span>
                <span>{t.avg_latency_ms != null ? ms(t.avg_latency_ms) : "—"} avg</span>
                <div className="ml-auto flex gap-1">
                  <Button size="sm" variant="ghost" onClick={() => setSchema(t)}>Schemas</Button>
                  {me?.role === "admin" && <Button size="sm" variant="ghost" icon={<KeyRound className="h-3.5 w-3.5" />} onClick={() => setCred(t.name)}>{t.has_credential ? "Rotate" : "Credential"}</Button>}
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}
      <Card className="mt-4">
        <CardHeader title="Recent tool calls" subtitle="Input, output, status and approver are recorded for every call." />
        <Table>
          <thead><tr><Th>Tool</Th><Th>Status</Th><Th>Risk</Th><Th>Approver</Th><Th align="right">Latency</Th><Th align="right">When</Th></tr></thead>
          <tbody>
            {(data?.recent || []).map((c: any) => (
              <tr key={c.id} className="hover:bg-subtle/60">
                <Td><a className="font-mono text-[12.5px] link" href={c.conversation_id ? `/app/conversations/${c.conversation_id}` : undefined}>{c.tool_name}</a></Td>
                <Td><StatusBadge value={c.status} /></Td>
                <Td><Badge>{c.risk_tier}</Badge></Td>
                <Td className="text-muted">{c.approver_label || "—"}</Td>
                <Td align="right" className="text-muted">{c.latency_ms != null ? ms(c.latency_ms) : "—"}</Td>
                <Td align="right" className="text-muted">{ago(c.created_at)}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Card>
      <Drawer open={!!schema} onClose={() => setSchema(null)} title={schema?.title} subtitle="Strict input and output schemas, enforced on every call whatever the model asked for.">
        {schema && <div className="space-y-4"><div><div className="label mb-2">Input schema</div><JsonView value={schema.input_schema} /></div><div><div className="label mb-2">Output schema</div><JsonView value={schema.output_schema} /></div></div>}
      </Drawer>
      <Dialog open={!!cred} onClose={() => setCred(null)} title={`Credential for ${cred}`}
        footer={<><Button onClick={() => setCred(null)}>Cancel</Button><Button variant="primary" onClick={saveCred} disabled={secret.length < 4}>Store encrypted</Button></>}>
        <p className="mb-3">Stored with envelope encryption: a fresh data key per secret, wrapped by the master key with this tenant as associated data.</p>
        <Input type="password" value={secret} onChange={(e) => setSecret(e.target.value)} placeholder="API token" />
      </Dialog>
    </>
  );
}
