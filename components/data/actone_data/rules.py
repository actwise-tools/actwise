"""Rule-pack loading for ActWise Data advisory rules and guardrail constraints."""
from __future__ import annotations

import copy
import logging
import os
import re
from pathlib import Path
from typing import Any

import yaml

from actone_data import guardrails

DEFAULT_RULES_DIR = Path(__file__).resolve().parent / "data"

_LOG = logging.getLogger(__name__)
_PREFIX_RE = re.compile(r"^(?:\*|[a-z0-9_]+)$")
_DIALECTS = {"postgres", "oracle", "mssql", "sybase"}
_TOP_LEVEL = {"metadata", "guidance", "preferences", "glossary", "examples", "constraints"}


def _safe_pack() -> dict:
    return {
        "metadata": {"solution": "actone", "version": "builtin", "is_base": True},
        "guidance": {"global": [], "by_family": {}, "by_object": {}},
        "preferences": {
            "preferred_families": [],
            "deprecated_families": [],
            "cross_links": {},
            "rationale": [],
        },
        "glossary": {},
        "examples": [],
        "constraints": {
            "read_only": True,
            "allowlist_prefixes": list(guardrails.Constraints().allowlist_prefixes),
            "deny_objects": [],
            "masked_columns": [],
            "default_max_rows": guardrails.DEFAULT_MAX_ROWS,
            "row_cap": guardrails.ROW_CAP,
        },
    }


def _read(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _version_key(path: Path) -> tuple[int, ...]:
    return tuple(int(p) for p in re.findall(r"\d+", path.stem.rsplit("-", 1)[-1]))


def _find_pack(solution: str, version: str | None = None) -> Path | None:
    solution = (solution or "actone").lower()
    if version:
        ver = version.lstrip("vV")
        path = DEFAULT_RULES_DIR / f"rules-{solution}-{ver}.yaml"
        return path if path.exists() else None
    packs = sorted(DEFAULT_RULES_DIR.glob(f"rules-{solution}-*.yaml"), key=_version_key)
    return packs[-1] if packs else None


def load(
    solution: str | None = None,
    version: str | None = None,
    path: Path | None = None,
) -> dict:
    """Load base ActOne rules and optionally layer a solution pack over them.

    Resolution is explicit ``path`` -> ``ACTONE_DATA_RULES`` -> bundled newest (or
    version-matched) ``rules-<solution>-<ver>.yaml``. If no files exist, returns
    safe built-in defaults so validation keeps running with the legacy guardrail.
    """
    explicit = path or (Path(os.environ["ACTONE_DATA_RULES"]) if os.getenv("ACTONE_DATA_RULES") else None)
    if explicit:
        explicit = Path(explicit)
        if not explicit.exists():
            _LOG.warning("rule pack not found: %s; using safe defaults", explicit)
            return _safe_pack()
        pack = _read(explicit)
        meta = pack.get("metadata", {}) if isinstance(pack.get("metadata"), dict) else {}
        if meta.get("solution") and meta.get("solution") != "actone" and not meta.get("is_base"):
            base_path = _find_pack("actone", version) or _find_pack("actone")
            base = _read(base_path) if base_path else _safe_pack()
            return merge(base, pack)
        return pack

    base_path = _find_pack("actone", version) or _find_pack("actone")
    requested = (solution or "actone").strip().lower() or "actone"
    if base_path is None:
        any_pack = next(iter(DEFAULT_RULES_DIR.glob("rules-*.yaml")), None)
        if any_pack is None:
            return _safe_pack()
        base = _safe_pack()
    else:
        base = _read(base_path)
    if requested == "actone":
        return base
    solution_path = _find_pack(requested, version)
    if solution_path is None:
        return base
    return merge(base, _read(solution_path))


def _is_str_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(v, str) for v in value)


def _check_keys(errors: list[str], path: str, data: dict, allowed: set[str]) -> None:
    for key in data:
        if key not in allowed:
            errors.append(f"{path}.{key}: unknown key")


