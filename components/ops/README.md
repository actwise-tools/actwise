# ActOne Ops (components/ops)

Turn a live ActOne instance into a discoverable, quirk-aware REST surface — Postman collections plus spec-driven runtime ops. Packages: `actone`, `actone_mcp`, `postman` (Node tooling). CLIs: `actone` (incl. the `ops` subcommand). MCP: `actone-mcp`. Skill(s): `skills/actone-ops` (+ `actone-api-suite`).

## Overview

Ops is component **C-O (ActOne Ops)** in the
[ecosystem blueprint](../../docs/2026-06-25-actwise-ecosystem-blueprint.md), built the
"generate-don't-hand-write" way from the ActOne **Extend REST API** OpenAPI spec. The
`actone` CLI has two halves: **build-time** (`fetch-spec`/`generate`/`provision`/`sanitize`/
`review` → Postman collections, portman contract tests, config-review reports) and
**run-time** (`actone ops` — a `search → describe → call` discovery loop over the live API,
read-only in P1). `actone_mcp` exposes the runtime loop to MCP agents; `postman/` holds the
JS contract tooling and the hard-won ActOne quirks catalog.

## Quick start

```powershell
uv tool install "git+ssh://git@github.com/vinayguda/actwise.git"   # puts actone on PATH
actone ops search "work item types"           # offline discovery over the bundled spec
actone ops describe getWorkItemTypes
actone provision --url http://HOST:8080/RCM --user admin --password pw --push   # spec → collection
```

## CLI reference

Run `actone <command> --help` for flags.

| Command | Purpose |
|---------|---------|
| `fetch-spec` | Log in, detect version, download the live OpenAPI spec (auto-converts Swagger 2.0 → OAS3). |
| `generate` | Turn an OpenAPI spec into a categorized, quirk-aware Postman collection. |
| `provision` | Orchestrate `fetch-spec` → `generate` → optional `--push` to a Postman workspace. |
| `sanitize` | Flatten self-referential enums / break `$ref` cycles → a portman-safe spec. |
| `review` | Read-only config review of a live instance → Markdown report. |
| `ops` | Runtime spec-driven discovery over the Extend REST API (`search`/`list`/`describe`/`call`/`tags`/`version`). Read-only in P1. |

## MCP server

`actone-mcp` (FastMCP) surfaces the runtime discovery loop.

| Tool | Purpose |
|------|---------|
| `search_ops` | Keyword search over operations. |
| `list_ops` | Enumerate the entire operation surface (uncapped; `--tag`, `--reads-only`). |
| `describe_op` | Params, request-body example, read/write access. |
| `invoke_op` | Run a **read** (GET) operation — writes are gated. |
| `list_tags` | Functional domains + operation counts. |

**How to run.** stdio: `actone-mcp`. HTTP: `python -m uvicorn actone_mcp.server:app --port 8765`
(endpoint `/mcp`, health `/healthz`).

```jsonc
// VS Code — .vscode/mcp.json  ("servers": { … })
{ "actone-ops": { "type": "stdio", "command": "actone-mcp",
                  "cwd": "${workspaceFolder}", "envFile": "${workspaceFolder}/.env" } }

// Claude Code — .mcp.json  ("mcpServers": { … })
{ "actone-ops": { "type": "stdio", "command": "actone-mcp" } }
```

## Skill

[`skills/actone-ops/`](../../skills/actone-ops/) (`SKILL.md` + `REFERENCE.md`) drives the
`actone ops` discovery loop against a **live** ActOne. The separate `actone-api-suite` skill
covers **building/pushing Postman collections**. Teammates install via
`uv tool install "git+ssh://git@github.com/vinayguda/actwise.git"`. An agent triggers
`actone-ops` when the user wants to query/inspect a running ActOne (list/search operations,
describe params, call a read op, check the version) — not for docs (use `actimize-docenter`).

## Configuration

Config search order: `$ACTWISE_CONFIG_DIR` → cwd → `~/.actwise` → dev repo root.

| File / env var | Purpose | Location |
|----------------|---------|----------|
| `actone-ops.yaml` (`actone-ops.example.yaml`) | ActOne instance/environment catalog + per-env write gate | repo root (gitignored) |
| `actone-ops.secrets.yaml` (`.secrets.example.yaml`) | Per-environment passwords | repo root (gitignored) |
| `<WORKDIR>/.env` (`ACTONE_URL/USER/PASSWORD`, `ACTONE_SPEC`, `POSTMAN_API_KEY`, `POSTMAN_WORKSPACE_ID`) | Default creds + Postman push settings | `ACTONE_WORKDIR` or cwd (e.g. `postman/.env`) |
| `ACTONE_WORKDIR`, `ACTONE_PROXY_API_KEY`, `ACTONE_ALLOW_WRITES` | Per-run artifact dir; HTTP MCP key; global write kill-switch | env |

## Auth

ActOne login is CSRFTOKEN + session cookie (handled by `actone/client.py`). Creds come from
`--url/--user/--password`, `ACTONE_*`, or `actone-ops.yaml` + `actone-ops.secrets.yaml`. The
`actone-mcp` HTTP transport takes an `X-API-Key` when `ACTONE_PROXY_API_KEY` is set. **Never
commit** `postman/.env`, `actone-ops.secrets.yaml`, or live credentials; rotate a leaked
Postman key in Postman → Settings → API keys. Writes are default-deny per environment.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `No such command 'ops'` | Stale uv snapshot — `uv tool install . --force` (or `pip install -e .`). |
| `unknown operationId` | Never guess — `actone ops search "…"` then `describe`. |
| `operation '…' is a WRITE … gated` | Expected (read-only P1); do not bypass. |
| `415 Unsupported Media Type` on save-step | Endpoint needs `multipart/form-data` — see the quirks catalog in [`postman/README.md`](postman/README.md). |
| `400 Invalid character in request target` | Tomcat rejects raw `{ } [ ] "` — pre-encode JSON query params. |
| `call` hangs / times out | Instance unreachable (VPN); offline `search`/`list`/`describe` still work. |

## Design docs & further reading

- [`actone/README.md`](actone/README.md) · [`postman/README.md`](postman/README.md) (quirks catalog)
- [`../../docs/components/ops/2026-06-29-actone-ops-design.md`](../../docs/components/ops/2026-06-29-actone-ops-design.md)
- [`../../docs/components/ops/ActOne-Ops-Tutorial.md`](../../docs/components/ops/ActOne-Ops-Tutorial.md)
- [`../../docs/components/ops/2026-07-10-actone-soap-services.md`](../../docs/components/ops/2026-07-10-actone-soap-services.md)
- [`../../docs/runbooks/2026-07-10-actwise-mcp-tunnel-runbook.md`](../../docs/runbooks/2026-07-10-actwise-mcp-tunnel-runbook.md)
