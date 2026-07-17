"""Build and load the ActWise Data schema pack.

The pack merges the two sources into one JSON artifact:

* **Live introspection is truth** for the allowlist and column types (every
  ``v_acm_*`` view and its ``information_schema`` columns).
* **Doc enrichment** (``docs_enrich``) contributes view/column descriptions and
  the reconciled FK graph.

Per-view classification (``family`` / ``preferred`` / ``related_views``) encodes
the item-preference model: the permission-aware entry views (``v_acm_items``,
``v_acm_cases``, ``v_acm_blotters``) and the unified ``v_acm_item*`` family are
``preferred``; legacy ``v_acm_alert*`` views are not, and are cross-linked to
their item equivalents.

Provenance:

* view-level ``both`` (live + documented) / ``introspected`` (live, no doc page) /
  ``doc_only`` (documented but absent live — kept visible but **excluded from the
  allowlist**);
* column-level ``both`` / ``introspected`` (live but not individually documented,
  e.g. the ``p11..p50`` custom-field slots) / ``doc_only``.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from actone_data import config as _config
from actone_data import db, docs_enrich

PACK_FORMAT = "actone-data/1"
# Packs are bundled package data (components/data/actone_data/data/), so resolve
# them relative to this package — not the git root, which no longer contains
# actone_data/data after the components/ bucketization.
DEFAULT_PACK_DIR = Path(__file__).resolve().parent / "data"


def _default_pack_path(version: str) -> Path:
    major_minor = ".".join(version.lstrip("vV").split(".")[:2])
    return DEFAULT_PACK_DIR / f"schema-pack-actone-{major_minor}.json"


NOTES = [
    "Prefer the unified item views: alerts/work items -> v_acm_items, cases -> "
    "v_acm_cases, blotters/transactions -> v_acm_blotters.",
    "v_acm_alert* views are legacy (alerts only); permissions over them are "
    "unsupported (standard A1). Still queryable, but prefer the item equivalent.",
    "Among legacy alert views, prefer the 2-suffixed ones (e.g. v_acm_alerts2).",
    "*_join_id columns are instance-internal surrogate keys: use them for JOINs "
    "only, never as literals in WHERE.",
    "Identifiers are all-lowercase in PostgreSQL; queries are read-only with row limits.",
]


def classify(name: str) -> tuple[str, bool]:
    """Return ``(family, preferred)`` for a view name."""
    n = name.lower()
    if n.startswith("v_acm_item"):
        return "item", True
    if n.startswith("v_acm_case"):
        return "case", n == "v_acm_cases"
    if n.startswith("v_acm_blotter"):
        return "blotter", n == "v_acm_blotters"
    if n.startswith("v_acm_alert"):
        return "alert", False
    return "other", False


def related_views(name: str, live: set[str]) -> list[str]:
    """Cross-link a legacy ``v_acm_alert*`` view to its preferred item equivalent(s),
    keeping only targets that exist in the live view set."""
    n = name.lower()
    if not n.startswith("v_acm_alert"):
        return []
    if n in ("v_acm_alerts", "v_acm_alerts2"):
        cands = ["v_acm_items", "v_acm_items_alerts"]
    else:
        base = re.sub(r"^v_acm_alert_?", "", n)  # types2, statuses2, custom_fields
        base = re.sub(r"2$", "", base)
        cands = ["v_acm_item_" + base]
    seen: list[str] = []
    for c in cands:
        if c in live and c not in seen:
            seen.append(c)
    return seen


def _merge_columns(live_cols: list[tuple[str, str]], doc_view) -> list[dict]:
    doc_by_name = {c.name: c for c in doc_view.columns} if doc_view else {}
    live_names = {c.lower() for c, _ in live_cols}
    out: list[dict] = []
    for col_name, col_type in live_cols:
        cn = col_name.lower()
        dc = doc_by_name.get(cn)
        if dc and not dc.synthetic:
            prov, desc, fk = "both", dc.description, dc.fk
        elif dc and dc.synthetic:
            # p11..p50 range: live-confirmed but not individually documented.
            prov, desc, fk = "introspected", dc.description, dc.fk
        else:
            prov, desc, fk = "introspected", "", None
        out.append({"name": cn, "type": col_type, "description": desc, "fk": fk, "provenance": prov})
    # Documented columns absent from the live view.
    for dc in (doc_view.columns if doc_view else []):
        if dc.name not in live_names and not dc.synthetic:
            out.append({"name": dc.name, "type": None, "description": dc.description,
                        "fk": dc.fk, "provenance": "doc_only"})
    return out


def build(cfg, bundle_dir: Path | None = None, doc_version: str | None = None) -> dict:
    """Introspect the live schema, parse + resolve the doc pages, and merge them
    into a schema-pack dict (deterministic apart from ``built_at``)."""
    bundle_dir = bundle_dir or docs_enrich.DEFAULT_BUNDLE

    live_cols = db.introspect_columns(cfg)          # {view: [(col, type)]}
    live_views = set(live_cols)

    ver_info = db.detect_version(cfg)
    db_version = ver_info["version"] or (doc_version or _config.DEFAULT_DOC_VERSION)

    docs = docs_enrich.enrich(bundle_dir, known_views=live_views)

    doc_bundle_version = (doc_version or _config.DEFAULT_DOC_VERSION)
    views: dict[str, dict] = {}

    # Live views: allowlisted, enriched with doc descriptions/FKs where available.
    for name in sorted(live_views):
        family, preferred = classify(name)
        dv = docs.get(name)
        views[name] = {
            "description": (dv.description if dv else None),
            "family": family,
            "preferred": preferred,
            "deprecated": False,
            "provenance": "both" if dv else "introspected",
            "related_views": related_views(name, live_views),
            "source_url": (dv.source_url if dv else None),
            "columns": _merge_columns(live_cols[name], dv),
        }

    # Doc-only views: documented but not live -> visible, excluded from allowlist.
    for name, dv in sorted(docs.items()):
        if name in live_views:
            continue
        family, preferred = classify(name)
        views[name] = {
            "description": dv.description,
            "family": family,
            "preferred": preferred,
            "deprecated": False,
            "provenance": "doc_only",
            "related_views": related_views(name, live_views),
            "source_url": dv.source_url,
            "columns": [
                {"name": c.name, "type": None, "description": c.description,
                 "fk": c.fk, "provenance": "doc_only"}
                for c in dv.columns if not c.synthetic
            ],
        }

    return {
        "pack_format": PACK_FORMAT,
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dialect": "postgres",
        "schema": cfg.schema,
        "source": {
            "db": ver_info["detail"],
            "db_product_version": db_version,
            "db_version_source": ver_info["source"],
            "doc_bundle": bundle_dir.name,
            "doc_versions_equivalent": doc_bundle_version,
        },
        "notes": list(NOTES),
        "views": views,
    }


def save(pack: dict, path: Path | None = None) -> Path:
    version = pack["source"]["db_product_version"]
    path = path or _default_pack_path(version)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(pack, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def canonical(pack: dict) -> str:
    """Deterministic serialization for rebuild comparison (excludes built_at)."""
    clone = {k: v for k, v in pack.items() if k != "built_at"}
    return json.dumps(clone, indent=2, sort_keys=True, ensure_ascii=False)


def _bundled_pack_path() -> Path | None:
    packs = sorted(DEFAULT_PACK_DIR.glob("schema-pack-actone-*.json"))
    return packs[-1] if packs else None


def load(path: Path | None = None) -> dict:
    """Resolve and load a pack: explicit path -> ``ACTONE_DATA_PACK`` -> bundled."""
    import os

    if path is None:
        env = os.getenv("ACTONE_DATA_PACK")
        path = Path(env) if env else _bundled_pack_path()
    if path is None or not Path(path).exists():
        raise FileNotFoundError(
            "no schema pack found; run `actone-data schema build` first"
        )
    return json.loads(Path(path).read_text(encoding="utf-8"))
