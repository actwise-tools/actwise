"use client";

import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { useEveAgent } from "eve/react";

// ── helpers ──────────────────────────────────────────────────────────────────

const URL_RE = /(https?:\/\/[^\s)]+)/g;

// Render assistant text with clickable links (the broker connect link arrives as
// a plain/Markdown URL in an assistant message — make it a real anchor).
function linkify(text: string): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  for (const m of text.matchAll(URL_RE)) {
    const url = m[0];
    const idx = m.index ?? 0;
    if (idx > last) out.push(text.slice(last, idx));
    out.push(
      <a key={idx} href={url} target="_blank" rel="noreferrer">
        {url}
      </a>,
    );
    last = idx + url.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

// ── chat ─────────────────────────────────────────────────────────────────────

function Chat() {
  const agent = useEveAgent({
    maxReconnectAttempts: 10,
    auth: {
      bearer: async () => {
        const r = await fetch("/api/token");
        if (!r.ok) return "";
        return (await r.json()).token ?? "";
      },
    },
  });
  const busy = agent.status === "submitted" || agent.status === "streaming";

  // Elapsed timer while a turn is running — documentation research can take a
  // minute or more (each portal search is slow), so show liveness.
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    if (!busy) {
      setElapsed(0);
      return;
    }
    const started = Date.now();
    const id = setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => clearInterval(id);
  }, [busy]);

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const message = String(form.get("message") ?? "").trim();
    if (message.length > 0) {
      void agent.send({ message });
      event.currentTarget.reset();
    }
  }

  return (
    <>
      <div className="hint">
        Ask a NICE Actimize product question — name the product (ActOne, SAM, IFM, CDD…) and
        what you need. On your first question you may be asked to connect your DOCenter account.
      </div>
      <div className="chat">
        {agent.data.messages.map((message) => {
          const text = message.parts
            .map((part) => (part.type === "text" ? part.text : ""))
            .join("");
          // Tool activity for this message (searches in flight / completed).
          const tools = message.parts.filter((part) => part.type === "dynamic-tool");
          const searching = tools.some((part) => part.state === "input-available");
          if (!text && tools.length === 0) return null;
          return (
            <div key={message.id} className={`msg ${message.role === "user" ? "user" : "assistant"}`}>
              {text ? (message.role === "assistant" ? linkify(text) : text) : null}
              {message.role === "assistant" && tools.length > 0 ? (
                <div className="tools">
                  {searching
                    ? "🔍 Searching the documentation…"
                    : `✓ searched the documentation (${tools.length}×)`}
                </div>
              ) : null}
            </div>
          );
        })}
        {busy ? (
          <div className="working">
            Working… {elapsed}s{elapsed >= 20 ? " — researching the docs, this can take a minute" : ""}
          </div>
        ) : null}
        {agent.status === "error" && agent.error ? (
          <div className="err">Something went wrong: {agent.error.message}</div>
        ) : null}
      </div>
      <form className="composer" onSubmit={onSubmit}>
        <input name="message" placeholder="Ask about NICE Actimize docs…" disabled={busy} autoFocus />
        <button type="submit" disabled={busy}>
          {busy ? "…" : "Send"}
        </button>
      </form>
    </>
  );
}

// ── page ─────────────────────────────────────────────────────────────────────

export default function Home() {
  const [user, setUser] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [email, setEmail] = useState("");
  const [err, setErr] = useState("");
  const [connecting, setConnecting] = useState(false);

  useEffect(() => {
    fetch("/api/session")
      .then((r) => r.json())
      .then((d) => setUser(d.user ?? null))
      .catch(() => setUser(null))
      .finally(() => setLoading(false));
  }, []);

  async function signIn(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setErr("");
    const r = await fetch("/api/session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email }),
    });
    const d = await r.json();
    if (!r.ok) {
      setErr(d.error ?? "sign-in failed");
      return;
    }
    setUser(d.user);
  }

  async function signOut() {
    await fetch("/api/session", { method: "DELETE" });
    setUser(null);
    setEmail("");
  }

  async function connect() {
    setErr("");
    setConnecting(true);
    try {
      const r = await fetch("/api/connect", { method: "POST" });
      const d = await r.json();
      if (!r.ok || !d.login_url) {
        setErr(d.error ?? "could not start the connect flow");
        return;
      }
      window.open(d.login_url, "_blank", "noopener");
    } finally {
      setConnecting(false);
    }
  }

  if (loading) {
    return (
      <div className="wrap">
        <div className="center">
          <div className="who">Loading…</div>
        </div>
      </div>
    );
  }

  if (!user) {
    return (
      <div className="wrap">
        <div className="center">
          <form className="card" onSubmit={signIn}>
            <h1>
              Act<span>Wise</span>
            </h1>
            <p>
              Ask NICE Actimize product documentation with your own DOCenter account. Enter your
              email to start.
            </p>
            <input
              type="email"
              placeholder="you@company.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoFocus
            />
            <div style={{ height: "0.6rem" }} />
            <button type="submit">Continue</button>
            {err ? <div className="err">{err}</div> : null}
            <div className="notice">
              You&apos;ll connect your DOCenter account (NICE SSO or username &amp; password) on the
              next step or your first question.
            </div>
          </form>
        </div>
      </div>
    );
  }

  return (
    <div className="wrap">
      <div className="topbar">
        <div className="brand">
          Act<span>Wise</span>
        </div>
        <div className="row">
          <span className="who">{user}</span>
          <button className="secondary" onClick={connect} disabled={connecting}>
            {connecting ? "Connecting…" : "Connect DOCenter"}
          </button>
          <button className="secondary" onClick={signOut}>
            Sign out
          </button>
        </div>
      </div>
      {err ? <div className="err">{err}</div> : null}
      <Chat />
    </div>
  );
}
