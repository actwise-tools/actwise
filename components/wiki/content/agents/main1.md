# ActWise-Main1-Dev

> One ActWise agent that fronts Docs, Data, and Ops via three MCP servers attached directly — and does the routing itself.

## Goal

`ActWise-Main1-Dev` is the **single-agent variant** of ActWise. Instead of routing
to separate specialist child agents, it attaches all three NICE Actimize ActOne MCP
servers — **Docs**, **Data**, and **Ops** — directly to one agent, and does the
domain routing itself in its own instructions. It exists to **A/B-compare** a single
all-in-one agent against the connected-agent orchestrator
([`Actwise-Main-Dev`](main.md)) on **quality** and **latency**.

## How it fits

- **Role:** single-agent front door (self-routing, not an orchestrator over child
  agents).
- **Surface:** Microsoft Copilot Studio agent (POC), model Claude Sonnet 4.6.
- **Topology:** one agent with **three MCP servers attached directly**. The
  domain-routing logic that normally lives in a parent's connection descriptions
  lives entirely in **this agent's own instructions** (a Step 1 classifier).
- **MCP grounding (same live backends the orchestrator uses):**
  - **Docs** → the [docenter MCP](../mcp/docenter-mcp.md) — a hosted MCP endpoint
    (self-hosted, managed public HTTPS).
  - **Data** → the [read-only NL→SQL MCP](../mcp/actone-data-mcp.md) — a hosted MCP
    endpoint (self-hosted, via a named tunnel).
  - **Ops** → the [live ActOne REST MCP](../mcp/actone-mcp.md) — a hosted MCP
    endpoint (self-hosted, via a named tunnel).
- **Counterpart:** [`Actwise-Main-Dev`](main.md) — the thin-router orchestrator over
  three connected child agents.

## What it can do

- **Classify** each plain-language request into exactly one domain (Docs / Data /
  Ops), then follow that domain's playbook. Meta questions ("who are you?") are
  answered directly without a tool call.
- **Docs** — NICE Actimize product knowledge and how-to guidance, answered strictly
  from official documentation with citations (`search_docs` before answering; cite
  the returned `source_url` verbatim; default to the latest product version).
- **Data** — read-only reporting and analytics that turns your question into a
  single validated SQL `SELECT` over the ActOne reporting views and returns real
  rows (`get_schema_summary` → discover views → write one `SELECT` → `validate_sql`
  → `run_query`).
- **Ops** — live ActOne operations via REST and curated SOAP admin, with a
  mandatory confirm-before-write safety step on any change (discover → describe →
  invoke with exact params).
- **Cross-reference domains** when a task legitimately spans them — e.g. read
  records with Data, then act on them with Ops after confirmation (identifiers carry
  forward; the confirmation gate is never waived).
- **Disambiguate environments** — there are two `list_environments` tools (Data =
  query targets, Ops = admin targets); a bare "what environments exist?" triggers a
  clarify-first question.

## Example prompts

- **"What is a blotter?"** — Docs domain; answered from official documentation with
  inline citations.
- **"List the last 3 QA-review work items in an environment."** — Data domain;
  returns real rows from a validated read-only `SELECT`.
- **"Create a business unit called Fraud-EU."** — Ops domain; proposes the operation
  and waits for explicit confirmation before writing.
- **"Find the last three QA-review work items, then move each to its next step."** —
  cross-domain (Data → Ops); reads with Data, then confirms before each Ops write.

## Safety & boundaries

- **Golden Rule** — every factual answer about docs, data, or live systems must come
  from a tool call it **actually executed**; never from prior knowledge.
- **Data is strictly read-only** — only `SELECT`/`UNION`; DML/DDL is refused with no
  workarounds offered.
- **Ops confirm-before-write** — it proposes the exact operation, target, change set,
  and environment, and proceeds only after explicit confirmation. Non-local
  environments are treated as sensitive.
- **Grounded citations** — Docs answers cite the returned `source_url`; Ops answers
  reference the executed `operationId`.
- **Clean output** — returns only the final user-facing answer; never leaks internal
  reasoning, tool names, or raw JSON.

## A/B result

Same **12-case workflow test set** (`agents/eval/actwise-main-dev-workflows.csv`),
General-quality grading, authed profile — run **2026-07-14**:

| Variant | Score | Pass / Fail / Error | Wall time |
|---------|-------|---------------------|-----------|
| **ActWise-Main1-Dev** (clean: web search OFF, Maker auth) | **92%** | 11 P / 1 F | **14:02** |
| [`Actwise-Main-Dev`](main.md) (orchestrator, 3 child agents) | 83% | 10 P / 1 F / 1 Err | 17:57 |

**Verdict:** the clean single-agent variant beat the orchestrator on **both**
quality (92 vs 83) **and** speed (14:02 vs 17:57).

Key findings:

- **Turning web search OFF was the decisive quality lever** — removing the
  ungrounded "Search all websites" shortcut jumped Main1 from 75% → 92%. It
  contradicts the Golden Rule; verify the removal persists after a reload.
- **Only shared failure:** "Progress WI-10432 to next step" — failed on *both*
  variants (bad/edge work-item id, not a routing problem).
- The orchestrator additionally **errored** (~4-min timeout) on the heavy
  five-high-severity + move-each case; Main1 passed that same case clean.
- **Citations verified** on "What is a blotter" — the docenter MCP tool was
  genuinely called and inline markers rendered.

Full write-up:
[`docs/agents/2026-07-14-actwise-main1-dev-single-agent-variant.md`](https://github.com/vinayguda/actwise/blob/main/docs/agents/2026-07-14-actwise-main1-dev-single-agent-variant.md).

## Copilot Studio descriptions

**Short description** (≤ 80 chars)

```text
One ActWise agent: Docs, Data, and Ops via three MCP servers attached directly.
```

**Long description**

```text
ActWise-Main1-Dev is the single-agent variant of ActWise. Instead of routing to separate specialist agents, it attaches all three NICE Actimize ActOne MCP servers — Docs, Data, and Ops — directly to one agent and does the domain routing itself in its own instructions. Ask it anything in plain language and it classifies the request into exactly one domain, then follows that domain's playbook:

• Docs — NICE Actimize product knowledge and how-to guidance, answered strictly from official documentation with citations.
• Data — read-only reporting and analytics that turns your question into a single validated SQL SELECT over the ActOne reporting views and returns real rows.
• Ops — live ActOne operations via REST and curated SOAP admin, with a confirm-before-write safety step on any change.

It preserves the same guarantees as the multi-agent experience: every factual answer comes from a tool call it actually executed (never from prior knowledge), Data is strictly read-only, and Ops proposes the exact operation, target, change, and environment and waits for your explicit confirmation before any write. When a request is ambiguous — for example a bare "what environments exist?" that could mean data-query or admin environments — it asks one short clarifying question before acting. It cross-references domains when a task legitimately spans them (e.g. read records with Data, then act on them with Ops after confirmation).

This variant exists to A/B-compare a single all-in-one agent against the connected-agent orchestrator (Actwise-Main-Dev) on quality and latency.
```

## See also

- [`Actwise-Main-Dev`](main.md) — the orchestrator counterpart.
- MCP backends: [docenter](../mcp/docenter-mcp.md) ·
  [actone-data-mcp](../mcp/actone-data-mcp.md) · [actone-mcp](../mcp/actone-mcp.md).
- [Agents hub](index.md) — roster and topology overview.
