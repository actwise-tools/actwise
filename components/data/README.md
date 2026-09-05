# ActWise Data (components/data)

Read-only natural-language-to-SQL over the ActOne `v_acm_*` PostgreSQL reporting views — the host LLM writes the SQL; this engine only grounds, validates, and executes it. Packages: `actone_data`, `actone_data_mcp`. CLIs: `actone-data`. MCP: `actone-data-mcp`. Skill(s): `skills/actone-data`.

## Overview

Data is component **C-D (SQL & DDQ generator)** in the
[ecosystem blueprint](../../docs/2026-06-25-actwise-ecosystem-blueprint.md). The engine holds
**no LLM key** and has **no write path**: a bundled schema pack grounds the model on exact
view/column names, a 7-step `sqlglot` guardrail proves a candidate query is a single
read-only `SELECT` over `v_acm_*` views, and execution runs in a `READ ONLY` transaction with
a statement timeout and row cap. Every attempt is appended to a JSONL audit log. It prefers
the permission-aware `v_acm_item*` views over legacy `v_acm_alert*`. Surfaced three ways: CLI
`actone-data`, MCP `actone-data-mcp`, and the `actone-data` agent skill.

**Multi-solution & performance.** Grounding is **solution-aware** — ActOne is a
platform with solutions layered on top (QAS enhances the base schema; SAM, CDD,
CDD Profiles, CDD DART, STAR, IFM add their own). Some solutions ship more than
one schema — IFM adds its application schema (`ifm`) plus a separate **Investigation
Database** (IDB) modeled as sibling packs `ifm_idb` (data) and `ifm_idb_stg`
(staging), where ingested transactions and analytics results land. Each is modeled
as a `solution` schema pack + rule pack (query conventions + PII masking); the
deployed schema name (e.g. `bppr_cdd_prf`, `fhba_ff_idb_data`) is resolved from the
environment prefix. IFM further ships license-driven **business solutions** (Remote/
Commercial/Private Banking, Card, Deposit, Authentication-IQ, New Account Fraud) —
catalogued in `business-solutions-ifm-11.2.1.yaml`, tagged onto the IDB `v_ff_*`
views, and detectable per deployment (`solutions detect`). A second,
parallel **performance-diagnostics** surface (`perf`) runs fixed, server-authored
`pg_catalog` / `pg_stat_*` checks and a scored, doc-cited `perf report` — issue
detection without ever executing model-authored catalog SQL.

## Quick start

```powershell
uv tool install "git+ssh://git@github.com/vinayguda/actwise.git"   # puts actone-data on PATH
actone-data schema summary                     # offline, from the bundled schema pack
actone-data ping                               # test the DB connection (needs a live DB)
actone-data query run "SELECT item_category, count(*) FROM v_acm_item_types GROUP BY 1" -f table
```

## CLI reference

Run `actone-data <command> --help` for flags.

| Command | Purpose |
|---------|---------|
| `ping` | Test the DB connection: server version, schema, ActOne sentinel check. |
| `version` | Detect the ActOne product version from the DB. |
| `schema` | Introspect the live `v_acm_*` views / build / show / summarize the schema pack (`--solution` for a solution pack); `schema solutions` lists every grounded surface. |
| `solutions` | Business solutions: `list` a product's licensed fraud lines + add-ons and their DB markers; `detect` which ones a live deployment runs (introspects the DB). |
| `query` | `validate` (dry-run guardrail) or `run` (validate + execute a read-only SELECT); `--solution` to target a solution. |
| `rules` | `show` a solution's rule pack — advisory guidance, enforced constraints, masked (PII) columns (`--solution`, `--format table\|json`); CLI twin of MCP `get_rules`. |
| `perf` | Read-only performance diagnostics: `extensions`/`health`/`top-queries`/`indexes`/`missing-indexes`/`vacuum`/`bloat`/`config`/`report`/`explain`. |
| `audit` | Inspect the query audit log (`tail -n`). |
| `env` | List the configured ActOne environments (DB profiles). |
| `docs` | Parse the `v_acm_*` doc pages (descriptions + FK graph). |
| `eval` | Run the NL→SQL eval set through the guardrail + execute path. |

