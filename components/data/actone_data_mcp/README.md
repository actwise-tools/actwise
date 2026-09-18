# ActWise Data MCP

Read-only **natural-language-to-SQL** MCP server over the NICE Actimize ActOne
`v_acm_*` PostgreSQL views. The **host LLM writes the SQL**; this server only
*grounds*, *validates* and *executes* it — it holds no LLM key.

## Tools

| Tool | Purpose |
|---|---|
| `get_schema_summary(solution="actone")` | DB version, schema, view counts by family, preference rules, global rules — **call once per conversation, first**. Pass a `solution` (`star`/`sam`/`cdd`/`wlf`/`ifm`) for that solution's schema/table summary. |
| `list_views(topic="", solution="actone")` | `[{name, description, column_count, family, preferred}]`; doc-only views hidden, legacy alert views marked `preferred:false`. With a `solution`, lists that solution's tables (`{name, description, column_count, kind, schema}`). |
| `describe_view(view, solution="actone")` | columns `{name, type, description, fk}` + `related_views` (legacy → preferred item equivalent) + `preferred`; unknown → `suggestions`. With a `solution`, describes that solution's table (columns + primary/foreign keys). |
| `validate_sql(sql, solution="actone")` | Dry-run the guardrail pipeline: `{ok, errors[], sql_used, views_used[], limit_injected}`. `solution` targets an installed solution's own schema. |
| `run_query(sql, max_rows=100, question="", solution="actone")` | Validate + execute: `{ok, columns, rows, row_count, truncated, sql_used, views_used, limit_injected, duration_ms}`. `solution` targets an installed solution's own schema. |

**Solutions.** Beyond the ActOne `v_acm_*` views, the server can ground + guardrail
queries against an installed solution's own schema. `solution` selects the bundled
*schema pack* (allowlisted tables) and *rule pack* (grounding + enforced constraints);
the deployment-prefixed schema is resolved automatically and the allowlist is the pack's
tables intersected with live objects. Omit it (default `actone`) for the view surface.

### Performance tools (Surface B — read-only diagnostics)

Fixed **server-authored** queries over `pg_stat_*` / `pg_catalog` / `pg_settings`
(never LLM-authored SQL), env-parameterized like Surface A. Extension-backed checks
degrade gracefully (`{available:false, note}`) when the extension is absent.

| Tool | Purpose |
|---|---|
| `perf_extensions(env)` | Which perf extensions are installed (`pg_stat_statements`, `pgstattuple`, `hypopg`). |
| `perf_health_check(env)` | Cache hit ratio, rollback/deadlock/temp activity, connection saturation, txn-ID wraparound headroom. |
| `perf_top_queries(env, sort, limit)` | Worst queries from `pg_stat_statements` (`sort` = total\|mean\|io\|calls). |
| `perf_index_issues(env)` | Unused (never-scanned) and invalid indexes. |
| `perf_missing_indexes(env)` | Tables with heavy sequential scans (indexing hotspots). |
| `perf_vacuum_health(env)` | Dead-tuple accumulation + autovacuum recency/settings. |
| `perf_bloat_estimate(env)` | Table bloat via `pgstattuple` (approx). |
| `perf_config_review(env)` | Key planner / memory / autovacuum settings (advisory). |
| `perf_report(env, markdown)` | Scored recommendation report rolling up all checks: `{health_score, grade, findings[]}`. |
| `explain_query(sql, env, analyze, solution, hypothetical_indexes)` | `EXPLAIN (FORMAT JSON)` a guardrail-validated SELECT; optional HypoPG what-if. |

## Safety (defense in depth)

DB read-only transaction → AST allowlist (`v_acm_*` views only, single SELECT/UNION)
→ statement timeout → row cap. Every attempt — including rejections — is appended
to the JSONL audit log (`~/.actone-data/audit.jsonl`, override `ACTONE_DATA_AUDIT_LOG`).
There are **no write tools**.

## Run

**stdio** (local MCP clients — Copilot CLI, VS Code, Claude):

```powershell
py -m actone_data_mcp.server
```

**Streamable HTTP** (containers / remote clients / Copilot Studio):

```powershell
py -m uvicorn actone_data_mcp.server:app --host 0.0.0.0 --port 8766
# endpoint: http://localhost:8766/mcp   health: http://localhost:8766/healthz
```

Set `ACTONE_DATA_PROXY_API_KEY` to require the `X-API-Key` header (needed for any
shared / tunnelled deployment). Grounding tools work offline from the bundled
schema pack; `validate_sql` / `run_query` need a live DB reachable via
`ACTONE_DATA_PROFILE` (default `local`) / `ACTONE_DATA_DSN` / `ACTONE_DB_*`.

## Copilot Studio

Expose over a tunnel (`cloudflared tunnel --url http://localhost:8766`), set the
`host` in `connector-swagger.json` to the tunnel hostname, and
`pac connector create` with `connector-properties.json`. See the plan's
"Copilot Studio wiring" section for the full playbook.
