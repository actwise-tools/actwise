---
name: actone-data
description: Query the NICE Actimize ActOne PostgreSQL database in natural language — read-only. The host model writes a single SELECT over the ActOne `v_acm_*` views (or a solution's own tables); the `actwise-data` (formerly `actone-data`) CLI and MCP server ground it (schema pack + rule pack), validate it (7-step guardrail pipeline), mask PII, and execute it on a read-only, row-capped, audited session. Use when the user wants to answer a data question from the ActOne database — count/list/aggregate work items, alerts, cases, blotters, item types, queues, users, policies — or query an installed solution (QAS, SAM, CDD, CDD Profiles, STAR, WLF, IFM, CTR), list a product's licensed business solutions (fraud lines), explore the reporting views/solution tables, describe a view's columns/FKs, read a solution's rule pack, validate a SQL query, or run read-only performance diagnostics (health check, index/vacuum/bloat, EXPLAIN). Prefers the permission-aware `v_acm_item*` views over legacy `v_acm_alert*`. Read-only — no INSERT/UPDATE/DELETE/DDL. Not the Extend REST API (use actone-ops) and not product documentation (use actimize-docenter).
---

# ActOne Data

Answer questions from the **live ActOne PostgreSQL database** in natural language,
**read-only**. The host model (this skill, or a Copilot Studio agent) writes the
SQL; the engine only **grounds → validates → executes** it — it holds no LLM key.

```
get_schema_summary  →  get_rules  →  list_views / describe_view  →  validate_sql  →  run_query
   (orient, once)      (solution rules)   (find & inspect names)      (dry-run)       (execute)
```

Backed by the `actwise-data` CLI and the `actwise-data` MCP server. Beyond ActOne it is
**multi-solution aware**: pass a `solution` (QAS, SAM, CDD, CDD Profiles, STAR, WLF, IFM,
CTR, …) to ground against that solution's own tables and rule pack. It also ships a
**read-only performance suite** (health check, index/vacuum/bloat diagnostics, `EXPLAIN`),
**business-solution detection** (which licensed fraud lines a deployment runs), and
**PII masking** driven by each solution's rule pack (**20 MCP tools total**).

> **Naming.** The CLI/MCP were renamed `actone-data` → **`actwise-data`** (back-compat).
> Both console scripts exist (`actwise-data` / `actwise-data-mcp` and the legacy
> `actone-data` / `actone-data-mcp`), and both `ACTWISE_DATA_*` and legacy `ACTONE_DATA_*`
> env vars are honored (product DB creds stay `ACTONE_DB_*`). The MCP server is still
> registered in `.vscode/mcp.json` under the key `actone-data`.

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
- "Query the STAR / CDD Profiles / QAS / WLF / IFM / CTR solution" (multi-solution grounding)
- "Which fraud lines / business solutions does this client run?" (business-solution detection)
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
For a **non-ActOne solution**, do not assume `v_acm_*` names — use the view/table
preferences that `get_rules` and `list_views` return for that solution.

## The loop (always follow this order)

1. **Pick the solution.** Call `list_solutions` if unsure which grounded surface
   applies (platform + each installed pack), then use that `solution` for every step.
2. **Orient — once per conversation.** Call `get_schema_summary` to get the DB
   version, schema, families, preference rules, and global rules.
3. **Read the rules (per solution).** Call `get_rules` (optionally with `solution`)
   to get advisory guidance, preferred/deprecated objects, enforced constraints
   (allowlist prefixes, row caps), and the **masked PII columns** for that solution.
4. **Find & inspect — never guess names.** Use `list_views` (optionally by `topic`
   / `solution`) and `describe_view` to get exact view/table and column names,
   types, and FK join keys.
5. **Write one SELECT** over the grounded objects (lowercase; `*_join_id` columns
   only in JOIN conditions, never as literals in WHERE).
6. **Validate**, then **run.** Call `validate_sql` first; if it rejects, read the
   errors, fix, and retry once. Then `run_query`, passing the user's `question` for
   the audit log.
7. **Present** the columns + rows, the row count, and note truncation and any
   **masked columns**. Show `sql_used` on request.

## Multi-solution grounding

ActOne is the platform; **solutions** install on top of it. Some only extend the
ActOne schema (e.g. **QAS** — reuses `v_acm_*`), others add their **own tables/schema**
(e.g. **STAR**, **CDD Profiles**, **IFM**). Pass a `solution` to ground against that
solution's tables and rule pack instead of the ActOne views:

| Solution | `solution` key | Grounding |
|---|---|---|
| ActOne platform | `actone` (default) | `v_acm_*` views |
| Quality Assurance Sampling | `qas` | extends ActOne `v_acm_*` |
| Suspicious Activity Monitoring | `sam` | own tables |
| Customer Due Diligence | `cdd` / `cdd_drt` | own tables |
| CDD Profiles (KYC) | `cdd_prf` | own schema (temporal `_h_latest` families) |
| STAR | `star` | own schema + ActOne add-on tables |
| Watch List Filtering | `wlf` | own tables |
| Integrated Fraud Management | `ifm` | own schema; `ifm_idb` / `ifm_idb_stg` for the IDB (staging) views |
| Currency Transaction Reporting | `ctr` | own tables |

The engine resolves the **deployed schema prefix** per environment (e.g. `cdd_prf`
canonical → `bppr_cdd_prf` in a given deployment), so always schema-qualify. Use
`get_rules --solution <key>` to see that solution's conventions before writing SQL.
Run `list_solutions` (CLI: `schema solutions`) to see the exact set of grounded
surfaces this build ships and their coverage/`draft` status.

## Business solutions (licensed fraud lines)

Some products — notably **IFM** — expose *business solutions*: the licensed fraud
lines a client actually runs (IFM Remote / Commercial / Private Banking, Card,
Deposit, Authentication-IQ, New Account Fraud). A business solution is a
**license-driven subset of one install** (not a separate schema), except New Account
Fraud.

| Tool / CLI | Purpose |
|---|---|
| `list_business_solutions(solution)` / `solutions list` | A product's business solutions + add-ons and their DB markers |
| `detect_business_solutions(env, solution)` / `solutions detect` | Introspect a live deployment to see which business solutions it actually runs |

Use these when the user asks about a specific fraud line, or "which solutions / fraud
lines does this client run." (These are distinct from `solution` grounding above:
`list_solutions` = which schema packs exist; business solutions = which licensed
fraud lines a deployment uses within one product.)

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
| `perf_report` / `perf report` | Consolidated, scored report — includes advisory `CREATE INDEX` candidates for unindexed FKs (with `source_url` citations) |
| `explain_query` / `perf explain` | `EXPLAIN` (read-only) a SELECT plan |

