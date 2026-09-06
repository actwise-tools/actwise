"""Curated product-key registry for the NICE Download Center.

The portal groups many components under a shared Flexera product-line id
(``plne``), so a friendly key maps to ``plne`` **plus** a title-match regex that
isolates one component. Modeled on docenter's product keys.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

_DATA_FILE = Path(__file__).resolve().parent / "data" / "product-keys.yaml"


@dataclass
class Product:
    key: str
    name: str
    plne: str
    search: str
    match: str
    description: str = ""
    aliases: list[str] = field(default_factory=list)
    catalog_terms: list[str] = field(default_factory=list)

    def title_matches(self, title: str) -> bool:
        if not self.match:
            return True
        return re.search(self.match, title, re.IGNORECASE) is not None


def load_products() -> list[Product]:
    if not _DATA_FILE.exists():
        return []
    data = yaml.safe_load(_DATA_FILE.read_text(encoding="utf-8")) or {}
    out: list[Product] = []
    for p in data.get("products", []):
        out.append(Product(
            key=str(p.get("key", "")),
            name=str(p.get("name", "")),
            plne=str(p.get("plne", "")),
            search=str(p.get("search", p.get("name", ""))),
            match=str(p.get("match", "")),
            description=str(p.get("description", "")).strip(),
            aliases=[str(a) for a in (p.get("aliases") or [])],
            catalog_terms=[str(t) for t in (p.get("catalog_terms") or [])],
        ))
    return out


def resolve(key: str) -> Optional[Product]:
    """Find a product by its key or any alias (case-insensitive)."""
    k = (key or "").strip().lower()
    for p in load_products():
        if p.key.lower() == k or k in [a.lower() for a in p.aliases]:
            return p
    return None


def product_dict(p: Product) -> dict:
    return {
        "key": p.key, "name": p.name, "plne": p.plne,
        "search": p.search, "match": p.match,
        "aliases": p.aliases, "description": p.description,
    }
