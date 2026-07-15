# `actone-data`

> Ask questions in plain English and get **real numbers** — a read-only query engine
> over the ActOne `v_acm_*` PostgreSQL reporting views.

## Goal

Answer analytics questions about a live ActOne system (counts, lists, aggregates over
work items, alerts, cases, blotters, queues, users, item types, policies) by turning a
natural-language question into **one safe `SELECT`**, validating it, and running it on
a read-only, row-capped, audited session.

## How it fits

`actone-data` is the CLI core of the [data bucket](../buckets/data.md). The same engine
is exposed as the [`actone-data-mcp`](../mcp/actone-data-mcp.md) MCP server and driven
by the [actone-data](../skills/actone-data.md) skill; it grounds the
[ActWise Data](../agents/data.md) Copilot Studio agent.

## Install / enable

Installed with the `actwise` distribution. Configure a DB profile in `actone-data.yaml`
(host, port, name, **read-only** user, schema) with the password in
`actone-data.secrets.yaml` — see [Install](../install.md).

```powershell
actone-data ping     # verify the connection + ActOne sentinel check
```

## Command reference

| Command | Description |
| --- | --- |
| `ping` | Test the DB connection: prints server version, schema, and the ActOne sentinel check. |
| `version` | Detect the ActOne product version from the DB (falls back to the bundled doc version). |
| `eval` | Run the NL→SQL eval set through the guardrail + execute path and print a scoreboard. |
| `schema` | Introspect the live ActOne schema (`v_acm_*` views). |
| `query` | Validate or run a read-only `SELECT` over the `v_acm_*` views. |
| `audit` | Inspect the query audit log. |
| `env` | List the configured ActOne environments (DB profiles). |
| `docs` | Parse the `v_acm_*` doc pages (descriptions + FK graph). |

Run `actone-data <command> --help` for flags.

## Walkthrough

```powershell
# 1. See which reporting views exist and their columns
actone-data schema --view v_acm_item

# 2. Validate a query without running it (guardrail check)
actone-data query --validate "SELECT count(*) FROM v_acm_item WHERE status='OPEN'"

# 3. Run it read-only and see the rows
actone-data query "SELECT count(*) FROM v_acm_item WHERE status='OPEN'"

# 4. Review what was run
actone-data audit
```

## Under the hood

- **Read-only by construction.** Every query passes a guardrail pipeline that rejects
  anything but a single `SELECT`; execution runs on a read-only, row-capped, audited
  session — no INSERT/UPDATE/DELETE/DDL.
- **Grounded on the reporting views.** It prefers the permission-aware `v_acm_item*`
  views and uses the parsed `docs` (descriptions + FK graph) as schema context.
- **`eval`** scores the NL→SQL pipeline against a bundled eval set for regression
  tracking.

## See also

- Bucket: [data](../buckets/data.md)
- MCP: [actone-data-mcp](../mcp/actone-data-mcp.md)
- Skill: [actone-data](../skills/actone-data.md)
- Agent: [ActWise Data](../agents/data.md)
