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
