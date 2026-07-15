# data bucket

> Read-only natural-language-to-SQL over the ActOne `v_acm_*` PostgreSQL
> reporting views — the host LLM writes the SQL; this engine only grounds,
> validates, and executes it.

## Goal

data answers questions about ActOne with **real numbers and rows**. The engine
holds **no LLM key** and has **no write path**: a bundled schema pack grounds the
model on exact view/column names, a `sqlglot` guardrail proves a candidate query
is a single read-only `SELECT` over `v_acm_*` views, and execution runs in a
`READ ONLY` transaction with a statement timeout and row cap. Every attempt is
appended to a JSONL audit log. It prefers permission-aware `v_acm_item*` views
over legacy `v_acm_alert*`.

## Packages

| Package | Role |
|---------|------|
| `actone_data` | The `actone-data` CLI plus the core engine: schema pack, `sqlglot` guardrail, DB layer, config/profiles, and audit log. |
| `actone_data_mcp` | The `actone-data-mcp` MCP server — exposes the schema/validate/run tools to agents. |

## CLI / MCP / Skills / Agent

- **CLI:** [`actone-data`](../cli/actone-data.md) — `ping`, `version`, `schema`,
  `query validate` / `query run`, `audit`, `env`, `docs`, `eval`.
- **MCP:** [`actone-data-mcp`](../mcp/actone-data-mcp.md) — five read-only tools:
  schema summary, list/describe views, validate SQL, run query.
- **Skill:** [`actone-data`](../skills/actone-data.md) — the behavior spec for the
  `get_schema_summary → list/describe → validate → run` loop.
- **Agent:** [ActWise Data](../agents/data.md) — grounded on
  `actone-data-mcp` via a self-hosted, API-key-gated MCP endpoint.

## Key concepts

- **Grounding, not guessing.** A bundled schema pack provides exact view and
  column names; the model must call `get_schema_summary` / `describe_view` before
  naming a view, so it never invents identifiers.
- **7-step guardrail.** `sqlglot` enforces a single read-only `SELECT`/`UNION`
  over the `v_acm_*` allowlist and injects/clamps a LIMIT; the guardrail always
  re-runs inside `run_query`, so it can't be bypassed.
- **Read-only execution.** Queries run in a `READ ONLY` transaction with a
  statement timeout and row cap — no DML/DDL, no multi-statement.
- **Item views preferred.** Legacy `v_acm_alert*` views are not permission-aware;
  the engine steers to the unified, permission-aware `v_acm_item*` equivalents.
- **Audited.** Every attempt (accepted or rejected) is appended to a JSONL audit
  log with the originating question.

## See also

- [Buckets hub](index.md)
- MCP: [`actone-data-mcp`](../mcp/actone-data-mcp.md)
- Related buckets: [ops](ops.md) (live REST operations) · [docenter](docenter.md) (documentation)
