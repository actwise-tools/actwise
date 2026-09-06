---
name: actone-ops
description: Operate a live NICE Actimize ActOne instance over its Extend REST API via the `actone ops` CLI and the `actone-ops` MCP server. Discover operations (search/list/describe) and invoke read (GET) operations against a running ActOne. Use when the user wants to query or inspect a live ActOne system — list or search its REST operations, describe an operation's parameters, call a read operation, fetch work-item types / licenses / diagnostics / policies, check the detected ActOne version, or drive ActOne from an MCP-connected AI agent. Read-only (writes are gated). Not for generating Postman collections — use the actone-api-suite skill for that.
---

# ActOne Ops

Operate a **running** ActOne instance through its Extend REST API. Instead of 149+
static tools, it exposes a **discovery loop** over a spec-driven registry:

```
search / list  →  describe  →  call
   (find)         (inspect)    (run, read-only)
```

Backed by the `actone` CLI (`actone ops ...`) and the `actone-ops` MCP server
(tools: `search_ops`, `list_ops`, `describe_op`, `invoke_op`, `list_tags`).

> **Safety:** read-only. `call`/`invoke_op` run only **read** (GET) operations.
> Writes (POST/PUT/DELETE/PATCH) are **refused before any login** — you cannot
> change ActOne data with this skill.

## When to use

Activate when the user wants to **interact with a live ActOne** (not just docs):
- "What REST operations does this ActOne expose?" / "list/search the API"
- "Show me the work-item types / licenses / diagnostics / policies"
- "Describe operation X — what params does it need?"
- "Call <operation> and summarize the result"
- "What ActOne version am I connected to?"
- Driving ActOne via an MCP agent (Copilot, Claude)

For building/pushing **Postman collections** or contract tests, use **actone-api-suite** instead.
For **product documentation** questions, use **actimize-docenter**.

## The discovery loop (always follow this order)

1. **Find** the operation — never guess an operationId:
   ```
   actone ops search "alert details"      # keyword search
   actone ops list --tag Diagnostics      # browse a whole domain (uncapped)
   actone ops tags                        # list domains + counts
   ```
2. **Inspect** it — read its params, body example, and read/write access:
   ```
   actone ops describe getWorkItemTypes
   ```
3. **Call** it (read-only) — build `--p` from the describe output:
   ```
   actone ops call getWorkItemTypes
   actone ops call getAlertDetailsGET --p alertIdentifier=12345
   ```

## Commands

```
actone ops search "<keywords>" [-n N] [--reads-only] [--spec PATH]
actone ops list   [--reads-only] [--tag NAME] [--group] [--spec PATH]   # ALL ops, no cap
actone ops describe <operationId> [--spec PATH]
actone ops tags   [--spec PATH]
actone ops call   <operationId> [--p key=value ...] [--params JSON] [--body JSON]
                  [--url U] [--user U] [--password P] [--spec PATH]
actone ops version [--url U] [--user U] [--password P]
```

`search` / `list` / `describe` / `tags` work **offline** (bundled/cached spec, no login).
Only `call` / `version` connect and log in. All output is JSON — paste it back to the
user or summarize it.

## MCP tools (same engine, for AI agents)

| Tool | Purpose |
|------|---------|
| `search_ops(query, limit, reads_only)` | Keyword search (limit ≤ 500) |
| `list_ops(reads_only, tag, group)` | Enumerate the **entire** surface (uncapped) |
| `describe_op(operation_id)` | Params, body example, read/write |
| `invoke_op(operation_id, params)` | Run a **read** op (writes refused) |
| `list_tags()` | Domains + counts |

Registered in `.vscode/mcp.json` as `actone-ops`. Start manually with `actone-mcp`.
`params` is a flat dict (path/query/header by name); a request body goes under the key `"body"`.

## Credentials & spec source

- **Creds** (only for `call`/`version`/`invoke_op`): `--url/--user/--password`, else
  `ACTONE_URL` / `ACTONE_USER` / `ACTONE_PASSWORD` (process env wins, then `<workdir>/.env`,
  e.g. `postman/.env`).
- **Spec** (precedence): `--spec` / `ACTONE_SPEC` → cached spec under
  `<workdir>/postman/specs/` → the bundled current spec shipped in the package.

## Install & invocation

