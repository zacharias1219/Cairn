"use client";

import {
  ArrowRight, BookOpen, Bot, Check, ClipboardCheck, Eraser, Flag, Lock, Scale, ScrollText, ShieldCheck, Sparkles, Store, Wrench,
} from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { CairnMark, Wordmark } from "@/components/brand";
import { cx } from "@/components/ui";

export default function Landing() {
  return (
    <div className="bg-bg text-ink overflow-x-hidden">
      <Nav />
      <Hero />
      <Gates />
      <Bets />
      <HowItWorks />
      <Principles />
      <Pricing />
      <Footer />
    </div>
  );
}

function Nav() {
  return (
    <header className="sticky top-0 z-40 border-b border-line/70 bg-bg/80 backdrop-blur-xl">
      <div className="max-w-6xl mx-auto px-4 sm:px-6 h-16 flex items-center gap-8">
        <Link href="/"><Wordmark /></Link>
        <nav className="hidden md:flex items-center gap-6 text-[13.5px] text-muted">
          <a href="#bets" className="hover:text-ink">Product</a>
          <a href="#how" className="hover:text-ink">How it works</a>
          <a href="#principles" className="hover:text-ink">Principles</a>
          <a href="#pricing" className="hover:text-ink">Pricing</a>
        </nav>
        <div className="ml-auto flex items-center gap-2">
          <Link href="/login" className="hidden sm:inline-flex h-9 items-center px-3 text-[13.5px] text-muted hover:text-ink">Sign in</Link>
          <Link href="/app" className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-ink text-bg px-3.5 text-[13.5px] font-medium hover:opacity-90">
            Open the console <ArrowRight className="h-3.5 w-3.5" />
          </Link>
        </div>
      </div>
    </header>
  );
}

function Hero() {
  return (
    <section className="relative">
      <div className="absolute inset-0 dotgrid opacity-50 [mask-image:radial-gradient(70%_60%_at_50%_0%,black,transparent)]" />
      <div className="relative max-w-6xl mx-auto px-4 sm:px-6 pt-16 sm:pt-24 pb-16 grid lg:grid-cols-[1.05fr_1fr] gap-12 items-center">
        <div className="animate-rise">
          <div className="inline-flex items-center gap-2 rounded-full border border-line bg-surface px-3 py-1 text-[12.5px] text-muted shadow-card">
            <span className="h-1.5 w-1.5 rounded-full bg-approve" /> Ready for the Personal Agent Protocol
          </div>
          <h1 className="font-display text-[56px] sm:text-[76px] leading-[0.98] tracking-[-0.025em] mt-6">
            Every agent<br />leaves a <em className="text-accent">trail.</em>
          </h1>
          <p className="text-[18px] text-muted mt-6 max-w-[34em] leading-relaxed">
            Cairn answers your customers, takes real actions in your systems, and keeps an audit record of every decision it
            makes. A supervisor checks every reply, hard rules guard every dollar, and memory forgets on command.
          </p>
          <div className="flex flex-wrap gap-3 mt-8">
            <Link href="/app" className="inline-flex h-11 items-center gap-2 rounded-xl bg-accent text-accent-ink px-5 font-medium shadow-pop hover:brightness-110 transition">
              Explore the console <ArrowRight className="h-4 w-4" />
            </Link>
            <a href="/demo/acme" className="inline-flex h-11 items-center gap-2 rounded-xl border border-line bg-surface px-5 font-medium hover:border-line-strong transition">
              <Store className="h-4 w-4" /> Try the demo store
            </a>
          </div>
          <div className="mt-6 text-[12.5px] text-faint">Demo sign-in: admin@acme.test · cairn-demo</div>
        </div>
        <HeroMock />
      </div>
    </section>
  );
}

