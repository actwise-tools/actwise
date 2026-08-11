# ActWise Data MCP

Read-only **natural-language-to-SQL** MCP server over the NICE Actimize ActOne
`v_acm_*` PostgreSQL views. The **host LLM writes the SQL**; this server only
*grounds*, *validates* and *executes* it — it holds no LLM key.

## Tools

| Tool | Purpose |
|---|---|
| `get_schema_summary()` | DB version, schema, view counts by family, preference rules, global rules — **call once per conversation, first**. |
| `list_views(topic="")` | `[{name, description, column_count, family, preferred}]`; doc-only views hidden, legacy alert views marked `preferred:false`. |
| `describe_view(view)` | columns `{name, type, description, fk}` + `related_views` (legacy → preferred item equivalent) + `preferred`; unknown → `suggestions`. |
| `validate_sql(sql)` | Dry-run the guardrail pipeline: `{ok, errors[], sql_used, views_used[], limit_injected}`. |
| `run_query(sql, max_rows=100, question="")` | Validate + execute: `{ok, columns, rows, row_count, truncated, sql_used, views_used, limit_injected, duration_ms}`. |

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
