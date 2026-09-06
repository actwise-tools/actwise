"""ActWise — ActOne Ops MCP discovery server.

Exposes the **runtime ActOne Extend REST API** to any MCP client (GitHub Copilot
CLI / VS Code, Claude Code, Copilot Studio) as a small set of *discovery* tools
rather than 149 static tools. The agent discovers operations on demand:

    search_ops  -> describe_op -> invoke_op

Discovery keeps the model's tool-selection context flat regardless of how large the
ActOne surface is, and tracks whatever the target instance actually exposes (the
registry is built from the live/cached/bundled OpenAPI spec).

Safety
------
P1 is **read-only**: `invoke_op` runs only operations the registry classifies as
reads (GET/HEAD). Writes are refused until the attribution-wall decision (P2).

Spec source: cached spec under <workdir>/postman/specs, else the bundled current
spec (see actone.registry.resolve_spec). Credentials: the built-in `default`
environment reads <workdir>/.env (ACTONE_URL/ACTONE_USER/ACTONE_PASSWORD) — only
needed for invoke_op. Additional named ActOne instances are defined in
actone-ops.yaml (passwords in actone-ops.secrets.yaml); list them with
`list_environments` and target one via the `env` argument of invoke_op.

Run (stdio, for local MCP clients — Copilot CLI, VS Code, Claude):
    py -m actone_mcp.server

Run (Streamable HTTP, for containers / remote MCP clients / Copilot Studio):
    py -m uvicorn actone_mcp.server:app --host 0.0.0.0 --port 8765
    # endpoint: http://localhost:8765/mcp   health: http://localhost:8765/healthz
    # optional shared secret: set ACTONE_PROXY_API_KEY (header X-API-Key).
"""
from __future__ import annotations

import hmac
import os
import threading
from typing import Optional

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import JSONResponse

from actone.registry import load_registry
from actone.invoke import invoke, precheck, make_client, InvokeError, writes_enabled

SERVER_NAME = "actwise-actone-ops"
API_KEY_ENV = "ACTONE_PROXY_API_KEY"

mcp = FastMCP(
    SERVER_NAME,
    stateless_http=True,
    # The MCP StreamableHTTP transport enables DNS-rebinding protection by default,
    # which rejects any request whose Host header isn't localhost ("Invalid Host
    # header"). This server runs behind a container / tunnel / ingress (variable
    # Host) and access is already gated by the X-API-Key auth gate, so disable the
    # Host/Origin check. (Mirrors docenter_mcp.)
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)

_lock = threading.Lock()
_registry = None
_clients: dict[str, object] = {}


def _reg():
    global _registry
    with _lock:
        if _registry is None:
            _registry = load_registry(os.environ.get("ACTONE_SPEC"))
        return _registry


def _get_client(env: Optional[str] = None):
    """Lazily login once per environment; reuse across invoke_op calls."""
    key = env or "default"
    with _lock:
        c = _clients.get(key)
        if c is None:
            c = make_client(env=env)
            c.login()
            c.detect_version()
            _clients[key] = c
        return c


@mcp.tool()
def search_ops(query: str = "", limit: int = 25, reads_only: bool = False) -> dict:
    """Discover ActOne operations by keyword (operationId / summary / tags / path).

    Start here, then call describe_op on a result before invoke_op. An empty query
    lists everything (ranked alphabetically).

    Args:
        query: Keywords, e.g. "alert details", "policy manager", "diagnostics".
        limit: Max results (1-500). For the full surface, prefer list_ops.
        reads_only: When true, only return read (GET) operations.

    Returns:
        dict with `specVersion`, `count` (total ops), and `results`
        (operationId, method, path, summary, tags, access).
    """
    reg = _reg()
    limit = max(1, min(500, limit))
    return {"specVersion": reg.info_version, "source": reg.source,
            "count": len(reg.ops), "results": reg.search(query, limit, reads_only)}