def validate_pack(pack: dict) -> list[str]:
    """Lightweight structural validation mirroring ``rules.schema.json``."""
    errors: list[str] = []
    if not isinstance(pack, dict):
        return ["pack must be an object"]

    _check_keys(errors, "pack", pack, _TOP_LEVEL)
    for key in ("metadata", "constraints"):
        if key not in pack:
            errors.append(f"{key}: required")

    meta = pack.get("metadata")
    if isinstance(meta, dict):
        _check_keys(
            errors, "metadata", meta,
            {"solution", "is_base", "version", "applies_to_schemas", "dialect"},
        )
        if not isinstance(meta.get("solution"), str) or not re.match(r"^[a-z0-9_-]+$", meta.get("solution", "")):
            errors.append("metadata.solution: expected lowercase solution id")
        if not isinstance(meta.get("version"), str):
            errors.append("metadata.version: expected string")
        if "is_base" in meta and not isinstance(meta["is_base"], bool):
            errors.append("metadata.is_base: expected boolean")
        if "applies_to_schemas" in meta and not _is_str_list(meta["applies_to_schemas"]):
            errors.append("metadata.applies_to_schemas: expected list of strings")
        if "dialect" in meta and meta["dialect"] not in _DIALECTS:
            errors.append("metadata.dialect: unsupported dialect")
    elif meta is not None:
        errors.append("metadata: expected object")

    guidance = pack.get("guidance")
    if guidance is not None:
        if not isinstance(guidance, dict):
            errors.append("guidance: expected object")
        else:
            _check_keys(errors, "guidance", guidance, {"global", "by_family", "by_object"})
            if "global" in guidance and not _is_str_list(guidance["global"]):
                errors.append("guidance.global: expected list of strings")
            for section in ("by_family", "by_object"):
                value = guidance.get(section)
                if value is not None:
                    if not isinstance(value, dict):
                        errors.append(f"guidance.{section}: expected object")
                    elif not all(_is_str_list(v) for v in value.values()):
                        errors.append(f"guidance.{section}: expected string-list values")

    prefs = pack.get("preferences")
    if prefs is not None:
        if not isinstance(prefs, dict):
            errors.append("preferences: expected object")
        else:
            _check_keys(
                errors, "preferences", prefs,
                {"preferred_families", "deprecated_families", "cross_links", "rationale"},
            )
            for key in ("preferred_families", "deprecated_families", "rationale"):
                if key in prefs and not _is_str_list(prefs[key]):
                    errors.append(f"preferences.{key}: expected list of strings")
            links = prefs.get("cross_links")
            if links is not None and (
                not isinstance(links, dict) or not all(isinstance(v, str) for v in links.values())
            ):
                errors.append("preferences.cross_links: expected string-valued object")

    glossary = pack.get("glossary")
    if glossary is not None:
        if not isinstance(glossary, dict):
            errors.append("glossary: expected object")
        else:
            for term, value in glossary.items():
                if not isinstance(value, dict):
                    errors.append(f"glossary.{term}: expected object")
                    continue
                _check_keys(errors, f"glossary.{term}", value, {"object", "column", "via", "note"})
                if not all(isinstance(v, str) for v in value.values()):
                    errors.append(f"glossary.{term}: expected string values")

    examples = pack.get("examples")
    if examples is not None:
        if not isinstance(examples, list):
            errors.append("examples: expected list")
        else:
            for i, ex in enumerate(examples):
                if not isinstance(ex, dict):
                    errors.append(f"examples[{i}]: expected object")
                    continue
                _check_keys(errors, f"examples[{i}]", ex, {"q", "sql", "note"})
                if not isinstance(ex.get("q"), str) or not isinstance(ex.get("sql"), str):
                    errors.append(f"examples[{i}]: q and sql strings are required")
                if "note" in ex and not isinstance(ex["note"], str):
                    errors.append(f"examples[{i}].note: expected string")

    constraints = pack.get("constraints")
    if isinstance(constraints, dict):
        _check_keys(
            errors, "constraints", constraints,
            {
                "read_only", "schema", "allowlist_prefixes", "deny_objects",
                "join_only_columns", "masked_columns", "default_max_rows", "row_cap",
            },
        )
        if constraints.get("read_only", True) is not True:
            errors.append("constraints.read_only: must be true")
        if "schema" in constraints and not isinstance(constraints["schema"], str):
            errors.append("constraints.schema: expected string")
        prefixes = constraints.get("allowlist_prefixes")
        if not _is_str_list(prefixes) or not prefixes:
            errors.append("constraints.allowlist_prefixes: expected non-empty list of strings")
        elif not all(_PREFIX_RE.match(p) for p in prefixes):
            errors.append("constraints.allowlist_prefixes: invalid prefix")
        for key in ("deny_objects", "join_only_columns", "masked_columns"):
            if key in constraints and not _is_str_list(constraints[key]):
                errors.append(f"constraints.{key}: expected list of strings")
        for key in ("default_max_rows", "row_cap"):
            if key in constraints and (
                not isinstance(constraints[key], int) or constraints[key] < 1
            ):
                errors.append(f"constraints.{key}: expected positive integer")
    elif constraints is not None:
        errors.append("constraints: expected object")

    return errors


def _merge_list(base: list, extra: list) -> list:
    out = list(base)
    for item in extra:
        if item not in out:
            out.append(item)
    return out


