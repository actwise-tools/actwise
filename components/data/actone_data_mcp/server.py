"""ActWise Data — read-only NL-to-SQL MCP server over the ActOne ``v_acm_*`` views.

The **host LLM writes the SQL**; this server only *grounds*, *validates* and
*executes* it — it holds no LLM key. It exposes five tools to any MCP client
(GitHub Copilot CLI / VS Code, Claude, Copilot Studio):

    get_schema_summary  ->  list_views  ->  describe_view  ->  validate_sql  ->  run_query

Grounding (``get_schema_summary`` / ``list_views`` / ``describe_view``) is served
offline from the bundled schema pack. Execution (``validate_sql`` / ``run_query``)
runs the shared 7-step guardrail pipeline (``actone_data.guardrails``) against the
**live** view allowlist and executes on a read-only + statement-timeout session
(``actone_data.db``). Every attempt — including rejections — is appended to the
JSONL audit log (``actone_data.audit``).

Safety (defense in depth): DB read-only txn -> AST allowlist (``v_acm_*`` only) ->
statement timeout -> row cap. There are no write tools.

Run (stdio, for local MCP clients — Copilot CLI, VS Code, Claude):
    py -m actone_data_mcp.server

Run (Streamable HTTP, for containers / remote clients / Copilot Studio):
    py -m uvicorn actone_data_mcp.server:app --host 0.0.0.0 --port 8766
    # endpoint: http://localhost:8766/mcp   health: http://localhost:8766/healthz
    # optional shared secret: set ACTONE_DATA_PROXY_API_KEY (header X-API-Key).

Connection: resolved from ACTONE_DATA_PROFILE (default ``local``) / ACTONE_DATA_DSN
/ ACTONE_DB_* env / the ``actone-data.yaml`` profiles, exactly like the CLI.
"""
from __future__ import annotations

import difflib
import hmac
import os
import threading
from typing import Optional

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import JSONResponse

from actone_data import audit, db, schema_pack
from actone_data.guardrails import GuardrailError, validate as _validate

SERVER_NAME = "actwise-actone-data"
API_KEY_ENV = "ACTONE_DATA_PROXY_API_KEY"

mcp = FastMCP(
    SERVER_NAME,
    stateless_http=True,
    # StreamableHTTP enables DNS-rebinding protection by default (rejects any
    # request whose Host header isn't localhost -> "Invalid Host header"). This
    # server runs behind a container / tunnel / ingress with a variable Host and
    # is already gated by the X-API-Key auth gate, so disable the Host/Origin
    # check. (Mirrors actone_mcp / docenter_mcp.)
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)

_lock = threading.Lock()
_pack_cache: Optional[dict] = None
_cfg_cache: dict = {}
# stdio by default; the HTTP auth gate flips this to "mcp-http" on first request
# so audit records carry the right transport label.
_transport = "mcp-stdio"


def _pack() -> dict:
    global _pack_cache
    with _lock:
        if _pack_cache is None:
            _pack_cache = schema_pack.load()
        return _pack_cache


def _default_env() -> str:
    return os.environ.get("ACTONE_DATA_PROFILE") or "local"


def _cfg(env: str = ""):
    """Resolve the DB config for the requested environment (profile), cached per env.

    ``env`` is a profile name from ``actone-data.yaml`` (see ``list_environments``);
    empty selects the default (``ACTONE_DATA_PROFILE`` or ``local``). Returns
    ``(env_name, ConnConfig)``.
    """
    from actone_data import config
    name = (env or "").strip() or _default_env()
    with _lock:
        if name not in _cfg_cache:
            # ACTONE_DATA_DSN is a single global override -> only for the default env.
            dsn = os.environ.get("ACTONE_DATA_DSN") if name == _default_env() else None
            _cfg_cache[name] = config.resolve(profile=name, dsn=dsn)
        return name, _cfg_cache[name]


def _allowlisted(pack: dict) -> dict[str, dict]:
    """Views eligible for querying (doc-only views are visible but not queryable)."""
    return {n: v for n, v in pack["views"].items() if v["provenance"] != "doc_only"}


