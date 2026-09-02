---
name: actone-data
description: Query the NICE Actimize ActOne PostgreSQL database in natural language — read-only. The host model writes a single SELECT over the ActOne `v_acm_*` views (or a solution's own tables); the `actone-data` CLI and `actone-data` MCP server ground it (schema pack + rule pack), validate it (7-step guardrail pipeline), mask PII, and execute it on a read-only, row-capped, audited session. Use when the user wants to answer a data question from the ActOne database — count/list/aggregate work items, alerts, cases, blotters, item types, queues, users, policies — or query an installed solution (QAS, SAM, CDD, CDD Profiles, STAR), explore the reporting views/solution tables, describe a view's columns/FKs, read a solution's rule pack, validate a SQL query, or run read-only performance diagnostics (health check, index/vacuum/bloat, EXPLAIN). Prefers the permission-aware `v_acm_item*` views over legacy `v_acm_alert*`. Read-only — no INSERT/UPDATE/DELETE/DDL. Not the Extend REST API (use actone-ops) and not product documentation (use actimize-docenter).
---

# ActOne Data

Answer questions from the **live ActOne PostgreSQL database** in natural language,
**read-only**. The host model (this skill, or a Copilot Studio agent) writes the
SQL; the engine only **grounds → validates → executes** it — it holds no LLM key.

```
get_schema_summary  →  get_rules  →  list_views / describe_view  →  validate_sql  →  run_query
   (orient, once)      (solution rules)   (find & inspect names)      (dry-run)       (execute)
```

Backed by the `actone-data` CLI and the `actone-data` MCP server. Beyond ActOne it is
**multi-solution aware**: pass a `solution` (QAS, SAM, CDD, CDD Profiles, STAR, …) to
ground against that solution's own tables and rule pack. It also ships a **read-only
performance suite** (health check, index/vacuum/bloat diagnostics, `EXPLAIN`) and
**PII masking** driven by each solution's rule pack (17 MCP tools total).

> **Safety — read-only, defense in depth.** Only a single `SELECT`/`UNION` over
> **allowlisted objects** is allowed (the ActOne `v_acm_*` views by default, or a
> solution's own tables when a `solution` is selected). The pipeline rejects all
> INSERT/UPDATE/DELETE/DDL/COPY/SET/CALL, multi-statement input, `SELECT … INTO`,
> `FOR UPDATE`, non-allowlisted objects, and tableless probes (`SELECT pg_sleep(…)`).
> Execution runs on a **read-only transaction** with a **statement timeout** and an
> injected **LIMIT**, and PII columns are masked per the rule pack. Every attempt —
> including rejections — is written to a JSONL audit log. **There is no write path.**
> If a task needs a write, stop and tell the user it is not supported.

## When to use

Activate when the user wants to **answer a data question from ActOne** or explore
its query surface:
- "How many open work items are there?" / "count alerts by scenario" / "items per queue"
- "How many item types are configured, by category?"
- "List high-risk cases" / "show the newest blotter rows"
- "What views/columns can I query?" / "describe `v_acm_items`"
- "Is this SQL valid / safe to run?" (validate before executing)
- "Query the STAR / CDD Profiles / QAS solution" (multi-solution grounding)
- "Check DB health / find missing indexes / EXPLAIN this query" (performance suite)
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
2. **Read the rules (per solution).** Call `get_rules` (optionally with `solution`)
   to get advisory guidance, preferred/deprecated objects, enforced constraints
   (allowlist prefixes, row caps), and the **masked PII columns** for that solution.
3. **Find & inspect — never guess names.** Use `list_views` (optionally by `topic`
   / `solution`) and `describe_view` to get exact view/table and column names,
   types, and FK join keys.
4. **Write one SELECT** over the grounded objects (lowercase; `*_join_id` columns
   only in JOIN conditions, never as literals in WHERE).
5. **Validate**, then **run.** Call `validate_sql` first; if it rejects, read the
   errors, fix, and retry once. Then `run_query`, passing the user's `question` for
   the audit log.
6. **Present** the columns + rows, the row count, and note truncation and any
   **masked columns**. Show `sql_used` on request.

## Multi-solution grounding

ActOne is the platform; **solutions** install on top of it. Some only extend the
ActOne schema (e.g. **QAS** — reuses `v_acm_*`), others add their **own tables/schema**
(e.g. **STAR**, **CDD Profiles**). Pass a `solution` to ground against that
solution's tables and rule pack instead of the ActOne views:

| Solution | `solution` key | Grounding |
|---|---|---|
| ActOne platform | `actone` (default) | `v_acm_*` views |
| Quality Assurance Sampling | `qas` | extends ActOne `v_acm_*` |
| Suspicious Activity Monitoring | `sam` | own tables |
| Customer Due Diligence | `cdd` / `cdd_drt` | own tables |
| CDD Profiles (KYC) | `cdd_prf` | own schema (temporal `_h_latest` families) |
| STAR | `star` | own schema + ActOne add-on tables |

The engine resolves the **deployed schema prefix** per environment (e.g. `cdd_prf`
canonical → `bppr_cdd_prf` in a given deployment), so always schema-qualify. Use
`get_rules --solution <key>` to see that solution's conventions before writing SQL.

## PII masking

Solution rule packs (notably KYC data like **CDD Profiles**) declare `masked_columns`
— direct identifiers (names, DOB, addresses, IDs, phone/email). `run_query`
**masks these values in the result** and reports them under `masked_columns`; the
underlying query still runs read-only. Call `get_rules` to see which columns a
solution masks, and always tell the user when returned data was masked.

## Performance suite (read-only diagnostics)

Fixed, server-authored diagnostic queries — no free-form SQL, no writes. Useful for
"is the DB healthy?", capacity/index reviews, and explaining a slow query:

| MCP tool / CLI | Purpose |
|---|---|
| `perf_health_check` / `perf health` | Overall health roll-up |
| `perf_top_queries` / `perf top-queries` | Slowest statements (`pg_stat_statements`) |
| `perf_index_issues` / `perf indexes` | Unused / duplicate / invalid indexes |
| `perf_missing_indexes` / `perf missing-indexes` | Seq-scan-heavy tables |
| `perf_vacuum_health` / `perf vacuum` | Dead tuples / autovacuum lag |
| `perf_bloat_estimate` / `perf bloat` | Table/index bloat estimate |
| `perf_config_review` / `perf config` | Key server settings vs. guidance |
| `perf_extensions` / `perf extensions` | Installed/available extensions |
| `perf_report` / `perf report` | Consolidated, scored report (with `source_url` citations) |
| `explain_query` / `perf explain` | `EXPLAIN` (read-only) a SELECT plan |

## CLI commands

```
actone-data ping     [--profile local] [--dsn DSN]        # connection + ActOne sentinel check
actone-data version  [--profile local]                    # detect DB product version (falls back to bundled)
actone-data schema summary [--pack PATH] [-s SOLUTION]    # pack overview (offline; -s for a solution pack)
actone-data schema list    [--profile local] [-s SOLUTION]  # live views / solution tables + column counts
actone-data schema show <view> [--pack PATH] [-s SOLUTION]  # a view/table's family/preference/FKs/columns (offline)
actone-data schema build   [--profile local] [--doc-version V]   # rebuild the schema pack
actone-data rules show     [-s SOLUTION] [-f table|json]  # advisory guidance + enforced constraints + masked PII cols
actone-data query validate "<sql>" [--profile local] [-s SOLUTION] [--max-rows N]
actone-data query run      "<sql>" [--profile local] [-s SOLUTION] [--max-rows N] [-q "question"] [--format table|json|csv]
actone-data perf report    [--profile local] [-s SOLUTION]   # consolidated scored diagnostics (+ explain, health, indexes, vacuum, bloat, config, extensions, top-queries, missing-indexes)
actone-data audit tail     [--n N]
```

`schema summary/show`, `rules show`, and `docs enrich` work **offline** from the
bundled packs. `ping`/`version`/`schema list/build`/`query validate/run`/`perf *`
connect to the DB. Pass `--solution/-s <key>` (e.g. `star`, `cdd_prf`, `qas`) to
ground against a solution's own tables and rule pack.

## MCP tools (same engine, for AI agents)

**Grounding** (offline from the bundled packs):

| Tool | Purpose |
|------|---------|
| `get_schema_summary()` | DB version, schema, view counts by family, preference + global rules — **call first, once** |
| `get_rules(solution="")` | Advisory guidance, preferred/deprecated objects, glossary, examples, enforced `constraints` (allowlist prefixes, deny objects, row caps) and **masked PII columns** for the solution |
| `list_views(topic="", solution="actone")` | `[{name, description, column_count, family, preferred}]`; doc-only hidden, legacy marked `preferred:false`; `solution` lists that solution's tables |
| `describe_view(view, solution="actone")` | columns `{name, type, description, fk}` + `related_views` + `preferred`; unknown → `suggestions` |
| `list_environments()` | Configured DB query environments/profiles |

**Execution** (need a live DB):

| Tool | Purpose |
|------|---------|
| `validate_sql(sql, solution="actone")` | Dry-run the pipeline → `{ok, errors[], sql_used, views_used[], limit_injected}` |
| `run_query(sql, max_rows=100, question="", solution="actone")` | Validate + execute → `{ok, columns, rows, row_count, truncated, sql_used, views_used, masked_columns, limit_injected, duration_ms}` |

**Performance** (read-only diagnostics; fixed server-authored queries): `perf_health_check`,
`perf_top_queries`, `perf_index_issues`, `perf_missing_indexes`, `perf_vacuum_health`,
`perf_bloat_estimate`, `perf_config_review`, `perf_extensions`, `perf_report`, `explain_query`.

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
  `actone_data/data/schema-pack-actone-*.json`. Solution packs
  (`schema-pack-<solution>-*.json`) and rule packs (`rules-<solution>-*.yaml`) ship
  bundled and are selected via `--solution`/`solution`.
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

1. **Orient first.** Call `get_schema_summary` once before naming any view. For a
   non-ActOne solution, call `get_rules(solution=…)` to load its conventions,
   deployed schema prefix, and masked columns.
2. **Never invent view or column names.** Use `list_views` / `describe_view` (pass
   `solution` for a solution's tables); `describe_view` suggests close matches for a typo.
3. **Prefer the item views.** Steer alerts/work-item questions to `v_acm_items`,
   cases to `v_acm_cases`, blotters/transactions to `v_acm_blotters`. Use
   `related_views` to convert a legacy `v_acm_alert*` view to its item equivalent.
4. **Write one read-only SELECT**, lowercase, over `v_acm_*` views only. Use
   `*_join_id` columns solely in JOIN conditions, never as WHERE literals.
5. **Validate before running.** Call `validate_sql`; on rejection, read the errors,
   fix, and retry once. Then `run_query` with the user's `question`.
6. **Summarize results** — columns + rows + row count; flag truncation and any
   **masked (PII) columns**; show `sql_used` on request.
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
