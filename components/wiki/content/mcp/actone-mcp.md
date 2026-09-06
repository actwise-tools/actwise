# actone-mcp

> Turns a live ActOne instance into a discoverable REST (and curated SOAP)
> surface — a `search → describe → invoke` loop with writes gated by default.

## Goal

Let an agent operate a running ActOne instance safely: discover operations by
keyword over the Extend REST API OpenAPI spec, inspect their parameters and
read/write access, then invoke them live. Read (GET) operations run freely; any
write is refused unless the operator opted in server-side. It also exposes a
curated set of legacy **SOAP** admin operations (e.g. create Business Unit) the
REST API lacks.

## How it fits

- **Bucket:** [ops](../buckets/ops.md).
- **Shares code with:** the [`actone`](../cli/actone.md) CLI's `actone ops`
  runtime discovery loop and its SOAP module — the MCP tools call the same
  registry, client, and gate logic.
- **Consumed by:** the **ActWise Ops** Copilot Studio agent
  ([agent page](../agents/ops.md)), grounded on this server through a
  self-hosted, API-key-gated MCP endpoint. Local IDE agents can register it over
  stdio.

## Tools exposed

Enumerated from `components/ops/actone_mcp/server.py` — eight `@mcp.tool`
registrations (FastMCP):

| Tool | What it does |
|------|--------------|
| `search_ops` | Discover REST operations by keyword (operationId / summary / tags / path); `reads_only` to filter to GETs. |
| `list_ops` | Enumerate the **entire** operation surface (uncapped); filter by `tag` / `reads_only`, or `group` by tag. |
| `describe_op` | Full detail for one operation: method, path, parameters, request-body example, read/write access. |
| `invoke_op` | Invoke a REST operation live. GETs always run; writes refused unless `ACTONE_ALLOW_WRITES` is truthy in the server env. |
| `list_soap_operations` | List the curated ActOne SOAP admin operations (offline), incl. Business-Unit create. |
| `invoke_soap_operation` | Invoke a curated SOAP operation live; write ops require the target environment to permit writes. |
| `list_environments` | List the live **administration** (OPS) environments — name, url, user, `allow_writes`, `requires_vpn`, … (never the password). |
| `list_tags` | List operation tags (functional domains) and their operation counts. |

## Request flow — tool call to a live ActOne instance

Every tool call travels the **same lifecycle**: an MCP client `POST`s JSON-RPC to
`/mcp` (Copilot Studio) or attaches over stdio (local IDE agents), the `_AuthGate`
ASGI middleware authenticates HTTP callers, and FastMCP dispatches the `@mcp.tool`
handler. **Discovery** (`search_ops` / `list_ops` / `describe_op` / `list_tags` /
`list_soap_operations`) answers **offline** from the operation registry (built once
from the live/cached/bundled OpenAPI spec) and the curated SOAP table — no live
call. **Invocation** (`invoke_op` / `invoke_soap_operation`) runs the write gate
**before any login**, logs in once per environment (client reused across calls),
then calls the live ActOne REST (or reuses that login cookie for SOAP).
`list_environments` reads config profiles (metadata only, never passwords).

Code path: `actone_mcp/server.py` (tools + transport) →
`actone.{registry, invoke, soap, ops_config}` — the same registry, client, and
gate logic the [`actone`](../cli/actone.md) CLI's `actone ops` loop drives.

### Shared request lifecycle

```mermaid
sequenceDiagram
    autonumber
    participant C as MCP client
    participant G as _AuthGate (ASGI)
    participant F as FastMCP
    participant T as tool handler
    participant R as registry / SOAP table
    participant O as live ActOne (REST + SOAP)
    C->>G: POST /mcp — JSON-RPC tools/call<br/>X-API-Key (HTTP)  ·  or stdio
    Note over G: /healthz → 200 (no auth)<br/>verify X-API-Key (hmac) when set
    G-->>C: 401 on missing/bad key
    G->>F: authorized → pass through
    F->>T: dispatch tool(args)
    alt Discovery — offline
        T->>R: _reg() / SOAP_OPS (cached)
        R-->>T: operations / detail / tags
    else Invocation — live
        T->>T: writes_enabled(env) + precheck gate<br/>(fires before any login)
        alt write & gate closed
            T-->>F: error (gated)
        else read / gate open
            T->>O: _get_client(env).login() (once per env)
            T->>O: invoke REST op  ·  or SoapClient.call
            O-->>T: response body
        end
    end
    T-->>F: dict → JSON content
    F-->>C: JSON-RPC result
```