## CLI commands

```
actwise-data ping     [--profile local] [--dsn DSN]        # connection + ActOne sentinel check
actwise-data version  [--profile local]                    # detect DB product version (falls back to bundled)
actwise-data schema summary   [--pack PATH] [-s SOLUTION]  # pack overview (offline; -s for a solution pack)
actwise-data schema solutions                              # list every grounded surface (platform + solution packs)
actwise-data schema list      [--profile local] [-s SOLUTION]  # live views / solution tables + column counts
actwise-data schema show <view> [--pack PATH] [-s SOLUTION]    # a view/table's family/preference/FKs/columns (offline)
actwise-data schema build     [--profile local] [--doc-version V]   # rebuild the schema pack
actwise-data solutions list   [-s SOLUTION]                # a product's business solutions + add-ons and DB markers
actwise-data solutions detect [--profile local] [-s SOLUTION]  # which business solutions a live deployment runs
actwise-data rules show       [-s SOLUTION] [-f table|json]    # advisory guidance + enforced constraints + masked PII cols
actwise-data query validate "<sql>" [--profile local] [-s SOLUTION] [--max-rows N]
actwise-data query run      "<sql>" [--profile local] [-s SOLUTION] [--max-rows N] [-q "question"] [--format table|json|csv]
actwise-data perf report    [--profile local] [-s SOLUTION]   # consolidated scored diagnostics (+ explain, health, indexes, vacuum, bloat, config, extensions, top-queries, missing-indexes)
actwise-data env list                                      # configured DB query environments (metadata only)
actwise-data audit tail     [--n N]
```

The legacy `actone-data <cmd>` invocation still works (same entry point).
`schema summary/solutions/show`, `rules show`, `solutions list`, and `docs enrich`
work **offline** from the bundled packs. `ping`/`version`/`schema list/build`/`solutions
detect`/`query validate/run`/`perf *` connect to the DB. Pass `--solution/-s <key>`
(e.g. `star`, `cdd_prf`, `qas`, `wlf`, `ifm`, `ctr`) to ground against a solution's own
tables and rule pack.

## MCP tools (same engine, for AI agents)

**Grounding** (offline from the bundled packs):

