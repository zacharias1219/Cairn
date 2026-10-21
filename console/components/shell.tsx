"use client";

import {
  Activity, BadgeCheck, BookOpenText, Bot, ChevronsUpDown, CircleDollarSign, ClipboardCheck, FlaskConical,
  Gauge, LogOut, MessagesSquare, Monitor, Moon, PanelLeft, Scale, Search, Settings, ShieldCheck, SlidersHorizontal,
  Sparkles, Store, Sun, UserRoundSearch, Wrench, ScrollText,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import React, { createContext, useContext, useEffect, useMemo, useRef, useState } from "react";

import { CairnMark } from "@/components/brand";
import { Avatar, Badge, Kbd, Menu, MenuItem, cx } from "@/components/ui";
import { api, useApi } from "@/lib/api";

export type Me = {
  tenant: { id: string; name: string; slug: string; plan: string; widget_key: string; settings: any };
  user: { id?: string; email?: string; name: string; role: string };
  role: "admin" | "builder" | "viewer";
  counts: { approvals: number; escalations: number };
  model_mode: "claude" | "sandbox";
};

const SessionCtx = createContext<Me | null>(null);
export const useMe = () => useContext(SessionCtx);
export const can = (me: Me | null, role: "viewer" | "builder" | "admin") =>
  !!me && ({ viewer: 0, builder: 1, admin: 2 }[me.role] >= { viewer: 0, builder: 1, admin: 2 }[role]);

type NavItem = { href: string; label: string; icon: React.ElementType; count?: keyof Me["counts"] };
const NAV: { group: string; items: NavItem[] }[] = [
  { group: "Monitor", items: [
    { href: "/app", label: "Overview", icon: Gauge },
    { href: "/app/conversations", label: "Conversations", icon: MessagesSquare, count: "escalations" },
    { href: "/app/approvals", label: "Approvals", icon: ClipboardCheck, count: "approvals" },
    { href: "/app/insights", label: "Insights", icon: Activity },
  ] },
  { group: "Build", items: [
    { href: "/app/playground", label: "Playground", icon: Sparkles },
    { href: "/app/config", label: "Agent config", icon: SlidersHorizontal },
    { href: "/app/rules", label: "Rules", icon: Scale },
    { href: "/app/tools", label: "Tools", icon: Wrench },
    { href: "/app/knowledge", label: "Knowledge", icon: BookOpenText },
    { href: "/app/evals", label: "Evaluations", icon: FlaskConical },
  ] },
  { group: "Trust", items: [
    { href: "/app/customers", label: "Customers & privacy", icon: UserRoundSearch },
    { href: "/app/agents", label: "Outside agents", icon: Bot },
    { href: "/app/outcomes", label: "Outcomes & billing", icon: CircleDollarSign },
    { href: "/app/audit", label: "Audit log", icon: ScrollText },
  ] },
];

function useTheme() {
  const [theme, setTheme] = useState<string>("light");
  useEffect(() => setTheme(document.documentElement.dataset.theme || "light"), []);
  const set = (t: string) => {
    const resolved = t === "system" ? (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light") : t;
    document.documentElement.dataset.theme = resolved;
    try { t === "system" ? localStorage.removeItem("cairn-theme") : localStorage.setItem("cairn-theme", t); } catch {}
    setTheme(resolved);
  };
  return { theme, set };
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const { data: me, error } = useApi<Me>("/api/auth/me", { refreshInterval: 15000 });
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [palette, setPalette] = useState(false);
  const pathname = usePathname();
  const router = useRouter();

  useEffect(() => {
    if (error && (error as any).status === 401) router.replace("/login?next=" + encodeURIComponent(pathname));
  }, [error, pathname, router]);
  useEffect(() => setMobileOpen(false), [pathname]);
  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setPalette((p) => !p); }
    };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, []);

  if (!me) {
    return (
      <div className="min-h-screen grid place-items-center">
        <div className="flex flex-col items-center gap-3 animate-fade-in">
          <CairnMark className="h-9 w-9 animate-pulse" />
          <div className="text-faint text-[12.5px]">Loading the trail…</div>
        </div>
      </div>
    );
  }

  return (
    <SessionCtx.Provider value={me}>
      <div className="min-h-screen flex">
        <Sidebar me={me} collapsed={collapsed} mobileOpen={mobileOpen} onClose={() => setMobileOpen(false)} onPalette={() => setPalette(true)} />
        <div className={cx("flex-1 min-w-0 transition-[padding] duration-200", collapsed ? "lg:pl-[68px]" : "lg:pl-[248px]")}>
          <Topbar me={me} onToggle={() => (window.innerWidth < 1024 ? setMobileOpen(true) : setCollapsed((c) => !c))} onPalette={() => setPalette(true)} />
          <main className="px-4 sm:px-6 lg:px-8 py-6 max-w-[1440px] mx-auto">{children}</main>
        </div>
      </div>
      {palette && <CommandPalette onClose={() => setPalette(false)} />}
    </SessionCtx.Provider>
  );
}

