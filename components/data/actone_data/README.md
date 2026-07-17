# ActWise Data

Read-only **natural-language-to-SQL** engine over the NICE Actimize ActOne
`v_acm_*` PostgreSQL reporting views. The **host LLM writes the SQL**; this engine
only **grounds → validates → executes** it — it holds no LLM key and has no write path.

```
get_schema_summary  →  list_views / describe_view  →  validate_sql  →  run_query
   (orient, once)         (find & inspect names)        (dry-run)       (execute)
```

The same engine is surfaced three ways:

| Surface | Package / path | Entry point |
|---|---|---|
| **CLI** | `actone_data/` | `actone-data` (`py -m actone_data`) |
| **MCP server** | `actone_data_mcp/` | `actone-data-mcp` (`py -m actone_data_mcp.server`) |
| **Agent skill** | `skills/actone-data/SKILL.md` | loaded by host agents (Copilot, Claude, Copilot Studio) |

Design docs: [`docs/components/data/2026-07-08-actone-data-mvp-plan.md`](../docs/components/data/2026-07-08-actone-data-mvp-plan.md)
and [`docs/components/data/HANDOFF-actone-data-mvp.md`](../docs/components/data/HANDOFF-actone-data-mvp.md).

---

## Architecture

The host model never touches the database directly. It calls small, typed tools that:

1. **Ground** — a bundled *schema pack* (JSON) gives the model the exact view names,
   columns, types, FK graph, view families, and preference rules **without a DB round-trip**,
   so it never invents a view or column name.
2. **Validate** — a 7-step `sqlglot` guardrail pipeline (below) parses the candidate SQL,
   proves it is a single read-only `SELECT` over `v_acm_*` views only, and injects a `LIMIT`.
3. **Execute** — the validated SQL runs inside a **read-only transaction** with a
   **statement timeout** and a **row cap**; every attempt (including rejections) is
   appended to a JSONL **audit log**.

There are **no write tools**. INSERT/UPDATE/DELETE/DDL/COPY/SET/CALL, multi-statement
input, `SELECT … INTO`, `FOR UPDATE/SHARE`, non-`v_acm_*` tables, and tableless probes
(`SELECT pg_sleep(…)`) are all rejected before execution.

### View-family preference

ActOne unifies alerts and work items under the **item** family. The engine steers the
model to the **permission-aware `v_acm_item*` views** and marks the legacy
`v_acm_alert*` views as `preferred: false` (alerts-only, not permission-aware —
legacy use only). `describe_view` also returns the preferred item equivalent for any
legacy view via `related_views`.

---

## Install

```powershell
py -m pip install -e .        # installs the actone-data / actone-data-mcp entry points
# or run without installing:
py -m actone_data --help
```

Requires Python 3.11+ and (for `validate`/`run`/`ping`) a reachable ActOne PostgreSQL DB.
The grounding commands (`schema show/summary`) work **offline** from the bundled pack.

---

## CLI

Run `actone-data --help` (or `py -m actone_data`). All commands accept a connection via
`--profile` / `--dsn` / discrete `--host/--port/--name/--user/--password/--schema` flags.

| Command | Purpose |
|---|---|
| `actone-data ping` | Test the DB connection: server version, schema, and the ActOne sentinel check. |
| `actone-data version` | Detect the ActOne product version from the DB (falls back to the bundled doc version). |
| `actone-data schema list` | List the live `v_acm_*` views and their column counts (`--names-only` for bare names). |
| `actone-data schema build` | Build the schema pack (introspection + doc enrichment) and write JSON. |
| `actone-data schema show <view>` | Show a view's family / preference / FKs and columns from the pack. |
| `actone-data schema summary` | Summarize the pack (view/column/coverage/preference counts). |
| `actone-data docs enrich` | Parse the `v_acm_*` doc pages (descriptions + FK graph); `--page <view>` to inspect one. |
| `actone-data query validate "<sql>"` | Dry-run the guardrail pipeline on a SQL string (no execution). |
| `actone-data query run "<sql>"` | Validate **and** execute a read-only SELECT; `--format table\|json\|csv`, `--question` for audit. |
| `actone-data audit tail` | Show the most recent audit records (`--n`). |
| `actone-data eval` | Run the NL→SQL eval set through the guardrail + execute path and print a scoreboard. |

### Examples

```powershell
actone-data ping
actone-data schema summary
actone-data schema show v_acm_items
actone-data query validate "SELECT item_category, count(*) FROM v_acm_item_types GROUP BY 1"
actone-data query run "SELECT item_category, count(*) FROM v_acm_item_types GROUP BY 1" -f table
actone-data audit tail -n 10
```

---

## Configuration

