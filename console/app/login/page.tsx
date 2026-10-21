"use client";

import { ArrowRight } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { Wordmark } from "@/components/brand";
import { TrailArt } from "@/components/trail-art";
import { Button, Field, Input } from "@/components/ui";
import { api } from "@/lib/api";

const DEMO = [
  { email: "admin@acme.test", role: "Admin", who: "Riley Morgan" },
  { email: "builder@acme.test", role: "Builder", who: "Jesse Alvarez" },
  { email: "viewer@acme.test", role: "Viewer", who: "Casey Nguyen" },
];

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const [email, setEmail] = useState("admin@acme.test");
  const [password, setPassword] = useState("cairn-demo");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api("/api/auth/login", { body: { email, password } });
      router.push(params.get("next") || "/app");
    } catch (err: any) {
      setError(err.message || "Sign in failed");
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="w-full max-w-[360px] animate-rise">
      <Link href="/"><Wordmark /></Link>
      <h1 className="font-display text-[40px] leading-[1.05] mt-10">Welcome back.</h1>
      <p className="text-muted mt-2">Sign in to review your agent's trail.</p>
      <div className="mt-8 space-y-4">
        <Field label="Work email"><Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" required /></Field>
        <Field label="Password"><Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required /></Field>
        {error && <div className="text-block text-[13px] rounded-lg bg-block/10 border border-block/20 px-3 py-2">{error}</div>}
        <Button variant="primary" size="lg" className="w-full" loading={busy} type="submit">
          Sign in <ArrowRight className="h-4 w-4" />
        </Button>
      </div>
      <div className="mt-8 rounded-xl border border-dashed border-line-strong p-3">
        <div className="label mb-2">Demo workspace · password cairn-demo</div>
        <div className="flex gap-1.5">
          {DEMO.map((d) => (
            <button type="button" key={d.email} onClick={() => { setEmail(d.email); setPassword("cairn-demo"); }}
              className={`flex-1 rounded-lg border px-2 py-1.5 text-left transition-colors ${email === d.email ? "border-accent bg-accent-soft" : "border-line hover:border-line-strong"}`}>
              <div className="text-[12px] font-medium">{d.role}</div>
              <div className="text-[11px] text-faint truncate">{d.who}</div>
            </button>
          ))}
        </div>
      </div>
    </form>
  );
}

export default function LoginPage() {
  return (
    <div className="min-h-screen grid lg:grid-cols-[1fr_1.05fr]">
      <div className="flex items-center justify-center px-6 py-12">
        <Suspense><LoginForm /></Suspense>
      </div>
      <div className="hidden lg:flex relative overflow-hidden bg-[#16302a] text-white p-14 flex-col justify-between">
        <div className="absolute inset-0 opacity-[.18]" style={{ backgroundImage: "radial-gradient(rgba(255,255,255,.5) 1px, transparent 1px)", backgroundSize: "22px 22px" }} />
        <div className="absolute -right-40 -top-40 h-[520px] w-[520px] rounded-full bg-[#2f5d50] blur-3xl opacity-70" />
        <div className="relative">
          <div className="text-white/60 text-[12px] uppercase tracking-[.14em]">Every agent leaves a trail</div>
          <h2 className="font-display text-[46px] leading-[1.04] mt-3 max-w-[13ch]">Nothing reaches a customer unchecked.</h2>
        </div>
        <TrailArt className="relative max-w-sm" />
        <p className="relative text-white/60 text-[13px] max-w-md">
          A supervisor reviews every drafted reply, a rule engine enforces money and policy in code, and every
          decision is written to an append-only trail you can open, search and export.
        </p>
      </div>
    </div>
  );
}
