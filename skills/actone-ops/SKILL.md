---
name: actone-ops
description: Operate a live NICE Actimize ActOne instance via the `actone ops` CLI and the `actone-ops` MCP server across two surfaces — (1) the runtime **Extend REST API** (discover search/list/describe, then call read operations), and (2) the design-time **ActOne Designer** config surface over SOAP (create/read/update/remove/clone/validate alert & case types, Drill Down Queries, workflows, lists, views, policies) driven by a reflected type catalog. Use when the user wants to query or inspect a live ActOne (REST operations, work-item types, licenses, diagnostics, policies, version) OR author ActOne Designer configuration. Reads are open; all writes (REST POST/PUT/DELETE and Designer create/update/remove/clone) are gated behind an explicit write flag. Prefer REST when a capability exists on both REST and Designer/SOAP. Not for generating Postman collections — use the actone-api-suite skill for that.
---

# ActOne Ops

Operate a **running** ActOne instance through two surfaces:

- **Runtime REST** (Extend API) — a **discovery loop** over a spec-driven registry
  instead of 149+ static tools:

  ```
  search / list  →  describe  →  call
     (find)         (inspect)    (run)
  ```

- **Design-time Designer** (SOAP) — author ActOne configuration (alert/case types,
  **Drill Down Queries**, workflows, lists, views, policies) through a **reflected
  type catalog**:

  ```
  search-types  →  describe-type  →  create / clone / update / remove / validate
     (find)          (inspect)               (author)
  ```

Backed by the `actone` CLI (`actone ops ...`, `actone ops designer ...`) and the
`actone-ops` MCP server (**23 tools**; see the tables below).

> **Safety — reads open, writes gated.** REST `call`/`invoke_op` run **read** (GET)
> operations freely; REST writes (POST/PUT/DELETE/PATCH) and all Designer writes
> (`create`/`update`/`remove`/`clone`) are **refused unless writes are explicitly
> enabled** — `--allow-write` (CLI), `ACTONE_ALLOW_WRITES=true`, or an env profile
> with `allow_writes: true`. Read operations never need the flag.

> **REST-first convention.** When a capability exists on **both** the runtime REST
> API and the Designer/SOAP surface, **prefer REST**. Use Designer/SOAP only for
> design-time objects REST does not expose.

## When to use

Activate when the user wants to **interact with a live ActOne** (not just docs):
- "What REST operations does this ActOne expose?" / "list/search the API"
- "Show me the work-item types / licenses / diagnostics / policies"
- "Describe operation X — what params does it need?"
- "Call <operation> and summarize the result"
- "What ActOne version am I connected to?"
- Driving ActOne via an MCP agent (Copilot, Claude)

**Designer (design-time config authoring):**
- "Create a Drill Down Query / alert type / case type in ActOne"
- "List / get / clone / update / delete a Designer object of type X"
- "What fields does <Designer type> need? What must pre-exist?"

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

## Designer authoring loop (design-time config over SOAP)

For **design-time** objects the REST API does not expose, author them through the
reflected type catalog. Same find → inspect → act shape as REST:

1. **Find** the type (never guess a `typeValue`):
   ```
   actone ops designer search-types "drill down" --creatable
   ```
2. **Inspect** it — payload fields, references (FKs that must pre-exist), and a
   `grounding` block pointing at the docs MCP for setup prerequisites:
   ```
   actone ops designer describe-type DrillDownQuery
   ```
