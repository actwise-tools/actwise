"""Read-only SQL guardrail pipeline (shared by ``validate_sql`` and ``run_query``).

A single deterministic AST pipeline over sqlglot's postgres dialect. It never
executes anything — it decides whether a statement is a safe, single, read-only
SELECT restricted to the live ``v_acm_*`` allowlist, and returns the normalized
SQL to run. ``run_query`` re-runs this internally, so skipping ``validate_sql``
can never bypass a guardrail.
"""
from __future__ import annotations

import sqlglot
from sqlglot import exp
from sqlglot.optimizer.normalize_identifiers import normalize_identifiers

DEFAULT_MAX_ROWS = 100
ROW_CAP = 1000
_VIEW_PREFIX = "v_acm_"


class GuardrailError(Exception):
    """Raised when a statement fails validation. Carries the full result dict."""

    def __init__(self, errors: list[str], result: dict | None = None):
        super().__init__("; ".join(errors))
        self.errors = errors
        self.result = result or {}


def _limit_value(root) -> int | None:
    lim = root.args.get("limit")
    if lim is None:
        return None
    try:
        return int(lim.expression.name)
    except (AttributeError, ValueError, TypeError):
        return None


def validate(
    sql: str,
    allowed_views,
    schema: str,
    max_rows: int = DEFAULT_MAX_ROWS,
    cap: int = ROW_CAP,
) -> dict:
    """Run the 7-step pipeline. Returns
    ``{ok, errors[], sql_used, views_used[], limit_injected}``."""
    allowed = {v.lower() for v in allowed_views}
    schema_l = (schema or "").lower()
    errors: list[str] = []
    result = {"ok": False, "errors": errors, "sql_used": None,
              "views_used": [], "limit_injected": False}

    # 1. Parse.
    try:
        statements = sqlglot.parse(sql, read="postgres")
    except Exception as e:  # sqlglot.errors.ParseError and friends
        errors.append(f"parse error: {e}")
        return result
    statements = [s for s in statements if s is not None]

    # 2. Exactly one statement.
    if len(statements) != 1:
        errors.append(f"expected exactly one statement, got {len(statements)}")
        return result
    root = statements[0]

    # 3. Root must be SELECT/UNION (CTEs allowed) — no DML/DDL/COPY/SET/CALL/…
    if not isinstance(root, (exp.Select, exp.Union)):
        errors.append(f"only read-only SELECT queries are allowed (got {type(root).__name__.upper()})")
        return result

    # 4. Reject SELECT … INTO and FOR UPDATE/SHARE.
    if root.args.get("into") or any(True for _ in root.find_all(exp.Into)):
        errors.append("SELECT ... INTO is not allowed")
    if any(True for _ in root.find_all(exp.Lock)):
        errors.append("FOR UPDATE/SHARE locking clauses are not allowed")

    # 5. Allowlist walk (excluding CTE-defined names); ≥1 real table required.
    cte_names = {c.alias.lower() for c in root.find_all(exp.CTE) if c.alias}
    real_tables = []
    for t in root.find_all(exp.Table):
        name = (t.name or "").lower()
        if name in cte_names:
            continue  # reference to a CTE, not a physical table
        real_tables.append(t)
        if t.catalog:
            errors.append(f"cross-database reference not allowed: {t.catalog}.{t.db}.{t.name}")
            continue
        if t.db and t.db.lower() != schema_l:
            errors.append(f"table {t.name} must be in schema {schema_l!r}, not {t.db!r}")
            continue
        if not name.startswith(_VIEW_PREFIX):
            errors.append(f"table {t.name!r} is not an allowlisted {_VIEW_PREFIX}* view")
            continue
        if name not in allowed:
            errors.append(f"view {name!r} is not in the live allowlist")
    if not real_tables:
        errors.append("query must read from at least one v_acm_* view")

    views_used = sorted({(t.name or "").lower() for t in real_tables})
    result["views_used"] = views_used
    if errors:
        return result

    # 6. Auto-LIMIT: inject or clamp to min(max_rows, cap).
    effective = max(1, min(int(max_rows), int(cap)))
    existing = _limit_value(root)
    if existing is None or existing > effective:
        root = root.limit(effective)
        result["limit_injected"] = True

    # 7. Re-render lowercase/unquoted via the postgres dialect.
    root = normalize_identifiers(root, dialect="postgres")
    result["sql_used"] = root.sql(dialect="postgres")
    result["ok"] = True
    return result
