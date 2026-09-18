"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { useEveAgent } from "eve/react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  CircleNotch,
  Copy,
  Check,
  FileText,
  MagnifyingGlass,
  PaperPlaneRight,
  PlugsConnected,
  Sparkle,
  WarningCircle,
} from "@phosphor-icons/react";
import type {
  InitialEvents,
  InitialSession,
  ThreadEvents,
  ThreadSession,
} from "@/app/lib/threads";

// ── helpers ──────────────────────────────────────────────────────────────────

const URL_RE = /(https?:\/\/[^\s)]+)/g;

// The distinctive signature of the docenter MCP's per-user gate (SessionRequired).
// Deliberately specific so a real doc page that merely mentions "login" never matches.
const LOGIN_REQUIRED_RE =
  /no docenter session|interactive login is required|login broker will provide|connect your docenter account/i;

function outputLooksLikeSessionRequired(output: unknown): boolean {
  if (output == null) return false;
  // The MCP returns { content: [{ type:"text", text }], isError: true }.
  const o = output as { isError?: unknown };
  const hasErrorFlag = o.isError === true;
  let text: string;
  try {
    text = JSON.stringify(output);
  } catch {
    return false;
  }
  const matches = LOGIN_REQUIRED_RE.test(text);
  // Require the error flag when present; otherwise fall back to the phrase alone.
  return "isError" in (o as object) ? hasErrorFlag && matches : matches;
}

function messageNeedsConnect(parts: readonly { type: string }[]): boolean {
  return parts.some((p) => {
    if (p.type !== "dynamic-tool") return false;
    const tp = p as { state?: string; errorText?: string; output?: unknown };
    // Tool EXECUTION failure -> output-error + errorText.
    if (
      tp.state === "output-error" &&
      typeof tp.errorText === "string" &&
      LOGIN_REQUIRED_RE.test(tp.errorText)
    ) {
      return true;
    }
    // The docenter MCP returns SessionRequired as a normal tool RESULT carrying
    // { content: [{ text }], isError: true }, so eve projects it as output-available
    // with the login message inside `output` (not output-error). Scan that too.
    if (tp.state === "output-available") {
      return outputLooksLikeSessionRequired(tp.output);
    }
    return false;
  });
}

function extractSources(text: string): string[] {
  const seen = new Set<string>();
  for (const m of text.matchAll(URL_RE)) {
    seen.add(m[0].replace(/[.,)]+$/, ""));
  }
  return [...seen];
}

function sourceTitle(url: string): string {
  try {
    const u = new URL(url);
    const seg = u.pathname.split("/").filter(Boolean).pop() ?? "";
    const tail = decodeURIComponent(seg)
      .replace(/\.[a-z0-9]{2,5}$/i, "")
      .replace(/[-_]+/g, " ")
      .trim();
    return tail || u.hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

function sourceUrlText(url: string): string {
  try {
    const u = new URL(url);
    const host = u.hostname.replace(/^www\./, "");
    const path = decodeURIComponent(u.pathname).replace(/\/$/, "");
    const full = `${host}${path}`;
    return full.length > 60 ? `${full.slice(0, 59)}…` : full;
  } catch {
    return url;
  }
}

// ── markdown ─────────────────────────────────────────────────────────────────

function AssistantMarkdown({ text }: { text: string }) {
  return (
    <div className="md">
      <Markdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: (props) => <a {...props} target="_blank" rel="noreferrer" />,
        }}
      >
        {text}
      </Markdown>
    </div>
  );
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      className="copy"
      title="Copy answer"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setCopied(true);
          setTimeout(() => setCopied(false), 1400);
        } catch {
          /* clipboard unavailable */
        }
      }}
    >
      {copied ? <Check size={13} weight="bold" /> : <Copy size={13} weight="bold" />}
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

