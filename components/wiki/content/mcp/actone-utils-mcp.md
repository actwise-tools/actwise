# actone-utils-mcp

> Exposes ActOne's server-side Java maintenance utilities as a typed,
> discoverable `list → describe → run` loop — dry-run by default, real runs gated.

## Goal

Let an agent discover and (carefully) run ActOne's server-side utilities
(Blotter Maintenance, DART runner, import/export, archive/delete/render alerts &
cases, policy-type deployment, dbupgrade, …) without hand-assembling `.bat/.sh`
lines. Every utility and its parameters come from a declarative catalog verified
against the shipped `<tool>_readme.txt`. `run_util` **assembles the exact command
and defaults to a dry run**; a real state-changing run needs a server-side gate.

## How it fits

- **Bucket:** [utils](../buckets/utils.md).
- **Shares code with:** the [`actone-utils`](../cli/actone-utils.md) CLI — the MCP
  tools call the same catalog, runner, and execution-backend abstraction
  (`local` / `ssh` / `winrm` / `container`).
- **Consumed by:** local IDE agents over stdio (VS Code, Claude Code, the GitHub
  Copilot CLI). This bucket ships **no Copilot Studio agent** grounded on it
  (the utils row in the project map has no agent); the separate ActWise Utility
  Copilot agent is a productivity toolkit whose capabilities are enabled
  incrementally.

## Tools exposed

Enumerated from `components/utils/actone_utils/server.py` — four `@mcp.tool`
registrations:

| Tool | What it does |
|------|--------------|
| `search_utils` | Discover utilities by keyword (name / title / tool / tags / summary). |
| `list_utils` | Enumerate the full utility catalog with each utility's read/write access and tags. |
| `describe_util` | Show one utility's parameters, access, source doc, and notes (build the `params` for `run_util`). |
| `run_util` | Assemble and (optionally) run a utility on the configured backend. `dry_run=true` by default; real state-changing runs also require `ACTONE_UTILS_ALLOW_RUN` to be truthy. |

## Transport & run

Runs as **stdio or HTTP**. Console script from `pyproject.toml`
(`actone-utils-mcp = "actone_utils.server:main"`):

```powershell
actone-utils-mcp
# or, as an ASGI HTTP app (serves /mcp, health /healthz):
python -m uvicorn actone_utils.server:app --port 8766
```

The HTTP transport is **self-hosted**; when `ACTONE_UTILS_API_KEY` is set it
enforces an `X-API-Key` header.

## Safety

**Dry-run by default, gated writes.** `run_util` returns the exact command that
*would* execute without running it; a real run of a state-changing utility
additionally requires `ACTONE_UTILS_ALLOW_RUN` set truthy in the server
environment — the model cannot lift the gate itself. Read-only utilities and
dry-run assembly are always available.

## See also

- CLI: [`actone-utils`](../cli/actone-utils.md)
- Bucket: [utils](../buckets/utils.md)