def _merge_dict(base: dict, extra: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in extra.items():
        if key in out and isinstance(out[key], dict) and isinstance(value, dict):
            out[key] = _merge_dict(out[key], value)
        elif key in out and isinstance(out[key], list) and isinstance(value, list):
            out[key] = _merge_list(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def merge(base: dict, solution: dict) -> dict:
    """Merge ``solution`` over ``base`` while constraints stay tightening-only.

    Advisory sections are deep-unioned (lists concatenate without duplicates,
    dictionaries merge recursively). Constraint prefixes are a union because a
    solution may add its own schema prefixes; caps use ``min``; deny/mask lists
    are unions; ``read_only`` is pinned true and cannot be relaxed.
    Malformed inputs fail closed by ignoring the solution (or using safe defaults
    if the base is malformed).
    """
    if validate_pack(base):
        _LOG.warning("base rule pack is invalid; using safe defaults")
        base = _safe_pack()
    solution_errors = validate_pack(solution)
    if solution_errors:
        _LOG.warning("solution rule pack is invalid; ignoring it: %s", "; ".join(solution_errors))
        return copy.deepcopy(base)

    out = copy.deepcopy(base)
    for key in ("metadata", "guidance", "preferences", "glossary"):
        out[key] = _merge_dict(out.get(key, {}), solution.get(key, {}))
    out["examples"] = _merge_list(out.get("examples", []), solution.get("examples", []))

    bc = out.setdefault("constraints", {})
    sc = solution.get("constraints", {})
    bc["read_only"] = True
    bc["allowlist_prefixes"] = _merge_list(
        bc.get("allowlist_prefixes", []), sc.get("allowlist_prefixes", [])
    )
    for key in ("deny_objects", "masked_columns", "join_only_columns"):
        bc[key] = _merge_list(bc.get(key, []), sc.get(key, []))
    for key, default in (
        ("default_max_rows", guardrails.DEFAULT_MAX_ROWS),
        ("row_cap", guardrails.ROW_CAP),
    ):
        bc[key] = min(int(bc.get(key, default)), int(sc.get(key, default)))
    if sc.get("schema") is not None:
        bc["schema"] = sc["schema"]
    return out


def to_constraints(pack: dict) -> guardrails.Constraints:
    """Convert a valid rule pack to guardrail constraints; invalid packs fail closed."""
    errors = validate_pack(pack)
    if errors:
        _LOG.warning("rule pack is invalid; using safe constraints: %s", "; ".join(errors))
        return guardrails.Constraints()
    c = pack.get("constraints", {})
    return guardrails.Constraints(
        allowlist_prefixes=tuple(p.lower() for p in c.get("allowlist_prefixes", ["v_acm_"])),
        deny_objects=frozenset(d.lower() for d in c.get("deny_objects", [])),
        row_cap=int(c.get("row_cap", guardrails.ROW_CAP)),
        masked_columns=frozenset(m.lower() for m in c.get("masked_columns", [])),
    )


def check_examples(solution: str | None = None, version: str | None = None) -> list[dict]:
    """Structurally validate a rule pack's example SQL through the guardrail (offline).

    For each ``examples[].sql`` in the (merged) pack, run the guardrail with the
    pack's own constraints and an allowlist built from the base ActOne views plus
    the solution pack's declared tables. Catches example SQL that references a
    non-allowlisted object or isn't a single read-only SELECT — without a DB.
    Returns a list of ``{q, ok, errors}``.
    """
    from actone_data import schema_pack, schema_packs

    pack = load(solution, version)
    constraints = to_constraints(pack)
    schema = "actone"
    allowed: set[str] = set()
    try:
        base = schema_pack.load()
        allowed |= {str(v).lower() for v in (base.get("views") or {})}
    except Exception:  # pragma: no cover - base pack always present in repo
        pass
    requested = (solution or "actone").strip().lower() or "actone"
    if requested != "actone":
        surface = schema_packs.surface(requested, version)
        if surface:
            allowed |= {t.lower() for t in surface["tables"]}
            schema = surface["schema"]
    results = []
    for ex in pack.get("examples", []):
        res = guardrails.validate(ex.get("sql") or "", allowed, schema, constraints=constraints)
        results.append({"q": ex.get("q"), "ok": res["ok"], "errors": res["errors"]})
    return results


def advisory(pack: dict) -> dict:
    """Return LLM-facing advisory sections; invalid packs fail closed to empty advice."""
    errors = validate_pack(pack)
    if errors:
        _LOG.warning("rule pack is invalid; using safe advisory: %s", "; ".join(errors))
        pack = _safe_pack()

    guidance = copy.deepcopy(pack.get("guidance", {}))
    preferences = copy.deepcopy(pack.get("preferences", {}))
    glossary = copy.deepcopy(pack.get("glossary", {}))
    examples = copy.deepcopy(pack.get("examples", []))

    lines = list(guidance.get("global", []))
    for section in ("by_family", "by_object"):
        for values in guidance.get(section, {}).values():
            lines.extend(values)
    lines.extend(preferences.get("rationale", []))

    return {
        "guidance": guidance,
        "preferences": preferences,
        "glossary": glossary,
        "examples": examples,
        "rules": lines,
    }