@mcp.tool()
def describe_op(operation_id: str) -> dict:
    """Show full detail for one operation: method, path, parameters, request-body
    example, and read/write access.

    Use the `parameters` and `requestBody.example` to assemble the `params` for
    invoke_op. Path params are required; a request body is passed under "body".

    Args:
        operation_id: An operationId from search_ops.

    Returns:
        The operation detail dict, or `error`/`suggestions` if unknown.
    """
    reg = _reg()
    info = reg.describe(operation_id)
    if not info:
        return {"error": "unknown_operation", "operationId": operation_id,
                "suggestions": [o["operationId"] for o in reg.search(operation_id, 5)]}
    return info


@mcp.tool()
def invoke_op(operation_id: str, params: Optional[dict] = None,
              env: Optional[str] = None) -> dict:
    """Invoke an ActOne operation live and return the response.

    Read (GET) operations always run. Write operations (POST/PUT/DELETE/PATCH)
    are refused unless the operator opted in by setting ACTONE_ALLOW_WRITES to a
    truthy value (1/true/yes/on) in the server's environment — the model cannot
    lift the gate itself. Build `params` from describe_op — path/query/header
    params by their spec name, and a request body (when needed) under the reserved
    key "body".

    Args:
        operation_id: An operationId from search_ops/describe_op.
        params: Flat dict of parameter values (plus optional "body").
        env: Named ActOne environment to run against (see list_environments).
            Omit to use the default (`.env`) instance.

    Returns:
        dict with `status`, `ok`, `url`, `content_type`, and `body` (the response),
        or `error` for unknown/gated/missing-param cases.
    """
    reg = _reg()
    aw = writes_enabled(env)
    try:
        precheck(reg, operation_id, allow_write=aw)  # gate fires before any login
        return invoke(reg, _get_client(env), operation_id, params or {}, allow_write=aw)
    except InvokeError as e:
        return {"error": str(e), "operationId": operation_id, "env": env or "default"}


@mcp.tool()
def list_soap_operations() -> dict:
    """List the curated ActOne **SOAP** operations (offline).

    These cover the legacy Axis admin surface the Extend REST API does not — most
    importantly creating a **Business Unit** (there is no create-BU REST op), which
    is the prerequisite for seeding work items on a fresh instance. Each entry has
    `operationId`, `service`, `operation`, `access` (read|write), `summary`, and
    `params`. Invoke one via `invoke_soap_operation`.
    """
    from actone.soap import list_operations
    ops = list_operations()
    return {"count": len(ops), "operations": ops}


@mcp.tool()
def invoke_soap_operation(operation_id: str, params: Optional[dict] = None,
                          env: Optional[str] = None) -> dict:
    """Invoke a curated ActOne SOAP operation live (see list_soap_operations).

    Read operations always run. Write operations (create/remove) are refused unless
    the target environment permits writes — a named environment must set
    `allow_writes: true` in actone-ops.yaml (the built-in `default` environment uses
    ACTONE_ALLOW_WRITES). The model cannot lift the gate itself. Reuses the same
    authenticated session as the REST ops (the login cookie authorizes the SOAP
    services), so the same `env` names apply.

    Args:
        operation_id: A curated SOAP opId, e.g. "bu.list", "bu.get", "bu.create".
        params: Flat dict of argument values (see the op's `params` from
            list_soap_operations), e.g. {"identifier": "MY_BU", "name": "My BU"}.
        env: Named ActOne environment (see list_environments). Omit for default.

    Returns:
        dict with `ok`, `status`, `messages`, `records`, and `result_scalar`
        (e.g. the new BU id from bu.create), or `error` for unknown/gated ops.
    """
    from actone.soap import SOAP_OPS, SoapClient, SoapError
    spec = SOAP_OPS.get(operation_id)
    if not spec:
        return {"error": "unknown_soap_operation", "operationId": operation_id,
                "known": list(SOAP_OPS)}
    if spec["access"] == "write" and not writes_enabled(env):
        return {"error": "operation %r is a WRITE (%s.%s) but writes are disabled for "
                         "environment %r; set `allow_writes: true` for it in "
                         "actone-ops.yaml (or ACTONE_ALLOW_WRITES=true for the default "
                         "environment) to enable"
                         % (operation_id, spec["service"], spec["operation"],
                            env or "default"),
                "operationId": operation_id, "env": env or "default"}
    try:
        return SoapClient(_get_client(env)).call(operation_id, params or {})
    except SoapError as e:
        return {"error": str(e), "operationId": operation_id, "env": env or "default"}