Driven by the `actone` CLI (root `pyproject.toml`: `actone = "actone:app"`, `actone-mcp`).
Prefer `actone ops <cmd>`; fall back as noted.

```bash
uv tool install .            # recommended (PATH-clean) — from repo root
# or
pip install -e .             # editable; auto-updates on code changes
# run without installing:
python -m actone.cli ops <cmd>
```

> **uv users:** `uv tool install` freezes a snapshot. If you get *"No such command 'ops'"*,
> refresh it: `uv tool install . --force`. (`pip install -e .` is editable and never needs this.)

## Instructions for the agent

1. **Never invent operationIds.** Always `search`/`list` first, then `describe`, then `call`.
2. **Respect the read-only gate.** If a task needs a write, stop and tell the user it is
   gated (read-only / P1) — do not try to work around it.
3. **Use `describe` to build params.** Path params are required; pass each as `--p name=value`
   (CLI) or in the `params` dict (MCP). Request bodies go under `"body"`.
4. **Summarize JSON results** for the user; surface `status`/`ok` and the key fields.
5. **If a `call` hangs/times out**, the instance is unreachable — `search`/`list`/`describe`
   still work offline against the bundled spec.

## Error handling

| Symptom | Action |
|---------|--------|
| `No such command 'ops'` | Stale uv snapshot — `uv tool install . --force` (or `pip install -e .`). |
| `actone: command not found` | Install via uv/pip, or run `python -m actone.cli ops ...`. |
| `unknown operationId` | Mistyped — run `actone ops search "..."`; the tool suggests close matches. |
| `operation '...' is a WRITE ... gated` | Expected. Read-only; do not bypass. |
| `missing credentials` | Set `ACTONE_*` in `<workdir>/.env` or pass `--url/--user/--password`. |
| `call` hangs / times out | Instance unreachable (network/VPN); offline discovery still works. |
| `missing required path params` | Run `describe` to see required params; add the missing `--p`. |

## Domains (auto-generated)

The live operation surface, grouped by tag. Regenerate from the current spec with
`actone ops sync-skill` (CI gate: `actone ops sync-skill --check`).

<!-- BEGIN GENERATED: actone-ops-domains (run `actone ops sync-skill` to refresh from the spec) -->
| Domain (tag)                             | Operations | Read (GET) |
|------------------------------------------|------------|------------|
| Access Control                           | 12         | 4          |
| Administration                           | 8          | 1          |
| Alert Details REST API                   | 3          | 1          |
| Audit Events                             | 1          | 1          |
| Automation                               | 2          | 0          |
| Configuration Management REST API        | 13         | 7          |
| Data Querying                            | 3          | 2          |
| Diagnostics                              | 27         | 22         |
| Easy Ingest                              | 1          | 0          |
| Entity Insights                          | 4          | 3          |
| Forms                                    | 9          | 2          |
| Migration                                | 3          | 1          |
| Mini-Widget REST API                     | 1          | 1          |
| Miscellaneous                            | 4          | 4          |
| Network Analytics                        | 14         | 6          |
| Notifications REST API                   | 2          | 0          |
| Platform Lists                           | 5          | 1          |
| Plugins                                  | 2          | 2          |
| Policy Manager                           | 27         | 13         |
| Search Repository                        | 3          | 2          |
| System Configuration                     | 17         | 9          |
| User API                                 | 2          | 0          |
| Virtual File System                      | 1          | 0          |
| Work Items                               | 38         | 16         |
| Work Items Metadata                      | 11         | 5          |
| Workflow Restrictions Templates REST API | 8          | 2          |

_217 operations across 26 domains - spec 10.2.0.20. Read (GET) operations are callable; writes are gated (read-only)._
<!-- END GENERATED: actone-ops-domains -->

> This is a snapshot of the **bundled/cached** spec for orientation. The real surface is
> whatever the **target instance** exposes — always confirm live with `actone ops tags`
> / `list_tags`.

## Further reading

- Beginner tutorial: `docs/components/ops/ActOne-Ops-Tutorial.md`
- Command reference: `actone/README.md` (ActOne Ops section)
- Design & roadmap: `docs/components/ops/2026-06-29-actone-ops-design.md`
- Deeper notes (spec resolution, quirks, version handling): [REFERENCE.md](REFERENCE.md)
