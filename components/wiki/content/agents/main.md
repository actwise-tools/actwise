# Actwise-Main-Dev

> One ActWise front door that routes each request to the right Actimize Docs, Data, or Ops specialist.

## Goal

`Actwise-Main-Dev` is the **orchestrator** front door for the ActWise experience.
You tell it what you need in plain language, and it delegates your request to
exactly one of three specialist child agents — **Docs**, **Data**, or **Ops** —
then lets that specialist answer you directly. It is a thin router: it owns
classification and hand-off, while each child agent owns the tools, grounding,
and safety guarantees for its domain.

## How it fits

- **Role:** orchestrator / router (not a grounded agent itself).
- **Surface:** Microsoft Copilot Studio agent.
- **Topology:** a thin router over **three connected child agents**. The routing
  signal lives in each child's **connection description**; the children own their
  own tools and guarantees.
- **Children it routes to:**
  - [`Actwise-Docs-Dev`](docs.md) — product-docs Q&A with citations.
  - [`Actwise-Data-Dev`](data.md) — read-only NL-to-SQL analytics.
  - [`Actwise-Ops-Dev`](ops.md) — live ActOne operations, confirm-before-write.
- **Single-agent counterpart:** [`ActWise-Main1-Dev`](main1.md) exposes the same
  three capabilities as **one agent with all three MCP servers attached directly**,
  instead of routing to child agents. See the
  [A/B comparison](main1.md#ab-result) for the quality/latency result.

## What it can do

- Accept a plain-language request and delegate it to **exactly one** of three
  specialist agents for that turn.
- Route **documentation** questions to ActWise Docs — NICE Actimize product
  knowledge and how-to guidance, answered from official documentation with
  citations.
- Route **reporting/analytics** questions to ActWise Data — read-only queries that
  turn your question into a single safe SQL query over the ActOne database and
  return real numbers.
- Route **operational** requests to ActWise Ops — live ActOne operations via REST,
  with a confirm-before-write safety step on any change.
- Ask **one quick clarifying question** when a request is ambiguous, before acting.
- Let the chosen specialist answer you directly — the specialist owns the answer.

## Example prompts

- **"How do I configure a policy in ActOne?"** — routed to Docs; answered from
  official documentation with citations.
- **"How many open alerts are there right now?"** — routed to Data; returns a real
  number from a read-only query.
- **"Progress work item 4821 to the next step."** — routed to Ops; proposes the
  change and confirms before writing.
- **"What environments are configured?"** — ambiguous; the front door asks one
  quick clarifying question before routing.

## Safety & boundaries

- **Delegation only** — the orchestrator never invents product facts, numbers, or
  system state; the specialist owns the answer.
- **One specialist per turn** — each request is routed to exactly one domain.
- **Clarify-first** — when a request is ambiguous, it asks one quick clarifying
  question before acting.
- **Inherited guarantees** — Docs cites its sources, Data is strictly read-only,
  and Ops confirms before any write. Those guarantees are enforced by the child
  agents.

## Copilot Studio descriptions

**Short description** (≤ 80 chars)

```text
ActWise: one front door that routes you to Actimize Docs, Data, and Ops experts.
```

**Long description**

```text
ActWise is the single entry point for the ActWise experience. Tell it what you need in plain language and it delegates your request to exactly one of three specialist agents, then lets that specialist answer you directly:

• ActWise Docs — NICE Actimize product knowledge and how-to guidance, answered from official documentation with citations.
• ActWise Data — read-only reporting and analytics that turns your question into a single safe SQL query over the ActOne database and returns real numbers.
• ActWise Ops — live ActOne operations via REST, with a confirm-before-write safety step on any change.

Ask a documentation question, request a count or list from live data, or perform an operation on a running ActOne instance — ActWise picks the right specialist for each turn. When a request is ambiguous, it asks one quick clarifying question before acting. It never invents product facts, numbers, or system state; the specialist owns the answer.
```

## See also

- [`ActWise-Main1-Dev`](main1.md) — the single-agent variant and A/B comparison.
- [`Actwise-Docs-Dev`](docs.md) · [`Actwise-Data-Dev`](data.md) ·
  [`Actwise-Ops-Dev`](ops.md) — the specialist child agents.
- [Agents hub](index.md) — the full roster and topology overview.