@mcp.tool()
def list_environments() -> dict:
    """List the **live ActOne administration (OPS) environments** — server instances for operations and writes.

    These are the **live-administration** environments and are DISTINCT from the Data
    MCP's database/query environments. Use this ONLY for live ActOne operations; for
    read-only database reporting use the Data server's ``list_environments`` instead.
    Each entry has `name`, `url`, `user`, `context_root`, `requires_vpn`,
    `allow_writes`, `notes`, `password_configured`, and `is_default` — **never the
    password**. Pass a `name` as the `env` argument of invoke_op to run against that
    instance. `allow_writes` reflects whether live writes are currently permitted
    for that environment (config-driven, default-deny). Environments come from
    `actone-ops.yaml`; the built-in `default` reads the server's `.env` / process env.

    Note: environments flagged `requires_vpn=true` (e.g. AWS-internal instances)
    are only reachable when the server host is on the corporate VPN.
    """
    from actone.ops_config import list_environments as _list_envs
    envs = _list_envs()
    return {"count": len(envs), "environments": envs}


@mcp.tool()
def list_tags() -> dict:
    """List the operation tags (functional domains) and their operation counts."""
    return _reg().tags()


@mcp.tool()
def list_ops(reads_only: bool = False, tag: Optional[str] = None,
             group: bool = False) -> dict:
    """List the ENTIRE ActOne operation surface (no cap).

    Use this to enumerate everything available — unlike search_ops, it is not
    limited. Filter with `tag` (one domain) and/or `reads_only`, or set
    `group=True` to organize results by tag.

    Args:
        reads_only: When true, only include read (GET) operations.
        tag: Optional single tag/domain to filter to (ignored when group=True).
        group: When true, return {tag: [operations]} instead of a flat list.

    Returns:
        dict with `specVersion`, `count` (total ops), and either `operations`
        (flat list) or `groups` (by tag).
    """
    reg = _reg()
    base = {"specVersion": reg.info_version, "source": reg.source,
            "count": len(reg.ops)}
    if group:
        base["groups"] = reg.grouped(reads_only=reads_only)
    else:
        ops = reg.list_ops(reads_only=reads_only, tag=tag)
        base["returned"] = len(ops)
        base["operations"] = ops
    return base


# ── ASGI app: auth gate + health, wrapping the Streamable-HTTP MCP ────────────
class _AuthGate:
    """Pure-ASGI middleware: serves /healthz, enforces X-API-Key when configured.

    Pure ASGI (not BaseHTTPMiddleware) so it never buffers the MCP stream and
    passes lifespan events straight through to the FastMCP session manager. When
    ACTONE_PROXY_API_KEY is unset the server runs open (convenient for local
    proving); set it for any shared / tunnelled / cloud deployment."""

    def __init__(self, app, api_key: Optional[str]):
        self.app = app
        self.api_key = api_key

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        if path == "/healthz":
            await JSONResponse({"status": "ok", "server": SERVER_NAME})(scope, receive, send)
            return
        if self.api_key:
            headers = dict(scope.get("headers") or [])
            provided = headers.get(b"x-api-key", b"").decode()
            if not (provided and hmac.compare_digest(provided, self.api_key)):
                await JSONResponse({"error": "unauthorized"}, status_code=401)(scope, receive, send)
                return
        await self.app(scope, receive, send)


# ASGI entrypoint for uvicorn (Streamable HTTP):
#   py -m uvicorn actone_mcp.server:app --host 0.0.0.0 --port 8765
#   endpoint: http://localhost:8765/mcp   health: http://localhost:8765/healthz
app = _AuthGate(mcp.streamable_http_app(), os.environ.get(API_KEY_ENV))


def main() -> None:
    """Run as a stdio MCP server (local clients: Copilot CLI, VS Code, Claude)."""
    mcp.run()


if __name__ == "__main__":
    main()