## MCP server

`actone-data-mcp` exposes **20 read-only tools** across two surfaces.

**Surface A — NL-to-SQL grounding + execution (solution-aware):**

| Tool | Purpose |
|------|---------|
| `list_solutions` | Discover every grounded surface (ActOne platform + each solution pack) with schema, version, object counts, description coverage, and draft status. Call first to pick a `solution`. |
| `list_business_solutions` | A product's licensed **business solutions** (IFM Remote/Commercial/Private Banking, Card, Deposit, Authentication-IQ, New Account Fraud) + add-ons, with license flags, detection processes, and `v_ff_*`/table markers. |
| `detect_business_solutions` | Which business solutions a live deployment actually runs — introspects the resolved IDB/app schemas and matches catalog markers (`present`/`absent`/`config_only`). |
| `get_schema_summary` | DB version, schema, view/table counts, preference + global rules — call once first. Accepts `solution`. |
| `get_rules` | The solution's rule pack: query conventions, preferred/deprecated views, masked (PII) columns. |
| `list_views` | Views/tables with description/column-count/family; legacy alert views marked `preferred:false`. Accepts `solution`. |
| `describe_view` | Columns (`name`,`type`,`description`,`fk`) + `related_views` + `preferred`. Accepts `solution`. |
| `validate_sql` | Dry-run the guardrail: `{ok, errors, sql_used, views_used, limit_injected}`. Scoped by `env`+`solution`. |
| `run_query` | Validate + execute: columns, rows, row_count, truncated, duration, `masked_columns`. Scoped by `env`+`solution`. |
| `list_environments` | Database (DATA) profiles for read-only SQL — metadata only, never passwords. |

**Surface B — performance diagnostics (fixed server-authored catalog queries):**

| Tool | Purpose |
|------|---------|
| `perf_extensions` | Installed perf extensions (`pg_stat_statements`, `pgstattuple`, `hypopg`). |
| `perf_health_check` | Cache hit ratio, rollbacks/deadlocks, connections, wraparound headroom. |
| `perf_top_queries` | Worst queries from `pg_stat_statements` (`sort`: total\|mean\|io\|calls). |
| `perf_index_issues` | Unused and invalid indexes (drop / REINDEX candidates). |
| `perf_missing_indexes` | Tables with heavy sequential scans (indexing hotspots). |
| `perf_vacuum_health` | Dead-tuple accumulation + autovacuum recency/settings. |
| `perf_bloat_estimate` | Table bloat via `pgstattuple` (degrades gracefully if absent). |
| `perf_config_review` | Key planner / memory / autovacuum settings (advisory). |
| `perf_report` | Scored recommendation report — findings carry severity, evidence, fix, `source_url`; includes advisory `CREATE INDEX` candidates for unindexed FKs. Accepts `solution`. |
| `explain_query` | `EXPLAIN (FORMAT JSON)` a guardrail-validated SELECT (optional HypoPG hypothetical indexes). |

**How to run.** stdio: `actone-data-mcp`. HTTP: `python -m uvicorn actone_data_mcp.server:app --port 8766`
(endpoint `/mcp`, health `/healthz`).

```jsonc
// VS Code — .vscode/mcp.json  ("servers": { … })
{ "actone-data": { "type": "stdio", "command": "actone-data-mcp",
                   "cwd": "${workspaceFolder}", "envFile": "${workspaceFolder}/.env" } }

// Claude Code — .mcp.json  ("mcpServers": { … })
{ "actone-data": { "type": "stdio", "command": "actone-data-mcp" } }
```

## Skill

