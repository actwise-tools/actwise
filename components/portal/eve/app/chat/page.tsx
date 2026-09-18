"use client";

import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import Link from "next/link";
import { signIn as ssoSignIn, signOut as ssoSignOut } from "next-auth/react";
import {
  BookOpenText,
  ChatCircle,
  CircleNotch,
  List,
  MagnifyingGlass,
  Plus,
  PlugsConnected,
  SignOut,
  Trash,
  WarningCircle,
  WindowsLogo,
} from "@phosphor-icons/react";
import ChatView, { type ChatPersist } from "./chat-view";
import {
  groupThreads,
  loadThreads,
  newThreadId,
  saveThreads,
  type Thread,
} from "@/app/lib/threads";

export default function ChatPage() {
  // ── session ────────────────────────────────────────────────────────────────
  const [user, setUser] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [email, setEmail] = useState("");
  const [err, setErr] = useState("");
  const [connecting, setConnecting] = useState(false);
  const [sso, setSso] = useState(false);

  useEffect(() => {
    Promise.all([
      fetch("/api/config").then((r) => r.json()).catch(() => ({ ssoEnabled: false })),
      fetch("/api/session").then((r) => r.json()).catch(() => ({ user: null })),
    ])
      .then(([cfg, d]) => {
        setSso(Boolean(cfg.ssoEnabled));
        setUser(d.user ?? null);
      })
      .finally(() => setLoading(false));
  }, []);

  // ── threads ────────────────────────────────────────────────────────────────
  const [threads, setThreads] = useState<Thread[]>([]);
  const [activeId, setActiveId] = useState<string>("");
  const [sideOpen, setSideOpen] = useState(false);

  useEffect(() => {
    if (!user) return;
    const list = loadThreads();
    setThreads(list);
    setActiveId(list[0]?.id ?? newThreadId());
  }, [user]);

  const activeThread = useMemo(
    () => threads.find((t) => t.id === activeId),
    [threads, activeId],
  );

  const persist = useCallback(
    (patch: ChatPersist) => {
      setThreads((prev) => {
        const rest = prev.filter((t) => t.id !== activeId);
        const merged: Thread = {
          id: activeId,
          title: patch.title || activeThread?.title || "New chat",
          updatedAt: Date.now(),
          session: patch.session,
          events: patch.events,
        };
        const next = [merged, ...rest].sort((a, b) => b.updatedAt - a.updatedAt);
        saveThreads(next);
        return next;
      });
    },
    [activeId, activeThread?.title],
  );

  function newChat() {
    setActiveId(newThreadId());
    setSideOpen(false);
  }

  function openThread(id: string) {
    setActiveId(id);
    setSideOpen(false);
  }

  function removeThread(id: string) {
    setThreads((prev) => {
      const next = prev.filter((t) => t.id !== id);
      saveThreads(next);
      return next;
    });
    if (id === activeId) setActiveId(newThreadId());
  }

  // ── session actions ──────────────────────────────────────────────────────────
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
    if (sso) {
      await ssoSignOut({ callbackUrl: "/" });
      return;
    }
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

  // ── render: loading ──────────────────────────────────────────────────────────
  if (loading) {
    return (
      <div className="wrap">
        <div className="center">
          <span className="working">
            <span className="spin" aria-hidden>
              <CircleNotch size={16} weight="bold" />
            </span>
            Loading
          </span>
        </div>
      </div>
    );
  }

  // ── render: sign-in gate ─────────────────────────────────────────────────────
  if (!user) {
    return (
      <div className="wrap">
        <div className="center">
          {sso ? (
            <div className="card">
              <div className="logo" aria-hidden>
                A
              </div>
              <h1>
                Act<span>Wise</span>
              </h1>
              <p>
                Ask NICE Actimize product documentation. Sign in with your Actimize Microsoft
                account to continue.
              </p>
              <button
                type="button"
                className="primary"
                onClick={() => ssoSignIn("microsoft-entra-id", { callbackUrl: "/chat" })}
              >
                <WindowsLogo size={17} weight="bold" /> Sign in with Microsoft
              </button>
              <div className="notice">
                Single sign-on for Actimize employees. No new password. You will connect your
                DOCenter account on your first question.
              </div>
            </div>
          ) : (
            <form className="card" onSubmit={signIn}>
              <div className="logo" aria-hidden>
                A
              </div>
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
              <button type="submit" className="primary">
                Continue
              </button>
              {err ? (
                <div className="err">
                  <WarningCircle size={15} weight="bold" />
                  {err}
                </div>
              ) : null}
              <div className="notice">
                You will connect your DOCenter account (NICE SSO or username and password) on your
                first question.
              </div>
            </form>
          )}
        </div>
      </div>
    );
  }

  // ── render: app shell ────────────────────────────────────────────────────────
  const groups = groupThreads(threads);
  const initials = (user.split("@")[0] || "?")
    .split(/[.\-_]/)
    .map((s) => s[0]?.toUpperCase() ?? "")
    .join("")
    .slice(0, 2);

  return (
    <div className="as-app">
      {sideOpen ? <div className="as-scrim" onClick={() => setSideOpen(false)} /> : null}

      <aside className={`as-side ${sideOpen ? "open" : ""}`}>
        <div className="as-side-top">
          <Link href="/" className="as-brand">
            <span className="as-dot" aria-hidden>
              <BookOpenText size={14} weight="fill" />
            </span>
            ActWise
          </Link>
          <button className="as-newchat" onClick={newChat}>
            <Plus size={16} weight="bold" /> New chat
          </button>
          <div className="as-search">
            <MagnifyingGlass size={15} />
            <input placeholder="Search chats" aria-label="Search chats" />
          </div>
        </div>

        <div className="as-threads">
          {threads.length === 0 ? (
            <div className="as-empty">No conversations yet. Ask something to start.</div>
          ) : (
            groups.map((g) => (
              <div key={g.label}>
                <div className="as-grp">{g.label}</div>
                {g.items.map((t) => (
                  <div
                    key={t.id}
                    className={`as-thread ${t.id === activeId ? "active" : ""}`}
                    onClick={() => openThread(t.id)}
                  >
                    <ChatCircle size={15} />
                    <span>{t.title || "New chat"}</span>
                    <button
                      className="as-del"
                      title="Delete chat"
                      aria-label="Delete chat"
                      onClick={(e) => {
                        e.stopPropagation();
                        removeThread(t.id);
                      }}
                    >
                      <Trash size={14} />
                    </button>
                  </div>
                ))}
              </div>
            ))
          )}
        </div>

        <div className="as-side-foot">
          <div className="as-user">
            <span className="as-avatar" aria-hidden>
              {initials || "?"}
            </span>
            <span className="as-who">
              <span className="n">{user.split("@")[0]}</span>
              <span className="e">{user}</span>
            </span>
            <button className="as-out" onClick={signOut} title="Sign out" aria-label="Sign out">
              <SignOut size={16} />
            </button>
          </div>
        </div>
      </aside>

      <main className="as-main">
        <div className="as-mtop">
          <button
            className="as-hamburger"
            onClick={() => setSideOpen(true)}
            aria-label="Open menu"
          >
            <List size={18} />
          </button>
          <div className="as-title">{activeThread?.title ?? "New chat"}</div>
          <button className="as-connect" onClick={connect} disabled={connecting}>
            {connecting ? (
              <span className="spin" aria-hidden>
                <CircleNotch size={14} weight="bold" />
              </span>
            ) : (
              <PlugsConnected size={14} weight="fill" />
            )}
            <span className="as-connect-label">
              {connecting ? "Connecting" : "Connect DOCenter"}
            </span>
          </button>
        </div>

        {err ? (
          <div className="err bar">
            <WarningCircle size={15} weight="bold" />
            {err}
          </div>
        ) : null}

        <ChatView
          key={activeId}
          initialSession={activeThread?.session}
          initialEvents={activeThread?.events}
          onPersist={persist}
        />
      </main>
    </div>
  );
}
