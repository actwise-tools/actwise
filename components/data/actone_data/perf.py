"""Read-only performance diagnostics (Surface B) for ActWise Data.

Server-authored **fixed** queries over ``pg_catalog`` / ``pg_stat_*`` /
``pg_settings`` — never LLM-authored SQL. This is the second, parallel tool
surface described in the 08-13 perf-tuning design: the model *names a tool*, it
does not write catalog SQL, so the read-only + audit guarantees are preserved.

Everything runs on the shared read-only session (``db.connect``:
``default_transaction_read_only=on`` + statement timeout). Extension-backed
checks (``pg_stat_statements``, ``pgstattuple``, ``hypopg``) **degrade
gracefully** — they return ``{"available": False, "note": ...}`` rather than
erroring when the extension is absent, mirroring how ``db.detect_version``
degrades on a stampless DB.

The functions here return structured findings; ``perf_report`` (Phase 2) rolls
them up into a scored recommendation report.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

from actone_data import db

if TYPE_CHECKING:
    from actone_data.config import ConnConfig

# Postgres settings surfaced by ``config_review`` (name -> short rationale).
_CONFIG_KEYS = (
    "shared_buffers",
    "effective_cache_size",
    "work_mem",
    "maintenance_work_mem",
    "wal_buffers",
    "max_wal_size",
    "min_wal_size",
    "checkpoint_completion_target",
    "random_page_cost",
    "effective_io_concurrency",
    "default_statistics_target",
    "max_connections",
    "autovacuum",
    "autovacuum_vacuum_scale_factor",
    "autovacuum_vacuum_threshold",
    "autovacuum_naptime",
    "max_parallel_workers",
    "max_worker_processes",
)


def _dictify(cur) -> list[dict]:
    cols = [d.name for d in cur.description] if cur.description else []
    return [{c: db._coerce(v) for c, v in zip(cols, row)} for row in cur.fetchall()]


def _installed_extensions(cur) -> set[str]:
    cur.execute("SELECT extname FROM pg_extension")
    return {r[0].lower() for r in cur.fetchall()}


def extensions(cfg: "ConnConfig") -> dict:
    """Report which perf-relevant extensions are installed (advisory)."""
    wanted = ("pg_stat_statements", "pgstattuple", "hypopg")
    with db.connect(cfg) as conn, conn.cursor() as cur:
        have = _installed_extensions(cur)
    return {"installed": {e: (e in have) for e in wanted}}


# ── Fixed diagnostics ─────────────────────────────────────────────────────────
def health_check(cfg: "ConnConfig") -> dict:
    """Cluster/DB health: cache hit ratio, rollback/deadlock/temp activity,
    connection saturation, and transaction-ID wraparound headroom."""
    with db.connect(cfg) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT numbackends,
                   xact_commit, xact_rollback,
                   blks_read, blks_hit,
                   round(100.0 * blks_hit / nullif(blks_hit + blks_read, 0), 2) AS cache_hit_pct,
                   round(100.0 * xact_rollback / nullif(xact_commit + xact_rollback, 0), 2) AS rollback_pct,
                   temp_files, temp_bytes, deadlocks, conflicts
            FROM pg_stat_database
            WHERE datname = current_database()
            """
        )
        db_stats = _dictify(cur)[0] if cur.rowcount != 0 else {}

        cur.execute(
            """
            SELECT (SELECT count(*) FROM pg_stat_activity) AS connections,
                   current_setting('max_connections')::int AS max_connections,
                   round(100.0 * (SELECT count(*) FROM pg_stat_activity)
                         / nullif(current_setting('max_connections')::int, 0), 1) AS connection_pct
            """
        )
        conn_stats = _dictify(cur)[0]

        # Transaction-ID wraparound headroom (autovacuum_freeze_max_age default 200M;
        # hard limit ~2^31). Report the most-aged database.
        cur.execute(
            """
            SELECT datname, age(datfrozenxid) AS xid_age,
                   2147483648 - age(datfrozenxid) AS xid_headroom
            FROM pg_database
            WHERE datallowconn
            ORDER BY age(datfrozenxid) DESC
            LIMIT 1
            """
        )
        wrap = _dictify(cur)[0]

    return {"ok": True, "database": db_stats, "connections": conn_stats,
            "wraparound": wrap}


