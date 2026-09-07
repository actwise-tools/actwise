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
| `ops` | Runtime spec-driven discovery over the Extend REST API (`search`/`list`/`describe`/`call`/`tags`/`version`). Reads open; writes gated (opt-in). |
| `ops soap` | Curated ActOne **SOAP** admin ops (`list`/`describe`/`call`) — the admin slice the REST API lacks. |
| `ops designer` | Design-time **SOAP** surface (ActOne Designer): catalog-driven `search-types`/`describe-type`/`search-ops`/`get`/`list`/`constraints`/`create`/`create-ddq`/`create-alert-type`/`update`/`clone`/`remove`/`validate`/`call`. Writes gated. |
| `ops smoke` | Pre-ship health check — drives the *actual MCP tool functions* across three layers (reads+auto-fixtures, opt-in write lifecycles, offline write-gating sweep). |

## MCP server

`actone-mcp` (FastMCP) surfaces the runtime discovery loop.

| Tool | Purpose |
|------|---------|
| `search_ops` | Keyword search over operations. |
| `list_ops` | Enumerate the entire operation surface (uncapped; `--tag`, `--reads-only`). |
| `describe_op` | Params, request-body example, read/write access. |
| `invoke_op` | Run a **read** (GET) operation — writes are gated. |
| `list_tags` | Functional domains + operation counts. |
| `list_soap_operations` / `invoke_soap_operation` | List / invoke the curated SOAP admin ops (writes gated). |
| `list_environments` | Configured ActOne environments (never shows passwords). |

### Designer (SOAP) tools

The same server also exposes the **ActOne Designer** config surface (design-time SOAP)
through a small set of catalog-driven, generic tools — one engine over 275 object types
instead of a static tool per type.

| Tool | Purpose |
|------|---------|
| `designer_search_types` / `designer_describe_type` | Discover creatable/editable object types; describe a type's fields, `references` (FKs that must pre-exist), and `composes` (nested beans). |
| `designer_search_operations` | Find a raw catalog SOAP operation across the Axis services (offline). |
| `designer_get_object` / `designer_list_objects` | Read a Designer object or list a type. |
| `designer_get_remove_constraints` | List an object's delete constraints (READ). |
| `designer_create_object` / `designer_update_object` / `designer_remove_object` | Generic write over any type (gated). |
| `designer_clone_object` | Copy an object under a new identifier with field overrides (gated). |
| `designer_validate_object` | Server-side validate a payload without saving (READ). |
| `designer_call_operation` | Escape hatch: invoke any catalog SOAP op (reads free; writes gated). |
| `create_drill_down_query` / `create_alert_type` | Typed convenience wrappers (gated). `create_case_type` also exists but is **legacy** (modern config uses case items). |

> **REST-first convention.** SOAP/Designer covers the **design-time** surface the REST
> Extend API does not. Whenever a REST equivalent exists for what you need (see
> `search_ops`/`describe_op`/`invoke_op`), **prefer REST** — reach for `designer_*`
> (SOAP) only for design-time objects with no REST operation. This keeps runtime work on
> the supported, discoverable REST loop and confines SOAP to configuration authoring.

> **Grounding convention.** The catalog gives a type's field *shape*, not the product
> *procedure*. `designer_describe_type` returns a `grounding` block; before authoring,
> follow its `suggestedQueries` into the **ActWise docs MCP** (docenter `search_docs`/
> `get_page`, aka `search_actimize_docs`) to learn the setup **sequence**, prerequisites,
> and server-enforced mandatory fields the catalog can't express (e.g. a DrillDownQuery
> needs an existing JDBC connection), then create any `references` objects first.


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