function HeroMock() {
  const steps = [
    { icon: Sparkles, label: "Triage", detail: "refund_request · 92%", tone: "info" },
    { icon: Wrench, label: "lookup_order", detail: "A1004 · delivered 10 days ago", tone: "accent" },
    { icon: Scale, label: "Rule engine", detail: "refund_over_100 → needs approval", tone: "escalate" },
    { icon: ShieldCheck, label: "Supervisor", detail: "approve · every figure grounded", tone: "approve" },
    { icon: ClipboardCheck, label: "Approved by Jesse", detail: "issue_refund · idempotent", tone: "approve" },
  ];
  return (
    <div className="relative animate-rise [animation-delay:120ms]">
      <div className="absolute -inset-6 rounded-[32px] bg-gradient-to-br from-accent/15 via-transparent to-escalate/10 blur-2xl" />
      <div className="relative card shadow-pop overflow-hidden">
        <div className="flex items-center gap-1.5 px-4 h-10 border-b border-line bg-subtle/60">
          {["#ec6a5e", "#f4bf4f", "#61c554"].map((c) => <span key={c} className="h-2.5 w-2.5 rounded-full" style={{ background: c }} />)}
          <span className="ml-3 text-[11.5px] text-faint font-mono">cairn · conversation trail</span>
        </div>
        <div className="grid sm:grid-cols-[1fr_1.05fr]">
          <div className="p-4 space-y-3 bg-subtle/40 border-b sm:border-b-0 sm:border-r border-line">
            <div className="ml-auto max-w-[90%] rounded-2xl rounded-br-md bg-ink text-bg px-3 py-2 text-[12.5px]">I want a refund for my tent, order A1004</div>
            <div className="max-w-[92%] rounded-2xl rounded-bl-md bg-surface border border-line px-3 py-2 text-[12.5px]">I can refund $249.00 for order A1004 to your original payment method. Shall I go ahead?</div>
            <div className="ml-auto max-w-[60%] rounded-2xl rounded-br-md bg-ink text-bg px-3 py-2 text-[12.5px]">Yes please</div>
            <div className="max-w-[92%] rounded-2xl rounded-bl-md bg-surface border border-line px-3 py-2 text-[12.5px]">
              Done. I've issued a refund of $249.00. Your reference is RF-2188.
              <div className="flex items-center gap-1 mt-1.5 text-[10.5px] text-faint"><ShieldCheck className="h-3 w-3 text-approve" /> checked · approved by a person</div>
            </div>
          </div>
          <ol className="p-4 space-y-3 relative">
            <span className="absolute left-[29px] top-6 bottom-6 w-px bg-line" />
            {steps.map((s, i) => (
              <li key={s.label} className="relative flex gap-3 animate-rise" style={{ animationDelay: `${300 + i * 140}ms` }}>
                <span className={cx("h-7 w-7 rounded-full grid place-items-center border bg-surface shrink-0 z-10", `text-${s.tone}`, "border-line")}><s.icon className="h-3.5 w-3.5" /></span>
                <div className="min-w-0"><div className="text-[12.5px] font-medium">{s.label}</div><div className="text-[11.5px] text-muted font-mono truncate">{s.detail}</div></div>
              </li>
            ))}
          </ol>
        </div>
      </div>
    </div>
  );
}

function Gates() {
  const g = [
    ["100%", "of critical seeded failures stopped before release"],
    ["0", "hard-rule violations allowed to reach a customer"],
    ["≤ 4 s", "p95 reply latency, supervisor included"],
    ["72 h", "re-contact window before a resolution is billable"],
  ];
  return (
    <section className="border-y border-line bg-surface">
      <div className="max-w-6xl mx-auto px-4 sm:px-6 py-8 grid grid-cols-2 md:grid-cols-4 gap-6">
        {g.map(([n, l]) => (
          <div key={l}><div className="font-display text-[40px] leading-none">{n}</div><div className="text-[13px] text-muted mt-2 max-w-[22ch]">{l}</div></div>
        ))}
      </div>
      <div className="max-w-6xl mx-auto px-4 sm:px-6 pb-5 -mt-2 text-[11.5px] text-faint">Release gates enforced in CI on every change. Targets to validate in pilots, not measured customer results.</div>
    </section>
  );
}

