"use client";

import type {
  EveMessageData,
  UseEveAgentOptions,
  UseEveAgentSnapshot,
} from "eve/react";

// A persisted conversation. `session` and `events` are eve's own serializable
// cursor and authoritative stream log, so a thread can be rehydrated (and
// resumed on the eve server) by remounting the chat with them as initial state.
export type ThreadSession = UseEveAgentSnapshot<EveMessageData>["session"];
export type ThreadEvents = UseEveAgentSnapshot<EveMessageData>["events"];
export type InitialSession = UseEveAgentOptions<EveMessageData>["initialSession"];
export type InitialEvents = UseEveAgentOptions<EveMessageData>["initialEvents"];

export type Thread = {
  id: string;
  title: string;
  updatedAt: number;
  session?: ThreadSession;
  events?: ThreadEvents;
};

const KEY = "actwise.threads.v1";

export function loadThreads(): Thread[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return [];
    const list = JSON.parse(raw) as Thread[];
    if (!Array.isArray(list)) return [];
    return list.filter((t) => t && t.id).sort((a, b) => b.updatedAt - a.updatedAt);
  } catch {
    return [];
  }
}

export function saveThreads(list: Thread[]): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(KEY, JSON.stringify(list));
  } catch {
    /* storage full or unavailable — history is best-effort */
  }
}

export function newThreadId(): string {
  return crypto.randomUUID();
}

// Group threads into recency buckets for the sidebar.
export function groupThreads(list: Thread[]): { label: string; items: Thread[] }[] {
  const now = new Date();
  const startOfDay = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const dayMs = 86_400_000;
  const buckets: Record<string, Thread[]> = { Today: [], Yesterday: [], Earlier: [] };
  for (const t of list) {
    if (t.updatedAt >= startOfDay) buckets.Today.push(t);
    else if (t.updatedAt >= startOfDay - dayMs) buckets.Yesterday.push(t);
    else buckets.Earlier.push(t);
  }
  return [
    { label: "Today", items: buckets.Today },
    { label: "Yesterday", items: buckets.Yesterday },
    { label: "Earlier", items: buckets.Earlier },
  ].filter((g) => g.items.length > 0);
}