# ── Tools ─────────────────────────────────────────────────────────────────────
@mcp.tool()
def get_schema_summary() -> dict:
    """Overview of the ActOne query surface — **call this once per conversation, first**.

    Returns the DB product version, schema, view counts by topic/family, the
    **preference rules** (prefer the permission-aware item views over legacy
    ``v_acm_alert*``), and the global query rules. Use it to orient before naming
    any view; then use ``list_views`` / ``describe_view`` to get exact names and
    columns. Never guess view or column names.

    Returns:
        dict with ``version``, ``schema``, ``dialect``, ``view_count``,
        ``doc_only_count``, ``families`` (counts by family), ``preferred_count``,
        ``preference_rules`` and ``rules`` (the global notes).
    """
    pack = _pack()
    allow = _allowlisted(pack)
    doc_only = [v for v in pack["views"].values() if v["provenance"] == "doc_only"]
    fams: dict[str, int] = {}
    for v in allow.values():
        fams[v["family"]] = fams.get(v["family"], 0) + 1
    return {
        "version": pack["source"]["db_product_version"],
        "version_source": pack["source"]["db_version_source"],
        "schema": pack["schema"],
        "dialect": pack["dialect"],
        "doc_bundle": pack["source"]["doc_bundle"],
        "view_count": len(allow),
        "doc_only_count": len(doc_only),
        "families": dict(sorted(fams.items())),
        "preferred_count": sum(1 for v in allow.values() if v["preferred"]),
        "preference_rules": [
            "Alerts / work items -> v_acm_items (permission-aware, unified item family).",
            "Cases -> v_acm_cases.  Blotters / transactions -> v_acm_blotters.",
            "v_acm_alert* views are legacy (alerts only) and NOT permission-aware "
            "(standard A1) — prefer the item equivalent shown in describe_view.related_views.",
        ],
        "rules": list(pack.get("notes", [])),
    }


@mcp.tool()
def list_views(topic: str = "") -> dict:
    """List the queryable ``v_acm_*`` views (doc-only views hidden).

    Legacy alert views are returned with ``preferred: false`` so the model steers
    to the item equivalents. Provide ``topic`` to filter by family
    (``item`` / ``case`` / ``blotter`` / ``alert`` / ``other``) or by a keyword
    matched against the view name and description.

    Args:
        topic: Optional family name or keyword filter. Empty returns all.

    Returns:
        dict with ``count`` and ``views``: ``{name, description, column_count,
        family, preferred}``, preferred views first.
    """
    pack = _pack()
    allow = _allowlisted(pack)
    t = (topic or "").strip().lower()
    out = []
    for name, v in allow.items():
        desc = v.get("description") or ""
        if t and not (t == v["family"] or t in name or t in desc.lower()):
            continue
        out.append({
            "name": name,
            "description": desc,
            "column_count": len(v["columns"]),
            "family": v["family"],
            "preferred": v["preferred"],
        })
    # Preferred first, then alphabetical.
    out.sort(key=lambda r: (not r["preferred"], r["name"]))
    return {"count": len(out), "views": out}


@mcp.tool()
def describe_view(view: str) -> dict:
    """Describe one view: columns (name/type/description/fk), preference and the
    preferred item equivalents for legacy alert views.

    Use the ``fk`` targets to build JOINs — ``*_join_id`` columns are internal
    surrogate keys, valid only in JOIN conditions, never as literals in WHERE.
    An unknown name returns ``suggestions`` (closest view names) instead.

    Args:
        view: A view name, e.g. ``v_acm_items``.

    Returns:
        The view detail dict, or ``{error, suggestions}`` if unknown.
    """
    pack = _pack()
    key = (view or "").strip().lower()
    v = pack["views"].get(key)
    if v is None:
        names = list(pack["views"])
        return {"error": "unknown_view", "view": key,
                "suggestions": difflib.get_close_matches(key, names, n=5, cutoff=0.4)}
    return {
        "name": key,
        "family": v["family"],
        "preferred": v["preferred"],
        "queryable": v["provenance"] != "doc_only",
        "provenance": v["provenance"],
        "description": v.get("description"),
        "related_views": v.get("related_views", []),
        "source_url": v.get("source_url"),
        "columns": [
            {"name": c["name"], "type": c["type"],
             "description": c["description"], "fk": c["fk"]}
            for c in v["columns"]
        ],
    }


@mcp.tool()
def list_environments() -> dict:
    """List the **database (DATA) environments** — ActOne DB connection profiles for read-only SQL reporting.

    These are the **data-query** environments and are DISTINCT from the Ops MCP's
    live-administration environments. Use this ONLY for Data/SQL work; for live ActOne
    operations use the Ops server's ``list_environments`` instead. Call this when the user
    asks which **database** environments exist or wants to run a query against a specific
    one. Pass the chosen ``name`` as the ``env`` argument to ``validate_sql`` /
    ``run_query``. Returns **metadata only** — never passwords.

    Returns:
        dict ``{default, environments: [{name, host, port, database, user, schema,
        dsn, password_configured, is_default}]}``.
    """
    from actone_data import config
    envs = config.list_profiles()
    return {"default": _default_env(), "environments": envs}


