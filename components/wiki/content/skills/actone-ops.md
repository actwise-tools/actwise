# ActOne Ops

> Operate a live ActOne instance over its Extend REST API through a `search → describe → call` discovery loop — read-only — via the `actone ops` CLI and the `actone-ops` MCP server.

## Goal
A running ActOne exposes 200+ REST operations, and hard-coding a tool per operation is unmanageable. This skill teaches an AI agent to discover the right operation from a spec-driven registry, inspect its parameters, and invoke read operations against a live instance — turning "what does this ActOne expose and what does operation X return?" into a safe, guided loop.

## How it fits
This skill drives the run-time half of the `actone` CLI (`actone ops …`) and the `actone-ops` MCP server in the **ops** bucket. It complements **actone-api-suite**, which builds Postman collections and contract tests from the same Extend REST API. For raw SQL over the reporting views use **actone-data**; for server-side Java utilities use **actone-utils**.

## When to use it
Activate when the user wants to interact with a live ActOne (not just docs):
- "What REST operations does this ActOne expose?" / "list/search the API".
- "Show me the work-item types / licenses / diagnostics / policies".
- "Describe operation X — what params does it need?".
- "Call `<operation>` and summarize the result".
- "What ActOne version am I connected to?".
- Driving ActOne via an MCP agent (Copilot, Claude).

## What it does
- **Finds** operations without guessing an operationId: `actone ops search "<keywords>"`, `actone ops list --tag <domain>`, `actone ops tags`.
- **Inspects** an operation: `actone ops describe <operationId>` (params, body example, read/write access).
- **Calls** read (GET) operations: `actone ops call <operationId> --p key=value …`.
- Detects the connected version (`actone ops version`).
- Exposes the same engine to AI agents via MCP tools: `search_ops`, `list_ops`, `describe_op`, `invoke_op`, `list_tags`.
- Discovery (`search`/`list`/`describe`/`tags`) works offline against the bundled/cached spec; only `call`/`version` connect and log in.

## Install / enable
Skills follow the open Agent Skills spec and install via the `skills` CLI:
```powershell
npx skills add https://github.com/vinayguda/actwise.git --skill actone-ops -a claude-code -g
```
Skills are instructions only — they drive the ActWise CLIs, so install the `actwise` distribution too. This skill requires the **`actone`** console script and the **`actone-mcp`** server (registered in `.vscode/mcp.json` as `actone-ops`). Set `ACTONE_URL`/`ACTONE_USER`/`ACTONE_PASSWORD` (or pass `--url/--user/--password`) for live calls.

## Walkthrough
- *"What operations relate to alert details?"* → `actone ops search "alert details"`, then `describe`.
- *"Show me the work-item types on this instance."* → `actone ops call getWorkItemTypes` and summarize the JSON.
- *"What ActOne version am I connected to?"* → `actone ops version`.

## Limits & safety
- **Read-only.** `call`/`invoke_op` run only read (GET) operations; writes (POST/PUT/DELETE/PATCH) are refused before any login — you cannot change ActOne data with this skill.
- Never invent operationIds — always `search`/`list` first, then `describe`, then `call`.
- If a `call` hangs the instance is unreachable (network/VPN); offline discovery still works against the bundled spec.

## See also
- CLI: [../cli/actone.md](../cli/actone.md)
- MCP: [../mcp/actone-mcp.md](../mcp/actone-mcp.md)
- Bucket: [../buckets/ops.md](../buckets/ops.md)
- Related skills: [actone-api-suite](actone-api-suite.md), [actone-data](actone-data.md), [actone-utils](actone-utils.md)
