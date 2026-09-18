"""Offline catalog cache for the NICE Download Center.

The portal has no API and every listing is a live authenticated scrape. This
module builds a local metadata cache (product -> releases) via a search sweep
over the curated product keys, so `ndc find` can locate a package by
product+version instantly and offline. Caches **metadata only** (element / plne
/ version / variant / title) — never the time-limited signed download URLs.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import yaml

from . import portal as P
from . import keys as K

# Store next to the cookies (repo browser-profile if present, else ~/.nicedl).
CATALOG_FILE = P.COOKIES_FILE.parent / "ndc-catalog.yaml"


def version_key(v: str) -> tuple:
    try:
        return tuple(int(x) for x in v.split("."))
    except Exception:
        return (0,)


def _release_row(r: P.Release) -> dict:
    return {
        "title": r.title, "version": r.version, "variant": r.variant,
        "element": r.element, "plne": r.plne, "cert_num": r.cert_num,
    }


def build(portal: P.Portal, product_keys: Optional[list[str]] = None,
          log: Callable[[str], None] = lambda _m: None) -> dict:
    """Sweep the portal for each curated product and return a catalog dict."""
    products = K.load_products()
    if product_keys:
        wanted = {k.lower() for k in product_keys}
        products = [p for p in products if p.key.lower() in wanted]

    out_products: dict[str, dict] = {}
    total = 0
    for prod in products:
        terms = prod.catalog_terms or [prod.search]
        rels: dict[str, P.Release] = {}
        for term in terms:
            try:
                for r in portal.search(term):
                    if prod.plne and r.plne != prod.plne:
                        continue
                    if not prod.title_matches(r.title):
                        continue
                    rels[r.element] = r
            except P.AuthError:
                raise
            except Exception as e:  # pragma: no cover - best effort per term
                log(f"  [{prod.key}] term '{term}' error: {e}")
        rows = sorted(rels.values(), key=lambda r: version_key(r.version), reverse=True)
        out_products[prod.key] = {
            "name": prod.name,
            "plne": prod.plne,
            "releases": [_release_row(r) for r in rows],
        }
        total += len(rows)
        log(f"  {prod.key:<20} {len(rows):>3} releases")

    return {
        "refreshed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": P.BASE,
        "product_count": len(out_products),
        "release_count": total,
        "products": out_products,
    }


def save(data: dict) -> Path:
    CATALOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CATALOG_FILE.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
                            encoding="utf-8")
    return CATALOG_FILE


def load() -> Optional[dict]:
    if not CATALOG_FILE.exists():
        return None
    try:
        return yaml.safe_load(CATALOG_FILE.read_text(encoding="utf-8")) or None
    except Exception:
        return None


def find(catalog: dict, product_key: str = "", version: str = "",
         variant: str = "") -> list[dict]:
    """Return cached releases matching product / version / variant filters."""
    products = catalog.get("products", {})
    if product_key:
        entry = products.get(product_key)
        buckets = [entry] if entry else []
    else:
        buckets = list(products.values())
    rows: list[dict] = []
    for b in buckets:
        for r in b.get("releases", []):
            if version and version not in (r.get("version") or ""):
                continue
            if variant and (r.get("variant") or "").lower() != variant.lower():
                continue
            rows.append(r)
    return sorted(rows, key=lambda r: version_key(r.get("version", "")), reverse=True)
