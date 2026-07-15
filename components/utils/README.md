# ActOne Utilities (components/utils)

Run ActOne's server-side Java maintenance utilities (the full 10.2 `Utilities/bin` set) as typed, discoverable, gated commands over local/ssh/winrm/container backends. Packages: `actone_utils`. CLIs: `actone-utils`. MCP: `actone-utils-mcp`. Skill(s): `skills/actone-utils`.

## Overview

Utils is component **C-U (Utilities runner)** in the
[ecosystem blueprint](../../docs/2026-06-25-actwise-ecosystem-blueprint.md). Instead of
hand-assembling `.bat/.sh` lines driven by `utilities.env`, it exposes a declarative
**33-utility catalog** (Blotter Maintenance, DART runner, import/export, archive/delete/render
alerts & cases, policy-type deployment, forms, dbupgrade, …) through a `list → describe →
run` loop. Every entry and its parameters are verified against the shipped
`<tool>_readme.txt`. `run` is **dry-run by default**; state-changing runs are gated. An
execution-backend abstraction runs the same utility on `local`, `ssh`, `winrm`, or a
`container` host.

## Quick start

```powershell
uv tool install "git+ssh://git@github.com/vinayguda/actwise.git"   # puts actone-utils on PATH
actone-utils list                              # the full utility catalog (offline)
actone-utils describe dart-runner
actone-utils run dart-runner -s action=execute -s eds_identifier=EDS_ALERTS --dry-run
```

## CLI reference

Run `actone-utils <command> --help` for flags.

| Command | Purpose |
|---------|---------|
| `list` | List all utilities in the catalog. |
| `search` | Search utilities by keyword (name/title/tool/tags/summary). |
| `describe` | Show a utility's parameters, read/write access, and source doc. |
| `run` | Assemble and run a utility — dry-run by default; `--yes` for a real state-changing run. |
| `backends` | Show the available execution backends and their config. |
| `doctor` | Show the effective config: backend, paths, JDK, `utilities.env`. |

## MCP server

`actone-utils-mcp` exposes the same discovery loop.

| Tool | Purpose |
|------|---------|
| `search_utils` | Keyword search over the utility catalog. |
| `list_utils` | Enumerate the full catalog. |
| `describe_util` | Parameters, access, source doc for one utility. |
| `run_util` | Assemble/run a utility; `dry_run=true` by default (real runs need `ACTONE_UTILS_ALLOW_RUN=1`). |

**How to run.** stdio: `actone-utils-mcp`. HTTP: `python -m uvicorn actone_utils.server:app --port 8766`
(endpoint `/mcp`, health `/healthz`).

```jsonc
// VS Code — .vscode/mcp.json  ("servers": { … })
{ "actone-utils": { "type": "stdio", "command": "actone-utils-mcp",
                    "cwd": "${workspaceFolder}", "envFile": "${workspaceFolder}/.env" } }

// Claude Code — .mcp.json  ("mcpServers": { … })
{ "actone-utils": { "type": "stdio", "command": "actone-utils-mcp" } }
```

## Skill

[`skills/actone-utils/`](../../skills/actone-utils/) (`SKILL.md` + `REFERENCE.md`) drives the
`actone-utils` runner: the `list/search → describe → run --dry-run` loop, the read/write
classification, and backend selection. Teammates install via
`uv tool install "git+ssh://git@github.com/vinayguda/actwise.git"`. An agent triggers it when
the user wants to run/preview/inspect an ActOne server-side utility (rematerialize blotters,
run a DART query, import/export/archive/delete alerts or cases, deploy a policy type) — not
the Extend REST API (`actone-ops`) or docs (`actimize-docenter`).

## Configuration

Config search order: `$ACTWISE_CONFIG_DIR` → cwd → `~/.actwise` → dev repo root.
Precedence: dataclass defaults → `actone-utils.yaml` (repo root) → `ACTONE_UTILS_*` env.

| File / env var | Purpose | Location |
|----------------|---------|----------|
| `actone-utils.yaml` | Backend + paths + JDK + `utilities.env` config | repo root |
| `ACTONE_UTILS_BACKEND` (`local`/`ssh`/`winrm`/`container`) | Execution backend | env |
| `ACTONE_UTILS_HOME` / `_DIR` / `_ENV` / `_JDK` | ActOne install root, utilities subdir, `utilities.env`, JDK | env |
| `ACTONE_UTILS_SSH_*` / `_WINRM_*` / `_CONTAINER` / `_DOCKER_BIN` | Per-backend targets | env |
| `ACTONE_UTILS_ALLOW_RUN` / `ACTONE_UTILS_API_KEY` | MCP real-run gate / HTTP `X-API-Key` | env |

## Auth

Utilities authenticate to ActOne via per-utility parameters — the shared **Authentication**
family (`user`/`password`/`auth_mode`/`ntlm_domain`/`encrypted`) and the `-acm=` URL; DB-script
tools (`dbupgrade`, `rcm-users-and-roles`) connect to the database instead. SSH/WinRM
credentials come from `ACTONE_UTILS_SSH_*` / `_WINRM_*`. The HTTP MCP takes `X-API-Key` when
`ACTONE_UTILS_API_KEY` is set. **Never commit** secrets; pass passwords via env/flags, and
always review the dry-run command before `--execute`.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `actone-utils: command not found` | `python -m actone_utils <cmd>`, or `uv tool install "git+ssh://git@github.com/vinayguda/actwise.git"`. |
| Utility name not found | Never guess — `actone-utils search "…"` then `describe`. |
| Real run refused | State-changing utilities need `--yes` (CLI) or `ACTONE_UTILS_ALLOW_RUN=1` (MCP). |
| Run fails: Utilities not on host | Stage `packages/ActOne-10.2.0-Utilities/Utilities/` at `ACTONE_UTILS_DIR` on the execution host. |
| Utility 404s / can't authenticate | ActOne app must be healthy and licensed at the `-acm=` URL. |
| Param not modelled | Pass it raw with `run … --arg <raw>` (repeatable). |

## Design docs & further reading

- [`skills/actone-utils/REFERENCE.md`](../../skills/actone-utils/REFERENCE.md) — full config, catalog schema, adding a utility
- [`../../docs/components/utils/2026-07-09-actone-utilities-runner-design.md`](../../docs/components/utils/2026-07-09-actone-utilities-runner-design.md)
- [`../../docs/runbooks/2026-07-10-actwise-mcp-tunnel-runbook.md`](../../docs/runbooks/2026-07-10-actwise-mcp-tunnel-runbook.md)
