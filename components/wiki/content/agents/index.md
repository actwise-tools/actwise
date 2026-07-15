# ActWise Copilot Studio agents

> **ActWise is an unofficial, experimental engineering toolkit — not a NICE Actimize
> product.** These Copilot Studio agents are POCs built on top of the ActWise MCP
> servers.

ActWise ships a small roster of **Microsoft Copilot Studio** agents that put NICE
Actimize ActOne capabilities behind a natural-language front door. Three of them are
**grounded specialists**, each fronting one ActWise MCP server:
[**Docs**](docs.md) (product Q&A with citations), [**Data**](data.md) (read-only
NL-to-SQL analytics), and [**Ops**](ops.md) (live ActOne operations with
confirm-before-write). A fourth agent, [**Utility**](utility.md), is a productivity
toolkit for diagrams, decks, and specs. Every grounded answer comes from a tool call
the agent actually executed — the agents never invent product facts, numbers, or
system state.

## Two front-door variants

There are **two front doors** to the same three capabilities, built to A/B-compare
two topologies:

- **[`Actwise-Main-Dev`](main.md)** — the **orchestrator**. A thin router that
  classifies each request and delegates it to one of three connected child agents
  (Docs / Data / Ops); the child owns the tools and answer.
- **[`ActWise-Main1-Dev`](main1.md)** — the **single-agent** variant. One agent with
  all three MCP servers attached directly, doing the domain routing itself in its own
  instructions.

**A/B result (2026-07-14, same 12-case workflow test set, General-quality grading):**
the clean single-agent variant (`ActWise-Main1-Dev`, web search OFF, Maker auth)
scored **92%** in **14:02**, beating the orchestrator (`Actwise-Main-Dev`) at **83%**
in **17:57** on **both** quality and latency. Turning web search OFF was the decisive
quality lever (75% → 92%). Full write-up:
[`docs/agents/2026-07-14-actwise-main1-dev-single-agent-variant.md`](https://github.com/vinayguda/actwise/blob/main/docs/agents/2026-07-14-actwise-main1-dev-single-agent-variant.md).

## Roster

| Agent | Role | Grounding / MCP | Short description |
|-------|------|-----------------|-------------------|
| [Actwise-Main-Dev](main.md) | Orchestrator front door (routes to child agents) | — (delegates to Docs / Data / Ops) | ActWise: one front door that routes you to Actimize Docs, Data, and Ops experts. |
| [ActWise-Main1-Dev](main1.md) | Single-agent front door (self-routing) | All three MCP servers attached directly | One ActWise agent: Docs, Data, and Ops via three MCP servers attached directly. |
| [Actwise-Docs-Dev](docs.md) | Docs specialist | [docenter MCP](../mcp/docenter-mcp.md) | Answers Actimize product questions from official docs, always with citations. |
| [Actwise-Data-Dev](data.md) | Data specialist (read-only) | [actone-data-mcp](../mcp/actone-data-mcp.md) | Read-only analytics: turns questions into safe SQL over ActOne reporting views. |
| [Actwise-Ops-Dev](ops.md) | Ops specialist (confirm-before-write) | [actone-mcp](../mcp/actone-mcp.md) | Runs live ActOne operations via REST, with confirm-before-write on any change. |
| [ActWise-Utility-Dev](utility.md) | Productivity toolkit | — (add-on capabilities) | Utility toolkit: diagrams, slide decks, and spec generation for ActWise. |

## Grounding & safety at a glance

- **Docs** — explains and cites; read-only, never touches a live system, always links
  its `source_url`.
- **Data** — strictly read-only; a single validated SQL `SELECT` on a row-capped,
  audited session; answers only from query results.
- **Ops** — reads directly; every write is gated by a **confirm-before-write** step
  and non-local environments are treated as sensitive.
- **Front doors** — route to exactly one domain per turn and ask one clarifying
  question when a request is ambiguous.

The grounded agents each talk to a hosted MCP endpoint (self-hosted): the docenter
MCP over managed public HTTPS, and the Ops/Data MCP servers over named tunnels. See
the [MCP pages](../mcp/index.md) for details.
