# ActOne Data

> Answer data questions from the live ActOne PostgreSQL database in natural language — strictly read-only — via the `actone-data` CLI and MCP server.

## Goal
People often want to count, list, or aggregate ActOne work items, alerts, cases, blotters, or configuration — but writing correct, safe SQL over the `v_acm_*` reporting views means knowing the exact view and column names and not touching anything you shouldn't. This skill lets the host model write a single `SELECT`, while the engine grounds it on real schema, validates it through a guardrail pipeline, and executes it read-only, row-capped, and audited.

## How it fits
This skill drives the `actone-data` CLI and the `actone-data` MCP server in the **data** bucket. The engine holds no LLM key and has no write path — it only grounds, validates, and executes SQL the host model writes. It is the read-only reporting counterpart to **actone-ops** (Extend REST operations) and **actone-utils** (server-side utilities); for documentation use **actimize-docenter**.

## When to use it
Activate when the user wants to answer a data question from ActOne or explore its query surface:
- "How many open work items are there?" / "count alerts by scenario" / "items per queue".
- "How many item types are configured, by category?".
- "List high-risk cases" / "show the newest blotter rows".
- "What views/columns can I query?" / "describe `v_acm_items`".
- "Is this SQL valid / safe to run?" (validate before executing).
- Driving ActOne data queries via an MCP agent (Copilot, Claude, Copilot Studio).

## What it does
- Follows a fixed loop: **orient** (`get_schema_summary`, once) → **find & inspect** (`list_views`, `describe_view`) → **validate** (`validate_sql`, dry-run) → **run** (`run_query`).
- Steers to the permission-aware **item views** (`v_acm_items`, `v_acm_item_types`, `v_acm_cases`, `v_acm_blotters`) and away from legacy `v_acm_alert*` views, following `related_views`.
- CLI commands: `actone-data ping|version`, `schema summary|list|show|build`, `query validate|run`, `audit tail`.
- MCP tools (same engine): `get_schema_summary`, `list_views`, `describe_view`, `validate_sql`, `run_query`.
- Grounding tools work offline from the bundled schema pack; `validate`/`run` need a live DB. Every attempt is written to a JSONL audit log.

## Install / enable
Skills follow the open Agent Skills spec and install via the `skills` CLI:
```powershell
npx skills add https://github.com/vinayguda/actwise.git --skill actone-data -a claude-code -g
```
Skills are instructions only — they drive the ActWise CLIs, so install the `actwise` distribution too. This skill requires the **`actone-data`** console script and the **`actone-data-mcp`** server. Configure the DB via `--profile`, a libpq `--dsn`/`ACTONE_DATA_DSN`, or `ACTONE_DB_*` env vars.

## Walkthrough
- *"How many work items are open, by queue?"* → orients, describes `v_acm_items`, validates, then runs a single `SELECT`.
- *"How many item types are configured, by category?"* → `run_query` over `v_acm_item_types` grouped by category.
- *"Is this SQL safe to run?"* → `validate_sql` dry-runs the guardrail pipeline and reports `{ok, errors, sql_used, limit_injected}`.

## Limits & safety
- **Read-only, defense in depth.** Only a single `SELECT`/`UNION` over `v_acm_*` views is allowed; INSERT/UPDATE/DELETE/DDL/COPY/SET/CALL, multi-statement input, `SELECT … INTO`, `FOR UPDATE`, non-`v_acm_*` tables, and tableless probes are rejected.
- Execution runs in a read-only transaction with a statement timeout and an injected LIMIT; every attempt (including rejections) is audited.
- There is **no write path** — if a task needs a write, the skill stops and points the user to the gated REST path (**actone-ops**).

## See also
- CLI: [../cli/actone-data.md](../cli/actone-data.md)
- MCP: [../mcp/actone-data-mcp.md](../mcp/actone-data-mcp.md)
- Bucket: [../buckets/data.md](../buckets/data.md)
- Related skills: [actone-ops](actone-ops.md), [actone-utils](actone-utils.md), [actimize-docenter](actimize-docenter.md)
