"""psycopg3 connection factory + read-only session for ActWise Data.

Every connection opens read-only at the DB level, with a statement timeout and
``search_path`` pinned to the configured schema, and identifies itself via
``application_name`` so it is greppable in ``pg_stat_activity`` / audit.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from actone_data.config import ConnConfig


def _session_options(cfg: "ConnConfig") -> str:
    return (
        "-c default_transaction_read_only=on "
        f"-c statement_timeout={int(cfg.timeout_ms)} "
        f"-c search_path={cfg.schema}"
    )


def connect(cfg: "ConnConfig"):
    """Open a read-only psycopg3 connection using the resolved config."""
    import psycopg

    options = _session_options(cfg)
    if cfg.dsn:
        return psycopg.connect(
            cfg.dsn,
            options=options,
            application_name=cfg.application_name,
            connect_timeout=cfg.connect_timeout_s,
        )
    return psycopg.connect(
        host=cfg.host,
        port=cfg.port,
        dbname=cfg.name,
        user=cfg.user,
        password=cfg.password,
        options=options,
        application_name=cfg.application_name,
        connect_timeout=cfg.connect_timeout_s,
    )


def ping(cfg: "ConnConfig") -> dict:
    """Connect and report server version, live schema, the ActOne sentinel table,
    and the count of documented ``v_acm_*`` views visible in the schema."""
    with connect(cfg) as conn, conn.cursor() as cur:
        cur.execute("SELECT version()")
        version = cur.fetchone()[0]
        cur.execute("SELECT current_schema()")
        current_schema = cur.fetchone()[0]
        cur.execute(
            "SELECT to_regclass(%s) IS NOT NULL",
            (f"{cfg.schema}.acm_md_config_params",),
        )
        sentinel = bool(cur.fetchone()[0])
        cur.execute(
            r"""
            SELECT count(*) FROM information_schema.views
            WHERE table_schema = %s AND table_name LIKE 'v\_acm\_%%'
            """,
            (cfg.schema,),
        )
        view_count = cur.fetchone()[0]
    return {
        "target": cfg.target,
        "schema": cfg.schema,
        "current_schema": current_schema,
        "server_version": version,
        "sentinel": sentinel,
        "v_acm_view_count": view_count,
    }


def introspect_views(cfg: "ConnConfig", prefix: str = "v_acm_") -> list[dict]:
    """Return the live ``prefix*`` views in the configured schema with their
    column counts, ordered by name. This is the ground truth the schema pack is
    reconciled against (doc-only vs introspected-only views)."""
    like = prefix.replace("_", r"\_") + "%"
    with connect(cfg) as conn, conn.cursor() as cur:
        cur.execute(
            r"""
            SELECT v.table_name,
                   (SELECT count(*) FROM information_schema.columns c
                    WHERE c.table_schema = v.table_schema
                      AND c.table_name = v.table_name) AS column_count
            FROM information_schema.views v
            WHERE v.table_schema = %s AND v.table_name LIKE %s
            ORDER BY v.table_name
            """,
            (cfg.schema, like),
        )
        return [{"name": r[0], "column_count": r[1]} for r in cur.fetchall()]


def introspect_columns(cfg: "ConnConfig", prefix: str = "v_acm_") -> dict[str, list[tuple[str, str]]]:
    """Return ``{view_name: [(column_name, data_type), ...]}`` in ordinal order
    for every ``prefix*`` view — the live source of truth for the schema pack's
    allowlist and column types."""
    like = prefix.replace("_", r"\_") + "%"
    out: dict[str, list[tuple[str, str]]] = {}
    with connect(cfg) as conn, conn.cursor() as cur:
        cur.execute(
            r"""
            SELECT c.table_name, c.column_name, c.data_type
            FROM information_schema.columns c
            JOIN information_schema.views v
              ON v.table_schema = c.table_schema AND v.table_name = c.table_name
            WHERE c.table_schema = %s AND c.table_name LIKE %s
            ORDER BY c.table_name, c.ordinal_position
            """,
            (cfg.schema, like),
        )
        for table, column, dtype in cur.fetchall():
            out.setdefault(table, []).append((column, dtype))
    return out


def _live_view_names(cur, schema: str, prefix: str = "v_acm_") -> set[str]:
    like = prefix.replace("_", r"\_") + "%"
    cur.execute(
        r"SELECT table_name FROM information_schema.views "
        r"WHERE table_schema = %s AND table_name LIKE %s",
        (schema, like),
    )
    return {r[0].lower() for r in cur.fetchall()}


def _coerce(value):
    """Make a DB value JSON-safe (dates/decimals/bytes -> str/float)."""
    import datetime as _dt
    from decimal import Decimal

    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (_dt.date, _dt.datetime, _dt.time)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).hex()
    return str(value)


def run_query(cfg: "ConnConfig", sql: str, max_rows: int = 100, cap: int = 1000) -> dict:
    """Validate (internally, always) then execute a read-only query.

    Raises ``guardrails.GuardrailError`` if the statement fails the pipeline, so a
    caller cannot bypass validation by skipping ``validate_sql``.
    """
    import time

    from actone_data import guardrails

    with connect(cfg) as conn, conn.cursor() as cur:
        allowed = _live_view_names(cur, cfg.schema)
        res = guardrails.validate(sql, allowed, cfg.schema, max_rows=max_rows, cap=cap)
        if not res["ok"]:
            raise guardrails.GuardrailError(res["errors"], res)

        t0 = time.perf_counter()
        cur.execute(res["sql_used"])
        columns = [d.name for d in cur.description] if cur.description else []
        fetched = cur.fetchmany(max_rows + 1)
        duration_ms = int((time.perf_counter() - t0) * 1000)

    truncated = len(fetched) > max_rows
    rows = [[_coerce(v) for v in row] for row in fetched[:max_rows]]
    return {
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "truncated": truncated,
        "sql_used": res["sql_used"],
        "views_used": res["views_used"],
        "limit_injected": res["limit_injected"],
        "duration_ms": duration_ms,
    }


def detect_version(cfg: "ConnConfig") -> dict:
    """Detect the ActOne product version from ``acm_md_versions``.

    On a freshly-seeded local DB this table is present but empty (no version
    stamp), so callers must fall back to the bundled/``--doc-version`` value.
    Returns ``{version, source, detail}`` where ``source`` is ``db`` or ``none``.
    """
    with connect(cfg) as conn, conn.cursor() as cur:
        cur.execute("SELECT to_regclass('acm_md_versions') IS NOT NULL")
        if not cur.fetchone()[0]:
            return {"version": None, "source": "none",
                    "detail": "acm_md_versions table absent"}
        cur.execute(
            """
            SELECT module_name, version_major, version_minor,
                   version_sub, version_build
            FROM acm_md_versions
            WHERE coalesce(fl_hidden, 0) = 0
            ORDER BY version_major DESC NULLS LAST,
                     version_minor DESC NULLS LAST,
                     version_sub   DESC NULLS LAST
            LIMIT 1
            """
        )
        row = cur.fetchone()
    if not row:
        return {"version": None, "source": "none",
                "detail": "acm_md_versions is empty (seeded DB carries no version stamp)"}
    module, maj, mnr, sub, build = row
    return {
        "version": f"V{maj}.{mnr}.{sub}",
        "source": "db",
        "detail": f"module={module} build={build}",
    }