// Shown in place of an answer when a docenter tool reports the user has no DOCenter
// session yet. Deterministic gate UX: never let a fabricated answer stand in for a
// real "connect first" step. The button mints a one-time login link via /api/connect.
function ConnectCard() {
  const [connecting, setConnecting] = useState(false);
  const [error, setError] = useState("");
  async function connect() {
    setError("");
    setConnecting(true);
    try {
      const r = await fetch("/api/connect", { method: "POST" });
      const d = await r.json().catch(() => ({}));
      if (!r.ok || !d.login_url) {
        setError(d.error ?? "Could not start the connect flow. Please try again.");
        return;
      }
      window.open(d.login_url, "_blank", "noopener");
    } catch {
      setError("Could not reach the connect service. Please try again.");
    } finally {
      setConnecting(false);
    }
  }
  return (
    <div className="connect-card">
      <div className="connect-ic" aria-hidden>
        <PlugsConnected size={20} weight="fill" />
      </div>
      <div className="connect-title">Connect your DOCenter account</div>
      <div className="connect-sub">
        ActWise searches the documentation with your own DOCenter entitlements, so you need to
        connect once before your first question. Sign in with NICE SSO (employees) or your
        DOCenter username and password (customers and partners), then ask again.
      </div>
      <button type="button" className="connect-btn" onClick={connect} disabled={connecting}>
        {connecting ? (
          <span className="spin" aria-hidden>
            <CircleNotch size={15} weight="bold" />
          </span>
        ) : (
          <PlugsConnected size={15} weight="fill" />
        )}
        {connecting ? "Opening secure sign-in…" : "Connect DOCenter"}
      </button>
      {error ? (
        <div className="err">
          <WarningCircle size={15} weight="bold" />
          {error}
        </div>
      ) : null}
    </div>
  );
}

// ── chat view ────────────────────────────────────────────────────────────────

export type ChatPersist = {
  session: ThreadSession;
  events: ThreadEvents;
  title: string;
};

type ChatViewProps = {
  initialSession?: InitialSession;
  initialEvents?: InitialEvents;
  onPersist: (patch: ChatPersist) => void;
};

const SUGGESTIONS = [
  "What is the latest release of ActOne?",
  "How do I upgrade SAM to the latest version?",
  "What is new in the most recent IFM release?",
  "How do I configure CDD risk scoring?",
];