@mcp.tool()
def validate_sql(sql: str, env: str = "") -> dict:
    """Dry-run the guardrail pipeline on a SQL string — **no execution**.

    Run this before ``run_query`` to check a query and see the normalized SQL that
    would run. It parses the statement, enforces single read-only SELECT/UNION,
    the ``v_acm_*`` live allowlist, and injects/clamps a LIMIT.

    Args:
        sql: A single PostgreSQL SELECT over ``v_acm_*`` views.
        env: Target environment (profile) name from ``list_environments``; empty =
            the default environment. The allowlist is read from that environment's DB.

    Returns:
        dict ``{ok, errors[], sql_used, views_used[], limit_injected}``.
    """
    try:
        env_name, cfg = _cfg(env)
    except KeyError as ke:
        return {"ok": False, "errors": [str(ke)], "sql_used": None,
                "views_used": [], "limit_injected": False}
    try:
        with db.connect(cfg) as conn, conn.cursor() as cur:
            allowed = db._live_view_names(cur, cfg.schema)
    except Exception as e:
        return {"ok": False, "errors": [f"connection failed: {e}"],
                "sql_used": None, "views_used": [], "limit_injected": False}
    res = _validate(sql, allowed, cfg.schema)
    audit.record(transport=_transport, question="", sql=sql, ok=res["ok"],
                 sql_used=res["sql_used"],
                 rejected_reason=None if res["ok"] else "; ".join(res["errors"]),
                 db=cfg.target, env=env_name)
    return res


@mcp.tool()
def run_query(sql: str, max_rows: int = 100, question: str = "", env: str = "") -> dict:
    """Validate and execute a read-only SELECT over ``v_acm_*`` views.

    The guardrail pipeline always re-runs internally, so this cannot be bypassed
    by skipping ``validate_sql``. Pass the user's natural-language ``question`` so
    it is captured in the audit log. Rejections return ``{ok: false, errors[]}``.

    Args:
        sql: A single PostgreSQL SELECT over ``v_acm_*`` views.
        max_rows: Max rows to return (clamped to the 1000 cap; a LIMIT is injected).
        question: The originating user question, recorded for audit.
        env: Target environment (profile) name from ``list_environments``; empty =
            the default environment. The query executes against that environment's DB.

    Returns:
        On success ``{ok: true, columns, rows, row_count, truncated, sql_used,
        views_used, limit_injected, duration_ms}``; on rejection/error
        ``{ok: false, errors[]}``.
    """
    try:
        env_name, cfg = _cfg(env)
    except KeyError as ke:
        return {"ok": False, "errors": [str(ke)]}
    try:
        res = db.run_query(cfg, sql, max_rows=max_rows)
    except GuardrailError as ge:
        audit.record(transport=_transport, question=question, sql=sql, ok=False,
                     rejected_reason="; ".join(ge.errors), db=cfg.target, env=env_name)
        return {"ok": False, "errors": ge.errors}
    except Exception as e:
        audit.record(transport=_transport, question=question, sql=sql, ok=False,
                     rejected_reason=f"execution error: {e}", db=cfg.target, env=env_name)
        return {"ok": False, "errors": [f"execution error: {e}"]}
    audit.record(transport=_transport, question=question, sql=res["sql_used"],
                 ok=True, sql_used=res["sql_used"], rows=res["row_count"],
                 truncated=res["truncated"], duration_ms=res["duration_ms"],
                 db=cfg.target, env=env_name)
    return {"ok": True, **res}


# ── ASGI app: auth gate + health, wrapping the Streamable-HTTP MCP ────────────
class _AuthGate:
    """Pure-ASGI middleware: serves /healthz, enforces X-API-Key when configured,
    and labels the transport as ``mcp-http`` for audit.

    Pure ASGI (not BaseHTTPMiddleware) so it never buffers the MCP stream and
    passes lifespan events straight through. When ACTONE_DATA_PROXY_API_KEY is
    unset the server runs open (convenient locally); set it for any shared /
    tunnelled / cloud deployment."""

    def __init__(self, app, api_key: Optional[str]):
        self.app = app
        self.api_key = api_key

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        global _transport
        _transport = "mcp-http"
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
#   py -m uvicorn actone_data_mcp.server:app --host 0.0.0.0 --port 8766
#   endpoint: http://localhost:8766/mcp   health: http://localhost:8766/healthz
app = _AuthGate(mcp.streamable_http_app(), os.environ.get(API_KEY_ENV))


def main() -> None:
    """Run as a stdio MCP server (local clients: Copilot CLI, VS Code, Claude)."""
    mcp.run()


if __name__ == "__main__":
    main()
