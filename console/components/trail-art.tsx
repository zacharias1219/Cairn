"use client";

import { Check, ShieldCheck, Scale, Search, Sparkles, Wrench } from "lucide-react";
import { useEffect, useState } from "react";

import { cx } from "@/components/ui";

const STEPS = [
  { icon: Search, label: "Triage", detail: "refund_request · 92%" },
  { icon: Wrench, label: "Tool", detail: "lookup_order → A1004" },
  { icon: Scale, label: "Rules", detail: "refund_over_100 → approval" },
  { icon: Sparkles, label: "Draft", detail: "3 sentences, 0 claims unbacked" },
  { icon: ShieldCheck, label: "Supervisor", detail: "approve · grounded" },
];

/** An animated trail: a reply moving through the supervised loop. */
export function TrailArt({ className }: { className?: string }) {
  const [n, setN] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setN((x) => (x + 1) % (STEPS.length + 3)), 900);
    return () => clearInterval(t);
  }, []);
  return (
    <div className={cx("relative", className)}>
      <div className="absolute left-[19px] top-4 bottom-4 w-px bg-white/15" />
      <div className="absolute left-[19px] top-4 w-px bg-white/70 transition-all duration-700"
        style={{ height: `calc(${Math.min(n, STEPS.length - 1) / (STEPS.length - 1)} * (100% - 32px))` }} />
      <ul className="space-y-4 relative">
        {STEPS.map((s, i) => {
          const on = i < n;
          return (
            <li key={s.label} className="flex items-center gap-3.5">
              <span className={cx("h-10 w-10 rounded-xl grid place-items-center border transition-all duration-500",
                on ? "bg-white text-[#1d3a32] border-white shadow-[0_0_0_6px_rgba(255,255,255,.08)]" : "bg-white/5 text-white/50 border-white/15")}>
                {on && i === STEPS.length - 1 ? <Check className="h-4 w-4" /> : <s.icon className="h-4 w-4" />}
              </span>
              <div className={cx("transition-opacity duration-500", on ? "opacity-100" : "opacity-45")}>
                <div className="text-[13px] font-medium text-white">{s.label}</div>
                <div className="text-[12px] text-white/60 font-mono">{s.detail}</div>
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