def top_queries(cfg: "ConnConfig", sort: str = "total", limit: int = 20) -> dict:
    """Worst queries from ``pg_stat_statements`` (needs the extension).

    ``sort``: ``total`` (total exec time) | ``mean`` | ``io`` (shared block IO) |
    ``calls``.
    """
    order = {
        "total": "total_exec_time",
        "mean": "mean_exec_time",
        "io": "(shared_blks_read + shared_blks_written)",
        "calls": "calls",
    }.get((sort or "total").lower(), "total_exec_time")
    limit = max(1, min(int(limit), 100))
    with db.connect(cfg) as conn, conn.cursor() as cur:
        if "pg_stat_statements" not in _installed_extensions(cur):
            return {"ok": True, "available": False,
                    "note": "pg_stat_statements is not installed; enable it "
                            "(shared_preload_libraries + CREATE EXTENSION) for query workload analysis."}
        cur.execute(
            f"""
            SELECT calls,
                   round(total_exec_time::numeric, 1) AS total_ms,
                   round(mean_exec_time::numeric, 2) AS mean_ms,
                   rows,
                   round(100.0 * shared_blks_hit
                         / nullif(shared_blks_hit + shared_blks_read, 0), 1) AS hit_pct,
                   left(query, 500) AS query
            FROM pg_stat_statements
            WHERE query NOT LIKE '%%pg_stat_statements%%'
            ORDER BY {order} DESC NULLS LAST
            LIMIT %s
            """,
            (limit,),
        )
        return {"ok": True, "available": True, "sort": sort, "queries": _dictify(cur)}


def index_issues(cfg: "ConnConfig", limit: int = 30, schema: str | None = None) -> dict:
    """Unused and invalid indexes (candidates to drop / rebuild).

    When ``schema`` is given, results are scoped to that schema (solution-aware).
    """
    limit = max(1, min(int(limit), 200))
    with db.connect(cfg) as conn, conn.cursor() as cur:
        unused_filter = "AND s.schemaname = %s" if schema else ""
        cur.execute(
            f"""
            SELECT s.schemaname, s.relname AS table, s.indexrelname AS index,
                   s.idx_scan,
                   pg_relation_size(s.indexrelid) AS bytes,
                   pg_size_pretty(pg_relation_size(s.indexrelid)) AS size
            FROM pg_stat_user_indexes s
            JOIN pg_index i ON i.indexrelid = s.indexrelid
            WHERE s.idx_scan = 0 AND NOT i.indisprimary AND NOT i.indisunique
              {unused_filter}
            ORDER BY pg_relation_size(s.indexrelid) DESC
            LIMIT %s
            """,
            ((schema, limit) if schema else (limit,)),
        )
        unused = _dictify(cur)
        invalid_filter = "AND n.nspname = %s" if schema else ""
        cur.execute(
            f"""
            SELECT n.nspname AS schemaname, t.relname AS table, c.relname AS index
            FROM pg_index i
            JOIN pg_class c ON c.oid = i.indexrelid
            JOIN pg_class t ON t.oid = i.indrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE NOT i.indisvalid AND n.nspname NOT IN ('pg_catalog', 'pg_toast')
              {invalid_filter}
            ORDER BY n.nspname, t.relname
            """,
            ((schema,) if schema else None),
        )
        invalid = _dictify(cur)
    return {"ok": True, "unused_indexes": unused, "invalid_indexes": invalid}