function Bets() {
  const bets = [
    { icon: ShieldCheck, title: "A supervised loop with a full audit trail", body: "A second process reviews every drafted reply and proposed action: grounding, policy, tone, prompt injection, personal data. Rules for money and eligibility run in code. Every step is written to an append-only trail you can open, search and export.", points: ["Fail closed on timeouts", "Revise, block or escalate with a reason code", "One page explains why any reply was sent"] },
    { icon: Bot, title: "PAP as a native channel", body: "Customers increasingly arrive through their own AI agents. Cairn publishes what outside agents may do, starts guest sessions for questions, and lets agents act only after the customer consents and picks read or write scope.", points: ["Per-agent allow lists and rate limits", "Same supervisor and rules as any customer", "Every action logged with its consent record"] },
    { icon: Eraser, title: "Memory that forgets on command", body: "Cross-channel memory makes the second conversation better than the first, and it is built to be deleted. One request erases messages, summaries, facts, embeddings, traces and cached sessions, then issues a receipt.", points: ["Consent-gated, per workflow", "Export as JSON on request", "CI fails if a table could leave data behind"] },
  ];
  return (
    <section id="bets" className="max-w-6xl mx-auto px-4 sm:px-6 py-24">
      <div className="max-w-2xl">
        <div className="label">Three bets, and nothing more</div>
        <h2 className="font-display text-[44px] leading-[1.05] mt-3">The front door for customers, and for the agents they send.</h2>
      </div>
      <div className="grid md:grid-cols-3 gap-4 mt-12">
        {bets.map((b) => (
          <div key={b.title} className="card p-6 flex flex-col hover:shadow-pop transition-shadow duration-300">
            <span className="h-10 w-10 rounded-xl bg-accent-soft text-accent grid place-items-center"><b.icon className="h-5 w-5" /></span>
            <h3 className="text-[17px] font-semibold mt-5">{b.title}</h3>
            <p className="text-[13.5px] text-muted mt-2 leading-relaxed">{b.body}</p>
            <ul className="mt-5 space-y-2 text-[13px]">
              {b.points.map((p) => <li key={p} className="flex gap-2"><Check className="h-4 w-4 text-approve shrink-0 mt-0.5" />{p}</li>)}
            </ul>
          </div>
        ))}
      </div>
    </section>
  );
}

function HowItWorks() {
  const Box = ({ title, sub, className }: { title: string; sub?: string; className?: string }) => (
    <div className={cx("rounded-xl border border-line bg-surface px-3 py-2.5 text-center", className)}>
      <div className="text-[13px] font-medium">{title}</div>{sub && <div className="text-[11.5px] text-muted">{sub}</div>}
    </div>
  );
  const Down = () => <div className="flex justify-center"><span className="h-5 w-px bg-line-strong" /></div>;
  return (
    <section id="how" className="bg-surface border-y border-line">
      <div className="max-w-6xl mx-auto px-4 sm:px-6 py-24 grid lg:grid-cols-[1fr_1.2fr] gap-14 items-center">
        <div>
          <div className="label">How it works</div>
          <h2 className="font-display text-[44px] leading-[1.05] mt-3">Every reply is checked before it is sent.</h2>
          <p className="text-muted mt-5 leading-relaxed">A message enters through one gateway and becomes the same internal object whatever the channel. The orchestrator runs small, specialized steps and saves its state after each one, so a conversation can pause for a human approval and resume exactly where it stopped. Nothing leaves until the supervisor and the rule engine both agree.</p>
          <ul className="mt-6 space-y-3 text-[13.5px]">
            {[["One Python service, one Postgres, one queue", "Small enough for one engineer to run."], ["Row-level security on every table", "Tenants never touch, enforced by the database."], ["Models are rented, context is owned", "Swap the model per step without a code change."]].map(([a, b]) => (
              <li key={a} className="flex gap-3"><span className="mt-1.5 h-1.5 w-1.5 rounded-full bg-accent shrink-0" /><span><b className="font-medium">{a}.</b> <span className="text-muted">{b}</span></span></li>
            ))}
          </ul>
        </div>
        <div className="rounded-2xl border border-line bg-bg p-5 sm:p-6">
          <div className="grid grid-cols-3 gap-2.5"><Box title="Web chat" sub="one script tag" /><Box title="Email" sub="threaded, DKIM" /><Box title="PAP gateway" sub="outside agents" /></div>
          <Down />
          <Box title="Channel gateway" sub="one message format · tenant routing · auth" />
          <Down />
          <div className="rounded-xl border border-line bg-subtle/70 p-3">
            <div className="text-[11.5px] text-muted mb-2">Orchestrator · a state machine, checkpointed after every step</div>
            <div className="grid grid-cols-4 gap-1.5 text-[12px]">{["Triage", "Answer", "Act", "Confirm"].map((s) => <div key={s} className="rounded-lg border border-line bg-surface py-1.5 text-center">{s}</div>)}</div>
            <div className="grid grid-cols-2 gap-2 mt-2.5">
              <div className="rounded-lg border-2 border-accent/60 bg-accent-soft px-3 py-2 text-center"><div className="text-[13px] font-semibold text-accent">Supervisor</div><div className="text-[11px] text-muted">approve · revise · block · escalate</div></div>
              <div className="rounded-lg border border-line bg-surface px-3 py-2 text-center"><div className="text-[13px] font-semibold">Rule engine</div><div className="text-[11px] text-muted">limits · eligibility · no model</div></div>
            </div>
          </div>
          <Down />
          <div className="grid grid-cols-3 gap-2.5"><Box title="Knowledge" sub="cited answers" /><Box title="Memory" sub="erasable" /><Box title="Tools (MCP)" sub="risk tiers" /></div>
          <Down />
          <div className="rounded-xl bg-ink px-3 py-2.5 text-center">
            <div className="text-[13px] font-medium text-bg">PostgreSQL</div>
            <div className="text-[11.5px] text-bg/60">config · chats · vectors · checkpoints · the trail</div>
          </div>
        </div>
      </div>
    </section>
  );
}

