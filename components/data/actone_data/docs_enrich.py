"""Parse ActOne ``v_acm_*.md`` doc pages into view/column descriptions + a
foreign-key graph, for merging into the schema pack (milestone 4).

FK targets come from two sources, reconciled against the live/allowlisted view
set so dangling doc targets are corrected, not trusted blindly:

1. **Parenthetical refs** — a ``(v_acm_...)`` at the end of a column description
   (e.g. ``owner_join_id | ... (v_acm_users2)``). Whitespace inside the target is
   normalized (the docs contain quirks like ``(v_acm_alert_ statuses2)``), then the
   name is reconciled singular/plural against the live views (doc-only
   ``v_acm_alert_type2`` -> real ``v_acm_alert_types2``).
2. **Naming-convention inference** for ``*_join_id`` columns that carry no
   parenthetical (the hero item views express joins purely by column name). A
   column is resolved by, in order: (a) the *learned* map — the same column name
   seen with a parenthetical ref on another page (so ``owner_join_id`` on
   ``v_acm_items`` inherits ``v_acm_users2``); then (b) stem naming — strip
   ``_join_id`` and reconcile ``v_acm_<stem>`` (so ``item_type_join_id`` ->
   ``v_acm_item_types``).
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from actwise.paths import repo_root

REPO_ROOT = repo_root() or Path(__file__).resolve().parent.parent
DEFAULT_BUNDLE = (
    REPO_ROOT / "raw_docs" / "bundles" / "Actimize_ActOne_10.2_Implementer_Guide"
)

# A (v_acm_...) reference inside a description cell. Spaces are allowed inside so
# the doc whitespace quirk `(v_acm_alert_ statuses2)` is still captured, then
# stripped by _norm().
_FK_RE = re.compile(r"\(\s*(v_acm_[a-z0-9_ ]+?)\s*\)", re.IGNORECASE)

# A custom-field range cell such as `p11…p50` or `p11,p12…p50`.
_RANGE_RE = re.compile(
    r"^p(\d+)(?:\s*,\s*p\d+)*\s*(?:\u2026|\.{2,})\s*p(\d+)$", re.IGNORECASE
)

_JOIN_SUFFIX = "_join_id"


@dataclass
class Column:
    name: str
    description: str = ""
    fk: str | None = None          # resolved, allowlisted target view (or None)
    fk_source: str | None = None   # parenthetical | learned | naming
    fk_raw: str | None = None      # the raw doc target, if it differs from `fk`
    synthetic: bool = False        # materialized from a p11..p50 range, not individually documented


@dataclass
class DocView:
    name: str
    description: str | None = None
    source_url: str | None = None
    version: str | None = None
    columns: list[Column] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _norm(target: str) -> str:
    """Normalize a doc FK target: drop internal whitespace, lowercase."""
    return re.sub(r"\s+", "", target).strip().lower()


def _split_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    block = text[3:end]
    body = text[end + 4:]
    try:
        meta = yaml.safe_load(block) or {}
    except yaml.YAMLError:
        meta = {}
    return (meta if isinstance(meta, dict) else {}), body


def _expand_range(name: str) -> list[str]:
    """`p11…p50` -> ['p11', ..., 'p50']; a plain name -> [name]."""
    m = _RANGE_RE.match(name)
    if not m:
        return [name]
    lo, hi = int(m.group(1)), int(m.group(2))
    if hi < lo or hi - lo > 200:  # guard against absurd ranges
        return [name]
    return [f"p{i}" for i in range(lo, hi + 1)]


def parse_page(path: Path) -> DocView:
    """Parse one ``v_acm_*.md`` page. FK targets are captured raw here; they are
    resolved against the live view set later by :func:`resolve_fks`."""
    text = path.read_text(encoding="utf-8")
    meta, body = _split_frontmatter(text)
    name = str(meta.get("page_title") or meta.get("title") or path.stem).strip().lower()
    view = DocView(
        name=name,
        source_url=meta.get("source_url"),
        version=str(meta.get("version")) if meta.get("version") is not None else None,
    )

    lines = body.splitlines()
    # View-level description: a `Description:` line before the field table.
    for ln in lines:
        s = ln.strip()
        if s.lower().startswith("description:"):
            view.description = s.split(":", 1)[1].strip() or None
            break
        if s.lower().startswith("field name"):
            break

    # Locate the `Field Name | Description` table header + `---|---` separator.
    start = None
    for i in range(len(lines) - 1):
        if lines[i].strip().lower().startswith("field name") and "|" in lines[i]:
            if set(lines[i + 1].strip()) <= set("-| "):
                start = i + 2
                break
    if start is None:
        view.warnings.append("no field table found")
        return view

    for ln in lines[start:]:
        s = ln.strip()
        if not s or s.startswith("!["):
            break
        if "|" not in s:
            break
        raw_name, _, desc = s.partition("|")
        col_name = raw_name.strip()
        desc = desc.strip()
        if not col_name:
            continue
        refs = _FK_RE.findall(desc)
        fk_raw = _norm(refs[-1]) if refs else None
        expanded = _expand_range(col_name)
        is_range = len(expanded) > 1
        for name_i in expanded:
            view.columns.append(
                Column(name=name_i.lower(), description=desc, fk_raw=fk_raw, synthetic=is_range)
            )
    return view


def _reconcile(target: str, known: set[str]) -> str | None:
    """Match a doc FK target to a live view name, tolerant of singular/plural."""
    t = _norm(target)
    if t in known:
        return t
    m = re.match(r"^(.*?)(\d*)$", t)
    stem, digits = m.group(1), m.group(2)
    variants = [
        stem + "s" + digits,                 # type   -> types
        stem + "es" + digits,                # status -> statuses (if not already)
        stem.rstrip("s") + digits,           # types  -> type (singularize)
    ]
    if stem.endswith("y"):
        variants.append(stem[:-1] + "ies" + digits)
    for v in variants:
        if v and v in known:
            return v
    return None


def _infer_naming(col_name: str, known: set[str]) -> str | None:
    """Stem inference for ``<x>_join_id`` -> nearest allowlisted ``v_acm_<x…>``."""
    if not col_name.endswith(_JOIN_SUFFIX):
        return None
    stem = col_name[: -len(_JOIN_SUFFIX)]
    if not stem:
        return None
    return _reconcile("v_acm_" + stem, known)


def resolve_fks(views: dict[str, DocView], known_views) -> dict[str, DocView]:
    """Two-pass FK resolution across all parsed views (see module docstring)."""
    known = {v.lower() for v in known_views}

    # Pass 1 — parenthetical refs: reconcile against live views, learn per-column.
    learned: dict[str, Counter] = {}
    for view in views.values():
        for col in view.columns:
            if not col.fk_raw:
                continue
            resolved = _reconcile(col.fk_raw, known)
            col.fk_source = "parenthetical"
            if resolved:
                col.fk = resolved
                if resolved != col.fk_raw:
                    view.warnings.append(
                        f"{col.name}: doc FK {col.fk_raw!r} reconciled to {resolved!r}"
                    )
                else:
                    col.fk_raw = None  # doc target matched exactly; nothing to flag
                learned.setdefault(col.name, Counter())[resolved] += 1
            else:
                view.warnings.append(
                    f"{col.name}: unresolved FK target {col.fk_raw!r} (not in live views)"
                )

    # Pass 2 — `*_join_id` columns with no parenthetical: learned map, then naming.
    for view in views.values():
        for col in view.columns:
            if col.fk or col.fk_raw:
                continue
            if not col.name.endswith(_JOIN_SUFFIX):
                continue
            if col.name in learned:
                col.fk = learned[col.name].most_common(1)[0][0]
                col.fk_source = "learned"
                continue
            target = _infer_naming(col.name, known)
            if target:
                col.fk = target
                col.fk_source = "naming"
    return views


def enrich(bundle_dir: Path | None = None, known_views=None) -> dict[str, DocView]:
    """Parse every ``v_acm_*.md`` page in the bundle and resolve its FK graph.

    ``known_views`` is the live/allowlisted view set used to reconcile FK targets;
    if omitted, the set of parsed page names is used as a self-consistent proxy.
    """
    bundle_dir = bundle_dir or DEFAULT_BUNDLE
    views: dict[str, DocView] = {}
    for path in sorted(bundle_dir.glob("v_acm_*.md")):
        view = parse_page(path)
        views[view.name] = view
    resolve_fks(views, known_views if known_views is not None else set(views))
    return views