function Sidebar({ me, collapsed, mobileOpen, onClose, onPalette }: { me: Me; collapsed: boolean; mobileOpen: boolean; onClose: () => void; onPalette: () => void }) {
  const pathname = usePathname();
  return (
    <>
      {mobileOpen && <div className="fixed inset-0 z-30 bg-black/30 lg:hidden animate-fade-in" onClick={onClose} />}
      <aside className={cx(
        "fixed inset-y-0 left-0 z-40 flex flex-col border-r border-line bg-surface/80 backdrop-blur-xl transition-all duration-200",
        collapsed ? "lg:w-[68px]" : "lg:w-[248px]", "w-[264px]",
        mobileOpen ? "translate-x-0 shadow-pop" : "-translate-x-full lg:translate-x-0",
      )}>
        <div className={cx("h-14 flex items-center gap-2.5 px-4 border-b border-line shrink-0", collapsed && "lg:justify-center lg:px-0")}>
          <Link href="/app" className="flex items-center gap-2.5 min-w-0">
            <CairnMark />
            <span className={cx("font-display text-[22px] leading-none", collapsed && "lg:hidden")}>Cairn</span>
          </Link>
        </div>
        <div className={cx("px-3 pt-3", collapsed && "lg:hidden")}>
          <div className="flex items-center gap-2.5 rounded-lg border border-line bg-subtle/60 px-2.5 py-2">
            <span className="h-6 w-6 rounded-md grid place-items-center text-[11px] font-bold text-white" style={{ background: "linear-gradient(135deg,#7a5c3e,#c9a27a)" }}>
              {me.tenant.name[0]}
            </span>
            <div className="min-w-0 flex-1">
              <div className="text-[12.5px] font-semibold truncate">{me.tenant.name}</div>
              <div className="text-[11px] text-faint capitalize">{me.tenant.plan} plan · {me.role}</div>
            </div>
            <ChevronsUpDown className="h-3.5 w-3.5 text-faint" />
          </div>
          <button onClick={onPalette} className="mt-2 w-full flex items-center gap-2 rounded-lg border border-line px-2.5 h-8 text-[12.5px] text-faint hover:text-muted hover:border-line-strong transition-colors">
            <Search className="h-3.5 w-3.5" /> Search or jump to…
            <span className="ml-auto flex gap-0.5"><Kbd>⌘</Kbd><Kbd>K</Kbd></span>
          </button>
        </div>
        <nav className="flex-1 overflow-y-auto px-3 py-3 space-y-5">
          {NAV.map((g) => (
            <div key={g.group}>
              <div className={cx("label px-2 mb-1.5", collapsed && "lg:hidden")}>{g.group}</div>
              <ul className="space-y-0.5">
                {g.items.map((it) => {
                  const active = it.href === "/app" ? pathname === "/app" : pathname.startsWith(it.href);
                  const n = it.count ? me.counts[it.count] : 0;
                  return (
                    <li key={it.href}>
                      <Link href={it.href} title={it.label}
                        className={cx("group relative flex items-center gap-2.5 rounded-lg px-2.5 h-8 text-[13px] transition-colors",
                          collapsed && "lg:justify-center lg:px-0",
                          active ? "bg-accent-soft text-accent font-medium" : "text-muted hover:text-ink hover:bg-subtle")}>
                        <it.icon className="h-[16px] w-[16px] shrink-0" strokeWidth={active ? 2.1 : 1.8} />
                        <span className={cx("truncate", collapsed && "lg:hidden")}>{it.label}</span>
                        {n > 0 && (
                          <span className={cx("ml-auto rounded-full px-1.5 text-[10.5px] font-semibold num leading-[17px]",
                            it.count === "approvals" ? "bg-revise text-white" : "bg-escalate/15 text-escalate",
                            collapsed && "lg:absolute lg:top-0.5 lg:right-1 lg:px-1")}>{n}</span>
                        )}
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
        </nav>
        <div className={cx("border-t border-line p-3 space-y-0.5", collapsed && "lg:px-2")}>
          <Link href="/app/settings" className={cx("flex items-center gap-2.5 rounded-lg px-2.5 h-8 text-[13px] text-muted hover:text-ink hover:bg-subtle", collapsed && "lg:justify-center", pathname.startsWith("/app/settings") && "bg-accent-soft text-accent")}>
            <Settings className="h-4 w-4" /><span className={cx(collapsed && "lg:hidden")}>Settings</span>
          </Link>
          <a href={`/demo/${me.tenant.slug}`} target="_blank" className={cx("flex items-center gap-2.5 rounded-lg px-2.5 h-8 text-[13px] text-muted hover:text-ink hover:bg-subtle", collapsed && "lg:justify-center")}>
            <Store className="h-4 w-4" /><span className={cx(collapsed && "lg:hidden")}>Open demo store</span>
          </a>
        </div>
      </aside>
    </>
  );
}

function Topbar({ me, onToggle, onPalette }: { me: Me; onToggle: () => void; onPalette: () => void }) {
  const { theme, set } = useTheme();
  const router = useRouter();
  return (
    <header className="sticky top-0 z-20 h-14 flex items-center gap-3 px-4 sm:px-6 lg:px-8 border-b border-line bg-bg/80 backdrop-blur-xl">
      <button onClick={onToggle} className="h-8 w-8 grid place-items-center rounded-lg text-muted hover:bg-subtle hover:text-ink" aria-label="Toggle sidebar">
        <PanelLeft className="h-4 w-4" />
      </button>
      <div className="flex-1" />
      <button onClick={onPalette} className="sm:hidden h-8 w-8 grid place-items-center rounded-lg text-muted hover:bg-subtle" aria-label="Search"><Search className="h-4 w-4" /></button>
      {me.model_mode === "sandbox" ? (
        <Badge tone="revise" dot className="hidden sm:inline-flex">Sandbox models</Badge>
      ) : (
        <Badge tone="approve" dot className="hidden sm:inline-flex">Claude live</Badge>
      )}
      <Badge tone="accent" className="hidden md:inline-flex"><ShieldCheck className="h-3 w-3" /> Supervisor on</Badge>
      <Menu trigger={
        <button className="h-8 w-8 grid place-items-center rounded-lg text-muted hover:bg-subtle hover:text-ink" aria-label="Theme">
          {theme === "dark" ? <Moon className="h-4 w-4" /> : <Sun className="h-4 w-4" />}
        </button>
      }>
        <MenuItem icon={<Sun className="h-4 w-4" />} onClick={() => set("light")}>Light</MenuItem>
        <MenuItem icon={<Moon className="h-4 w-4" />} onClick={() => set("dark")}>Dark</MenuItem>
        <MenuItem icon={<Monitor className="h-4 w-4" />} onClick={() => set("system")}>System</MenuItem>
      </Menu>
      <Menu trigger={
        <button className="flex items-center gap-2 rounded-full pl-0.5 pr-2 h-8 hover:bg-subtle" aria-label="Account">
          <Avatar name={me.user.name} />
          <span className="hidden md:block text-[13px] font-medium">{me.user.name}</span>
        </button>
      }>
        <div className="px-2.5 py-2 border-b border-line mb-1">
          <div className="text-[13px] font-medium">{me.user.name}</div>
          <div className="text-[12px] text-faint">{me.user.email} · <span className="capitalize">{me.role}</span></div>
        </div>
        <MenuItem icon={<Settings className="h-4 w-4" />} onClick={() => router.push("/app/settings")}>Settings</MenuItem>
        <MenuItem icon={<BadgeCheck className="h-4 w-4" />} onClick={() => router.push("/")}>Product site</MenuItem>
        <MenuItem icon={<LogOut className="h-4 w-4" />} onClick={async () => { await api("/api/auth/logout", { method: "POST" }); router.push("/login"); }}>Sign out</MenuItem>
      </Menu>
    </header>
  );
}

function CommandPalette({ onClose }: { onClose: () => void }) {
  const [q, setQ] = useState("");
  const [i, setI] = useState(0);
  const router = useRouter();
  const input = useRef<HTMLInputElement>(null);
  const { data } = useApi<{ items: any[] }>(q.length > 1 ? `/api/conversations?q=${encodeURIComponent(q)}&limit=6` : null);
  useEffect(() => input.current?.focus(), []);
  const items = useMemo(() => {
    const pages = NAV.flatMap((g) => g.items).concat([{ href: "/app/settings", label: "Settings", icon: Settings }])
      .filter((p) => p.label.toLowerCase().includes(q.toLowerCase()))
      .map((p) => ({ key: p.href, label: p.label, hint: "Page", icon: p.icon, go: () => router.push(p.href) }));
    const convs = (data?.items || []).map((c) => ({
      key: c.id, label: c.first_message || c.intent || c.id, hint: c.email || c.channel, icon: MessagesSquare,
      go: () => router.push(`/app/conversations/${c.id}`),
    }));
    return [...pages, ...convs];
  }, [q, data, router]);
  const run = (n: number) => { items[n]?.go(); onClose(); };
  return (
    <div className="fixed inset-0 z-[70] flex items-start justify-center pt-[12vh] px-4">
      <div className="absolute inset-0 bg-black/30 backdrop-blur-[2px] animate-fade-in" onClick={onClose} />
      <div className="relative w-full max-w-[560px] card shadow-pop overflow-hidden animate-rise">
        <div className="flex items-center gap-2.5 px-4 border-b border-line">
          <Search className="h-4 w-4 text-faint" />
          <input ref={input} value={q} onChange={(e) => { setQ(e.target.value); setI(0); }}
            onKeyDown={(e) => {
              if (e.key === "Escape") onClose();
              if (e.key === "ArrowDown") { e.preventDefault(); setI((x) => Math.min(items.length - 1, x + 1)); }
              if (e.key === "ArrowUp") { e.preventDefault(); setI((x) => Math.max(0, x - 1)); }
              if (e.key === "Enter") run(i);
            }}
            placeholder="Jump to a page, or search conversations…" className="flex-1 h-12 bg-transparent outline-none text-[14px] placeholder:text-faint" />
          <Kbd>Esc</Kbd>
        </div>
        <ul className="max-h-[380px] overflow-y-auto p-1.5">
          {items.length === 0 && <li className="px-3 py-6 text-center text-faint text-[13px]">No matches</li>}
          {items.map((it, n) => (
            <li key={it.key}>
              <button onMouseEnter={() => setI(n)} onClick={() => run(n)}
                className={cx("w-full flex items-center gap-3 rounded-lg px-3 py-2 text-left", n === i ? "bg-subtle" : "")}>
                <it.icon className="h-4 w-4 text-faint shrink-0" />
                <span className="truncate text-[13.5px]">{it.label}</span>
                <span className="ml-auto text-[11.5px] text-faint shrink-0">{it.hint}</span>
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