[`skills/actone-data/SKILL.md`](../../skills/actone-data/SKILL.md) is the behavior spec for
host agents: the `get_schema_summary → get_rules → list_views/describe_view → validate_sql → run_query`
loop, the item-view preference, and the read-only refusal rules. Teammates install via
`uv tool install "git+ssh://git@github.com/vinayguda/actwise.git"`. An agent triggers it when
the user asks a **data** question about ActOne alerts/work items/cases (counts, breakdowns,
trends) — not the Extend REST API (`actone-ops`) or documentation (`actimize-docenter`).

## Configuration

Config search order: `$ACTWISE_CONFIG_DIR` → cwd → `~/.actwise` → dev repo root.
Connection precedence: explicit `--dsn`/flags → `ACTONE_DB_*` env → named profile → built-in `local`.

| File / env var | Purpose | Location |
|----------------|---------|----------|
| `actone-data.yaml` (`actone-data.example.yaml`) | DB profile (environment) catalog | repo root (gitignored) |
| `actone-data.secrets.yaml` (`.secrets.example.yaml`) | Per-profile passwords | repo root (gitignored) |
| `ACTONE_DB_URL` / `ACTONE_DB_HOST/PORT/NAME/USER/PASSWORD/SCHEMA` | DB connection | env |
| `ACTONE_DATA_PROFILE` (default `local`), `ACTONE_DATA_PACK`, `ACTONE_DATA_AUDIT_LOG` | Profile, schema-pack path, audit-log path | env |
| `ACTONE_DATA_PROXY_API_KEY` | HTTP MCP `X-API-Key` gate | env |

## Auth

DB connections use libpq creds; **passwords are never read from profile YAML** — supply them
via `ACTONE_DB_PASSWORD` / `ACTONE_DB_PASSWORD__<PROFILE>` or `actone-data.secrets.yaml`.
Prefer a least-privilege read-only DB user. The HTTP MCP transport requires `X-API-Key` when
`ACTONE_DATA_PROXY_API_KEY` is set (mandatory for any tunnelled deployment). **Never commit**
`actone-data.secrets.yaml` or `.env`; rotate DB passwords in Postgres.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `connection refused` / `ping` fails | Start the DB (`actone-local db-up`) or fix `ACTONE_DATA_PROFILE` / `ACTONE_DB_*`. |
| Query rejected (not read-only) | Only single `SELECT`/`UNION` over `v_acm_*` views is allowed — no DML/DDL/multi-statement. |
| Model invents a view/column | Call `get_schema_summary` + `describe_view` first; grounding prevents guesses. |
| `actone-data-mcp` 401 | `ACTONE_DATA_PROXY_API_KEY` set — send the `X-API-Key` header. |
| Grounding works but `run_query` fails | Grounding is offline; execution needs a reachable DB — check the profile/DSN. |
| Wrong (legacy) results | Legacy `v_acm_alert*` views aren't permission-aware — use the preferred `v_acm_item*` equivalents. |

## Design docs & further reading

- [`actone_data/README.md`](actone_data/README.md) · [`actone_data_mcp/README.md`](actone_data_mcp/README.md)
- [`../../docs/components/data/2026-07-08-actone-data-mvp-plan.md`](../../docs/components/data/2026-07-08-actone-data-mvp-plan.md) (incl. Copilot Studio wiring)
- [`../../docs/components/data/2026-08-27-actone-data-multi-solution-schema-discovery.md`](../../docs/components/data/2026-08-27-actone-data-multi-solution-schema-discovery.md) (multi-solution schema packs + rule packs + live validation)
- [`../../docs/components/data/2026-08-13-actone-data-perf-tuning-and-multiproduct-enhancements.md`](../../docs/components/data/2026-08-13-actone-data-perf-tuning-and-multiproduct-enhancements.md) (performance-diagnostics suite)
- [`../../docs/components/data/HANDOFF-actone-data-mvp.md`](../../docs/components/data/HANDOFF-actone-data-mvp.md)
- [`../../docs/runbooks/2026-07-10-actwise-mcp-tunnel-runbook.md`](../../docs/runbooks/2026-07-10-actwise-mcp-tunnel-runbook.md)
