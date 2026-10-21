import clsx from "clsx";

/** The cairn mark: three stacked stones, the trail marker. */
export function CairnMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={clsx("h-7 w-7", className)} aria-hidden>
      <rect width="32" height="32" rx="9" className="fill-accent" />
      <ellipse cx="16" cy="23.2" rx="9" ry="3.3" fill="white" opacity=".95" />
      <ellipse cx="15.2" cy="16.6" rx="6.4" ry="2.9" fill="white" opacity=".85" />
      <ellipse cx="16.4" cy="10.9" rx="3.9" ry="2.3" fill="white" opacity=".72" />
    </svg>
  );
}

export function Wordmark({ className }: { className?: string }) {
  return (
    <span className={clsx("inline-flex items-center gap-2", className)}>
      <CairnMark />
      <span className="font-display text-[23px] leading-none tracking-tight text-ink">Cairn</span>
    </span>
  );
}
