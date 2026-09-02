# Actwise-Data-Dev

> Read-only analytics — turns your question into a single safe SQL SELECT over ActOne reporting views and returns real rows.

## Goal

`Actwise-Data-Dev` (ActWise Data) answers questions with **real numbers and records**
from the live ActOne database. It converts your natural-language question into a
single, read-only SQL `SELECT` over the ActOne reporting views, validates it, runs it
on a read-only, row-capped, audited session, and returns the actual rows. It answers
only from query results — never from guesswork.

## How it fits

- **Role:** grounded **specialist** — the Data domain of ActWise.
- **Surface:** Microsoft Copilot Studio agent.
- **Grounding / MCP:** fronts the [read-only NL→SQL MCP](../mcp/actone-data-mcp.md)
  (`get_schema_summary`, `list_views`, `describe_view`, `validate_sql`, `run_query`,
  `list_environments`), served from a hosted MCP endpoint (self-hosted, via a named
  tunnel). See the [data bucket](../buckets/data.md) for the NL-to-SQL pipeline.
- **Consumed by the front doors:** routed to by [`Actwise-Main-Dev`](main.md)
  (orchestrator) and attached directly in [`ActWise-Main1-Dev`](main1.md)
  (single-agent variant).

## What it can do

- Turn a plain-language question into a **single, read-only SQL `SELECT`** over the
  ActOne reporting views: work items, alerts, cases, blotters, queues, users, item
  types, and policies.
- **Validate** the query, then run it on a **read-only, row-capped, audited** session
  and return the **actual rows**.
- Answer counts, lists, metrics, and aggregations with real values.
- Discover the exact views and column names before writing SQL — it never invents
  view or column names.
- Return results as a one-line summary plus a Markdown table with a row count.

## Example prompts

- **"How many open alerts are there right now?"** — a live count returned from a
  validated read-only query.
- **"List the last 3 QA-review work items in an environment."** — a small record
  listing over the reporting views.
- **"What is the average handling time per analyst?"** — an aggregation/metric over
  live data.
- **"Show the top 10 blotters by volume."** — a ranked list returned as real rows.

## Safety & boundaries

- **Strictly read-only** — it never inserts, updates, deletes, or changes anything.
  Only `SELECT`/`UNION` is allowed; all DML/DDL is refused.
- **Declines modifications** — if you ask it to modify data, it declines and offers
  an equivalent read-only query instead, without suggesting workarounds.
- **Validated & audited** — queries run on a read-only, row-capped, audited session;
  SQL is validated before execution.
- **Never fabricates** — it answers only from query results, never from guesswork.

## Copilot Studio descriptions

**Short description** (≤ 80 chars)

```text
Read-only analytics: turns questions into safe SQL over ActOne reporting views.
```

**Long description**

```text
ActWise Data answers questions with real numbers and records from the live ActOne database. It converts your natural-language question into a single, read-only SQL SELECT over the ActOne reporting views (work items, alerts, cases, blotters, queues, users, item types, and policies), validates it, runs it on a read-only, row-capped, audited session, and returns the actual rows.

Examples:
• How many open alerts are there right now?
• List the last 3 QA-review work items in an environment.
• What is the average handling time per analyst?
• Show the top 10 blotters by volume.

It is strictly read-only — it never inserts, updates, deletes, or changes anything. If you ask it to modify data, it declines and offers an equivalent read-only query instead. It answers only from query results, never from guesswork.
```

## See also

- MCP backend: [actone-data-mcp](../mcp/actone-data-mcp.md).
- Bucket: [data](../buckets/data.md) — read-only NL-to-SQL tooling.
- Front doors: [`Actwise-Main-Dev`](main.md) · [`ActWise-Main1-Dev`](main1.md).
- Sibling specialists: [`Actwise-Docs-Dev`](docs.md) · [`Actwise-Ops-Dev`](ops.md).
