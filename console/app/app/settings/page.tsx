"use client";

import { Code2, KeyRound, Plus, Users } from "lucide-react";
import { useState } from "react";

import { useMe } from "@/components/shell";
import { Avatar, Badge, Button, Card, CardHeader, CopyButton, Dialog, Field, Input, LoadingRows, PageHeader, Select, Table, Td, Th, useToast } from "@/components/ui";
import { api, useApi } from "@/lib/api";
import { ago, money } from "@/lib/format";

export default function Settings() {
  const me = useMe();
  const toast = useToast();
  const admin = me?.role === "admin";
  const { data, mutate } = useApi<any>("/api/settings");
  const [invite, setInvite] = useState<any>(null);
  const [keyDlg, setKeyDlg] = useState<any>(null);
  const [newKey, setNewKey] = useState<string | null>(null);
  const [retention, setRetention] = useState<string>("");
  const [cap, setCap] = useState<string>("");

  async function role(uid: string, r: string) {
    try { await api(`/api/users/${uid}`, { method: "PATCH", body: { role: r } }); toast({ title: "Role changed", body: "Recorded in the audit log." }); mutate(); }
    catch (e: any) { toast({ title: "Could not change role", body: e.message, tone: "block" }); }
  }
  async function addUser() {
    try { await api("/api/users", { body: invite }); toast({ title: "Teammate added" }); setInvite(null); mutate(); }
    catch (e: any) { toast({ title: "Could not add", body: e.message, tone: "block" }); }
  }
  async function createKey() {
    try { const r = await api("/api/api-keys", { body: keyDlg }); setNewKey(r.key); setKeyDlg(null); mutate(); }
    catch (e: any) { toast({ title: "Could not create key", body: e.message, tone: "block" }); }
  }
  async function revokeKey(id: string) { await api(`/api/api-keys/${id}`, { method: "DELETE" }); toast({ title: "Key revoked" }); mutate(); }
  async function saveTenant() {
    const body: any = {};
    if (retention) body.retention_days = +retention;
    if (cap) body.monthly_cap_usd = +cap;
    await api("/api/settings", { method: "PATCH", body }); toast({ title: "Settings saved" }); mutate();
  }

  if (!data) return <LoadingRows />;
  const t = data.tenant;
  const origin = typeof window !== "undefined" ? window.location.origin : "";
  const snippet = `<script>
  window.CairnSettings = {
    key: "${t.widget_key}",
    api: "${origin}",
    // Optional: vouch for a signed-in customer (HMAC-SHA256 of their email
    // with your identity secret, computed on your server).
    customer: { email: user.email, name: user.name, signature: user.cairnSignature }
  };
</script>
<script src="${origin}/widget.js" async></script>`;

  return (
    <>
      <PageHeader eyebrow="Workspace" title="Settings" description="Team, keys, data retention and the one script tag that puts the agent on your site." />
      <div className="grid gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader title="Install the chat widget" subtitle="One script tag. Streams replies, resumes after a reload, under 60 KB gzipped." action={<CopyButton value={snippet} />} />
          <pre className="code mx-5 mb-5 p-3 rounded-lg bg-subtle border border-line overflow-x-auto">{snippet}</pre>
        </Card>
        <Card>
          <CardHeader title="Workspace" />
          <div className="px-5 pb-5 space-y-4">
            <div className="grid grid-cols-2 gap-3 text-[13px]">
              <div><div className="label">Name</div>{t.name}</div><div><div className="label">Slug</div><span className="font-mono">{t.slug}</span></div>
              <div><div className="label">Plan</div><span className="capitalize">{t.plan}</span></div><div><div className="label">Region</div>{t.settings?.region || "us-east"}</div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Trace retention (days)" hint={`Currently ${t.settings?.retention_days ?? 365}`}><Input type="number" disabled={!admin} placeholder={String(t.settings?.retention_days ?? 365)} value={retention} onChange={(e) => setRetention(e.target.value)} /></Field>
              <Field label="Monthly spending cap (USD)" hint={t.settings?.monthly_cap_usd ? `Currently ${money(t.settings.monthly_cap_usd, 0)}` : "No cap"}><Input type="number" disabled={!admin} value={cap} onChange={(e) => setCap(e.target.value)} placeholder="none" /></Field>
            </div>
            {admin && <Button onClick={saveTenant} disabled={!retention && !cap}>Save</Button>}
          </div>
        </Card>
        <Card>
          <CardHeader title="Team" subtitle="Admins manage people and keys; builders change the agent; viewers read." action={admin && <Button size="sm" icon={<Plus className="h-3.5 w-3.5" />} onClick={() => setInvite({ email: "", name: "", role: "viewer", password: "" })}>Add</Button>} />
          <Table>
            <tbody>{data.users.map((u: any) => (
              <tr key={u.id}>
                <Td><div className="flex items-center gap-2.5"><Avatar name={u.name} /><div><div className="font-medium">{u.name}</div><div className="text-[11.5px] text-faint">{u.email}</div></div></div></Td>
                <Td className="text-muted text-[12px]">{u.last_login_at ? `active ${ago(u.last_login_at)}` : "never signed in"}</Td>
                <Td align="right">
                  {admin && u.id !== me?.user.id ? (
                    <Select value={u.role} onChange={(e) => role(u.id, e.target.value)} className="w-[120px] ml-auto"><option value="admin">Admin</option><option value="builder">Builder</option><option value="viewer">Viewer</option></Select>
                  ) : <Badge tone="accent" className="capitalize">{u.role}</Badge>}
                </Td>
              </tr>
            ))}</tbody>
          </Table>
        </Card>
        <Card>
          <CardHeader title="API keys" subtitle="Narrow scopes per key. Only a hash is stored." action={admin && <Button size="sm" icon={<KeyRound className="h-3.5 w-3.5" />} onClick={() => setKeyDlg({ name: "", scopes: ["read"] })}>New key</Button>} />
          {data.api_keys.length === 0 ? <div className="px-5 pb-5 text-[13px] text-muted">No keys yet. Inbound email needs a key with the <span className="font-mono">email:inbound</span> scope.</div> : (
            <Table><tbody>{data.api_keys.map((k: any) => (
              <tr key={k.id}>
                <Td><div className="font-medium">{k.name}</div><div className="font-mono text-[11.5px] text-faint">{k.prefix}…</div></Td>
                <Td><div className="flex gap-1">{k.scopes.map((s: string) => <Badge key={s}>{s}</Badge>)}</div></Td>
                <Td align="right">{k.revoked_at ? <Badge>revoked</Badge> : admin && <Button size="sm" variant="ghost" className="text-block" onClick={() => revokeKey(k.id)}>Revoke</Button>}</Td>
              </tr>
            ))}</tbody></Table>
          )}
        </Card>
      </div>
      <Dialog open={!!invite} onClose={() => setInvite(null)} title="Add a teammate" footer={<><Button onClick={() => setInvite(null)}>Cancel</Button><Button variant="primary" onClick={addUser}>Add</Button></>}>
        {invite && <div className="space-y-3 text-ink">
          <Field label="Name"><Input value={invite.name} onChange={(e) => setInvite({ ...invite, name: e.target.value })} /></Field>
          <Field label="Email"><Input value={invite.email} onChange={(e) => setInvite({ ...invite, email: e.target.value })} /></Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Role"><Select value={invite.role} onChange={(e) => setInvite({ ...invite, role: e.target.value })}><option value="viewer">Viewer</option><option value="builder">Builder</option><option value="admin">Admin</option></Select></Field>
            <Field label="Temporary password"><Input type="password" value={invite.password} onChange={(e) => setInvite({ ...invite, password: e.target.value })} /></Field>
          </div>
        </div>}
      </Dialog>
      <Dialog open={!!keyDlg} onClose={() => setKeyDlg(null)} title="Create an API key" footer={<><Button onClick={() => setKeyDlg(null)}>Cancel</Button><Button variant="primary" onClick={createKey} disabled={!keyDlg?.name}>Create</Button></>}>
        {keyDlg && <div className="space-y-3 text-ink">
          <Field label="Name"><Input value={keyDlg.name} onChange={(e) => setKeyDlg({ ...keyDlg, name: e.target.value })} placeholder="Inbound email" /></Field>
          <div className="flex flex-wrap gap-2">{["read", "write", "admin", "email:inbound", "chat"].map((s) => (
            <label key={s} className="flex items-center gap-1.5 text-[12.5px] rounded-lg border border-line px-2 py-1 cursor-pointer">
              <input type="checkbox" checked={keyDlg.scopes.includes(s)} onChange={(e) => setKeyDlg({ ...keyDlg, scopes: e.target.checked ? [...keyDlg.scopes, s] : keyDlg.scopes.filter((x: string) => x !== s) })} />{s}
            </label>
          ))}</div>
        </div>}
      </Dialog>
      <Dialog open={!!newKey} onClose={() => setNewKey(null)} title="Copy your key now" footer={<Button variant="primary" onClick={() => setNewKey(null)}>Done</Button>}>
        It is shown once. Only a hash is stored.
        <div className="mt-3 flex items-center gap-2 rounded-lg bg-subtle border border-line px-3 py-2 font-mono text-[12.5px] text-ink break-all">{newKey}<CopyButton value={newKey || ""} /></div>
      </Dialog>
    </>
  );
}
