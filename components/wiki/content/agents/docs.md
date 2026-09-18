# Actwise-Docs-Dev

> Answers NICE Actimize product questions strictly from official documentation — always with citations.

## Goal

`Actwise-Docs-Dev` (ActWise Docs) is a NICE Actimize **product-documentation
assistant**. It answers questions about the Actimize portfolio — ActOne, SAM, CDD,
IFM, and more — strictly from the official documentation, and always links its
sources. It covers how-to, what-is, conceptual, configuration, and "where is this
documented" questions, and automatically uses the newest documentation version
unless you specify one.

## How it fits

- **Role:** grounded **specialist** — the Docs domain of ActWise.
- **Surface:** Microsoft Copilot Studio agent.
- **Grounding / MCP:** fronts the [docenter MCP](../mcp/docenter-mcp.md)
  (`search_docs`, `get_page`, `find_bundles`, `list_docs`), served from a hosted MCP
  endpoint (self-hosted, managed public HTTPS — no VPN or tunnel needed). See the
  [docenter bucket](../buckets/docenter.md) for the extractor and search pipeline.
- **Consumed by the front doors:** routed to by
  [`Actwise-Main-Dev`](main.md) (orchestrator) and attached directly in
  [`ActWise-Main1-Dev`](main1.md) (single-agent variant).

## What it can do

- Answer questions about the Actimize portfolio — **ActOne, SAM, CDD, IFM**, and
  more — strictly from the official documentation.
- Always **link its sources** — every factual statement cites the returned
  `source_url`, copied exactly.
- Handle **how-to, what-is, conceptual, configuration**, and "where is this
  documented" questions.
- Automatically use the **newest documentation version** unless you specify one.
- Pull full pages (not just snippets) for procedures, installation, and step-by-step
  configuration guidance.

## Example prompts

- **"How do I configure a policy in ActOne?"** — a how-to answered from the official
  configuration docs, with citations.
- **"What is a blotter?"** — a conceptual "what-is" answer grounded in the docs.
- **"Where is the Extend API documented?"** — a "where is this documented" lookup
  that returns the source location.
- **"What's the latest ActOne release?"** — a version/release-notes question, using
  the newest documentation version by default.

## Safety & boundaries

- **Read-only, docs-only** — it explains and cites; it does **not** touch any live
  system, run queries, or perform operations.
- **Citation policy** — every factual statement is backed by the returned
  `source_url`; it never invents or modifies documentation URLs.
- **Never fabricates** — it answers only from returned documentation; if nothing
  relevant is found, it says so and invites you to rephrase.
- **Scope guard** — if a question falls outside the product documentation (for
  example portal sign-in or account access), it says so and points you to your NICE
  Actimize account team or support portal.

## Copilot Studio descriptions

**Short description** (≤ 80 chars)

```text
Answers Actimize product questions from official docs, always with citations.
```

**Long description**

```text
ActWise Docs is a NICE Actimize product-documentation assistant. It answers questions about the Actimize portfolio — ActOne, SAM, CDD, IFM, and more — strictly from the official documentation at docs.niceactimize.com, and always links its sources. It automatically uses the newest documentation version unless you specify one, and covers how-to, what-is, conceptual, configuration, and "where is this documented" questions.

Examples:
• How do I configure a policy in ActOne?
• What is a blotter?
• Where is the Extend API documented?
• What's the latest ActOne release?

It explains and cites; it does not touch any live system, run queries, or perform operations. If a question falls outside the product documentation (for example portal sign-in or account access), it says so and points you to your NICE Actimize account team or support portal.
```

## See also

- MCP backend: [docenter MCP](../mcp/docenter-mcp.md).
- Bucket: [docenter](../buckets/docenter.md) — doc-portal tooling and extractor.
- Front doors: [`Actwise-Main-Dev`](main.md) · [`ActWise-Main1-Dev`](main1.md).
- Sibling specialists: [`Actwise-Data-Dev`](data.md) · [`Actwise-Ops-Dev`](ops.md).
