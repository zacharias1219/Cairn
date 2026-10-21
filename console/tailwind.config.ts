import type { Config } from "tailwindcss";

const v = (name: string) => `rgb(var(--${name}) / <alpha-value>)`;

export default {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  darkMode: ["class", '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: {
        bg: v("bg"),
        surface: v("surface"),
        subtle: v("subtle"),
        sunken: v("sunken"),
        line: v("line"),
        "line-strong": v("line-strong"),
        ink: v("ink"),
        muted: v("muted"),
        faint: v("faint"),
        accent: v("accent"),
        "accent-ink": v("accent-ink"),
        "accent-soft": v("accent-soft"),
        approve: v("approve"),
        revise: v("revise"),
        block: v("block"),
        escalate: v("escalate"),
        info: v("info"),
      },
      fontFamily: {
        sans: ["var(--font-geist-sans)", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["var(--font-geist-mono)", "ui-monospace", "SFMono-Regular", "monospace"],
        display: ['"Instrument Serif"', "Georgia", "serif"],
      },
      fontSize: { "2xs": ["11px", "16px"] },
      boxShadow: {
        card: "0 1px 0 rgb(var(--shadow) / 0.04), 0 1px 2px rgb(var(--shadow) / 0.05)",
        pop: "0 12px 40px -12px rgb(var(--shadow) / 0.25), 0 2px 6px rgb(var(--shadow) / 0.06)",
        ring: "0 0 0 4px rgb(var(--accent) / 0.12)",
      },
      borderRadius: { xl: "14px", "2xl": "18px" },
      keyframes: {
        "fade-in": { from: { opacity: "0" }, to: { opacity: "1" } },
        "rise": { from: { opacity: "0", transform: "translateY(6px)" }, to: { opacity: "1", transform: "none" } },
        "slide-in": { from: { transform: "translateX(24px)", opacity: "0" }, to: { transform: "none", opacity: "1" } },
        shimmer: { "100%": { transform: "translateX(100%)" } },
        "pulse-dot": { "0%,100%": { opacity: "1" }, "50%": { opacity: ".35" } },
        draw: { from: { strokeDashoffset: "var(--len, 400)" }, to: { strokeDashoffset: "0" } },
      },
      animation: {
        "fade-in": "fade-in .25s ease-out both",
        rise: "rise .35s cubic-bezier(.2,.7,.2,1) both",
        "slide-in": "slide-in .28s cubic-bezier(.2,.7,.2,1) both",
        shimmer: "shimmer 1.4s infinite",
        "pulse-dot": "pulse-dot 1.6s ease-in-out infinite",
        draw: "draw 1.6s cubic-bezier(.65,0,.35,1) both",
      },
    },
  },
  safelist: [{ pattern: /^(bg|text|border)-(approve|revise|block|escalate|info|accent|faint|muted)$/ }],
  plugins: [],
} satisfies Config;