Precedence: explicit `--dsn`/flags **>** `ACTONE_DB_URL` / `ACTONE_DB_*` env **>** named
profile in `actone-data.yaml` **>** built-in `local` default.

The built-in **`local`** profile mirrors the `actone_local` Docker DB defaults
(`localhost:5432`, db `actone`, user `actone`, schema `actone`), so a laptop running
`actone-local db-up` needs **zero config**. Passwords are never read from profile YAML —
supply them via `ACTONE_DB_PASSWORD` or `--password`.

| Env | Meaning |
|---|---|
| `ACTONE_DB_URL` / `ACTONE_DB_HOST/PORT/NAME/USER/PASSWORD/SCHEMA` | DB connection. |
| `ACTONE_DATA_PROFILE` | Named profile (default `local`). |
| `ACTONE_DATA_PACK` | Override the schema-pack path. |
| `ACTONE_DATA_AUDIT_LOG` | Override the audit log path (default `~/.actone-data/audit.jsonl`). |

---

## Guardrail pipeline (7 steps)

Implemented in `actone_data/guardrails.py`, shared by `query validate`, `query run`,
and the MCP `validate_sql` / `run_query` tools:

1. **Parse** the SQL with `sqlglot` (postgres dialect).
2. **Exactly one statement** — reject multi-statement input.
3. **Root must be SELECT/UNION** (CTEs allowed) — no DML/DDL/COPY/SET/CALL.
4. **Reject `SELECT … INTO` and `FOR UPDATE/SHARE`.**
5. **Allowlist walk** — every real table must be a `v_acm_*` view (CTE names excluded);
   at least one real table is required (blocks tableless probes).
6. **Auto-LIMIT** — inject or clamp to `min(max_rows, cap)` (cap 1000).
7. **Re-render** lowercase/unquoted via the postgres dialect (the canonical `sql_used`).

Execution then runs the re-rendered SQL in a `READ ONLY` transaction with a statement
timeout, and appends the attempt to the audit log.

---

## Schema pack

`actone-data schema build` introspects the live views and enriches them from the ActOne
doc bundle (descriptions + FK graph), writing `actone_data/data/schema-pack-actone-<ver>.json`.
The pack is what the grounding tools serve — so `get_schema_summary` / `list_views` /
`describe_view` work with no DB round-trip. A pack for ActOne 10.2 is bundled.

---

## MCP server

`actone_data_mcp/` exposes the engine as an MCP server (stdio for local clients, or
Streamable HTTP for containers / Copilot Studio) with five read-only tools:
`get_schema_summary`, `list_views`, `describe_view`, `validate_sql`, `run_query`.

```powershell
# stdio (Copilot CLI, VS Code, Claude)
py -m actone_data_mcp.server

# Streamable HTTP (remote clients / Copilot Studio)
py -m uvicorn actone_data_mcp.server:app --host 0.0.0.0 --port 8766
#   endpoint http://localhost:8766/mcp    health http://localhost:8766/healthz
```

Set `ACTONE_DATA_PROXY_API_KEY` to require the `X-API-Key` header on any shared/tunnelled
deployment. See [`actone_data_mcp/README.md`](../actone_data_mcp/README.md) for the tool
contract, and the Copilot Studio wiring notes below.

---

## Agent skill

`skills/actone-data/SKILL.md` is the behavior spec for host agents: it encodes the
`get_schema_summary → list_views/describe_view → validate_sql → run_query` loop, the
item-view preference, the read-only refusal rules, and output hygiene. Loaded by Copilot,
Claude, or a Copilot Studio agent.

- For the **Extend REST API** (invoking ActOne operations / work-item actions), use `actone-ops`.
- For **product documentation**, use `actimize-docenter`.

---

## Copilot Studio deployment

The MCP server can back a Copilot Studio agent (**ActWise Data**) so business users can
ask ActOne data questions in natural language. High-level wiring:

1. Run the Streamable-HTTP server with `ACTONE_DATA_PROXY_API_KEY` set.
2. Expose it over a tunnel: `cloudflared tunnel --url http://localhost:8766`.
3. Point the custom connector's `host` at the tunnel hostname; create a connection with the API key.
4. Add the MCP tool to the agent, paste the NL-to-SQL instructions, set the connection
   auth mode to **Maker**, and publish.

`actone_data_mcp/connector-swagger.json` + `connector-properties.json` are the connector
definition. See the plan doc's "Copilot Studio wiring" section for the full playbook.

> **Note:** the ephemeral `cloudflared` quick tunnel is fine for dev/testing but changes
> hostname on every restart — swap in a stable/named host for durable operation.

---

## Audit

Every query attempt — successful or rejected — is appended as one JSON line to
`~/.actone-data/audit.jsonl` (override with `ACTONE_DATA_AUDIT_LOG`). Inspect it with
`actone-data audit tail`.