| Tool | Purpose |
|------|---------|
| `list_solutions()` | Discover every grounded surface — ActOne platform + each solution pack — with `surface`, `schema`, `version`, object counts, description coverage, `draft` status. **Call first to pick a `solution`** |
| `get_schema_summary()` | DB version, schema, view counts by family, preference + global rules — **call first, once** |
| `get_rules(solution="")` | Advisory guidance, preferred/deprecated objects, glossary, examples, enforced `constraints` (allowlist prefixes, deny objects, row caps) and **masked PII columns** for the solution |
| `list_views(topic="", solution="actone")` | `[{name, description, column_count, family, preferred}]`; doc-only hidden, legacy marked `preferred:false`; `solution` lists that solution's tables |
| `describe_view(view, solution="actone")` | columns `{name, type, description, fk}` + `related_views` + `preferred`; unknown → `suggestions` |
| `list_business_solutions(solution="ifm")` | A product's licensed business solutions + add-ons and their DB markers |
| `detect_business_solutions(env="", solution="ifm")` | Introspect a live deployment to detect which business solutions it runs |
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
`actwise-data-mcp` (or legacy `actone-data-mcp`, stdio) or
`python -m uvicorn actone_data_mcp.server:app --host 0.0.0.0 --port 8766` (HTTP,
endpoint `/mcp`, health `/healthz`, optional `X-API-Key` via
`ACTWISE_DATA_PROXY_API_KEY`). Grounding tools (`list_solutions` / `get_schema_summary`
/ `list_views` / `describe_view`) work offline from the bundled schema pack;
`validate_sql` / `run_query` / `perf_*` need a live DB.

## Credentials & config

- **Connection** (only for the DB-touching commands/tools): a named profile
  (`--profile`, default `local`), a full libpq `--dsn`/`ACTWISE_DATA_DSN`, or the
  `ACTONE_DB_*` env vars (`ACTONE_DB_HOST/NAME/USER/PASSWORD/SCHEMA/PORT`).
  Precedence: flags → env → profile → built-in local default. The MCP server reads
  `ACTWISE_DATA_PROFILE` (default `local`). (Legacy `ACTONE_DATA_DSN` /
  `ACTONE_DATA_PROFILE` still work as fallbacks.)
- **Schema pack** (grounding source): `--pack`/`ACTWISE_DATA_PACK` → the bundled
  `actone_data/data/schema-pack-actone-*.json`. Solution packs
  (`schema-pack-<solution>-*.json`) and rule packs (`rules-<solution>-*.yaml`) ship
  bundled and are selected via `--solution`/`solution`.
- **Config profiles**: `actwise-data.yaml` (legacy `actone-data.yaml` still honored),
  resolved via `ACTWISE_CONFIG_DIR` → cwd → `~/.actwise` → repo root. No secrets.
- **Audit log**: `~/.actwise-data/audit.jsonl` (override `ACTWISE_DATA_AUDIT_LOG`;
  legacy `~/.actone-data/audit.jsonl` is still read as a fallback).

## Install & invocation

Driven by the root `pyproject.toml` (`actwise-data = "actone_data:app"`,
`actwise-data-mcp`; the legacy `actone-data` / `actone-data-mcp` scripts remain).
Prefer `actwise-data <cmd>`; fall back as noted.

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

1. **Pick the solution, then orient.** Call `list_solutions` if unsure which surface
   applies, then `get_schema_summary` once before naming any view. For a non-ActOne
   solution, call `get_rules(solution=…)` to load its conventions, deployed schema
   prefix, and masked columns.
2. **Never invent view or column names.** Use `list_views` / `describe_view` (pass
   `solution` for a solution's tables); `describe_view` suggests close matches for a typo.
3. **Prefer the item views.** Steer alerts/work-item questions to `v_acm_items`,
   cases to `v_acm_cases`, blotters/transactions to `v_acm_blotters`. Use
   `related_views` to convert a legacy `v_acm_alert*` view to its item equivalent.
   For other solutions, follow the preferences `get_rules` returns.
4. **Write one read-only SELECT**, lowercase, over the grounded objects. Use
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
| `actwise-data: command not found` | Install via uv/pip, or run `python -m actone_data.cli ...` (legacy `actone-data` also works). |
| `REJECTED: only read-only SELECT queries are allowed` | Expected for any non-SELECT — rewrite as a single SELECT; do not bypass. |
| `table '...' is not an allowlisted v_acm_* view` | You referenced a base table or unknown view — use a preferred view from `list_views`. |
| `unknown_view` (with `suggestions`) | Mistyped view — pick from the suggested names. |
| `expected exactly one statement` | Remove extra statements / trailing `;` — one SELECT only. |
| empty result on a fresh DB | Some views (e.g. `v_acm_items`) are empty until data is seeded; the SQL may still be correct. Prefer configuration views (e.g. `v_acm_item_types`) for a data-bearing check. |
| `connection failed` / timeout | DB unreachable (container down / network / VPN). Grounding tools still work offline. |
| `no schema pack found` | Run `actwise-data schema build` (or set `ACTWISE_DATA_PACK`). |

## Further reading

- Design & milestones: `docs/components/data/2026-07-08-actone-data-mvp-plan.md`
- Cold-start handoff: `docs/components/data/HANDOFF-actone-data-mvp.md`
- MCP server: `actone_data_mcp/README.md`
