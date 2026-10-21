/**
 * Cairn web chat widget (F1).
 *
 *   <script>window.CairnSettings = { key: "pk_…", api: "https://cairn.example" }</script>
 *   <script src="https://cairn.example/widget.js" async></script>
 *
 * Framework-free, rendered in a Shadow DOM so the host page's CSS never leaks
 * in. Replies stream over a WebSocket after the supervisor has approved them,
 * and the session resumes after a page reload.
 */

import { STYLES } from "./styles";

type Settings = {
  key: string;
  api?: string;
  customer?: { email: string; name?: string; signature: string } | null;
  open?: boolean;
};

type Citation = { chunk_id: string; title: string; heading?: string | null };
type Msg = { role: "customer" | "agent"; content: string; citations?: Citation[]; action?: string };

const ICON = {
  chat: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>',
  close: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M18 6 6 18M6 6l12 12"/></svg>',
  send: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m22 2-7 20-4-9-9-4Z"/><path d="M22 2 11 13"/></svg>',
  shield: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10"/><path d="m9 12 2 2 4-4"/></svg>',
  book: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/></svg>',
  stones: '<svg viewBox="0 0 32 32"><ellipse cx="16" cy="23.2" rx="9" ry="3.3" fill="currentColor" opacity=".95"/><ellipse cx="15.2" cy="16.6" rx="6.4" ry="2.9" fill="currentColor" opacity=".8"/><ellipse cx="16.4" cy="10.9" rx="3.9" ry="2.3" fill="currentColor" opacity=".65"/></svg>',
};

function el<K extends keyof HTMLElementTagNameMap>(tag: K, cls?: string, html?: string): HTMLElementTagNameMap[K] {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (html !== undefined) e.innerHTML = html;
  return e;
}

function store(k: string, v?: string | null): string | null {
  try {
    if (v === undefined) return localStorage.getItem(k);
    if (v === null) localStorage.removeItem(k);
    else localStorage.setItem(k, v);
  } catch {
    /* storage can be unavailable (private mode); the widget still works */
  }
  return null;
}

class CairnWidget {
  private s: Settings;
  private api: string;
  private root: ShadowRoot;
  private panel!: HTMLDivElement;
  private list!: HTMLDivElement;
  private input!: HTMLTextAreaElement;
  private sendBtn!: HTMLButtonElement;
  private status!: HTMLDivElement;
  private launcher!: HTMLButtonElement;
  private ws: WebSocket | null = null;
  private token: string | null = null;
  private streaming: { bubble: HTMLDivElement; text: string } | null = null;
  private busy = false;
  private retries = 0;
  private config = { name: "Support", agent_name: "Assistant", accent: "#2f5d50", greeting: "Hi! How can I help?", suggestions: [] as string[] };

  constructor(s: Settings) {
    this.s = s;
    this.api = (s.api || "").replace(/\/$/, "");
    const host = el("div");
    host.id = "cairn-widget";
    document.body.appendChild(host);
    this.root = host.attachShadow({ mode: "open" });
    const style = el("style");
    style.textContent = STYLES;
    this.root.appendChild(style);
    this.render();
    this.boot();
  }

  private get storeKey() { return `cairn:session:${this.s.key}`; }