def missing_indexes(cfg: "ConnConfig", limit: int = 30, min_live_tup: int = 10000,
                    schema: str | None = None) -> dict:
    """Heavy sequential-scan tables — candidates that may benefit from an index.

    When ``schema`` is given, results are scoped to that schema (solution-aware).
    """
    limit = max(1, min(int(limit), 200))
    with db.connect(cfg) as conn, conn.cursor() as cur:
        schema_filter = "AND schemaname = %s" if schema else ""
        params = ([int(min_live_tup)] + ([schema] if schema else []) + [limit])
        cur.execute(
            f"""
            SELECT schemaname, relname AS table,
                   seq_scan, seq_tup_read, idx_scan,
                   n_live_tup,
                   round(seq_tup_read::numeric / nullif(seq_scan, 0), 0) AS avg_tup_per_seq,
                   pg_size_pretty(pg_relation_size(relid)) AS size
            FROM pg_stat_user_tables
            WHERE seq_scan > 0
              AND n_live_tup >= %s
              {schema_filter}
              AND (idx_scan IS NULL OR seq_scan > idx_scan)
            ORDER BY seq_tup_read DESC
            LIMIT %s
            """,
            tuple(params),
        )
        return {"ok": True, "seq_scan_hotspots": _dictify(cur)}


def _ident(name: str) -> str:
    """Quote a SQL identifier only when needed (advisory DDL is display-only)."""
    return name if re.fullmatch(r"[a-z_][a-z0-9_]*", name or "") else '"' + str(name).replace('"', '""') + '"'


def unindexed_foreign_keys(cfg: "ConnConfig", limit: int = 50,
                           schema: str | None = None) -> dict:
    """Foreign-key columns with no supporting index — concrete index candidates.

    A FK whose columns are not the leading prefix of any index forces a
    sequential scan on every JOIN and parent-row delete/update. This is the
    canonical, universally-safe indexing win (independent of schema-pack
    coverage). Results carry an **advisory** ``CREATE INDEX`` statement — the
    engine is read-only and never executes it. When ``schema`` is given the scan
    is scoped to that solution's schema.
    """
    limit = max(1, min(int(limit), 200))
    with db.connect(cfg) as conn, conn.cursor() as cur:
        schema_filter = "AND n.nspname = %s" if schema else "AND n.nspname NOT IN ('pg_catalog','information_schema')"
        params = ([schema] if schema else []) + [limit]
        cur.execute(
            f"""
            SELECT n.nspname AS schemaname,
                   cl.relname AS table,
                   c.conname AS fk_name,
                   ( SELECT string_agg(a.attname, ', ' ORDER BY k.ord)
                       FROM unnest(c.conkey) WITH ORDINALITY AS k(attnum, ord)
                       JOIN pg_attribute a
                         ON a.attrelid = c.conrelid AND a.attnum = k.attnum ) AS fk_columns,
                   pg_size_pretty(pg_relation_size(c.conrelid)) AS table_size
            FROM pg_constraint c
            JOIN pg_class cl ON cl.oid = c.conrelid
            JOIN pg_namespace n ON n.oid = cl.relnamespace
            WHERE c.contype = 'f'
              {schema_filter}
              AND NOT EXISTS (
                  SELECT 1 FROM pg_index i
                  WHERE i.indrelid = c.conrelid
                    AND (i.indkey::int2[])[0:cardinality(c.conkey) - 1] @> c.conkey
              )
            ORDER BY pg_relation_size(c.conrelid) DESC, n.nspname, cl.relname
            LIMIT %s
            """,
            tuple(params),
        )
        rows = _dictify(cur)

    for r in rows:
        cols = [c.strip() for c in str(r.get("fk_columns") or "").split(",") if c.strip()]
        if not cols:
            continue
        idx_name = "idx_{}_{}".format(r["table"], "_".join(cols)).replace(" ", "")[:63]
        target = f'{_ident(r["schemaname"])}.{_ident(r["table"])}'
        col_list = ", ".join(_ident(c) for c in cols)
        r["candidate_ddl"] = (
            f"CREATE INDEX CONCURRENTLY {_ident(idx_name)} ON {target} ({col_list});"
        )
    return {"ok": True, "unindexed_fks": rows}