function Principles() {
  const p = [
    ["Fail closed", "If a check cannot run, the agent does not act. A supervisor timeout means escalate, never send."],
    ["Rules in code, judgment in models", "Money limits, eligibility and consent are deterministic. Models never override a rule."],
    ["Every action leaves a trail", "No tool call, rule decision or verdict exists without a record a reviewer can open."],
    ["Forgetting is a feature", "A person can be deleted completely, including summaries and embeddings."],
    ["Tenants never touch", "Row-level security on every table from the first migration."],
    ["Rent the models, own the context", "Rules, memory and outcomes stay yours and stay exportable."],
    ["Quality gates speed", "A change that fails a critical evaluation does not ship, however urgent."],
    ["The smallest thing that works", "One agent loop, one database, one queue."],
  ];
  return (
    <section id="principles" className="max-w-6xl mx-auto px-4 sm:px-6 py-24">
      <div className="label">Product principles</div>
      <h2 className="font-display text-[44px] leading-[1.05] mt-3 max-w-2xl">Eight rules. When two conflict, the lower number wins.</h2>
      <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-px bg-line border border-line rounded-2xl overflow-hidden mt-12">
        {p.map(([t, b], i) => (
          <div key={t} className="bg-surface p-5">
            <div className="font-display text-[30px] text-accent leading-none">{i + 1}</div>
            <div className="font-semibold text-[14.5px] mt-3">{t}</div>
            <p className="text-[13px] text-muted mt-1.5 leading-relaxed">{b}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

function Pricing() {
  const [volume, setVolume] = useState(10000);
  const [rate, setRate] = useState(60);
  const plans = [
    { name: "Pilot", note: "90 days", fee: 1000, per: 1.25, includes: ["One workflow", "One channel", "One integration"] },
    { name: "Growth", fee: 2000, per: 1.0, includes: ["Up to five workflows", "Chat and email", "PAP gateway", "Three integrations"], featured: true },
    { name: "Scale", fee: null, per: null, includes: ["SSO", "Data residency", "Support commitments"] },
  ];
  const est = useMemo(() => {
    const res = Math.round((volume * rate) / 100);
    return { res, monthly: 2000 + res * 1.0 };
  }, [volume, rate]);
  return (
    <section id="pricing" className="bg-surface border-y border-line">
      <div className="max-w-6xl mx-auto px-4 sm:px-6 py-24">
        <div className="grid lg:grid-cols-[1fr_1fr] gap-12 items-end">
          <div>
            <div className="label">Pricing</div>
            <h2 className="font-display text-[44px] leading-[1.05] mt-3">A rate card you can model. Pay only for verified resolutions.</h2>
          </div>
          <p className="text-muted leading-relaxed">Escalated, abandoned and failed conversations are free. A resolution counts only after the re-contact window closes with no repeat contact and no negative signal, and you can open the evidence behind every charge. A monthly cap keeps it predictable.</p>
        </div>
        <div className="grid md:grid-cols-3 gap-4 mt-12">
          {plans.map((p) => (
            <div key={p.name} className={cx("rounded-2xl border p-6 flex flex-col", p.featured ? "border-accent bg-accent-soft/40 shadow-pop" : "border-line bg-bg")}>
              <div className="flex items-center gap-2"><span className="font-semibold text-[16px]">{p.name}</span>{p.note && <span className="text-[11.5px] text-muted border border-line rounded-full px-2">{p.note}</span>}{p.featured && <span className="text-[11.5px] text-accent border border-accent/30 rounded-full px-2">most teams</span>}</div>
              <div className="mt-5"><span className="font-display text-[44px] leading-none">{p.fee ? `$${p.fee.toLocaleString()}` : "Custom"}</span>{p.fee && <span className="text-muted text-[13px]"> / month</span>}</div>
              <div className="text-[13.5px] text-muted mt-1">{p.per ? `+ $${p.per.toFixed(2)} per verified resolution` : "Negotiated per resolution"}</div>
              <ul className="mt-6 space-y-2 text-[13.5px] flex-1">{p.includes.map((x) => <li key={x} className="flex gap-2"><Check className="h-4 w-4 text-approve mt-0.5" />{x}</li>)}</ul>
            </div>
          ))}
        </div>
        <div className="mt-6 rounded-2xl border border-line bg-bg p-6 grid md:grid-cols-[1fr_1fr_1.1fr] gap-6 items-center">
          <label className="block"><span className="text-[13px] text-muted">Conversations a month</span>
            <div className="font-semibold text-[22px] num mt-1">{volume.toLocaleString()}</div>
            <input type="range" min={2000} max={100000} step={1000} value={volume} onChange={(e) => setVolume(+e.target.value)} className="w-full accent-[rgb(var(--accent))]" />
          </label>
          <label className="block"><span className="text-[13px] text-muted">Verified resolution rate</span>
            <div className="font-semibold text-[22px] num mt-1">{rate}%</div>
            <input type="range" min={20} max={90} value={rate} onChange={(e) => setRate(+e.target.value)} className="w-full accent-[rgb(var(--accent))]" />
          </label>
          <div className="rounded-xl bg-ink text-bg p-5">
            <div className="text-[12px] opacity-60">Growth plan estimate</div>
            <div className="font-display text-[40px] leading-none mt-1">${est.monthly.toLocaleString()}<span className="text-[14px] opacity-60 font-sans"> / month</span></div>
            <div className="text-[12.5px] opacity-70 mt-2">{est.res.toLocaleString()} × $1.00 + $2,000 platform · ${(est.monthly * 12).toLocaleString()} a year</div>
          </div>
        </div>
        <p className="text-[11.5px] text-faint mt-3">Prices are hypotheses under test with design partners.</p>
      </div>
    </section>
  );
}

function Footer() {
  return (
    <footer className="max-w-6xl mx-auto px-4 sm:px-6 py-16">
      <div className="rounded-3xl bg-[#16302a] text-white p-10 sm:p-14 relative overflow-hidden">
        <div className="absolute -right-24 -bottom-24 h-80 w-80 rounded-full bg-[#2f5d50] blur-3xl opacity-70" />
        <div className="relative max-w-xl">
          <h2 className="font-display text-[44px] leading-[1.05]">A cairn marks the path for whoever walks it next.</h2>
          <p className="text-white/70 mt-4">Every conversation leaves a marker — memory, an audit record and a measured outcome — that the next conversation can follow.</p>
          <div className="flex flex-wrap gap-3 mt-8">
            <Link href="/app" className="inline-flex h-11 items-center gap-2 rounded-xl bg-white text-[#16302a] px-5 font-medium">Open the console <ArrowRight className="h-4 w-4" /></Link>
            <a href="/demo/acme" className="inline-flex h-11 items-center gap-2 rounded-xl border border-white/25 px-5 font-medium">Chat with the demo store</a>
          </div>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-4 mt-10 text-[12.5px] text-faint">
        <CairnMark className="h-5 w-5" /><span>Cairn · Every agent leaves a trail.</span>
        <span className="ml-auto flex gap-4"><span className="inline-flex items-center gap-1"><Lock className="h-3 w-3" /> No compliance claims without counsel review</span><span className="inline-flex items-center gap-1"><ScrollText className="h-3 w-3" /> Evaluation pack published with each release</span></span>
      </div>
    </footer>
  );
}
