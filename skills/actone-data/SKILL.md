---
name: actone-data
description: Query the NICE Actimize ActOne PostgreSQL database in natural language — read-only. The host model writes a single SELECT over the ActOne `v_acm_*` views; the `actone-data` CLI and `actone-data` MCP server ground it (schema pack), validate it (7-step guardrail pipeline), and execute it on a read-only, row-capped, audited session. Use when the user wants to answer a data question from the ActOne database — count/list/aggregate work items, alerts, cases, blotters, item types, queues, users, policies — or explore the `v_acm_*` reporting views, describe a view's columns/FKs, or validate a SQL query before running it. Prefers the permission-aware `v_acm_item*` views over legacy `v_acm_alert*`. Read-only — no INSERT/UPDATE/DELETE/DDL. Not the Extend REST API (use actone-ops) and not product documentation (use actimize-docenter).
---

# ActOne Data

Answer questions from the **live ActOne PostgreSQL database** in natural language,
**read-only**. The host model (this skill, or a Copilot Studio agent) writes the
SQL; the engine only **grounds → validates → executes** it — it holds no LLM key.

```
get_schema_summary  →  list_views / describe_view  →  validate_sql  →  run_query
   (orient, once)         (find & inspect names)       (dry-run)       (execute)
```

Backed by the `actone-data` CLI and the `actone-data` MCP server (tools:
`get_schema_summary`, `list_views`, `describe_view`, `validate_sql`, `run_query`).

> **Safety — read-only, defense in depth.** Only a single `SELECT`/`UNION` over
> `v_acm_*` views is allowed. The pipeline rejects all INSERT/UPDATE/DELETE/DDL/
> COPY/SET/CALL, multi-statement input, `SELECT … INTO`, `FOR UPDATE`, non-`v_acm_*`
> tables, and tableless probes (`SELECT pg_sleep(…)`). Execution runs on a
> **read-only transaction** with a **statement timeout** and an injected **LIMIT**.
> Every attempt — including rejections — is written to a JSONL audit log. **There
> is no write path.** If a task needs a write, stop and tell the user it is not
> supported.

## When to use

Activate when the user wants to **answer a data question from ActOne** or explore
its query surface:
- "How many open work items are there?" / "count alerts by scenario" / "items per queue"
- "How many item types are configured, by category?"
- "List high-risk cases" / "show the newest blotter rows"
- "What views/columns can I query?" / "describe `v_acm_items`"
- "Is this SQL valid / safe to run?" (validate before executing)
- Driving ActOne data queries via an MCP agent (Copilot, Claude, Copilot Studio)

For the **Extend REST API** (invoking ActOne operations, work-item actions), use
**actone-ops**. For **product documentation**, use **actimize-docenter**. To run
server-side **utilities** (blotter maintenance, DART), use **actone-utils**.

## Prefer the item views (important)

ActOne unifies alerts and work items under the **item** family. Always steer to the
permission-aware entry views and away from the legacy alert views:

| Concept | Prefer | Avoid (legacy, alerts-only, not permission-aware) |
|---|---|---|
| Alerts / work items | `v_acm_items` (+ `v_acm_item*`) | `v_acm_alerts`, `v_acm_alerts2` |
| Item / alert types | `v_acm_item_types` | `v_acm_alert_types2` |
| Cases | `v_acm_cases` | — |
| Blotters / transactions | `v_acm_blotters` | — |

`describe_view` on a legacy alert view returns its preferred equivalents under
`related_views` — follow them. `list_views` marks legacy views `preferred:false`.

## The loop (always follow this order)

1. **Orient — once per conversation.** Call `get_schema_summary` to get the DB
   version, schema, families, preference rules, and global rules.
2. **Find & inspect — never guess names.** Use `list_views` (optionally by topic)
   and `describe_view` to get exact view and column names, types, and FK join keys.
3. **Write one SELECT** over `v_acm_*` views (lowercase; `*_join_id` columns only in
   JOIN conditions, never as literals in WHERE).
4. **Validate**, then **run.** Call `validate_sql` first; if it rejects, read the
   errors, fix, and retry once. Then `run_query`, passing the user's `question` for
   the audit log.
5. **Present** the columns + rows, the row count, and note truncation. Show
   `sql_used` on request.

## CLI commands

```
actone-data ping     [--profile local] [--dsn DSN]        # connection + ActOne sentinel check
actone-data version  [--profile local]                    # detect DB product version (falls back to bundled)
actone-data schema summary [--pack PATH]                  # pack overview (offline)
actone-data schema list    [--profile local]             # live v_acm_* views + column counts
actone-data schema show <view> [--pack PATH]             # a view's family/preference/FKs/columns (offline)
actone-data schema build   [--profile local] [--doc-version V]   # rebuild the schema pack
actone-data query validate "<sql>" [--profile local] [--max-rows N]
actone-data query run      "<sql>" [--profile local] [--max-rows N] [-q "question"] [--format table|json|csv]
actone-data audit tail     [--n N]
```

`schema summary/show` and `docs enrich` work **offline** from the bundled pack.
`ping`/`version`/`schema list/build`/`query validate/run` connect to the DB.

