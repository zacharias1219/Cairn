export const STYLES = `
:host { all: initial; --cairn-accent: #2f5d50; --ink: #1c1b19; --muted: #6c6861; --line: #e7e4dd; --bg: #fff; --soft: #f6f5f1;
  font: 14px/1.5 ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif; color: var(--ink); }
@media (prefers-color-scheme: dark) { :host { --ink: #eeebe5; --muted: #a29e96; --line: #2d2c29; --bg: #171715; --soft: #1f1f1d; } }
* { box-sizing: border-box; }
button { font: inherit; cursor: pointer; }
.launcher { position: fixed; right: 20px; bottom: 20px; width: 56px; height: 56px; border-radius: 18px; border: 0;
  background: var(--cairn-accent); color: #fff; display: grid; place-items: center; z-index: 2147483000;
  box-shadow: 0 12px 30px -10px rgba(0,0,0,.45), inset 0 1px 0 rgba(255,255,255,.15); transition: transform .2s, border-radius .2s; }
.launcher:hover { transform: translateY(-2px) scale(1.03); }
.launcher.open { border-radius: 50%; }
.launcher svg { width: 24px; height: 24px; }
.panel { position: fixed; right: 20px; bottom: 88px; width: 380px; height: min(640px, calc(100vh - 120px)); background: var(--bg);
  border: 1px solid var(--line); border-radius: 20px; display: flex; flex-direction: column; overflow: hidden; z-index: 2147483000;
  box-shadow: 0 30px 80px -24px rgba(0,0,0,.35), 0 4px 14px rgba(0,0,0,.06);
  opacity: 0; transform: translateY(12px) scale(.98); transform-origin: bottom right; pointer-events: none; transition: opacity .2s, transform .25s cubic-bezier(.2,.8,.2,1); }
.panel.open { opacity: 1; transform: none; pointer-events: auto; }
@media (max-width: 480px) { .panel { right: 0; bottom: 0; width: 100vw; height: 100dvh; border-radius: 0; } .launcher.open { display: none; } }
.head { display: flex; align-items: center; gap: 10px; padding: 14px 14px 14px 16px; border-bottom: 1px solid var(--line); }
.avatar { width: 36px; height: 36px; border-radius: 11px; background: var(--cairn-accent); color: #fff; display: grid; place-items: center; flex: none; }
.avatar svg { width: 24px; height: 24px; }
.who { flex: 1; min-width: 0; }
.name { font-weight: 600; font-size: 14.5px; }
.sub { font-size: 11.5px; color: var(--muted); display: flex; align-items: center; gap: 5px; }
.dot { width: 6px; height: 6px; border-radius: 50%; background: #1f8458; }
.icon { width: 32px; height: 32px; border: 0; background: transparent; color: var(--muted); border-radius: 9px; display: grid; place-items: center; }
.icon:hover { background: var(--soft); color: var(--ink); }
.icon svg { width: 16px; height: 16px; }
.end { border: 1px solid var(--line); background: transparent; color: var(--muted); border-radius: 8px; font-size: 11.5px; padding: 4px 8px; }
.end:hover { color: var(--ink); }
.list { flex: 1; overflow-y: auto; padding: 16px; display: flex; flex-direction: column; gap: 10px; background: var(--soft); scroll-behavior: smooth; }
.row { display: flex; flex-direction: column; max-width: 86%; }
.row.in { animation: rise .28s cubic-bezier(.2,.7,.2,1) both; }
@keyframes rise { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
.row.customer { align-self: flex-end; align-items: flex-end; }
.bubble { padding: 9px 13px; border-radius: 16px; white-space: pre-wrap; word-wrap: break-word; font-size: 14px; line-height: 1.5; }
.agent .bubble { background: var(--bg); border: 1px solid var(--line); border-bottom-left-radius: 5px; }
.customer .bubble { background: var(--ink); color: var(--bg); border-bottom-right-radius: 5px; }
.meta { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 5px; }
.cite, .tag { display: inline-flex; align-items: center; gap: 4px; font-size: 11px; color: var(--muted); border: 1px solid var(--line); background: var(--bg); border-radius: 999px; padding: 1px 8px; }
.cite svg { width: 11px; height: 11px; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 2px; }
.chip { border: 1px solid var(--line); background: var(--bg); color: var(--ink); border-radius: 999px; padding: 5px 11px; font-size: 12.5px; transition: border-color .15s; }
.chip:hover { border-color: var(--cairn-accent); color: var(--cairn-accent); }
.status { min-height: 0; max-height: 0; overflow: hidden; display: flex; align-items: center; gap: 8px; padding: 0 16px; font-size: 12px; color: var(--muted); background: var(--soft); transition: max-height .2s, padding .2s; }
.status.on { max-height: 40px; padding: 4px 16px 8px; }
.dots { display: inline-flex; gap: 3px; }
.dots i { width: 5px; height: 5px; border-radius: 50%; background: var(--cairn-accent); animation: blink 1.2s infinite ease-in-out; }
.dots i:nth-child(2) { animation-delay: .15s; } .dots i:nth-child(3) { animation-delay: .3s; }
@keyframes blink { 0%, 80%, 100% { opacity: .25; transform: scale(.8); } 40% { opacity: 1; transform: none; } }
.composer { display: flex; align-items: flex-end; gap: 8px; padding: 10px 12px; border-top: 1px solid var(--line); background: var(--bg); }
textarea { flex: 1; resize: none; border: 1px solid var(--line); border-radius: 12px; padding: 9px 12px; font: inherit; color: var(--ink); background: var(--bg); outline: none; max-height: 120px; }
textarea:focus { border-color: var(--cairn-accent); box-shadow: 0 0 0 3px color-mix(in srgb, var(--cairn-accent) 15%, transparent); }
.send { width: 38px; height: 38px; border-radius: 11px; border: 0; background: var(--cairn-accent); color: #fff; display: grid; place-items: center; flex: none; transition: opacity .15s; }
.send:disabled { opacity: .45; cursor: default; }
.send svg { width: 16px; height: 16px; }
.foot { display: flex; align-items: center; justify-content: center; gap: 5px; font-size: 10.5px; color: var(--muted); padding: 0 0 9px; background: var(--bg); }
.foot svg { width: 12px; height: 12px; }
.rate { align-self: center; text-align: center; font-size: 12.5px; color: var(--muted); background: var(--bg); border: 1px solid var(--line); border-radius: 14px; padding: 10px 16px; }
.stars { display: flex; gap: 4px; justify-content: center; margin-top: 4px; }
.stars button { border: 0; background: transparent; font-size: 20px; color: #d9b44a; padding: 0 2px; }
.stars button:hover { transform: scale(1.15); }
`;
