"""Render docs/catalog.md from docs/catalog.yaml.

Split out of cli.py. CATALOG_FILE is imported lazily from docenter.cli to avoid a
circular import at module load.
"""

from __future__ import annotations

import typer
from rich import print as rprint


def render_catalog_md() -> None:
    """Render docs/catalog.md from CATALOG_FILE."""
    from docenter.cli import CATALOG_FILE

    try:
        import yaml
    except ImportError:
        rprint("[red]Missing dependency:[/red] pip install pyyaml")
        raise typer.Exit(1)

    output = CATALOG_FILE.parent / "catalog.md"
    with CATALOG_FILE.open(encoding="utf-8") as f:
        catalog = yaml.safe_load(f)

    totals = catalog.get("totals", {})
    gen_at = (catalog.get("generated_at") or "")[:10]
    unique_names: set[str] = set()
    for c in catalog["categories"]:
        for p in c["products"]:
            for b in p["bundles"]:
                if b.get("name"):
                    unique_names.add(b["name"])

    lines: list[str] = []
    lines.append("# NICE Actimize DOCenter — Full Catalog\n")
    lines.append("Auto-generated from `docs/catalog.yaml` (run `docenter catalog refresh` to rebuild).\n")
    lines.append(f"**Snapshot:** {gen_at}  ·  **Source:** `{catalog.get('source_api', '')}`\n")
    lines.append(
        f"**Totals:** {totals.get('categories', 0)} categories · "
        f"{totals.get('products', 0)} products · "
        f"{totals.get('bundles', 0)} bundle listings ({len(unique_names)} unique bundle names)\n"
    )
    lines.append(
        "> **Note on duplicates.** Zoomin cross-tags many bundles under more than one product. "
        "The tree below reflects the portal's taxonomy faithfully, so the same bundle can appear in several places.\n"
    )
    lines.append("---\n")
    lines.append("## Category Summary\n")
    lines.append("| # | Category | Slug | Products | Bundles |")
    lines.append("|---|---|---|---:|---:|")
    for i, cat in enumerate(catalog["categories"], start=1):
        cat_bundles = sum(p["bundle_count"] for p in cat["products"])
        lines.append(f"| {i} | {cat['title']} | `{cat['id']}` | {cat['product_count']} | {cat_bundles} |")
    lines.append("\n---\n")
    lines.append("## Full Tree\n")
    for cat in catalog["categories"]:
        cat_bundles = sum(p["bundle_count"] for p in cat["products"])
        lines.append("<details>")
        lines.append(
            f"<summary><strong>{cat['title']}</strong> (<code>{cat['id']}</code>) — "
            f"{cat['product_count']} products, {cat_bundles} bundles</summary>\n"
        )
        if cat.get("description"):
            lines.append(f"*{cat['description']}*\n")
        for prod in cat["products"]:
            count = prod["bundle_count"]
            lines.append(f"### {prod['title']}  ·  {count} bundle{'s' if count != 1 else ''}\n")
            if prod.get("description"):
                lines.append(f"> {prod['description']}\n")
            if prod.get("label_keys"):
                lines.append("**Label keys:** " + ", ".join(f"`{k}`" for k in prod["label_keys"]) + "\n")
            if count == 0:
                lines.append("_No bundles published._\n")
                continue
            lines.append("| Bundle | Type | Updated |")
            lines.append("|---|---|---|")
            for b in prod["bundles"]:
                updated = (b.get("updated") or "")[:10] if b.get("updated") else "—"
                lines.append(f"| `{b.get('name', '')}` | {b.get('doc_type') or ''} | {updated} |")
            lines.append("")
        lines.append("</details>\n")

    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {output} ({output.stat().st_size / 1024:.1f} KB)")