export default function ChatView({ initialSession, initialEvents, onPersist }: ChatViewProps) {
  const agent = useEveAgent({
    maxReconnectAttempts: 10,
    initialSession,
    initialEvents,
    auth: {
      bearer: async () => {
        const r = await fetch("/api/token");
        if (!r.ok) return "";
        return (await r.json()).token ?? "";
      },
    },
  });
  const busy = agent.status === "submitted" || agent.status === "streaming";
  const messages = agent.data.messages;

  // Title = the first user message, trimmed. Drives the sidebar entry.
  const firstUser = messages.find((m) => m.role === "user");
  const title =
    firstUser?.parts
      .map((p) => (p.type === "text" ? p.text : ""))
      .join("")
      .trim()
      .slice(0, 80) ?? "";

  // Persist the thread on every completed turn, and as soon as it gets a title
  // (so a brand-new chat appears in the sidebar the moment you ask something).
  const persistRef = useRef(onPersist);
  persistRef.current = onPersist;
  const wasBusy = useRef(false);
  useEffect(() => {
    if (wasBusy.current && !busy && agent.events.length > 0) {
      persistRef.current({ session: agent.session, events: agent.events, title });
    }
    wasBusy.current = busy;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [busy]);
  useEffect(() => {
    if (title) persistRef.current({ session: agent.session, events: agent.events, title });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [title]);

  // Elapsed timer while a turn is running.
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

  // Auto-scroll to newest content as it streams.
  const endRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, busy, elapsed]);

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const message = String(form.get("message") ?? "").trim();
    if (message.length > 0) {
      void agent.send({ message });
      event.currentTarget.reset();
    }
  }

  function ask(text: string) {
    if (!busy) void agent.send({ message: text });
  }

  const lastId = messages.length ? messages[messages.length - 1].id : null;
  const empty = messages.length === 0;

  return (
    <>
      <div className="chat">
        <div className="thread">
          {empty && !busy ? (
            <div className="empty">
              <div className="badge" aria-hidden>
                <Sparkle size={22} weight="fill" />
              </div>
              <div className="empty-title">Ask NICE Actimize documentation</div>
              <div className="empty-sub">
                Name the product (ActOne, SAM, IFM, CDD) and what you need. On your first question
                you may be asked to connect your DOCenter account.
              </div>
              <div className="suggestions">
                {SUGGESTIONS.map((s) => (
                  <button key={s} type="button" className="suggest" onClick={() => ask(s)}>
                    {s}
                  </button>
                ))}
              </div>
            </div>
          ) : null}

          {messages.map((message) => {
            const text = message.parts
              .map((part) => (part.type === "text" ? part.text : ""))
              .join("");
            const tools = message.parts.filter((part) => part.type === "dynamic-tool");
            const searching = tools.some((part) => part.state === "input-available");
            if (!text && tools.length === 0) return null;
            const isAssistant = message.role !== "user";
            const streaming = busy && message.id === lastId && isAssistant;
            const sources = isAssistant && text ? extractSources(text) : [];

            if (!isAssistant) {
              return (
                <div key={message.id} className="q">
                  <span className="q-label">Question</span>
                  <div className="q-text">{text}</div>
                </div>
              );
            }

            const showMeta = tools.length > 0 || Boolean(text);
            const needsConnect = messageNeedsConnect(message.parts);
            if (needsConnect) {
              return (
                <div key={message.id} className="answer">
                  <div className="rail" aria-hidden />
                  <div className="answer-body">
                    <ConnectCard />
                  </div>
                </div>
              );
            }
            return (
              <div key={message.id} className="answer">
                <div className="rail" aria-hidden />
                <div className="answer-body">
                  {showMeta ? (
                    <div className="answer-meta">
                      {tools.length > 0 ? (
                        <span className={`activity ${searching ? "live" : ""}`}>
                          <MagnifyingGlass size={14} weight="bold" />
                          {searching
                            ? "Searching the documentation"
                            : `Searched the documentation across ${tools.length} lookups`}
                        </span>
                      ) : null}
                      {text ? <CopyButton text={text} /> : null}
                    </div>
                  ) : null}

                  {text ? (
                    <>
                      <AssistantMarkdown text={text} />
                      {streaming ? <span className="cursor" /> : null}
                    </>
                  ) : null}

                  {sources.length > 0 ? (
                    <div className="sources">
                      <span className="sources-label">Sources</span>
                      {sources.map((url) => (
                        <a
                          key={url}
                          className="source-card"
                          href={url}
                          target="_blank"
                          rel="noreferrer"
                          title={url}
                        >
                          <span className="ic" aria-hidden>
                            <FileText size={16} weight="regular" />
                          </span>
                          <span className="meta">
                            <span className="t">{sourceTitle(url)}</span>
                            <span className="u">{sourceUrlText(url)}</span>
                          </span>
                        </a>
                      ))}
                    </div>
                  ) : null}
                </div>
              </div>
            );
          })}

          {busy && (lastId === null || messages[messages.length - 1].role === "user") ? (
            <div className="answer">
              <div className="rail" aria-hidden />
              <div className="answer-body">
                <span className="working">
                  <span className="spin" aria-hidden>
                    <CircleNotch size={15} weight="bold" />
                  </span>
                  Researching the docs… {elapsed}s
                  {elapsed >= 20 ? " · this can take a minute" : ""}
                </span>
              </div>
            </div>
          ) : null}

          {agent.status === "error" && agent.error ? (
            <div className="err">
              <WarningCircle size={15} weight="bold" />
              Something went wrong: {agent.error.message}
            </div>
          ) : null}

          <div ref={endRef} />
        </div>
      </div>

      <div className="composer-wrap">
        <form className="composer" onSubmit={onSubmit}>
          <input
            name="message"
            placeholder="Ask an ActOne, SAM, IFM or CDD question."
            disabled={busy}
            autoFocus
          />
          <button type="submit" className="send" disabled={busy} aria-label="Send" title="Send">
            {busy ? (
              <span className="spin" aria-hidden>
                <CircleNotch size={17} weight="bold" />
              </span>
            ) : (
              <PaperPlaneRight size={17} weight="fill" />
            )}
          </button>
        </form>
        <div className="composer-hint">
          Grounded in your DOCenter entitlements. Every answer cites its source.
        </div>
      </div>
    </>
  );
}
