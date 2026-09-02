"""Loader for per-solution schema packs (``schema-pack-<solution>-<ver>.json``).

The ActOne base surface is served by ``schema_pack.py`` (live ``v_acm_*`` views).
This module loads the *solution* packs produced by the download→DDL pilots (STAR,
SAM, CDD, …): package-derived table inventories in their own solution schema.

It exposes just what the query engine needs to ground + guardrail a solution
query: the canonical schema name and the set of table names the pack declares.
It never touches the DB — schema **resolution** (canonical → deployment-prefixed)
lives in ``config`` and the live intersection lives in ``db``.
"""
from __future__ import annotations

import difflib
import json
import re
from pathlib import Path

DEFAULT_PACK_DIR = Path(__file__).resolve().parent / "data"


def _version_key(path: Path) -> tuple[int, ...]:
    return tuple(int(p) for p in re.findall(r"\d+", path.stem.rsplit("-", 1)[-1]))


def _find_pack(solution: str, version: str | None = None) -> Path | None:
    solution = (solution or "").strip().lower()
    if not solution or solution == "actone":
        return None
    if version:
        ver = version.lstrip("vV")
        path = DEFAULT_PACK_DIR / f"schema-pack-{solution}-{ver}.json"
        return path if path.exists() else None
    packs = sorted(DEFAULT_PACK_DIR.glob(f"schema-pack-{solution}-*.json"), key=_version_key)
    return packs[-1] if packs else None


def load(solution: str, version: str | None = None) -> dict | None:
    """Return the raw solution schema pack dict, or ``None`` if none is bundled.

    ``actone`` (and unknown solutions) return ``None`` — the caller falls back to
    the live ``v_acm_*`` view surface.
    """
    path = _find_pack(solution, version)
    if path is None:
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def pack_schema(pack: dict) -> str:
    """Canonical (unprefixed) schema name the pack's tables live in."""
    return str(pack.get("schema") or "").strip().lower()


def pack_tables(pack: dict) -> frozenset[str]:
    """Lowercased set of table names declared by the pack."""
    tables = pack.get("tables") or {}
    return frozenset(name.strip().lower() for name in tables)


def _pack_version(pack: dict) -> str:
    src = pack.get("source", {}) if isinstance(pack.get("source"), dict) else {}
    return str(src.get("db_product_version")
               or src.get("version")
               or pack.get("version") or "").strip()


def _columns(table: dict) -> list[dict]:
    cols = table.get("columns") or []
    if isinstance(cols, dict):  # description-overlay shape {name: desc}
        return [{"name": n, "type": "", "description": d, "fk": None} for n, d in cols.items()]
    out = []
    for c in cols:
        if not isinstance(c, dict):
            continue
        out.append({
            "name": c.get("name"),
            "type": c.get("type") or "",
            "description": c.get("description") or "",
            "fk": c.get("fk"),
            "nullable": c.get("nullable"),
        })
    return out


def table_summary(pack: dict) -> dict:
    """Grounding overview of a solution pack (schema, version, table/kind counts)."""
    tables = pack.get("tables") or {}
    kinds: dict[str, int] = {}
    described = 0
    for t in tables.values():
        if not isinstance(t, dict):
            continue
        kinds[t.get("kind") or "table"] = kinds.get(t.get("kind") or "table", 0) + 1
        if (t.get("description") or "").strip():
            described += 1
    return {
        "surface": "solution",
        "schema": pack_schema(pack),
        "version": _pack_version(pack),
        "table_count": len(tables),
        "described_count": described,
        "kinds": dict(sorted(kinds.items())),
        "auxiliary_schemas": pack.get("auxiliary_schemas") or [],
        "draft": bool(pack.get("draft")),
        "draft_reason": pack.get("draft_reason"),
        "notes": pack.get("notes"),
    }


def list_pack_tables(pack: dict, topic: str = "") -> dict:
    """List a solution pack's tables, optionally keyword-filtered (name/description)."""
    tables = pack.get("tables") or {}
    t = (topic or "").strip().lower()
    out = []
    for name, tbl in tables.items():
        if not isinstance(tbl, dict):
            continue
        desc = (tbl.get("description") or "")
        if t and t not in name.lower() and t not in desc.lower():
            continue
        out.append({
            "name": name,
            "description": desc,
            "column_count": len(_columns(tbl)),
            "kind": tbl.get("kind") or "table",
            "schema": tbl.get("schema") or pack_schema(pack),
        })
    out.sort(key=lambda r: r["name"])
    return {"surface": "solution", "schema": pack_schema(pack),
            "count": len(out), "views": out}


def describe_pack_table(pack: dict, table: str) -> dict:
    """Describe one solution-pack table (columns/PK/FKs), or suggest close names."""
    tables = pack.get("tables") or {}
    key = (table or "").strip().lower()
    # tables are keyed lowercased in the packs, but match case-insensitively anyway.
    tbl = tables.get(key) or next(
        (v for k, v in tables.items() if k.lower() == key and isinstance(v, dict)), None)
    if not isinstance(tbl, dict):
        return {"error": "unknown_table", "table": key,
                "suggestions": difflib.get_close_matches(key, list(tables), n=5, cutoff=0.4)}
    return {
        "surface": "solution",
        "name": key,
        "schema": tbl.get("schema") or pack_schema(pack),
        "kind": tbl.get("kind") or "table",
        "description": tbl.get("description") or "",
        "primary_key": tbl.get("primary_key") or [],
        "foreign_keys": tbl.get("foreign_keys") or [],
        "columns": _columns(tbl),
    }


def surface(solution: str, version: str | None = None) -> dict | None:
    """Convenience: ``{schema, tables, version}`` for a solution, or ``None``."""
    pack = load(solution, version)
    if pack is None:
        return None
    return {
        "schema": pack_schema(pack),
        "tables": pack_tables(pack),
        "version": _pack_version(pack),
    }


def available_solutions() -> list[str]:
    """Sorted list of solution names that have a bundled schema pack."""
    seen = set()
    for path in DEFAULT_PACK_DIR.glob("schema-pack-*.json"):
        # schema-pack-<solution>-<ver>.json ; solution may contain no dashes today.
        stem = path.stem[len("schema-pack-"):]
        sol = stem.rsplit("-", 1)[0].lower()
        if sol and sol != "actone":
            seen.add(sol)
    return sorted(seen)