  private render() {
    this.launcher = el("button", "launcher", ICON.chat) as HTMLButtonElement;
    this.launcher.setAttribute("aria-label", "Open chat");
    this.launcher.onclick = () => this.toggle();

    this.panel = el("div", "panel") as HTMLDivElement;
    this.panel.setAttribute("role", "dialog");
    this.panel.setAttribute("aria-label", "Chat");
    const head = el("div", "head");
    head.innerHTML = `<div class="avatar">${ICON.stones}</div><div class="who"><div class="name"></div><div class="sub"><span class="dot"></span>Replies are checked before they're sent</div></div>`;
    const close = el("button", "icon", ICON.close) as HTMLButtonElement;
    close.setAttribute("aria-label", "Close chat");
    close.onclick = () => this.toggle(false);
    const menu = el("button", "end", "End chat") as HTMLButtonElement;
    menu.onclick = () => this.end();
    head.append(menu, close);

    this.list = el("div", "list") as HTMLDivElement;
    this.list.setAttribute("aria-live", "polite");
    this.status = el("div", "status") as HTMLDivElement;

    const form = el("form", "composer");
    this.input = el("textarea") as HTMLTextAreaElement;
    this.input.rows = 1;
    this.input.placeholder = "Write a message…";
    this.input.setAttribute("aria-label", "Message");
    this.input.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); this.send(); }
    });
    this.input.addEventListener("input", () => {
      this.input.style.height = "auto";
      this.input.style.height = Math.min(120, this.input.scrollHeight) + "px";
    });
    this.sendBtn = el("button", "send", ICON.send) as HTMLButtonElement;
    this.sendBtn.type = "submit";
    this.sendBtn.setAttribute("aria-label", "Send");
    form.onsubmit = (e) => { e.preventDefault(); this.send(); };
    form.append(this.input, this.sendBtn);

    const foot = el("div", "foot", `${ICON.shield}<span>Supervised by Cairn · every reply leaves a trail</span>`);
    this.panel.append(head, this.list, this.status, form, foot);
    this.root.append(this.panel, this.launcher);
  }

  private async boot() {
    try {
      const r = await fetch(`${this.api}/v1/widget/config?key=${encodeURIComponent(this.s.key)}`);
      if (r.ok) Object.assign(this.config, await r.json());
    } catch { /* defaults are fine */ }
    (this.root.host as HTMLElement).style.setProperty("--cairn-accent", this.config.accent);
    (this.panel.querySelector(".name") as HTMLElement).textContent = this.config.name;
    if (this.s.open || store(this.storeKey + ":open") === "1") this.toggle(true);
    await this.session();
  }

  private async session() {
    const r = await fetch(`${this.api}/v1/chat/sessions`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ key: this.s.key, session_token: store(this.storeKey), customer: this.s.customer || null }),
    });
    if (!r.ok) { this.setStatus("Chat is unavailable right now."); return; }
    const data = await r.json();
    this.token = data.session_token;
    store(this.storeKey, this.token);
    this.list.innerHTML = "";
    if (!data.messages.length) {
      this.add({ role: "agent", content: this.config.greeting });
      this.suggestions();
    }
    for (const m of data.messages) {
      if (m.role === "customer" || m.role === "agent") {
        this.add({ role: m.role, content: m.content, citations: m.metadata?.citations, action: m.metadata?.action }, false);
      }
    }
    if (data.status === "awaiting_approval") this.setStatus("Waiting for our team to review your request…", true);
    this.connect();
  }

  private connect() {
    if (!this.token) return;
    const url = this.api.replace(/^http/, "ws") || location.origin.replace(/^http/, "ws");
    const ws = new WebSocket(`${url}/v1/chat/ws?key=${encodeURIComponent(this.s.key)}&token=${encodeURIComponent(this.token)}`);
    this.ws = ws;
    ws.onopen = () => { this.retries = 0; };
    ws.onmessage = (ev) => this.onEvent(JSON.parse(ev.data));
    ws.onclose = (ev) => {
      if (ev.code === 4401) { store(this.storeKey, null); this.session(); return; }
      if (ev.code === 4001) return; // erased
      const wait = Math.min(15000, 500 * 2 ** this.retries++);
      setTimeout(() => this.connect(), wait);
    };
  }

  private onEvent(e: any) {
    switch (e.type) {
      case "status":
        if (e.step !== "respond") this.setStatus(e.label, true);
        break;
      case "reply.start": {
        this.setStatus("");
        const bubble = this.add({ role: "agent", content: "" });
        this.streaming = { bubble, text: "" };
        break;
      }
      case "reply.delta":
        if (this.streaming) {
          this.streaming.text += e.text;
          (this.streaming.bubble.querySelector(".text") as HTMLElement).textContent = this.streaming.text;
          this.scroll();
        }
        break;
      case "reply.done": {
        const b = this.streaming?.bubble;
        this.streaming = null;
        if (b) this.decorate(b, { role: "agent", content: e.text, citations: e.citations, action: e.action });
        this.busy = false;
        this.sendBtn.disabled = false;
        if (e.status === "awaiting_approval") this.setStatus("Waiting for our team to review your request…", true);
        else if (e.action === "escalate") this.setStatus("A teammate will pick this up here.");
        else this.setStatus("");
        break;
      }
      case "error":
        this.busy = false;
        this.sendBtn.disabled = false;
        this.setStatus(e.message);
        break;
      case "ended":
        this.add({ role: "agent", content: "Thanks for chatting. This conversation is closed." });
        this.rate();
        store(this.storeKey, null);
        break;
    }
  }

  private send(text?: string) {
    const content = (text ?? this.input.value).trim();
    if (!content || this.busy) return;
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) { this.setStatus("Reconnecting…", true); return; }
    this.root.querySelector(".chips")?.remove();
    this.add({ role: "customer", content });
    this.input.value = "";
    this.input.style.height = "auto";
    this.busy = true;
    this.sendBtn.disabled = true;
    this.setStatus("Reading your message", true);
    this.ws.send(JSON.stringify({ type: "message", content }));
  }

  private add(m: Msg, animate = true): HTMLDivElement {
    const row = el("div", `row ${m.role}${animate ? " in" : ""}`) as HTMLDivElement;
    const bubble = el("div", "bubble");
    const t = el("div", "text");
    t.textContent = m.content;
    bubble.appendChild(t);
    row.appendChild(bubble);
    this.list.appendChild(row);
    if (m.content) this.decorate(row, m);
    this.scroll();
    return row;
  }

  private decorate(row: HTMLDivElement, m: Msg) {
    (row.querySelector(".text") as HTMLElement).textContent = m.content;
    if (m.role !== "agent") return;
    row.querySelector(".meta")?.remove();
    const meta = el("div", "meta");
    for (const c of m.citations || []) {
      meta.appendChild(el("span", "cite", `${ICON.book}${escapeHtml(c.title)}`));
    }
    if (m.action === "escalate") meta.appendChild(el("span", "tag", "Passed to our team"));
    if (meta.childNodes.length) row.appendChild(meta);
  }

  private suggestions() {
    if (!this.config.suggestions?.length) return;
    const chips = el("div", "chips");
    for (const s of this.config.suggestions) {
      const b = el("button", "chip") as HTMLButtonElement;
      b.textContent = s;
      b.onclick = () => this.send(s);
      chips.appendChild(b);
    }
    this.list.appendChild(chips);
  }

  private rate() {
    const box = el("div", "rate", "<div>How did we do?</div>");
    const stars = el("div", "stars");
    for (let i = 1; i <= 5; i++) {
      const b = el("button", "", "★") as HTMLButtonElement;
      b.setAttribute("aria-label", `${i} of 5`);
      b.onclick = () => {
        this.ws?.send(JSON.stringify({ type: "feedback", value: i }));
        box.innerHTML = "<div>Thank you for the feedback.</div>";
      };
      stars.appendChild(b);
    }
    box.appendChild(stars);
    this.list.appendChild(box);
    this.scroll();
  }

  private end() {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify({ type: "end" }));
  }

  private setStatus(text: string, working = false) {
    this.status.innerHTML = text ? `${working ? '<span class="dots"><i></i><i></i><i></i></span>' : ""}<span>${escapeHtml(text)}</span>` : "";
    this.status.classList.toggle("on", !!text);
  }

  private scroll() {
    requestAnimationFrame(() => { this.list.scrollTop = this.list.scrollHeight; });
  }

  private toggle(open?: boolean) {
    const on = open ?? !this.panel.classList.contains("open");
    this.panel.classList.toggle("open", on);
    this.launcher.classList.toggle("open", on);
    this.launcher.innerHTML = on ? ICON.close : ICON.chat;
    this.launcher.setAttribute("aria-label", on ? "Close chat" : "Open chat");
    store(this.storeKey + ":open", on ? "1" : "0");
    if (on) setTimeout(() => this.input.focus(), 180);
  }
}

function escapeHtml(s: string) {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c] as string));
}

function start() {
  const s = (window as any).CairnSettings as Settings | undefined;
  if (!s?.key || document.getElementById("cairn-widget")) return;
  (window as any).Cairn = new CairnWidget(s);
}

if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
else start();