## MCP tools (same engine, for AI agents)

| Tool | Purpose |
|------|---------|
| `get_schema_summary()` | DB version, schema, view counts by family, preference + global rules — **call first, once** |
| `list_views(topic="")` | `[{name, description, column_count, family, preferred}]`; doc-only hidden, legacy marked `preferred:false` |
| `describe_view(view)` | columns `{name, type, description, fk}` + `related_views` + `preferred`; unknown → `suggestions` |
| `validate_sql(sql)` | Dry-run the pipeline → `{ok, errors[], sql_used, views_used[], limit_injected}` |
| `run_query(sql, max_rows=100, question="")` | Validate + execute → `{ok, columns, rows, row_count, truncated, sql_used, views_used, limit_injected, duration_ms}` |

Registered in `.vscode/mcp.json` as `actone-data`. Start manually with
`actone-data-mcp` (stdio) or
`python -m uvicorn actone_data_mcp.server:app --host 0.0.0.0 --port 8766` (HTTP,
endpoint `/mcp`, health `/healthz`, optional `X-API-Key` via
`ACTONE_DATA_PROXY_API_KEY`). Grounding tools (`get_schema_summary` / `list_views`
/ `describe_view`) work offline from the bundled schema pack; `validate_sql` /
`run_query` need a live DB.

## Credentials & config

- **Connection** (only for the DB-touching commands/tools): a named profile
  (`--profile`, default `local`), a full libpq `--dsn`/`ACTONE_DATA_DSN`, or the
  `ACTONE_DB_*` env vars (`ACTONE_DB_HOST/NAME/USER/PASSWORD/SCHEMA/PORT`).
  Precedence: flags → env → profile → built-in local default. The MCP server reads
  `ACTONE_DATA_PROFILE` (default `local`).
- **Schema pack** (grounding source): `--pack`/`ACTONE_DATA_PACK` → the bundled
  `actone_data/data/schema-pack-actone-*.json`.
- **Audit log**: `~/.actone-data/audit.jsonl` (override `ACTONE_DATA_AUDIT_LOG`).

## Install & invocation

Driven by the root `pyproject.toml` (`actone-data = "actone_data:app"`,
`actone-data-mcp`). Prefer `actone-data <cmd>`; fall back as noted.

```bash
uv tool install .            # recommended (PATH-clean) — from repo root
# or
pip install -e .             # editable; auto-updates on code changes
# run without installing:
python -m actone_data.cli <cmd>
```

> **uv users:** `uv tool install` freezes a snapshot. After code changes, refresh
> with `uv tool install . --force`. (`pip install -e .` is editable and never needs this.)

## Instructions for the agent

1. **Orient first.** Call `get_schema_summary` once before naming any view.
2. **Never invent view or column names.** Use `list_views` / `describe_view`;
   `describe_view` suggests close matches for a typo.
3. **Prefer the item views.** Steer alerts/work-item questions to `v_acm_items`,
   cases to `v_acm_cases`, blotters/transactions to `v_acm_blotters`. Use
   `related_views` to convert a legacy `v_acm_alert*` view to its item equivalent.
4. **Write one read-only SELECT**, lowercase, over `v_acm_*` views only. Use
   `*_join_id` columns solely in JOIN conditions, never as WHERE literals.
5. **Validate before running.** Call `validate_sql`; on rejection, read the errors,
   fix, and retry once. Then `run_query` with the user's `question`.
6. **Summarize results** — columns + rows + row count; flag truncation; show
   `sql_used` on request.
7. **Refuse writes.** If the user asks to insert/update/delete or change data, stop
   and explain this skill is strictly read-only — direct them to the appropriate
   write path (e.g. actone-ops for gated REST writes), do not attempt a workaround.

## Error handling

| Symptom | Action |
|---------|--------|
| `No such command 'query'`/`schema` | Stale uv snapshot — `uv tool install . --force` (or `pip install -e .`). |
| `actone-data: command not found` | Install via uv/pip, or run `python -m actone_data.cli ...`. |
| `REJECTED: only read-only SELECT queries are allowed` | Expected for any non-SELECT — rewrite as a single SELECT; do not bypass. |
| `table '...' is not an allowlisted v_acm_* view` | You referenced a base table or unknown view — use a `v_acm_*` view from `list_views`. |
| `unknown_view` (with `suggestions`) | Mistyped view — pick from the suggested names. |
| `expected exactly one statement` | Remove extra statements / trailing `;` — one SELECT only. |
| empty result on a fresh DB | Some views (e.g. `v_acm_items`) are empty until data is seeded; the SQL may still be correct. Prefer configuration views (e.g. `v_acm_item_types`) for a data-bearing check. |
| `connection failed` / timeout | DB unreachable (container down / network / VPN). Grounding tools still work offline. |
| `no schema pack found` | Run `actone-data schema build` (or set `ACTONE_DATA_PACK`). |

## Further reading

- Design & milestones: `docs/components/data/2026-07-08-actone-data-mvp-plan.md`
- Cold-start handoff: `docs/components/data/HANDOFF-actone-data-mvp.md`
- MCP server: `actone_data_mcp/README.md`