### `search_ops`

Discover REST operations by keyword (operationId / summary / tags / path) from the
offline registry — the **start** of the loop. An empty query lists everything
(ranked); `reads_only` restricts to GETs.

```mermaid
flowchart TD
    A["search_ops(query, limit, reads_only?)"] --> REG["_reg() — OpenAPI registry (offline)"]
    REG --> M["reg.search — rank by<br/>operationId · summary · tags · path"]
    M --> F{reads_only?}
    F -->|yes| RO["keep GET/HEAD only"]
    F -->|no| ALL["all methods"]
    RO --> O
    ALL --> O["result: specVersion, count,<br/>results (operationId·method·path·summary·tags·access)"]
```

### `list_ops`

Enumerate the **entire** operation surface (no cap) — unlike `search_ops`. Filter
by `tag` and/or `reads_only`, or set `group=True` to organize by tag.

```mermaid
flowchart TD
    A["list_ops(reads_only?, tag?, group?)"] --> REG["_reg() (offline)"]
    REG --> G{group?}
    G -->|yes| GR["reg.grouped(reads_only)<br/>→ groups {tag: [ops]}"]
    G -->|no| FL["reg.list_ops(reads_only, tag)<br/>→ flat operations[]"]
    GR --> O["result: specVersion, count, …"]
    FL --> O
```

### `describe_op`

Full detail for one operation: method, path, parameters, request-body example, and
read/write access — used to assemble `params` for `invoke_op`. An unknown id
returns `suggestions`.

```mermaid
flowchart TD
    A["describe_op(operation_id)"] --> REG["_reg() (offline)"]
    REG --> K{known op?}
    K -->|no| S["error: unknown_operation<br/>+ reg.search suggestions"]
    K -->|yes| O["result: method · path · parameters ·<br/>requestBody.example · access"]
```

### `invoke_op`

Invoke a REST operation live. The write gate (`writes_enabled` + `precheck`)
**fires before any login**; GETs always run, writes are refused unless
`ACTONE_ALLOW_WRITES` is truthy in the server env. The client logs in once per
environment and is reused.

```mermaid
flowchart TD
    A["invoke_op(operation_id, params?, env?)"] --> AW["writes_enabled(env)"]
    AW --> PRE{"precheck gate<br/>write op & writes disabled?"}
    PRE -->|blocked| X["error (gated) — before any login"]
    PRE -->|read / allowed| CL["_get_client(env).login()<br/>once per env, reused"]
    CL --> INV["invoke REST op live"]
    INV --> R["result: status · ok · url ·<br/>content_type · body"]
    INV -.->|InvokeError| E["error: message · operationId · env"]
```

### `list_soap_operations`

List the curated ActOne **SOAP** admin operations (offline) — the legacy Axis
surface the REST API lacks, most importantly create Business Unit. Each entry
feeds `invoke_soap_operation`.

```mermaid
flowchart TD
    A["list_soap_operations()"] --> S["actone.soap.list_operations()<br/>curated table (offline)"]
    S --> O["result: count, operations<br/>operationId·service·operation·access·summary·params"]
```

### `invoke_soap_operation`

Invoke a curated SOAP op live. Reads always run; writes (create/remove) are refused
unless the target environment permits writes (`allow_writes: true`, or
`ACTONE_ALLOW_WRITES` for `default`). Reuses the **same authenticated session** as
the REST ops (the login cookie authorizes SOAP).

```mermaid
flowchart TD
    A["invoke_soap_operation(operation_id, params?, env?)"] --> K{known SOAP op?}
    K -->|no| U["error: unknown_soap_operation<br/>+ known ids"]
    K -->|yes| W{"write op & writes disabled for env?"}
    W -->|blocked| X["error (gated)"]
    W -->|allowed| CALL["SoapClient(_get_client(env)).call<br/>reuses REST login cookie"]
    CALL --> R["result: ok · status · messages ·<br/>records · result_scalar"]
    CALL -.->|SoapError| E["error: message · operationId · env"]
```

