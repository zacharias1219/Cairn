"use client";

import clsx from "clsx";
import { Check, ChevronDown, Copy, Loader2, X } from "lucide-react";
import React, { createContext, useCallback, useContext, useEffect, useId, useRef, useState } from "react";

export const cx = clsx;

/* ------------------------------------------------------------------ Button */

type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger" | "subtle";
  size?: "sm" | "md" | "lg" | "icon";
  loading?: boolean;
  icon?: React.ReactNode;
};

export function Button({ variant = "secondary", size = "md", loading, icon, className, children, disabled, ...rest }: ButtonProps) {
  return (
    <button
      {...rest}
      disabled={disabled || loading}
      className={cx(
        "inline-flex items-center justify-center gap-1.5 font-medium whitespace-nowrap select-none transition-all duration-150",
        "disabled:opacity-50 disabled:pointer-events-none active:scale-[.98]",
        {
          sm: "h-7 px-2.5 text-[12.5px] rounded-md",
          md: "h-8.5 h-[34px] px-3 text-[13px] rounded-lg",
          lg: "h-10 px-4 text-[14px] rounded-lg",
          icon: "h-8 w-8 rounded-lg",
        }[size],
        {
          primary: "bg-accent text-accent-ink hover:brightness-110 shadow-[inset_0_1px_0_rgb(255_255_255/.12),0_1px_2px_rgb(0_0_0/.12)]",
          secondary: "bg-surface text-ink border border-line hover:border-line-strong hover:bg-subtle shadow-card",
          ghost: "text-muted hover:text-ink hover:bg-subtle",
          subtle: "bg-subtle text-ink hover:bg-sunken",
          danger: "bg-block text-white hover:brightness-110",
        }[variant],
        className,
      )}
    >
      {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : icon}
      {children}
    </button>
  );
}

/* ------------------------------------------------------------------- Badge */

const TONES = {
  neutral: "bg-subtle text-muted border-line",
  accent: "bg-accent-soft text-accent border-accent/20",
  approve: "bg-approve/10 text-approve border-approve/20",
  revise: "bg-revise/10 text-revise border-revise/25",
  block: "bg-block/10 text-block border-block/20",
  escalate: "bg-escalate/10 text-escalate border-escalate/20",
  info: "bg-info/10 text-info border-info/20",
} as const;
export type Tone = keyof typeof TONES;

export function Badge({ tone = "neutral", dot, children, className }: { tone?: Tone; dot?: boolean; children: React.ReactNode; className?: string }) {
  return (
    <span className={cx("inline-flex items-center gap-1 rounded-full border px-2 py-[1px] text-[11.5px] font-medium leading-[18px] whitespace-nowrap", TONES[tone], className)}>
      {dot && <span className="h-1.5 w-1.5 rounded-full bg-current" />}
      {children}
    </span>
  );
}

export function verdictTone(v?: string | null): Tone {
  switch (v) {
    case "approve": case "allow": case "succeeded": case "resolved": case "approved": case "passed": case "completed": return "approve";
    case "revise": case "warn": case "pending_approval": case "awaiting_approval": case "pending": case "abandoned": return "revise";
    case "block": case "blocked": case "refused": case "denied": case "failed": case "deny": return "block";
    case "escalate": case "escalated": case "require_approval": return "escalate";
    case "active": case "running": return "info";
    default: return "neutral";
  }
}

const LABELS: Record<string, string> = {
  pending_approval: "Awaiting approval", awaiting_approval: "Awaiting approval", require_approval: "Needs approval",
  approve: "Approved", revise: "Revised", block: "Blocked", escalate: "Escalated", blocked: "Blocked",
};

export function StatusBadge({ value, label, dot = true }: { value?: string | null; label?: string; dot?: boolean }) {
  if (!value) return <Badge>—</Badge>;
  return <Badge tone={verdictTone(value)} dot={dot}>{label || LABELS[value] || value.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase())}</Badge>;
}

/* -------------------------------------------------------------------- Card */

export function Card({ className, children, ...rest }: React.HTMLAttributes<HTMLDivElement>) {
  return <div {...rest} className={cx("card", className)}>{children}</div>;
}

export function CardHeader({ title, subtitle, action, className }: { title: React.ReactNode; subtitle?: React.ReactNode; action?: React.ReactNode; className?: string }) {
  return (
    <div className={cx("flex items-start justify-between gap-3 px-5 pt-4 pb-3", className)}>
      <div className="min-w-0">
        <h3 className="text-[14px] font-semibold text-ink">{title}</h3>
        {subtitle && <p className="text-[12.5px] text-muted mt-0.5">{subtitle}</p>}
      </div>
      {action && <div className="shrink-0 flex items-center gap-2">{action}</div>}
    </div>
  );
}