3. **Ground yourself first.** `describe-type` returns `grounding.suggestedQueries`;
   before authoring, look those up with the **docenter docs MCP**
   (`search_docs` / `search_actimize_docs`) to learn the object's setup sequence and
   server-enforced prerequisites (e.g. a DrillDownQuery needs an existing JDBC
   `connectionId` — the catalog can't express that; the docs can). Then create any
   `references` objects FIRST.
4. **Author** (WRITE — needs `--allow-write`):
   ```
   actone ops designer create-ddq myddq --sql "select ..." --connection-id 5 --allow-write
   actone ops designer clone DrillDownQuery src new --allow-write
   actone ops designer validate DrillDownQuery myddq --xml "<...>"     # READ, no gate
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
actone ops smoke  [--env E] [--no-rest] [--no-soap] [--no-catalog] [--write]
                  [--gating --ro-env RO] [--fixtures JSON] [--no-autofixtures]
                  [--limit N] [--full]                     # verify the MCP surface
```

`search` / `list` / `describe` / `tags` work **offline** (bundled/cached spec, no login).
Only `call` / `version` / `smoke` connect and log in. All output is JSON — paste it back
to the user or summarize it.

**`ops smoke`** — pre-ship health check. Drives the *actual MCP tool functions* so a
`pass` proves the op works **from the MCP**, not just the engine. Reports
`pass`/`fail`/`error`/`skip` per surface across three layers of coverage:

- **Reads** (default, safe): invokes every reachable read op — REST (`invoke_op`),
  curated SOAP (`invoke_soap_operation`), full SOAP catalog (`designer_call_operation`).
  `--autofixtures` (on by default) discovers real ids from safe reads (work-item types,
  business units, policy types, connections) so id-dependent reads run instead of
  skipping; add more with `--fixtures '{"paramName":"value"}'`.
- **`--write`** (opt-in, auto-cleanup): runs the shipped write-authoring lifecycles
  `create → verify persisted → remove` — typed (AlertType, DDQ), curated SOAP
  (BusinessUnit), and the generic engine (clone). Needs a writes-enabled env.
- **`--gating --ro-env <ro-profile>`** (side-effect-free): asserts **every** write op
  (~311: REST + curated SOAP + full catalog) is **refused at the gate** when the env
  forbids writes — proving the MCP protects and correctly classifies every write before
  shipping, without executing any of them. `<ro-profile>` must set `allow_writes: false`.

Note: HTTP 501/500/403 or "no longer supported" read results are environment/feature/
deprecation-gated, not MCP bugs (the call reached the server). Exits non-zero on any
real `fail`/`error`.

**Designer subcommands** (`actone ops designer ...`) — SOAP config surface:

```
actone ops designer search-types "<keywords>" [--creatable]          # offline
actone ops designer describe-type <typeValue>                        # offline (+ grounding)
actone ops designer search-ops "<keywords>"                          # offline
actone ops designer list       <typeValue> [--full]                 # READ
actone ops designer get        <typeValue> <identifier>             # READ
actone ops designer constraints <typeValue> <identifier>            # READ (delete constraints)
actone ops designer validate   <typeValue> <identifier> --xml <XML> # READ (no save)
actone ops designer create     <typeValue> --fields <JSON>          --allow-write
actone ops designer create-ddq <identifier> --sql <SQL> ...         --allow-write
actone ops designer create-alert-type <identifier> ...              --allow-write
actone ops designer create-case-type  <identifier> ...              --allow-write  # legacy
actone ops designer clone      <typeValue> <src> <new>              --allow-write
actone ops designer update     <typeValue> <identifier> --xml <XML> --allow-write
actone ops designer remove     <typeValue> <identifier>             --allow-write
actone ops designer call       <service> <operation> [--inner-xml X]   # escape hatch (reads free)
```

`search-types` / `describe-type` / `search-ops` work **offline** against the bundled
catalog. `create` / `update` / `remove` / `clone` are WRITEs (gated); `list` / `get`
/ `constraints` / `validate` are reads. `call` classifies by verb: read operations
(`get*`/`list*`/`has*`/`count*` ...) run freely, writes need `--allow-write`.

## MCP tools (same engine, for AI agents)

The `actone-ops` MCP server registers **23 tools**.

**Runtime REST + curated SOAP (8):**

| Tool | Purpose |
|------|---------|
| `search_ops(query, limit, reads_only)` | Keyword search (limit ≤ 500) |
| `list_ops(reads_only, tag, group, offset, limit)` | Enumerate the REST surface, **paged** (default 50/page) |
| `describe_op(operation_id)` | Params, body example, read/write |
| `invoke_op(operation_id, params)` | Run a REST op (writes gated) |
| `list_tags()` | Domains + counts |
| `list_soap_operations()` | List the curated SOAP operations (offline) |
| `invoke_soap_operation(operation_id, params)` | Invoke a curated SOAP op (writes gated) |
| `list_environments()` | Configured ActOne environments (never shows passwords) |

**Designer / catalog-driven SOAP (15):**

| Tool | Purpose |
|------|---------|
| `designer_search_types(query, creatable_only)` | Find a Designer `typeValue` (offline) |
| `designer_describe_type(type_value)` | Fields, references, createPaths + **grounding** block (offline) |
| `designer_search_operations(query, limit)` | Find a raw catalog SOAP operation (offline) |
| `designer_list_objects(type_value, full)` | List existing objects of a type (READ) |
| `designer_get_object(type_value, identifier)` | Fetch one object (READ) |
| `designer_get_remove_constraints(type_value, identifier)` | Delete constraints (READ) |
| `designer_validate_object(type_value, identifier, object_xml)` | Server-side validate, no save (READ) |
| `designer_create_object(type_value, fields)` | Create any type from a field dict (WRITE) |
| `create_drill_down_query(identifier, sql_query, ...)` | Typed DDQ create convenience (WRITE) |
| `create_alert_type(identifier, ...)` | Typed alert-type create convenience (WRITE) |
| `create_case_type(identifier, ...)` | Typed case-type create convenience (WRITE) — **legacy** (modern config uses case *items*/work-item types) |
| `designer_clone_object(type_value, source_identifier, new_identifier)` | Copy under a new id (WRITE) |
| `designer_update_object(type_value, identifier, object_xml)` | Save a modified payload (WRITE) |
| `designer_remove_object(type_value, identifier)` | Delete an object (WRITE) |
| `designer_call_operation(service, operation, inner_xml)` | Escape hatch: any catalog op (reads free; writes gated) |

Registered in `.vscode/mcp.json` as `actone-ops`. Start manually with `actone-mcp`.
`params` is a flat dict (path/query/header by name); a request body goes under the key `"body"`.

> **Grounding:** `designer_describe_type` returns a `grounding` block with
> `suggestedQueries` — before authoring, look them up via the **docenter docs MCP**
> (`search_docs` / `search_actimize_docs`) to learn setup prerequisites the catalog
> cannot express. This enrichment is optional: Ops works fully standalone without
> the docs MCP mounted.

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
2. **Respect the write gate.** Reads run freely. For a write (REST POST/PUT/DELETE or
   Designer `create`/`update`/`remove`/`clone`), require an explicit opt-in
   (`--allow-write` / `ACTONE_ALLOW_WRITES=true` / an `allow_writes: true` profile).
   If writes are not enabled, stop and tell the user it is gated — do not work around it.
3. **Prefer REST over Designer/SOAP** when both expose the capability (REST-first).
4. **Ground before authoring Designer objects.** Run `describe-type`, follow its
   `grounding.suggestedQueries` into the docs MCP, and create any `references`
   (must-pre-exist FKs) FIRST.
5. **Use `describe` to build params.** Path params are required; pass each as `--p name=value`
   (CLI) or in the `params` dict (MCP). Request bodies go under `"body"`.
6. **Summarize JSON results** for the user; surface `status`/`ok` and the key fields.
7. **If a `call` hangs/times out**, the instance is unreachable — `search`/`list`/`describe`
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
