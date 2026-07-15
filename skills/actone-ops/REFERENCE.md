# ActOne Ops — Reference

Deeper notes for the `actone-ops` skill. Load this only when the SKILL.md summary
isn't enough (spec resolution, ActOne quirks, version handling, worked examples,
write-gate rationale).

---

## 1. Architecture (one engine, two surfaces)

| Module | Role |
|--------|------|
| `actone/client.py` | `ActOneClient`: login (CSRFTOKEN + cookie), version detect, request execution, ActOne quirks. |
| `actone/registry.py` | Build a searchable operation index from an OpenAPI spec; `search` / `list_ops` / `grouped` / `describe` / `tags`. |
| `actone/invoke.py` | `precheck` (offline existence + read-only gate) → build request → execute → summarize. |
| `actone/cli.py` | `actone ops` Typer sub-app (search/list/describe/tags/call/version). |
| `actone_mcp/server.py` | FastMCP server exposing the same surface as MCP tools (stdio). |

The CLI and MCP are thin shells over the **same** registry + invoke engine, so they
behave identically and inherit the same read-only gate.

## 2. Discovery vs. static tools (why this design)

The common "≤25 tools or the model degrades" rule is a property of **static tool
registration** (every tool's schema sits in the prompt each turn). This skill uses
**discovery**: ~5 meta-tools (`search_ops` → `describe_op` → `invoke_op`, plus
`list_ops`/`list_tags`). Tool-selection context stays flat no matter how large the
ActOne surface is, and it tracks whatever the **target instance** actually exposes
(the registry is built from that instance's spec, not a hard-coded list).

A current ActOne exposes ~149–217 operations across ~25 tags (Diagnostics, Work
Items, Policy Manager, Access Control, Forms, Network Analytics, …). Use `list_tags`
/ `actone ops tags` to see the live breakdown.

## 3. Spec resolution (where the operation list comes from)

`actone/registry.resolve_spec` tries, in order:

1. **Explicit** — `--spec PATH` or `ACTONE_SPEC` env var.
2. **Cached** — newest matching file under `<workdir>/postman/specs/`
   (`*.oas3.json` → `*.oas3.yaml` → `*.json` → `*.yaml`, newest mtime first).
3. **Bundled** — the current spec shipped in the package
   (`actone/data/ActOne_Extend_Rest_APIs.bundled.yaml`).

This makes discovery work **offline** out of the box, and lets you point at a freshly
downloaded live spec when you have one (`actone fetch-spec` from the actone-api-suite
skill writes into `postman/specs/`).

> **method ≠ intent.** read/write is seeded from the HTTP method (GET/HEAD = read,
> else write). Many ActOne **POST** endpoints are actually *searches* — they are
> classified `write` and therefore gated in P1. This is conservative on purpose; a
> later capability profile can reclassify specific POST-searches as reads.

## 4. Auth & version detection

`call`/`version` perform:
1. `POST /api/public/v1/auth/login` with `{username, password}` (JSON) →
   response header **CSRFTOKEN** + a `JSESSIONID` cookie (kept in a cookie jar).
2. Authed requests carry the `CSRFTOKEN` header and the session cookie.
3. Version via `GET /api/v1/system/diagnostics` → `content.acmVersion` (or
   `rcmVersion`) plus a `servicePackVersion` regex → e.g. `10.1.0_SP5`.

Public endpoints (`/api/public/...`) are handled so they don't clobber the authed
session.

## 5. ActOne quirks the engine handles for you

- **Tomcat raw-JSON rejection.** Raw `{ } [ ] "` in a query string is percent-encoded
  before sending (Tomcat 400s otherwise).
- **415 → multipart retry.** If a JSON body is rejected with HTTP 415, the request is
  retried as `multipart/form-data` automatically.
- **Header discipline.** Authed calls send `CSRFTOKEN` (no stray `Accept` that some
  endpoints dislike); content-type defaults to JSON for bodies.

These mirror the proven quirks catalog from the build-time pipeline (see
`postman/README.md`).

## 6. Parameter model

`describe` returns each parameter's `name`, `in` (path/query/header), `required`,
`type`, and a `requestBody.example` when a body is needed.

Passing values:
- **CLI:** `--p name=value` (repeatable), or `--params '{"k":"v"}'` for a JSON blob,
  or `--body '{"...":...}'` for the request body.
- **MCP:** a single flat `params` dict; path/query/header by name; request body under
  the reserved key `"body"`.

Path params are substituted into the URL and are **required** — a missing one raises
`missing required path params` *before* any network call.

## 7. The read-only gate (P1)

`invoke.precheck` runs **before login** and refuses any operation classified `write`:

```
operation 'getAlertDetailsPOST' is a WRITE (POST /RCM/api/v1/work-items-details/{alertIdentifier})
and is gated in P1 (read-only). Writes await the attribution-wall decision.
```

Rationale: writes against a live fraud/AML platform need an **attribution wall**
(who/why/audit) and confirmation UX. That is deferred to P2. Until then, this skill
is safe to point at production for inspection.

Agents must **not** try to bypass the gate (e.g. by hand-rolling a raw HTTP call).
If a task genuinely needs a write, report that it's gated and stop.

## 8. Worked examples (verified no-input reads)

```
actone ops describe getWorkItemTypes        # read, no params, no body
actone ops call getWorkItemTypes            # -> {"status":200,"ok":true,"body":[...]}

actone ops describe getACMLicenseInfo       # read, no params
actone ops call getACMLicenseInfo

actone ops list --tag Diagnostics --reads-only   # 22 safe diagnostics reads
```

With a path param:
```
actone ops describe getAlertDetailsGET      # requires path param 'alertIdentifier'
actone ops call getAlertDetailsGET --p alertIdentifier=12345 --p includeNotes=true
```

MCP equivalents:
```
search_ops(query="work item types", reads_only=true)
describe_op(operation_id="getWorkItemTypes")
invoke_op(operation_id="getWorkItemTypes")
invoke_op(operation_id="getAlertDetailsGET", params={"alertIdentifier":"12345"})
```

## 9. MCP wiring

`.vscode/mcp.json` entry (already present in this repo):

```json
"actone-ops": {
  "type": "stdio",
  "command": "actone-mcp",
  "cwd": "${workspaceFolder}",
  "envFile": "${workspaceFolder}/postman/.env"
}
```

For other agents, register a stdio MCP server that runs `python -m actone_mcp.server`
(or the `actone-mcp` console script) with `ACTONE_URL/USER/PASSWORD` in its env. The
server logs in lazily on the first `invoke_op`; `search_ops`/`list_ops`/`describe_op`/
`list_tags` need no credentials.

## 10. Environment variables

| Variable | Used by | Meaning |
|----------|---------|---------|
| `ACTONE_URL` / `ACTONE_USER` / `ACTONE_PASSWORD` | `call`, `version`, `invoke_op` | Instance + login. Process env wins over `<workdir>/.env`. |
| `ACTONE_SPEC` | registry (CLI + MCP) | Explicit spec path; otherwise cached-then-bundled. |
| `ACTONE_WORKDIR` | all | Base dir for `.env` and `postman/specs/`. Defaults to the current directory. |

## 11. Roadmap (so you can set expectations)

- **P1a (done):** discovery engine + CLI + MCP, **read-only**.
- **P1b:** harden ranking/summarization/error mapping; ship this skill.
- **P2:** guarded **writes** (confirmation + audit) behind the attribution wall.
- **P3:** Remote Client (Java) bridge for non-REST surfaces (Cases, ImportExport,
  Blotter/Asynch) where the SOAP API is the only option.

See `docs/components/ops/2026-06-29-actone-ops-design.md` for the full design.