export function PageHeader({ title, description, actions, eyebrow }: { title: React.ReactNode; description?: React.ReactNode; actions?: React.ReactNode; eyebrow?: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4 mb-6 animate-rise">
      <div className="min-w-0">
        {eyebrow && <div className="label mb-1.5">{eyebrow}</div>}
        <h1 className="font-display text-[34px] leading-[1.1] text-ink">{title}</h1>
        {description && <p className="text-muted mt-1.5 max-w-2xl">{description}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}

/* ------------------------------------------------------------------- Stats */

export function Stat({ label, value, hint, tone, children, className }: { label: string; value: React.ReactNode; hint?: React.ReactNode; tone?: Tone; children?: React.ReactNode; className?: string }) {
  return (
    <Card className={cx("p-4 flex flex-col gap-1 min-w-0", className)}>
      <div className="label">{label}</div>
      <div className={cx("text-[26px] font-semibold num leading-tight tracking-tight", tone && `text-${tone}`)}>{value}</div>
      {hint && <div className="text-[12px] text-muted">{hint}</div>}
      {children}
    </Card>
  );
}

export function Progress({ value, tone = "accent", className }: { value: number; tone?: "accent" | Tone; className?: string }) {
  const bg = tone === "accent" ? "bg-accent" : `bg-${tone}`;
  return (
    <div className={cx("h-1.5 w-full rounded-full bg-sunken overflow-hidden", className)}>
      <div className={cx("h-full rounded-full transition-[width] duration-700", bg)} style={{ width: `${Math.max(0, Math.min(100, value))}%` }} />
    </div>
  );
}

/* ------------------------------------------------------------------ Inputs */

export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(function Input({ className, ...rest }, ref) {
  return <input ref={ref} {...rest} className={cx("input h-[34px]", className)} />;
});

export const Textarea = React.forwardRef<HTMLTextAreaElement, React.TextareaHTMLAttributes<HTMLTextAreaElement>>(function Textarea({ className, ...rest }, ref) {
  return <textarea ref={ref} {...rest} className={cx("input py-2 leading-relaxed", className)} />;
});

export function Select({ className, children, ...rest }: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <div className={cx("relative", className)}>
      <select {...rest} className="input h-[34px] appearance-none pr-8 cursor-pointer">{children}</select>
      <ChevronDown className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-faint" />
    </div>
  );
}

export function Field({ label, hint, children, className }: { label: string; hint?: React.ReactNode; children: React.ReactNode; className?: string }) {
  return (
    <label className={cx("block", className)}>
      <span className="block text-[12.5px] font-medium text-ink mb-1">{label}</span>
      {children}
      {hint && <span className="block text-[12px] text-muted mt-1">{hint}</span>}
    </label>
  );
}

export function Switch({ checked, onChange, disabled, label }: { checked: boolean; onChange: (v: boolean) => void; disabled?: boolean; label?: string }) {
  return (
    <button
      type="button" role="switch" aria-checked={checked} aria-label={label} disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cx("relative inline-flex h-[20px] w-[34px] shrink-0 rounded-full transition-colors duration-200 disabled:opacity-50",
        checked ? "bg-accent" : "bg-line-strong")}
    >
      <span className={cx("absolute top-[2px] h-4 w-4 rounded-full bg-white shadow transition-transform duration-200",
        checked ? "translate-x-[16px]" : "translate-x-[2px]")} />
    </button>
  );
}

