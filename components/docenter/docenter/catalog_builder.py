"""Build docs/catalog.yaml from the live Zoomin API.

Split out of cli.py so the catalog discovery/build logic lives in its own module.
Shared primitives (BASE_API, CATALOG_FILE, load_session, _type_from_labels) are
imported lazily from docenter.cli inside the functions to avoid a circular import
at module load.
"""

from __future__ import annotations

import datetime
import time

import typer
from rich import print as rprint

CATALOG_PER_PAGE = 50
CATALOG_REQUEST_DELAY = 0.4


def build_descendants_map(taxonomy: list) -> dict[str, set[str]]:
    """Walk /api/taxonomy and return label_key -> set of descendant keys (incl. self)."""
    result: dict[str, set[str]] = {}

    def collect(node: dict) -> set[str]:
        key = (node.get("subject") or {}).get("key")
        descendants: set[str] = set()
        if key:
            descendants.add(key)
        for child in node.get("children", []) or []:
            descendants |= collect(child)
        if key:
            result[key] = descendants
        return descendants

    for top in taxonomy:
        collect(top)
    return result


def expand_label_keys(seed_keys: list[str], descendants_map: dict[str, set[str]]) -> list[str]:
    expanded: set[str] = set()
    for k in seed_keys:
        expanded |= descendants_map.get(k, {k})
    return sorted(expanded)


def fetch_bundles(session, labelkey: str) -> list[dict]:
    from docenter.cli import BASE_API

    out: list[dict] = []
    page = 0
    while True:
        url = f"{BASE_API}/bundlelist?labelkey={labelkey}&per_page={CATALOG_PER_PAGE}&page={page}"
        try:
            r = session.get(url, timeout=30, headers={"Accept-Encoding": "identity"})
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            print(f"    ! page {page} failed for {labelkey}: {e}", flush=True)
            break
        batch = data.get("bundle_list", [])
        if not batch:
            break
        out.extend(batch)
        if len(batch) < CATALOG_PER_PAGE:
            break
        page += 1
        time.sleep(CATALOG_REQUEST_DELAY)
    return out


def normalize_bundle(b: dict) -> dict:
    from docenter.cli import _type_from_labels

    dates = b.get("dates") or {}
    return {
        "name": b.get("name"),
        "title": b.get("title"),
        "doc_type": _type_from_labels(b.get("labels", [])),
        "updated": dates.get("Updated on") or dates.get("Added on") or dates.get("Created on"),
    }


def build_catalog() -> None:
    """Discover the live category -> product -> bundle tree and write CATALOG_FILE."""
    from docenter.cli import BASE_API, CATALOG_FILE, load_session

    try:
        import yaml
    except ImportError:
        rprint("[red]Missing dependency:[/red] pip install pyyaml")
        raise typer.Exit(1)

    session = load_session()

    print(f"GET {BASE_API}/categories", flush=True)
    cats = session.get(f"{BASE_API}/categories", timeout=30).json()
    print(f"  -> {len(cats)} top-level entries", flush=True)

    print(f"GET {BASE_API}/taxonomy", flush=True)
    taxonomy = session.get(f"{BASE_API}/taxonomy", timeout=30, headers={"Accept-Encoding": "identity"}).json()
    descendants_map = build_descendants_map(taxonomy)
    print(f"  -> {len(descendants_map)} label keys in taxonomy", flush=True)

    out_categories: list[dict] = []
    total_products = 0
    total_bundles = 0

    for cat in cats:
        children = cat.get("children") or []
        cat_id = cat.get("id")
        cat_title = cat.get("title") or cat.get("linkText")
        if not children:
            print(f"\n[skip] {cat_title!r} (no products)", flush=True)
            continue

        print(f"\n## {cat_title}  ({len(children)} products)", flush=True)
        out_products = []
        for prod in children:
            prod_title = prod.get("title") or prod.get("linkText")
            seed_keys = prod.get("checkedFacets") or []
            label_keys = expand_label_keys(seed_keys, descendants_map)

            seen: set[str] = set()
            bundles: list[dict] = []
            for lk in label_keys:
                for b in fetch_bundles(session, lk):
                    name = b.get("name")
                    if not name or name in seen:
                        continue
                    seen.add(name)
                    bundles.append(normalize_bundle(b))
                time.sleep(CATALOG_REQUEST_DELAY)
            bundles.sort(key=lambda x: (x["name"] or "").lower())
            print(f"  - {prod_title}  [{len(bundles)} bundles]", flush=True)

            out_products.append({
                "id": prod.get("id"),
                "title": prod_title,
                "description": prod.get("description") or None,
                "label_keys": label_keys,
                "bundle_count": len(bundles),
                "bundles": bundles,
            })
            total_products += 1
            total_bundles += len(bundles)

        out_categories.append({
            "id": cat_id,
            "title": cat_title,
            "description": cat.get("description") or None,
            "product_count": len(out_products),
            "products": out_products,
        })

    catalog = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "source_api": BASE_API,
        "totals": {"categories": len(out_categories), "products": total_products, "bundles": total_bundles},
        "categories": out_categories,
    }

    CATALOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with CATALOG_FILE.open("w", encoding="utf-8") as f:
        yaml.safe_dump(catalog, f, sort_keys=False, allow_unicode=True, width=120)
    print(f"\nWrote {CATALOG_FILE}", flush=True)
    print(f"Totals: {len(out_categories)} categories, {total_products} products, {total_bundles} bundles", flush=True)