### `list_environments`

List the live **administration (OPS)** environments — server instances for
operations and writes (distinct from the Data MCP's DB environments). Reads
`actone-ops.yaml` + the built-in `default` (`.env`); passwords are never returned.

```mermaid
flowchart TD
    A["list_environments()"] --> C["ops_config.list_environments()<br/>actone-ops.yaml + default .env"]
    C --> O["result: count, environments<br/>name·url·user·context_root·requires_vpn·<br/>allow_writes·is_default (never password)"]
```

### `list_tags`

List the operation tags (functional domains) and their operation counts from the
offline registry — a quick map of the ActOne surface.

```mermaid
flowchart TD
    A["list_tags()"] --> REG["_reg().tags() (offline)"]
    REG --> O["result: tags + operation counts"]
```

> Full parameter/return contracts for each tool live in the tool docstrings in
> `components/ops/actone_mcp/server.py`; the write-gate model is summarized under
> [Safety](#safety) below.

## Transport & run

Runs as **stdio or HTTP**. Console script from `pyproject.toml`
(`actone-mcp = "actone_mcp.server:main"`):

```powershell
actone-mcp
# or, as an ASGI HTTP app (serves /mcp, health /healthz):
python -m uvicorn actone_mcp.server:app --port 8765
```

The HTTP transport is **self-hosted**; when `ACTONE_PROXY_API_KEY` is set it
enforces an `X-API-Key` header (required for any shared/tunnelled deployment,
which is how the ActWise Ops agent reaches it).

## Self-host setup

1. **Configure an environment.** Copy `components/ops/actone-ops.example.yaml` to
   `~/.actwise/actone-ops.yaml` (resolution order: `$ACTWISE_CONFIG_DIR` → cwd →
   `~/.actwise` → repo root) and set each profile's `url`, `context_root`, `user`,
   and — for shared/QAS instances — `requires_vpn: true` and `allow_writes: false`.
   The shipped example carries a `local-dev` (`http://localhost:8082`, matches the
   `actone-local` container) and a placeholder `popular-qas-dev` — replace the host
   with your own instance. Profile YAML holds **no passwords**.
2. **Provide the password** out-of-band: `ACTONE_PASSWORD__<ENV>` (env name
   upper-cased, non-alphanumerics → `_`, e.g. `ACTONE_PASSWORD__POPULAR_QAS_DEV`)
   or an `actone-ops.secrets.yaml` beside the config.
3. **Fetch the OpenAPI spec once (required).** The published snapshot ships **no
   bundled REST spec**, so `search_ops`/`describe_op`/`invoke_op` need one fetched
   from your live instance first:

   ```powershell
   actone fetch-spec --url http://<host>:8080/RCM --user <user> --password <pwd>
   ```

   This discovers the springdoc/springfox spec, converts Swagger2→OAS3, and caches
   it under `<workdir>/postman/specs/*.oas3.json` where the registry auto-resolves
   it. Override explicitly with `--spec <path>` or `ACTONE_SPEC`. (The SOAP tools
   and `list_environments` work without a spec.)
4. **Gate writes** per environment (`allow_writes: true` in the profile) and/or the
   global `ACTONE_ALLOW_WRITES` — default-deny otherwise.
5. **Shared HTTP deploy:** set `ACTONE_PROXY_API_KEY` and require the `X-API-Key`
   header on the tunnel. VPN-gated instances are only reachable when the host is on
   the corporate VPN.

## Safety

**Default-deny writes.** Read operations always run; write operations
(POST/PUT/DELETE/PATCH, and SOAP create/remove) are gated — the REST gate is the
global `ACTONE_ALLOW_WRITES`, and SOAP/named environments require
`allow_writes: true` in `actone-ops.yaml`. The gate is server-side; the model
cannot lift it itself, and it fires before any login. The agent's contract is to
confirm-before-write.

## See also

- CLI: [`actone`](../cli/actone.md) (`actone ops …`)
- Bucket: [ops](../buckets/ops.md)
- Agent: [ActWise Ops](../agents/ops.md)
