export function money(v: unknown, digits = 2) {
  const n = Number(v ?? 0);
  return n.toLocaleString("en-US", { style: "currency", currency: "USD", minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function pct(v: unknown, digits = 1) {
  const n = Number(v);
  return Number.isFinite(n) ? `${n.toFixed(digits)}%` : "—";
}

export function num(v: unknown) {
  const n = Number(v ?? 0);
  return n.toLocaleString("en-US");
}

export function ms(v: unknown) {
  const n = Number(v ?? 0);
  if (n < 1) return "<1 ms";
  return n >= 1000 ? `${(n / 1000).toFixed(2)} s` : `${Math.round(n)} ms`;
}

export function ago(d?: string | null) {
  if (!d) return "—";
  const s = (Date.now() - new Date(d).getTime()) / 1000;
  if (s < 0) return "in " + until(d);
  if (s < 45) return "just now";
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  if (s < 86400 * 30) return `${Math.round(s / 86400)}d ago`;
  return date(d);
}

export function until(d?: string | null) {
  if (!d) return "—";
  const s = (new Date(d).getTime() - Date.now()) / 1000;
  if (s <= 0) return "now";
  if (s < 3600) return `${Math.round(s / 60)}m`;
  if (s < 86400) return `${Math.round(s / 3600)}h`;
  return `${Math.round(s / 86400)}d`;
}

export function date(d?: string | null, withTime = false) {
  if (!d) return "—";
  const x = new Date(d);
  return x.toLocaleDateString("en-US", { month: "short", day: "numeric", ...(withTime ? { hour: "numeric", minute: "2-digit" } : {}) });
}

export function time(d?: string | null) {
  if (!d) return "";
  return new Date(d).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
}

export function title(s?: string | null) {
  if (!s) return "—";
  return s.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

export function shortId(id?: string | null) {
  return id ? id.slice(0, 8) : "";
}