def vacuum_health(cfg: "ConnConfig", limit: int = 30, min_dead_tup: int = 1000,
                  schema: str | None = None) -> dict:
    """Dead-tuple accumulation + autovacuum recency and settings.

    When ``schema`` is given, the dead-tuple table list is scoped to that schema
    (solution-aware); the global autovacuum settings are always returned.
    """
    """Dead-tuple accumulation + autovacuum recency and settings.

    When ``schema`` is given, the dead-tuple table list is scoped to that schema
    (solution-aware); the global autovacuum settings are always returned.
    """
    limit = max(1, min(int(limit), 200))
    with db.connect(cfg) as conn, conn.cursor() as cur:
        schema_filter = "AND schemaname = %s" if schema else ""
        params = ([int(min_dead_tup)] + ([schema] if schema else []) + [limit])
        cur.execute(
            f"""
            SELECT schemaname, relname AS table,
                   n_live_tup, n_dead_tup,
                   round(100.0 * n_dead_tup / nullif(n_live_tup + n_dead_tup, 0), 1) AS dead_pct,
                   last_vacuum, last_autovacuum, last_analyze, last_autoanalyze,
                   vacuum_count, autovacuum_count
            FROM pg_stat_user_tables
            WHERE n_dead_tup >= %s
              {schema_filter}
            ORDER BY n_dead_tup DESC
            LIMIT %s
            """,
            tuple(params),
        )
        tables = _dictify(cur)
        cur.execute(
            """
            SELECT name, setting FROM pg_settings
            WHERE name IN ('autovacuum', 'autovacuum_vacuum_scale_factor',
                           'autovacuum_vacuum_threshold', 'autovacuum_naptime',
                           'autovacuum_max_workers')
            ORDER BY name
            """
        )
        settings = {r["name"]: r["setting"] for r in _dictify(cur)}
    return {"ok": True, "autovacuum_settings": settings, "high_dead_tuple_tables": tables}


def bloat_estimate(cfg: "ConnConfig", limit: int = 20, schema: str | None = None) -> dict:
    """Table bloat via ``pgstattuple`` (needs the extension).

    Uses the lighter ``pgstattuple_approx`` when available; bounded to the
    largest tables to keep it cheap. Degrades gracefully — fall back to
    ``vacuum_health`` dead-tuple ratios when the extension is absent. When
    ``schema`` is given, candidate tables are scoped to that schema.
    """
    limit = max(1, min(int(limit), 50))
    with db.connect(cfg) as conn, conn.cursor() as cur:
        if "pgstattuple" not in _installed_extensions(cur):
            return {"ok": True, "available": False,
                    "note": "pgstattuple is not installed; enable it (CREATE EXTENSION "
                            "pgstattuple) for precise bloat, or use vacuum_health dead-tuple "
                            "ratios as a proxy."}
        schema_filter = "AND n.nspname = %s" if schema else ""
        params = (([schema] if schema else []) + [limit])
        cur.execute(
            f"""
            SELECT n.nspname AS schemaname, c.relname AS table,
                   pg_relation_size(c.oid) AS bytes,
                   pg_size_pretty(pg_relation_size(c.oid)) AS size
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relkind = 'r'
              AND n.nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
              AND pg_relation_size(c.oid) > 8 * 1024 * 1024
              {schema_filter}
            ORDER BY pg_relation_size(c.oid) DESC
            LIMIT %s
            """,
            tuple(params),
        )
        candidates = _dictify(cur)
        out = []
        for row in candidates:
            ident = f'"{row["schemaname"]}"."{row["table"]}"'
            try:
                cur.execute(
                    "SELECT approx_free_percent, approx_free_space "
                    "FROM pgstattuple_approx(%s::regclass)",
                    (ident,),
                )
                stat = _dictify(cur)
            except Exception as e:  # noqa: BLE001 - degrade per-table, never fail the tool
                conn.rollback()
                out.append({**row, "error": str(e)})
                continue
            if stat:
                out.append({
                    "schemaname": row["schemaname"], "table": row["table"],
                    "size": row["size"],
                    "free_pct": stat[0].get("approx_free_percent"),
                    "free_bytes": stat[0].get("approx_free_space"),
                })
        out.sort(key=lambda r: (r.get("free_pct") or 0), reverse=True)
    return {"ok": True, "available": True, "bloat": out}


