"""ActWise Data — read-only NL-to-SQL MCP server over the ActOne ``v_acm_*`` views.

The **host LLM writes the SQL**; this server only *grounds*, *validates* and
*executes* it — it holds no LLM key. It exposes two tool surfaces to any MCP
client (GitHub Copilot CLI / VS Code, Claude, Copilot Studio):

  Surface A (data questions):
    get_schema_summary  ->  list_views  ->  describe_view  ->  validate_sql  ->  run_query
  Surface B (read-only perf tuning — fixed server-authored diagnostics):
    perf_extensions / perf_health_check / perf_top_queries / perf_index_issues /
    perf_missing_indexes / perf_vacuum_health / perf_bloat_estimate /
    perf_config_review / perf_report / explain_query

Grounding (``get_schema_summary`` / ``list_views`` / ``describe_view``) is served
offline from the bundled schema pack. Execution (``validate_sql`` / ``run_query``)
runs the shared 7-step guardrail pipeline (``actone_data.guardrails``) against the
**live** view allowlist and executes on a read-only + statement-timeout session
(``actone_data.db``). The ``perf_*`` surface runs **fixed** (not LLM-authored)
diagnostic queries over ``pg_stat_*`` / ``pg_catalog`` / ``pg_settings``
(``actone_data.perf``), degrading gracefully when optional extensions are absent.
Every attempt — including rejections — is appended to the JSONL audit log
(``actone_data.audit``).

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

from actone_data import audit, db, rules, schema_pack, schema_packs
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
_rules_cache: dict[str, dict] = {}
_cfg_cache: dict = {}
_surface_cache: dict[str, Optional[dict]] = {}
_sol_pack_cache: dict[str, Optional[dict]] = {}
# stdio by default; the HTTP auth gate flips this to "mcp-http" on first request
# so audit records carry the right transport label.
_transport = "mcp-stdio"


def _pack() -> dict:
    global _pack_cache
    with _lock:
        if _pack_cache is None:
            _pack_cache = schema_pack.load()
        return _pack_cache


def _rules(solution: str = "actone") -> dict:
    key = (solution or "actone").strip().lower() or "actone"
    with _lock:
        if key not in _rules_cache:
            _rules_cache[key] = rules.load(solution=key)
        return _rules_cache[key]


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


def _constraints(solution: str = "actone"):
    return rules.to_constraints(_rules(solution))


def _surface(solution: str = "actone") -> Optional[dict]:
    """Solution schema-pack surface (``{schema, tables, version}``) or None for ActOne."""
    key = (solution or "actone").strip().lower() or "actone"
    with _lock:
        if key not in _surface_cache:
            _surface_cache[key] = schema_packs.surface(key)
        return _surface_cache[key]


def _sol_pack(solution: str) -> Optional[dict]:
    """Raw solution schema pack (full table/column detail) or None for ActOne/unknown."""
    key = (solution or "actone").strip().lower() or "actone"
    with _lock:
        if key not in _sol_pack_cache:
            _sol_pack_cache[key] = schema_packs.load(key)
        return _sol_pack_cache[key]


def _query_ctx(cfg, solution: str = "actone"):
    """Resolve ``(eff_schema, allowed)`` for a query.

    ActOne (no solution pack): ``(cfg.schema, None)`` — the live ``v_acm_*`` view
    allowlist is used. A solution with a bundled pack: the deployment-resolved
    solution schema and the pack's declared table names (intersected live).
    """
    surface = _surface(solution)
    if surface is None:
        return cfg.schema, None
    return cfg.solution_schema(surface["schema"]), surface["tables"]


# ── Tools ─────────────────────────────────────────────────────────────────────
@mcp.tool()
def get_schema_summary(solution: str = "actone") -> dict:
    """Overview of the query surface — **call this once per conversation, first**.

    Default (``solution="actone"``): the ActOne ``v_acm_*`` view surface — DB
    version, schema, view counts by family, the **preference rules** (prefer the
    permission-aware item views over legacy ``v_acm_alert*``) and global rules.

    Pass a **solution** name (``star`` / ``sam`` / ``cdd`` / ``wlf`` / ``ifm``) to
    orient on that installed solution's own schema instead: its schema name,
    version, table/kind counts, draft status, notes and the solution's rule-pack
    guidance. Then use ``list_views`` / ``describe_view`` (with the same
    ``solution``) for exact table + column names. Never guess names.

    Args:
        solution: ActOne (default) or a bundled solution name.

    Returns:
        For ActOne: ``version``, ``schema``, ``dialect``, ``view_count``,
        ``doc_only_count``, ``families``, ``preferred_count``, ``preference_rules``,
        ``rules``. For a solution: ``surface="solution"``, ``schema``, ``version``,
        ``table_count``, ``described_count``, ``kinds``, ``auxiliary_schemas``,
        ``draft``, ``notes``, ``preference_rules``, ``rules``. Unknown solution ->
        ``{error, available}``.
    """
    key = (solution or "actone").strip().lower() or "actone"
    if key != "actone":
        pack = _sol_pack(key)
        if pack is None:
            return {"error": "unknown_solution", "solution": key,
                    "available": schema_packs.available_solutions()}
        advice = rules.advisory(_rules(key))
        return {
            **schema_packs.table_summary(pack),
            "solution": key,
            "preference_rules": advice["preferences"].get("rationale", []),
            "rules": advice["rules"],
        }
    pack = _pack()
    advice = rules.advisory(_rules())
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
        "preference_rules": advice["preferences"].get("rationale", []),
        "rules": advice["rules"],
    }


@mcp.tool()
def list_solutions() -> dict:
    """Discover every grounded surface: the ActOne platform plus each solution pack.

    Returns one entry per bundled schema pack (latest version) with its grounding
    ``surface`` (``platform`` = ActOne ``v_acm_*`` views, ``solution`` = the
    solution's own tables), ``schema``, ``version``, object counts, description
    coverage, and ``draft`` status. Use this first to pick a ``solution`` name for
    the other tools.
    """
    return schema_packs.list_solutions()


@mcp.tool()
def list_business_solutions(solution: str = "ifm") -> dict:
    """List a product's licensed **business solutions** (e.g. IFM's Remote/Commercial/
    Card/Deposit/Authentication-IQ/New-Account-Fraud lines) and optional add-ons.

    A *business solution* is a license-driven subset of ONE product install — not a
    separate installer (except New Account Fraud). Each entry carries its official
    name, aliases, license flag, detection processes, and DB name markers
    (``v_ff_*`` views / tables) used for tagging and client detection. Use this to
    understand which fraud lines a product supports before querying, then
    ``detect_business_solutions`` to see which ones a specific deployment runs.

    Args:
        solution: product key (default ``ifm``).
    """
    from actone_data import business_solutions
    return business_solutions.list_business_solutions(solution or "ifm")


@mcp.tool()
def detect_business_solutions(env: str = "", solution: str = "ifm") -> dict:
    """Detect which **business solutions** a live deployment actually runs (read-only).

    Introspects the resolved solution/IDB schemas for the ``env`` deployment,
    collects the tables + views present, and matches them against the
    business-solution catalog markers. Returns ``present`` / ``absent`` /
    ``config_only`` verdicts so query grounding can be scoped to the fraud lines
    a client is licensed for (e.g. New Account Fraud present vs. absent).

    Args:
        env: environment/profile name (see ``list_environments``); empty = default.
        solution: product key (default ``ifm``).
    """
    from actone_data import perf
    return _perf_call(env, "detect_business_solutions",
                      lambda c: perf.detect_business_solutions(c, product=solution or "ifm"))


@mcp.tool()
def get_rules(solution: str = "") -> dict:
    """Return the active advisory rule pack and effective enforced constraints."""
    pack = _rules(solution or "actone")
    advice = rules.advisory(pack)
    constraints = rules.to_constraints(pack)
    raw_constraints = pack.get("constraints", {}) if isinstance(pack.get("constraints"), dict) else {}
    default_max_rows = raw_constraints.get("default_max_rows", 100)
    if not isinstance(default_max_rows, int):
        default_max_rows = 100
    return {
        **advice,
        "constraints": {
            "allowlist_prefixes": list(constraints.allowlist_prefixes),
            "deny_objects": sorted(constraints.deny_objects),
            "default_max_rows": default_max_rows,
            "row_cap": constraints.row_cap,
        },
    }


@mcp.tool()
def list_views(topic: str = "", solution: str = "actone") -> dict:
    """List the queryable objects for the surface (ActOne views or a solution's tables).

    Default (ActOne): the ``v_acm_*`` views (doc-only views hidden). Legacy alert
    views are returned with ``preferred: false`` so the model steers to the item
    equivalents. Pass a **solution** name to list that solution's own tables
    instead. ``topic`` filters by family (ActOne) or keyword (name/description).

    Args:
        topic: Optional family name or keyword filter. Empty returns all.
        solution: ActOne (default) or a bundled solution name.

    Returns:
        dict with ``count`` and ``views``: for ActOne ``{name, description,
        column_count, family, preferred}`` (preferred first); for a solution
        ``{name, description, column_count, kind, schema}`` plus
        ``surface="solution"``. Unknown solution -> ``{error, available}``.
    """
    key = (solution or "actone").strip().lower() or "actone"
    if key != "actone":
        pack = _sol_pack(key)
        if pack is None:
            return {"error": "unknown_solution", "solution": key,
                    "available": schema_packs.available_solutions()}
        return schema_packs.list_pack_tables(pack, topic)
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
def describe_view(view: str, solution: str = "actone") -> dict:
    """Describe one object: columns (name/type/description/fk), keys and relationships.

    Default (ActOne view): columns plus preference and the preferred item
    equivalents for legacy alert views. Use the ``fk`` targets to build JOINs —
    ``*_join_id`` columns are internal surrogate keys, valid only in JOIN
    conditions, never as literals in WHERE. Pass a **solution** name to describe
    that solution's table (columns, primary key, foreign keys). An unknown name
    returns ``suggestions`` (closest names) instead.

    Args:
        view: A view name (ActOne) or table name (solution), e.g. ``v_acm_items``.
        solution: ActOne (default) or a bundled solution name.

    Returns:
        The object detail dict, or ``{error, suggestions}`` if unknown.
    """
    key = (solution or "actone").strip().lower() or "actone"
    if key != "actone":
        pack = _sol_pack(key)
        if pack is None:
            return {"error": "unknown_solution", "solution": key,
                    "available": schema_packs.available_solutions()}
        return schema_packs.describe_pack_table(pack, view)
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
def validate_sql(sql: str, env: str = "", solution: str = "actone") -> dict:
    """Dry-run the guardrail pipeline on a SQL string — **no execution**.

    Run this before ``run_query`` to check a query and see the normalized SQL that
    would run. It parses the statement, enforces single read-only SELECT/UNION,
    the ``v_acm_*`` live allowlist, and injects/clamps a LIMIT.

    Args:
        sql: A single PostgreSQL SELECT over ``v_acm_*`` views.
        env: Target environment (profile) name from ``list_environments``; empty =
            the default environment. The allowlist is read from that environment's DB.
        solution: Rule-pack solution name. Defaults to the ActOne base pack.

    Returns:
        dict ``{ok, errors[], sql_used, views_used[], limit_injected}``.
    """
    try:
        env_name, cfg = _cfg(env)
    except KeyError as ke:
        return {"ok": False, "errors": [str(ke)], "sql_used": None,
                "views_used": [], "limit_injected": False}
    constraints = _constraints(solution)
    eff_schema, pack_tables = _query_ctx(cfg, solution)
    try:
        with db.connect(cfg, schema=(None if pack_tables is None else eff_schema)) as conn, conn.cursor() as cur:
            if pack_tables is None:
                allowed = db._live_view_names(cur, eff_schema, constraints.allowlist_prefixes)
            else:
                allowed = db.solution_allowlist(cur, eff_schema, pack_tables)
    except Exception as e:
        return {"ok": False, "errors": [f"connection failed: {e}"],
                "sql_used": None, "views_used": [], "limit_injected": False}
    res = _validate(sql, allowed, eff_schema, constraints=constraints)
    audit.record(transport=_transport, question="", sql=sql, ok=res["ok"],
                 sql_used=res["sql_used"],
                 rejected_reason=None if res["ok"] else "; ".join(res["errors"]),
                 db=cfg.target, env=env_name)
    return res


@mcp.tool()
def run_query(
    sql: str,
    max_rows: int = 100,
    question: str = "",
    env: str = "",
    solution: str = "actone",
) -> dict:
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
        solution: Rule-pack solution name. Defaults to the ActOne base pack.

    Returns:
        On success ``{ok: true, columns, rows, row_count, truncated, sql_used,
        views_used, limit_injected, duration_ms, masked_columns}``; on
        rejection/error ``{ok: false, errors[]}``. ``masked_columns`` lists any
        output columns whose values were redacted per the solution's PII rules.
    """
    try:
        env_name, cfg = _cfg(env)
    except KeyError as ke:
        return {"ok": False, "errors": [str(ke)]}
    try:
        eff_schema, pack_tables = _query_ctx(cfg, solution)
        res = db.run_query(
            cfg, sql, max_rows=max_rows, constraints=_constraints(solution),
            schema=(None if pack_tables is None else eff_schema),
            allowed=pack_tables,
        )
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


# ── Perf tools (Surface B: fixed server-authored diagnostics) ─────────────────
def _perf_call(env: str, tool: str, fn) -> dict:
    """Resolve the env, run a fixed diagnostic, audit it (category=perf)."""
    try:
        env_name, cfg = _cfg(env)
    except KeyError as ke:
        return {"ok": False, "errors": [str(ke)]}
    try:
        from actone_data import perf  # noqa: F401  (ensure module importable)
        result = fn(cfg)
    except Exception as e:  # noqa: BLE001
        audit.record(transport=_transport, question=tool, sql=f"[perf:{tool}]", ok=False,
                     rejected_reason=f"perf error: {e}", db=cfg.target, env=env_name,
                     category="perf")
        return {"ok": False, "errors": [f"perf error: {e}"]}
    audit.record(transport=_transport, question=tool, sql=f"[perf:{tool}]", ok=True,
                 db=cfg.target, env=env_name, category="perf")
    return result


@mcp.tool()
def perf_extensions(env: str = "") -> dict:
    """Which perf-relevant Postgres extensions are installed (``pg_stat_statements``,
    ``pgstattuple``, ``hypopg``). Call this first — several perf tools need them."""
    from actone_data import perf
    return _perf_call(env, "perf_extensions", perf.extensions)


@mcp.tool()
def perf_health_check(env: str = "") -> dict:
    """Cluster/DB health: cache hit ratio, rollback/deadlock/temp activity,
    connection saturation, and transaction-ID wraparound headroom (read-only)."""
    from actone_data import perf
    return _perf_call(env, "perf_health_check", perf.health_check)


@mcp.tool()
def perf_top_queries(env: str = "", sort: str = "total", limit: int = 20) -> dict:
    """Worst queries from ``pg_stat_statements`` — ``sort`` = total|mean|io|calls.

    Returns ``{available: false, note}`` if the extension isn't installed."""
    from actone_data import perf
    return _perf_call(env, "perf_top_queries", lambda c: perf.top_queries(c, sort=sort, limit=limit))


@mcp.tool()
def perf_index_issues(env: str = "") -> dict:
    """Unused (never-scanned) and invalid indexes — candidates to drop / REINDEX."""
    from actone_data import perf
    return _perf_call(env, "perf_index_issues", perf.index_issues)


@mcp.tool()
def perf_missing_indexes(env: str = "") -> dict:
    """Tables with heavy sequential scans — candidate indexing hotspots."""
    from actone_data import perf
    return _perf_call(env, "perf_missing_indexes", perf.missing_indexes)


@mcp.tool()
def perf_vacuum_health(env: str = "") -> dict:
    """Dead-tuple accumulation, autovacuum recency and settings (bloat risk)."""
    from actone_data import perf
    return _perf_call(env, "perf_vacuum_health", perf.vacuum_health)


@mcp.tool()
def perf_bloat_estimate(env: str = "") -> dict:
    """Table bloat via ``pgstattuple`` (degrades to a note if the extension is absent)."""
    from actone_data import perf
    return _perf_call(env, "perf_bloat_estimate", perf.bloat_estimate)


@mcp.tool()
def perf_config_review(env: str = "") -> dict:
    """Key planner / memory / autovacuum settings for review (advisory)."""
    from actone_data import perf
    return _perf_call(env, "perf_config_review", perf.config_review)


@mcp.tool()
def perf_report(env: str = "", markdown: bool = False, solution: str = "actone") -> dict:
    """Scored recommendation report — rolls up all Phase-1 checks.

    Returns ``{ok, health_score, grade, summary, severity_counts, findings[],
    sections{}, scope}`` (finding → severity → evidence → recommendation,
    worst-first). Set ``markdown=True`` to also include a rendered ``markdown``
    field. Pass ``solution`` (e.g. ``sam``, ``cdd``, ``cdd_prf``) to scope the
    table/index/vacuum checks to that solution's deployment schema; the default
    ``actone`` runs unscoped across the whole database.
    """
    from actone_data import perf
    result = _perf_call(env, "perf_report", lambda c: perf.perf_report(c, solution=solution))
    if markdown and result.get("ok"):
        result = {**result, "markdown": perf.render_report(result)}
    return result


@mcp.tool()
def explain_query(
    sql: str,
    env: str = "",
    analyze: bool = False,
    solution: str = "actone",
    hypothetical_indexes: Optional[list[str]] = None,
) -> dict:
    """``EXPLAIN (FORMAT JSON)`` a guardrail-validated SELECT (plan review).

    The SQL runs through the same guardrail as ``run_query`` before planning, so
    only a single read-only SELECT over the allowlist is accepted. ``analyze=True``
    **executes** the query (still read-only) to get real timings — default off.
    ``hypothetical_indexes`` are ``CREATE INDEX`` statements simulated in-session
    via HypoPG (no real DDL); ignored with a note if the extension is absent.

    Args:
        sql: A single SELECT over the (solution) allowlist.
        env: Target environment (profile) name; empty = default.
        analyze: Execute the query for real timings (read-only). Default False.
        solution: Solution surface for the allowlist. Default the ActOne views.
        hypothetical_indexes: Optional CREATE INDEX statements to simulate.

    Returns:
        ``{ok, analyze, sql_used, plan, hypothetical_indexes?, hypopg_note?}`` or
        ``{ok: false, errors[]}``.
    """
    from actone_data import perf
    try:
        env_name, cfg = _cfg(env)
    except KeyError as ke:
        return {"ok": False, "errors": [str(ke)]}
    try:
        eff_schema, pack_tables = _query_ctx(cfg, solution)
        result = perf.explain_query(
            cfg, sql, analyze=analyze, constraints=_constraints(solution),
            schema=(None if pack_tables is None else eff_schema),
            allowed=pack_tables, hypothetical_indexes=hypothetical_indexes,
        )
    except Exception as e:  # noqa: BLE001
        audit.record(transport=_transport, question="explain_query", sql=sql, ok=False,
                     rejected_reason=f"explain error: {e}", db=cfg.target, env=env_name,
                     category="perf")
        return {"ok": False, "errors": [f"explain error: {e}"]}
    audit.record(transport=_transport, question="explain_query", sql=sql,
                 ok=result.get("ok", False), sql_used=result.get("sql_used"),
                 rejected_reason=None if result.get("ok") else "; ".join(result.get("errors", [])),
                 db=cfg.target, env=env_name, category="perf")
    return result


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
