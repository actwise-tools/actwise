"""Business-solution catalog: taxonomy, object tagging, and client detection.

A NICE Actimize *business solution* is a license-driven subset of a single
product install (canonical example: IFM's Remote/Commercial/Card/Deposit/AIQ/NAF
lines). This module loads the ``business-solutions-<product>-<ver>.yaml`` catalog
and provides three capabilities over it:

  - :func:`list_business_solutions`  — enumerate the catalog (discovery).
  - :func:`tag_object` / :func:`tag_pack` — annotate schema-pack objects with the
    business solution(s) whose name markers they match.
  - :func:`detect` — given the object names present in a live deployment, report
    which business solutions / add-ons that client actually runs.

Markers are SQL-LIKE patterns ('%' = wildcard); matching is case-insensitive on
lowercased object names. The catalog is advisory metadata only — it never widens
the guardrail and never touches the database.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

DEFAULT_CATALOG_DIR = Path(__file__).resolve().parent / "data"

_MARKER_KEYS = ("view_markers", "feed_view_markers", "table_markers")


def _version_key(path: Path) -> tuple[int, ...]:
    return tuple(int(p) for p in re.findall(r"\d+", path.stem.rsplit("-", 1)[-1]))


def _find_catalog(product: str, version: str | None = None) -> Path | None:
    product = (product or "").strip().lower()
    if not product:
        return None
    if version:
        ver = version.lstrip("vV")
        path = DEFAULT_CATALOG_DIR / f"business-solutions-{product}-{ver}.yaml"
        return path if path.exists() else None
    packs = sorted(
        DEFAULT_CATALOG_DIR.glob(f"business-solutions-{product}-*.yaml"),
        key=_version_key,
    )
    return packs[-1] if packs else None


def load_catalog(product: str = "ifm", version: str | None = None) -> dict | None:
    """Return the raw business-solution catalog dict, or ``None`` if none bundled."""
    path = _find_catalog(product, version)
    if path is None:
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None
    return data if isinstance(data, dict) else None


def available_products() -> list[str]:
    """Sorted product keys that have a bundled business-solution catalog."""
    seen = set()
    for path in DEFAULT_CATALOG_DIR.glob("business-solutions-*.yaml"):
        stem = path.stem[len("business-solutions-"):]
        prod = stem.rsplit("-", 1)[0].lower()
        if prod:
            seen.add(prod)
    return sorted(seen)


def _marker_regex(pattern: str) -> re.Pattern:
    """Compile a SQL-LIKE marker ('%' wildcard) into an anchored, ci regex."""
    esc = re.escape((pattern or "").strip().lower()).replace("%", ".*")
    return re.compile(f"^{esc}$")


def _entries(catalog: dict) -> dict[str, dict]:
    """Flatten business_solutions + add_ons into one {key: entry} map."""
    out: dict[str, dict] = {}
    for section in ("business_solutions", "add_ons"):
        block = catalog.get(section) or {}
        if isinstance(block, dict):
            for key, entry in block.items():
                if isinstance(entry, dict):
                    out[key] = {**entry, "_section": section}
    return out


def _matchers(catalog: dict) -> dict[str, list[re.Pattern]]:
    """Precompile every entry's markers into name matchers."""
    result: dict[str, list[re.Pattern]] = {}
    for key, entry in _entries(catalog).items():
        pats: list[re.Pattern] = []
        for mk in _MARKER_KEYS:
            for pat in entry.get(mk) or []:
                if isinstance(pat, str) and pat.strip():
                    pats.append(_marker_regex(pat))
        result[key] = pats
    return result


def tag_object(name: str, catalog: dict, matchers: dict | None = None) -> list[str]:
    """Business-solution keys whose name markers match ``name`` (sorted)."""
    n = (name or "").strip().lower()
    if not n:
        return []
    matchers = matchers if matchers is not None else _matchers(catalog)
    hits = [key for key, pats in matchers.items() if any(p.match(n) for p in pats)]
    return sorted(hits)