def config_review(cfg: "ConnConfig") -> dict:
    """Key planner / memory / autovacuum settings for review (advisory)."""
    with db.connect(cfg) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT name, setting, unit, source, boot_val
            FROM pg_settings
            WHERE name = ANY(%s)
            ORDER BY name
            """,
            (list(_CONFIG_KEYS),),
        )
        settings = _dictify(cur)
        cur.execute("SELECT version()")
        version = cur.fetchone()[0]
    return {"ok": True, "server_version": version, "settings": settings}


# ── Phase 2 · scored recommendation report ────────────────────────────────────
_SEVERITY_RANK = {"critical": 3, "warn": 2, "info": 1, "ok": 0}
_SEVERITY_PENALTY = {"critical": 25, "warn": 10, "info": 3, "ok": 0}

# Authoritative PostgreSQL documentation per finding dimension, so every
# recommendation carries a source_url the caller can cite (plan Workstream 2:
# finding · severity · evidence · fix · source_url).
_DOC_CITATIONS = {
    "cache": "https://www.postgresql.org/docs/current/runtime-config-resource.html#GUC-SHARED-BUFFERS",
    "transactions": "https://www.postgresql.org/docs/current/monitoring-stats.html",
    "connections": "https://www.postgresql.org/docs/current/runtime-config-connection.html#GUC-MAX-CONNECTIONS",
    "wraparound": "https://www.postgresql.org/docs/current/routine-vacuuming.html#VACUUM-FOR-WRAPAROUND",
    "health": "https://www.postgresql.org/docs/current/monitoring-stats.html",
    "indexes": "https://www.postgresql.org/docs/current/indexes.html",
    "missing_indexes": "https://www.postgresql.org/docs/current/indexes.html",
    "index_candidates": "https://www.postgresql.org/docs/current/ddl-constraints.html#DDL-CONSTRAINTS-FK",
    "vacuum": "https://www.postgresql.org/docs/current/routine-vacuuming.html",
    "workload": "https://www.postgresql.org/docs/current/pgstatstatements.html",
}


def _finding(dimension: str, severity: str, title: str, evidence, recommendation: str,
             source_url: str | None = None) -> dict:
    return {"dimension": dimension, "severity": severity, "title": title,
            "evidence": evidence, "recommendation": recommendation,
            "source_url": source_url or _DOC_CITATIONS.get(dimension)}


def _num(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def resolve_solution_schema(cfg: "ConnConfig", solution: str | None) -> str | None:
    """Resolve a solution name to its live deployment schema, or None.

    Returns None for the ActOne base (``actone``/empty) — perf checks then run
    unscoped across the whole database. For a solution pack, returns the
    deployment-resolved schema (e.g. ``bppr_sam_app``) so perf checks target
    only that solution's tables/indexes.
    """
    sol = (solution or "").strip().lower()
    if not sol or sol == "actone":
        return None
    from actone_data import schema_packs

    surface = schema_packs.surface(sol)
    if surface is None:
        return None
    return cfg.solution_schema(surface["schema"])


def detect_business_solutions(cfg: "ConnConfig", product: str = "ifm") -> dict:
    """Detect which business solutions a live deployment actually runs (read-only).

    Scans every bundled schema pack for ``product`` (e.g. ``ifm``, ``ifm_idb``,
    ``ifm_idb_stg``), resolves each to its live deployment schema, collects the
    base tables + views present, and matches them against the business-solution
    catalog markers. Returns the catalog ``detect()`` verdict (present / absent /
    config_only) plus the schemas scanned and the live object count.
    """
    from actone_data import business_solutions as bs, schema_packs, db

    catalog = bs.load_catalog(product)
    if catalog is None:
        return {"ok": False, "errors": [f"no business-solution catalog for {product!r}"]}
    prod = (product or "").strip().lower()
    keys = [k for k in schema_packs.available_solutions()
            if k == prod or k.startswith(prod + "_")]
    scanned: list[dict] = []
    present: set[str] = set()
    conn = db.connect(cfg)
    try:
        with conn.cursor() as cur:
            for key in keys:
                surface = schema_packs.surface(key)
                if surface is None:
                    continue
                schema = cfg.solution_schema(surface["schema"])
                try:
                    objs = db._live_object_names(cur, schema)
                except Exception as e:  # noqa: BLE001
                    scanned.append({"pack": key, "schema": schema, "ok": False, "error": str(e)})
                    continue
                present |= objs
                scanned.append({"pack": key, "schema": schema, "ok": True,
                                "object_count": len(objs)})
    finally:
        conn.close()
    verdict = bs.detect(present, catalog)
    return {"ok": True, "scanned_schemas": scanned,
            "live_object_count": len(present), **verdict}


def perf_report(cfg: "ConnConfig", solution: str | None = None) -> dict:
    """Roll up the Phase 1 diagnostics into a scored recommendation report.

    Returns ``{ok, health_score, grade, summary, findings[], sections{}, scope}``.
    ``findings`` is finding -> severity -> evidence -> recommendation -> source_url,
    sorted worst-first. ``sections`` carries the raw per-check output. When ``solution``
    resolves to a solution schema, the table/index-scoped checks (indexes,
    missing_indexes, vacuum) target only that schema; server-wide checks
    (health, config, top_queries) remain global.
    """
    schema = resolve_solution_schema(cfg, solution)
    sections: dict[str, dict] = {}
    findings: list[dict] = []

    def _safe(name, fn):
        try:
            sections[name] = fn()
        except Exception as e:  # noqa: BLE001 - a failed check must not sink the report
            sections[name] = {"ok": False, "error": str(e)}

    _safe("health", lambda: health_check(cfg))
    _safe("indexes", lambda: index_issues(cfg, schema=schema))
    _safe("missing_indexes", lambda: missing_indexes(cfg, schema=schema))
    _safe("index_candidates", lambda: unindexed_foreign_keys(cfg, schema=schema))
    _safe("vacuum", lambda: vacuum_health(cfg, schema=schema))
    _safe("config", lambda: config_review(cfg))
    _safe("top_queries", lambda: top_queries(cfg))

    # ── Health ────────────────────────────────────────────────────────────────
    health = sections.get("health", {})
    if health.get("ok"):
        dbst = health.get("database", {})
        hit = _num(dbst.get("cache_hit_pct"))
        if hit is not None:
            if hit < 90:
                findings.append(_finding("cache", "critical", f"Low cache hit ratio ({hit}%)",
                    {"cache_hit_pct": hit}, "Increase shared_buffers / effective_cache_size; investigate large seq scans."))
            elif hit < 99:
                findings.append(_finding("cache", "warn", f"Cache hit ratio below 99% ({hit}%)",
                    {"cache_hit_pct": hit}, "Consider raising shared_buffers or adding indexes for hot tables."))
        rb = _num(dbst.get("rollback_pct"))
        if rb is not None and rb > 5:
            findings.append(_finding("transactions", "warn" if rb <= 20 else "critical",
                f"High rollback ratio ({rb}%)", {"rollback_pct": rb},
                "Investigate failing transactions / application error handling."))
        if _num(dbst.get("deadlocks")) and _num(dbst.get("deadlocks")) > 0:
            findings.append(_finding("transactions", "info", f"Deadlocks recorded ({dbst.get('deadlocks')})",
                {"deadlocks": dbst.get("deadlocks")}, "Review lock ordering in concurrent write paths."))
        conns = health.get("connections", {})
        cpct = _num(conns.get("connection_pct"))
        if cpct is not None and cpct > 80:
            findings.append(_finding("connections", "warn" if cpct <= 90 else "critical",
                f"Connection pool near saturation ({cpct}%)",
                {"connections": conns.get("connections"), "max_connections": conns.get("max_connections")},
                "Add a pooler (PgBouncer) or raise max_connections with care for memory."))
        wrap = health.get("wraparound", {})
        age = _num(wrap.get("xid_age"))
        if age is not None and age > 1_500_000_000:
            findings.append(_finding("wraparound", "warn" if age <= 1_800_000_000 else "critical",
                f"Transaction-ID age high on {wrap.get('datname')} ({int(age):,})",
                wrap, "Ensure autovacuum is keeping up; a manual VACUUM (FREEZE) may be needed."))
    else:
        findings.append(_finding("health", "warn", "Health check failed",
            {"error": health.get("error")}, "Ensure the role has pg_monitor / pg_read_all_stats."))

    # ── Indexes ─────────────────────────────────────────────────────────────────
    idx = sections.get("indexes", {})
    if idx.get("ok"):
        invalid = idx.get("invalid_indexes") or []
        if invalid:
            findings.append(_finding("indexes", "warn", f"{len(invalid)} invalid index(es)",
                invalid[:10], "REINDEX the invalid indexes (likely from a failed CREATE INDEX)."))
        unused = idx.get("unused_indexes") or []
        big_unused = [u for u in unused if (_num(u.get("bytes")) or 0) > 50 * 1024 * 1024]
        if big_unused:
            findings.append(_finding("indexes", "info",
                f"{len(big_unused)} large unused index(es) (never scanned)",
                big_unused[:10], "Consider dropping after confirming they aren't needed for rare/failover queries."))

    # ── Missing indexes ────────────────────────────────────────────────────────
    mi = sections.get("missing_indexes", {})
    if mi.get("ok"):
        hot = mi.get("seq_scan_hotspots") or []
        if hot:
            findings.append(_finding("missing_indexes", "info" if len(hot) < 5 else "warn",
                f"{len(hot)} table(s) with heavy sequential scans",
                hot[:10], "Review WHERE/JOIN predicates on these tables for indexing opportunities (see explain_query)."))

    # ── Index candidates (unindexed foreign keys) ──────────────────────────────
    ic = sections.get("index_candidates", {})
    if ic.get("ok"):
        fks = ic.get("unindexed_fks") or []
        if fks:
            findings.append(_finding("index_candidates", "info" if len(fks) < 5 else "warn",
                f"{len(fks)} unindexed foreign key(s) — concrete index candidates",
                fks[:10],
                "Each foreign key without a supporting index forces a sequential scan on JOINs "
                "and parent-row deletes/updates. Review and apply the advisory `candidate_ddl` "
                "(shown per row) — the engine is read-only and does not execute it. Prefer "
                "`CREATE INDEX CONCURRENTLY` in production."))

    # ── Vacuum ─────────────────────────────────────────────────────────────────
    vac = sections.get("vacuum", {})
    if vac.get("ok"):
        if (vac.get("autovacuum_settings", {}).get("autovacuum") or "on") == "off":
            findings.append(_finding("vacuum", "critical", "autovacuum is disabled",
                vac.get("autovacuum_settings"), "Re-enable autovacuum; manual vacuuming rarely keeps pace."))
        dead = vac.get("high_dead_tuple_tables") or []
        worst = [t for t in dead if (_num(t.get("dead_pct")) or 0) >= 20]
        if worst:
            crit = any((_num(t.get("dead_pct")) or 0) >= 40 for t in worst)
            findings.append(_finding("vacuum", "critical" if crit else "warn",
                f"{len(worst)} table(s) with high dead-tuple ratio (bloat risk)",
                worst[:10], "Tune per-table autovacuum thresholds or VACUUM the worst offenders."))

    # ── Top queries ────────────────────────────────────────────────────────────
    tq = sections.get("top_queries", {})
    if tq.get("ok") and not tq.get("available", True):
        findings.append(_finding("workload", "info", "pg_stat_statements not installed",
            {"note": tq.get("note")}, "Enable pg_stat_statements to identify the heaviest queries."))

    findings.sort(key=lambda f: _SEVERITY_RANK.get(f["severity"], 0), reverse=True)
    score = max(0, 100 - sum(_SEVERITY_PENALTY.get(f["severity"], 0) for f in findings))
    grade = ("A" if score >= 90 else "B" if score >= 75 else
             "C" if score >= 60 else "D" if score >= 40 else "F")
    counts = {s: sum(1 for f in findings if f["severity"] == s)
              for s in ("critical", "warn", "info")}
    summary = (f"{counts['critical']} critical, {counts['warn']} warnings, "
               f"{counts['info']} advisory findings.")
    return {"ok": True, "target": cfg.target, "health_score": score, "grade": grade,
            "summary": summary, "severity_counts": counts, "findings": findings,
            "sections": sections,
            "scope": {"solution": (solution or "actone"), "schema": schema}}


def render_report(report: dict) -> str:
    """Render a ``perf_report`` result as Markdown."""
    if not report.get("ok"):
        return f"# Performance report — FAILED\n\n{report.get('error', 'unknown error')}\n"
    lines = [
        f"# Performance report — {report.get('target', '')}",
        "",
        f"**Health score:** {report['health_score']}/100 (grade {report['grade']})  ",
        f"**Summary:** {report['summary']}",
    ]
    scope = report.get("scope") or {}
    if scope.get("schema"):
        lines.append(f"**Scope:** solution `{scope.get('solution')}` (schema `{scope['schema']}`)  ")
    lines += [
        "",
        "## Findings",
        "",
    ]
    if not report["findings"]:
        lines.append("_No issues detected._")
    for f in report["findings"]:
        badge = f["severity"].upper()
        lines.append(f"### [{badge}] {f['title']}  ·  _{f['dimension']}_")
        lines.append(f"- **Recommendation:** {f['recommendation']}")
        if f.get("source_url"):
            lines.append(f"- **Reference:** {f['source_url']}")
        ddls = [row.get("candidate_ddl") for row in f["evidence"]
                if isinstance(row, dict) and row.get("candidate_ddl")] \
            if isinstance(f.get("evidence"), list) else []
        if ddls:
            lines.append("- **Candidate indexes (advisory — not executed):**")
            lines.append("")
            lines.append("```sql")
            lines.extend(ddls)
            lines.append("```")
        lines.append("")
    return "\n".join(lines) + "\n"


# ── Phase 3 · EXPLAIN plan review + hypothetical-index what-if ─────────────────
_CREATE_INDEX_RE = re.compile(r"^\s*create\s+index\b", re.IGNORECASE)


def explain_query(
    cfg: "ConnConfig",
    sql: str,
    *,
    analyze: bool = False,
    schema: str | None = None,
    allowed=None,
    constraints=None,
    hypothetical_indexes: list[str] | None = None,
) -> dict:
    """``EXPLAIN (FORMAT JSON)`` a guardrail-validated SELECT, optionally with
    HypoPG hypothetical indexes.

    The SQL is put through the same guardrail as ``run_query`` (single read-only
    SELECT over the allowlist) before planning, so this cannot run arbitrary SQL.
    ``analyze=True`` **executes** the query (still read-only) — the tool layer
    keeps it default-off. ``hypothetical_indexes`` are ``CREATE INDEX`` statements
    simulated in-session via HypoPG (no real DDL); ignored with a note when the
    extension is absent.
    """
    from actone_data import guardrails

    eff_schema = schema or cfg.schema
    with db.connect(cfg, schema=schema) as conn, conn.cursor() as cur:
        active = constraints or guardrails.Constraints()
        if allowed is None:
            allowed_set = db._live_view_names(cur, eff_schema, active.allowlist_prefixes)
        else:
            allowed_set = db.solution_allowlist(cur, eff_schema, allowed)
        res = guardrails.validate(sql, allowed_set, eff_schema, constraints=active)
        if not res["ok"]:
            return {"ok": False, "errors": res["errors"]}

        exts = _installed_extensions(cur)
        hypo_created: list[dict] = []
        hypo_note = None
        if hypothetical_indexes:
            if "hypopg" not in exts:
                hypo_note = "hypopg not installed; hypothetical indexes ignored."
            else:
                for ddl in hypothetical_indexes:
                    if not _CREATE_INDEX_RE.match(ddl or ""):
                        return {"ok": False, "errors": [
                            "hypothetical_indexes accepts only CREATE INDEX statements"]}
                    cur.execute("SELECT indexname FROM hypopg_create_index(%s)", (ddl,))
                    hypo_created.extend(_dictify(cur))

        analyze_kw = "ANALYZE, " if analyze else ""
        try:
            cur.execute(f"EXPLAIN ({analyze_kw}FORMAT JSON) {res['sql_used']}")
            plan = cur.fetchone()[0]
        finally:
            if hypo_created:
                cur.execute("SELECT hypopg_reset()")

    out = {"ok": True, "analyze": analyze, "sql_used": res["sql_used"], "plan": plan}
    if hypothetical_indexes:
        out["hypothetical_indexes"] = hypo_created
    if hypo_note:
        out["hypopg_note"] = hypo_note
    return out


