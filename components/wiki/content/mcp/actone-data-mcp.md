# actone-data-mcp

> Read-only natural-language-to-SQL over the ActOne `v_acm_*` PostgreSQL
> reporting views — grounds, validates, and executes; never writes.

## Goal

Answer data questions about ActOne (alerts, work items, cases, blotters, queues,
users, item types, policies) with real rows. The host LLM writes a single SQL
`SELECT`; this engine grounds it on exact view/column names, proves it through a
`sqlglot` guardrail (single read-only SELECT over `v_acm_*`, injected/clamped
LIMIT), and executes it in a `READ ONLY`, row-capped, audited transaction. The
engine holds **no LLM key and no write path**.

## How it fits

- **Bucket:** [data](../buckets/data.md).
- **Shares code with:** the [`actone-data`](../cli/actone-data.md) CLI — the MCP
  tools call the same schema pack, guardrail pipeline, and DB layer as
  `actone-data schema` / `query validate` / `query run`.
- **Consumed by:** the **ActWise Data** Copilot Studio agent
  ([agent page](../agents/data.md)), grounded on this server via a
  self-hosted, API-key-gated MCP endpoint. Local IDE agents can register it over
  stdio.

## Tools exposed

Enumerated from `components/data/actone_data_mcp/server.py` — six `@mcp.tool`
registrations (all read-only):

| Tool | What it does |
|------|--------------|
| `get_schema_summary` | Overview of the query surface — DB version, schema, view counts by family, preference + global rules. Call once, first. |
| `list_views` | List queryable `v_acm_*` views (doc-only hidden); legacy alert views marked `preferred: false`. Filter by `topic`. |
| `describe_view` | One view's columns (`name`/`type`/`description`/`fk`), `related_views`, and preferred item equivalents. |
| `list_environments` | List the **database (DATA)** environment profiles for read-only SQL — metadata only, never passwords. |
| `validate_sql` | Dry-run the guardrail on a SQL string (no execution): `{ok, errors, sql_used, views_used, limit_injected}`. |
| `run_query` | Validate **and** execute a read-only SELECT: columns, rows, row_count, truncated, sql_used, duration. |

## Transport & run

Runs as **stdio or HTTP**. Console script from `pyproject.toml`
(`actone-data-mcp = "actone_data_mcp.server:main"`):

```powershell
actone-data-mcp
# or, as an ASGI HTTP app (serves /mcp, health /healthz):
python -m uvicorn actone_data_mcp.server:app --port 8766
```

The HTTP transport is **self-hosted**; when `ACTONE_DATA_PROXY_API_KEY` is set it
enforces an `X-API-Key` header (mandatory for any tunnelled deployment — how the
ActWise Data agent reaches it).

## Safety

Strictly **read-only**. The guardrail always re-runs inside `run_query`, so it
cannot be bypassed by skipping `validate_sql`: only a single `SELECT`/`UNION`
over allowlisted `v_acm_*` views is permitted, execution runs in a `READ ONLY`
transaction with a statement timeout and row cap, and every attempt is appended
to a JSONL audit log. It steers to permission-aware `v_acm_item*` views over
legacy `v_acm_alert*`.

## See also

- CLI: [`actone-data`](../cli/actone-data.md)
- Bucket: [data](../buckets/data.md)
- Agent: [ActWise Data](../agents/data.md)