export function Segmented<T extends string>({ value, onChange, options, size = "md" }: { value: T; onChange: (v: T) => void; options: { value: T; label: React.ReactNode }[]; size?: "sm" | "md" }) {
  return (
    <div className="inline-flex rounded-lg bg-subtle border border-line p-0.5">
      {options.map((o) => (
        <button key={o.value} type="button" onClick={() => onChange(o.value)}
          className={cx("rounded-md font-medium transition-all", size === "sm" ? "px-2 py-0.5 text-[12px]" : "px-3 py-1 text-[12.5px]",
            value === o.value ? "bg-surface text-ink shadow-card" : "text-muted hover:text-ink")}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Tabs<T extends string>({ value, onChange, tabs }: { value: T; onChange: (v: T) => void; tabs: { value: T; label: React.ReactNode; count?: number }[] }) {
  return (
    <div className="flex gap-1 border-b border-line mb-4 overflow-x-auto">
      {tabs.map((t) => (
        <button key={t.value} onClick={() => onChange(t.value)}
          className={cx("relative px-3 py-2 text-[13px] font-medium transition-colors whitespace-nowrap",
            value === t.value ? "text-ink" : "text-muted hover:text-ink")}>
          {t.label}
          {t.count !== undefined && <span className="ml-1.5 text-[11px] text-faint num">{t.count}</span>}
          {value === t.value && <span className="absolute inset-x-2 -bottom-px h-[2px] rounded-full bg-accent" />}
        </button>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------------ Tables */

export function Table({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={cx("overflow-x-auto", className)}>
      <table className="w-full text-[13px] border-collapse">{children}</table>
    </div>
  );
}
export function Th({ children, className, align }: { children?: React.ReactNode; className?: string; align?: "right" | "left" }) {
  return <th className={cx("label !normal-case !tracking-normal !text-[12px] text-left font-medium px-4 py-2.5 border-b border-line bg-subtle/60 whitespace-nowrap", align === "right" && "text-right", className)}>{children}</th>;
}
export function Td({ children, className, align }: { children?: React.ReactNode; className?: string; align?: "right" | "left" }) {
  return <td className={cx("px-4 py-2.5 border-b border-line align-middle", align === "right" && "text-right num", className)}>{children}</td>;
}

/* ------------------------------------------------------------ Empty, load */

export function Empty({ icon, title, children, action }: { icon?: React.ReactNode; title: string; children?: React.ReactNode; action?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center text-center py-14 px-6">
      {icon && <div className="h-11 w-11 rounded-xl bg-subtle border border-line grid place-items-center text-faint mb-3">{icon}</div>}
      <div className="font-medium text-ink">{title}</div>
      {children && <div className="text-muted text-[13px] mt-1 max-w-sm">{children}</div>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cx("skeleton", className)} />;
}

export function LoadingRows({ rows = 6 }: { rows?: number }) {
  return (
    <div className="p-4 space-y-3">
      {Array.from({ length: rows }).map((_, i) => <Skeleton key={i} className="h-9" />)}
    </div>
  );
}

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cx("h-4 w-4 animate-spin text-faint", className)} />;
}

/* ------------------------------------------------------------- Overlays */

export function Drawer({ open, onClose, title, subtitle, children, width = 640, footer }: {
  open: boolean; onClose: () => void; title: React.ReactNode; subtitle?: React.ReactNode; children: React.ReactNode; width?: number; footer?: React.ReactNode;
}) {
  useEffect(() => {
    if (!open) return;
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50">
      <div className="absolute inset-0 bg-black/25 backdrop-blur-[2px] animate-fade-in" onClick={onClose} />
      <aside className="absolute right-0 top-0 h-full bg-surface border-l border-line shadow-pop flex flex-col animate-slide-in max-w-full" style={{ width }}>
        <header className="flex items-start justify-between gap-3 px-6 py-4 border-b border-line">
          <div className="min-w-0">
            <div className="font-semibold text-[15px] truncate">{title}</div>
            {subtitle && <div className="text-muted text-[12.5px] mt-0.5">{subtitle}</div>}
          </div>
          <Button variant="ghost" size="icon" onClick={onClose} aria-label="Close"><X className="h-4 w-4" /></Button>
        </header>
        <div className="flex-1 overflow-y-auto px-6 py-5">{children}</div>
        {footer && <footer className="border-t border-line px-6 py-3 flex justify-end gap-2 bg-subtle/50">{footer}</footer>}
      </aside>
    </div>
  );
}

export function Dialog({ open, onClose, title, children, footer, width = 480 }: { open: boolean; onClose: () => void; title: React.ReactNode; children: React.ReactNode; footer?: React.ReactNode; width?: number }) {
  useEffect(() => {
    if (!open) return;
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 grid place-items-center p-4">
      <div className="absolute inset-0 bg-black/30 backdrop-blur-[2px] animate-fade-in" onClick={onClose} />
      <div className="relative card shadow-pop w-full animate-rise" style={{ maxWidth: width }}>
        <div className="px-5 pt-4 pb-2 font-semibold text-[15px]">{title}</div>
        <div className="px-5 pb-4 text-[13.5px] text-muted">{children}</div>
        {footer && <div className="px-5 py-3 border-t border-line flex justify-end gap-2 bg-subtle/50 rounded-b-xl">{footer}</div>}
      </div>
    </div>
  );
}

/* ----------------------------------------------------------------- Toasts */

type Toast = { id: number; title: string; body?: string; tone?: Tone };
const ToastCtx = createContext<(t: Omit<Toast, "id">) => void>(() => {});
export const useToast = () => useContext(ToastCtx);

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const push = useCallback((t: Omit<Toast, "id">) => {
    const id = Date.now() + Math.random();
    setItems((x) => [...x, { ...t, id }]);
    setTimeout(() => setItems((x) => x.filter((i) => i.id !== id)), 4800);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="fixed bottom-4 right-4 z-[60] flex flex-col gap-2 w-[360px] max-w-[calc(100vw-32px)]">
        {items.map((t) => (
          <div key={t.id} className="card shadow-pop px-4 py-3 animate-rise flex gap-3">
            <span className={cx("mt-1.5 h-2 w-2 rounded-full shrink-0", `bg-${t.tone || "approve"}`)} />
            <div className="min-w-0">
              <div className="font-medium text-[13.5px]">{t.title}</div>
              {t.body && <div className="text-muted text-[12.5px] mt-0.5 break-words">{t.body}</div>}
            </div>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

/* --------------------------------------------------------------- Code/JSON */

export function CopyButton({ value, className }: { value: string; className?: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      onClick={() => { navigator.clipboard?.writeText(value); setDone(true); setTimeout(() => setDone(false), 1200); }}
      className={cx("inline-flex items-center gap-1 text-[11.5px] text-faint hover:text-ink transition-colors", className)}
      aria-label="Copy"
    >
      {done ? <Check className="h-3.5 w-3.5 text-approve" /> : <Copy className="h-3.5 w-3.5" />}
    </button>
  );
}

function highlight(json: string) {
  return json
    .replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/("(?:\\.|[^"\\])*")(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d+)?(?:e[+-]?\d+)?/g, (m, str, colon, lit) => {
      if (str) return colon ? `<span class="text-info">${str}</span>${colon}` : `<span class="text-approve">${str}</span>`;
      if (lit) return `<span class="text-escalate">${m}</span>`;
      return `<span class="text-revise">${m}</span>`;
    });
}

export function JsonView({ value, className, maxHeight = 360 }: { value: unknown; className?: string; maxHeight?: number }) {
  const text = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  return (
    <div className={cx("relative group rounded-lg border border-line bg-subtle/70", className)}>
      <CopyButton value={text} className="absolute right-2 top-2 opacity-0 group-hover:opacity-100" />
      <pre className="code overflow-auto p-3 text-ink/90" style={{ maxHeight }} dangerouslySetInnerHTML={{ __html: highlight(text) }} />
    </div>
  );
}

export function Kbd({ children }: { children: React.ReactNode }) {
  return <kbd className="inline-flex h-5 min-w-5 items-center justify-center rounded border border-line bg-subtle px-1 font-mono text-[10.5px] text-muted">{children}</kbd>;
}

export function Avatar({ name, className }: { name?: string | null; className?: string }) {
  const n = (name || "?").trim();
  const initials = n.includes("@") ? n[0] : n.split(/\s+/).map((p) => p[0]).slice(0, 2).join("");
  let h = 0;
  for (const c of n) h = (h * 31 + c.charCodeAt(0)) % 360;
  return (
    <span className={cx("inline-grid place-items-center rounded-full text-[11px] font-semibold uppercase shrink-0 h-7 w-7", className)}
      style={{ background: `hsl(${h} 35% 88%)`, color: `hsl(${h} 35% 28%)` }}>
      {initials}
    </span>
  );
}

export function Tooltip({ content, children }: { content: React.ReactNode; children: React.ReactNode }) {
  const id = useId();
  return (
    <span className="relative inline-flex group/tt" aria-describedby={id}>
      {children}
      <span id={id} role="tooltip"
        className="pointer-events-none absolute bottom-full left-1/2 -translate-x-1/2 mb-1.5 whitespace-nowrap rounded-md bg-ink text-bg text-[11.5px] px-2 py-1 opacity-0 group-hover/tt:opacity-100 transition-opacity z-50 shadow-pop">
        {content}
      </span>
    </span>
  );
}

export function useClickOutside(ref: React.RefObject<HTMLElement | null>, fn: () => void) {
  useEffect(() => {
    const h = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) fn(); };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, [ref, fn]);
}

export function Menu({ trigger, children, align = "right" }: { trigger: React.ReactNode; children: React.ReactNode; align?: "left" | "right" }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useClickOutside(ref, () => setOpen(false));
  return (
    <div className="relative" ref={ref}>
      <div onClick={() => setOpen((o) => !o)}>{trigger}</div>
      {open && (
        <div onClick={() => setOpen(false)}
          className={cx("absolute z-40 mt-1.5 min-w-[200px] card shadow-pop p-1 animate-rise", align === "right" ? "right-0" : "left-0")}>
          {children}
        </div>
      )}
    </div>
  );
}

export function MenuItem({ children, onClick, icon, danger }: { children: React.ReactNode; onClick?: () => void; icon?: React.ReactNode; danger?: boolean }) {
  return (
    <button onClick={onClick} className={cx("w-full flex items-center gap-2 rounded-md px-2.5 py-1.5 text-[13px] text-left hover:bg-subtle", danger ? "text-block" : "text-ink")}>
      {icon && <span className="text-faint">{icon}</span>}
      {children}
    </button>
  );
}