def tag_pack(pack: dict, catalog: dict) -> dict:
    """Annotate a schema pack's objects in place with ``business_solutions``.

    Adds/refreshes a ``business_solutions`` list on each table/view whose name
    matches one or more catalog markers; clears it (removes the key) otherwise, so
    re-running is idempotent. Returns ``{tagged, by_solution}`` counts.
    """
    matchers = _matchers(catalog)
    tables = pack.get("tables") or {}
    tagged = 0
    by_solution: dict[str, int] = {}
    for name, obj in tables.items():
        if not isinstance(obj, dict):
            continue
        hits = tag_object(name, catalog, matchers)
        if hits:
            obj["business_solutions"] = hits
            tagged += 1
            for h in hits:
                by_solution[h] = by_solution.get(h, 0) + 1
        else:
            obj.pop("business_solutions", None)
    return {"tagged": tagged, "by_solution": dict(sorted(by_solution.items()))}


def detect(present_objects, catalog: dict) -> dict:
    """Report which business solutions / add-ons a deployment runs.

    ``present_objects`` is any iterable of live object names (tables + views) in
    the resolved schema(s). An entry is considered *present* when at least one of
    its markers matches a live object; *absent* otherwise. Entries with no name
    markers (differentiated only by config/license, e.g. Authentication-IQ when
    only feed views exist) are reported under ``config_only`` for follow-up.
    """
    names = {str(o).strip().lower() for o in present_objects if str(o).strip()}
    matchers = _matchers(catalog)
    entries = _entries(catalog)
    present, absent, config_only = [], [], []
    for key, entry in entries.items():
        pats = matchers.get(key) or []
        row = {
            "key": key,
            "official_name": entry.get("official_name"),
            "section": entry.get("_section"),
            "license_flag": entry.get("license_flag"),
            "separate_installer": bool(entry.get("separate_installer")),
        }
        if not pats:
            config_only.append(row)
            continue
        matched = sorted(n for n in names if any(p.match(n) for p in pats))
        if matched:
            present.append({**row, "matched_objects": matched[:25], "match_count": len(matched)})
        else:
            absent.append(row)
    return {
        "product": (catalog.get("metadata") or {}).get("product"),
        "version": (catalog.get("metadata") or {}).get("version"),
        "present": sorted(present, key=lambda r: r["key"]),
        "absent": sorted(absent, key=lambda r: r["key"]),
        "config_only": sorted(config_only, key=lambda r: r["key"]),
    }


def list_business_solutions(product: str = "ifm", version: str | None = None) -> dict:
    """Enumerate the business-solution catalog for a product (discovery entry point)."""
    catalog = load_catalog(product, version)
    if catalog is None:
        return {"product": product, "found": False,
                "available_products": available_products(), "business_solutions": []}
    meta = catalog.get("metadata") or {}

    def _row(key, entry):
        markers = []
        for mk in _MARKER_KEYS:
            markers.extend(entry.get(mk) or [])
        return {
            "key": key,
            "official_name": entry.get("official_name"),
            "aliases": entry.get("aliases") or [],
            "separate_installer": bool(entry.get("separate_installer")),
            "license_flag": entry.get("license_flag"),
            "detection_processes": entry.get("detection_processes") or [],
            "markers": markers,
            "variant_of": entry.get("variant_of"),
            "summary": (entry.get("summary") or "").strip(),
        }

    bs = catalog.get("business_solutions") or {}
    ao = catalog.get("add_ons") or {}
    return {
        "product": meta.get("product") or product,
        "version": meta.get("version"),
        "found": True,
        "term": meta.get("term"),
        "idb_access": meta.get("idb_access"),
        "detection": catalog.get("detection") or {},
        "business_solutions": [_row(k, v) for k, v in bs.items() if isinstance(v, dict)],
        "add_ons": [_row(k, v) for k, v in ao.items() if isinstance(v, dict)],
    }
