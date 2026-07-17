"""ActWise — ActOne Utilities MCP runner (C-U).

Exposes ActOne's maintenance utilities (Blotter Maintenance, DART runner, …) to
any MCP client (GitHub Copilot CLI / VS Code, Claude Code, Copilot Studio) as a
small discovery surface rather than one static tool per utility:

    search_utils / list_utils  ->  describe_util  ->  run_util

The utility catalog and the execution backend (local / ssh / winrm) come from the
process config (env ``ACTONE_UTILS_*`` or ``actone-utils.yaml``).

Safety
------
``run_util`` defaults to ``dry_run=True`` (assemble + return the command, never
execute). A **state-changing** utility only runs for real when the operator sets
``ACTONE_UTILS_ALLOW_RUN`` to a truthy value in the server environment — the model
cannot lift the gate itself.

Run (stdio, for local MCP clients):
    py -m actone_utils.server

Run (Streamable HTTP, for containers / Copilot Studio):
    py -m uvicorn actone_utils.server:app --host 0.0.0.0 --port 8766
    # endpoint: http://localhost:8766/mcp   health: http://localhost:8766/healthz
    # optional shared secret: set ACTONE_UTILS_API_KEY (header X-API-Key).
"""
from __future__ import annotations

import hmac
import os
import threading
from typing import Optional

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import JSONResponse

from . import catalog
from .config import UtilsConfig
from .runner import run_utility, writes_enabled, UtilityError, RunGate

SERVER_NAME = "actwise-actone-utils"
API_KEY_ENV = "ACTONE_UTILS_API_KEY"

mcp = FastMCP(
    SERVER_NAME,
    stateless_http=True,
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)

_lock = threading.Lock()
_cfg: Optional[UtilsConfig] = None


def _config() -> UtilsConfig:
    global _cfg
    with _lock:
        if _cfg is None:
            _cfg = UtilsConfig.load()
        return _cfg


@mcp.tool()
def search_utils(query: str = "", limit: int = 25) -> dict:
    """Discover ActOne utilities by keyword (name / title / tool / tags / summary).

    Start here, then describe_util a result before run_util. Empty query lists all.

    Returns:
        dict with `count` and `results` (name, title, tool, tags, access).
    """
    return {"count": len(catalog.all_utils()), "results": catalog.search(query, max(1, min(100, limit)))}


@mcp.tool()
def list_utils() -> dict:
    """List every utility in the catalog with its access (read/write) and tags."""
    return {"count": len(catalog.all_utils()), "utilities": catalog.list_briefs(),
            "tags": catalog.tags()}


@mcp.tool()
def describe_util(name: str) -> dict:
    """Show one utility's parameters, access, source doc, and notes.

    Use the `parameters` to build the `params` dict for run_util.

    Args:
        name: A utility name from search_utils/list_utils.
    """
    util = catalog.get(name)
    if not util:
        return {"error": "unknown_utility", "name": name,
                "suggestions": [b["name"] for b in catalog.search(name, 5)]}
    return util.describe()


@mcp.tool()
def run_util(name: str, params: Optional[dict] = None, dry_run: bool = True,
             raw_args: Optional[list] = None) -> dict:
    """Assemble and (optionally) run an ActOne utility on the configured backend.

    Defaults to a **dry run**: returns the exact command that would execute,
    without running it. A real run of a state-changing utility additionally
    requires ACTONE_UTILS_ALLOW_RUN to be truthy in the server environment.

    Args:
        name: Utility name from describe_util.
        params: Flat dict of parameter values (see describe_util `parameters`).
        dry_run: When true (default), assemble only. When false, execute
            (subject to the ALLOW_RUN gate for state-changing utilities).
        raw_args: Optional list of extra args appended verbatim (for options
            not yet modelled in the catalog).

    Returns:
        ExecResult dict (backend, target, command, remote_command, ok,
        returncode, stdout, stderr) plus `utility`/`tool`/`access`,
        or an `error`/`gated` dict.
    """
    try:
        return run_utility(_config(), name, params or {},
                           dry_run=dry_run, assume_yes=writes_enabled(),
                           raw_args=list(raw_args or []))
    except RunGate as e:
        return {"gated": str(e), "utility": name,
                "hint": "set ACTONE_UTILS_ALLOW_RUN=1 on the server to permit real runs"}
    except UtilityError as e:
        return {"error": str(e), "utility": name}
    except RuntimeError as e:
        return {"error": str(e), "utility": name}


# ── ASGI app: auth gate + health, wrapping the Streamable-HTTP MCP ────────────
class _AuthGate:
    def __init__(self, app, api_key: Optional[str]):
        self.app = app
        self.api_key = api_key

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        if scope.get("path", "") == "/healthz":
            await JSONResponse({"status": "ok", "server": SERVER_NAME})(scope, receive, send)
            return
        if self.api_key:
            headers = dict(scope.get("headers") or [])
            provided = headers.get(b"x-api-key", b"").decode()
            if not (provided and hmac.compare_digest(provided, self.api_key)):
                await JSONResponse({"error": "unauthorized"}, status_code=401)(scope, receive, send)
                return
        await self.app(scope, receive, send)


app = _AuthGate(mcp.streamable_http_app(), os.environ.get(API_KEY_ENV))


def main() -> None:
    """Run as a stdio MCP server (local clients: Copilot CLI, VS Code, Claude)."""
    mcp.run()


if __name__ == "__main__":
    main()
