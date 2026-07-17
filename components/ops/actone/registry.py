#!/usr/bin/env python
"""
registry.py — build a searchable operation registry from an ActOne OpenAPI spec.

The registry is the discovery surface: instead of registering 149 static tools, the
CLI and MCP server expose three meta-operations (search / describe / invoke) over this
index. Spec-driven, so it tracks whatever surface the target ActOne actually exposes.

Spec source (resolve_spec):
  1. explicit path (--spec / ACTONE_SPEC)
  2. cached live spec under <workdir>/postman/specs/*.oas3.json|yaml (most specific first)
  3. bundled current spec shipped in the wheel (actone/data/*.bundled.yaml)

Stdlib + pyyaml only. Importable; no top-level work.
"""
import json
import re
from pathlib import Path

import yaml

from actone.paths import BUNDLED, workdir

_READ_METHODS = {"GET", "HEAD"}


# --------------------------------------------------------------------------- #
# spec acquisition
# --------------------------------------------------------------------------- #
def resolve_spec(explicit=None):
    """Return (path, spec_dict). Raises FileNotFoundError if nothing is found."""
    candidates = []
    if explicit:
        candidates.append(Path(explicit))
    specs_dir = workdir() / "postman" / "specs"
    if specs_dir.is_dir():
        # prefer oas3 over swagger, json over yaml; newest mtime first
        found = sorted(
            list(specs_dir.glob("*.oas3.json")) + list(specs_dir.glob("*.oas3.yaml"))
            + list(specs_dir.glob("*.json")) + list(specs_dir.glob("*.yaml")),
            key=lambda p: p.stat().st_mtime, reverse=True,
        )
        candidates.extend(found)
    candidates.append(BUNDLED)

    for p in candidates:
        if p and p.exists():
            return p, _load(p)
    raise FileNotFoundError("no spec found (looked in --spec, postman/specs, bundled)")


def _load(path):
    text = Path(path).read_text(encoding="utf-8")
    if str(path).lower().endswith((".yaml", ".yml")):
        return yaml.safe_load(text)
    return json.loads(text)


# --------------------------------------------------------------------------- #
# schema example sampler (for request-body / param hints)
# --------------------------------------------------------------------------- #
def _example(schema, defs, depth=0):
    if not isinstance(schema, dict) or depth > 6:
        return None
    if "$ref" in schema:
        name = schema["$ref"].split("/")[-1]
        return _example(defs.get(name, {}), defs, depth + 1)
    if "example" in schema:
        return schema["example"]
    if "enum" in schema and schema["enum"]:
        return schema["enum"][0]
    t = schema.get("type")
    if t == "object" or "properties" in schema:
        return {k: _example(v, defs, depth + 1)
                for k, v in (schema.get("properties") or {}).items()}
    if t == "array":
        return [_example(schema.get("items", {}), defs, depth + 1)]
    return {"string": "string", "integer": 0, "number": 0,
            "boolean": False}.get(t, None)


# --------------------------------------------------------------------------- #
# registry
# --------------------------------------------------------------------------- #
class Registry:
    def __init__(self, spec, source=None):
        self.source = str(source) if source else None
        self.spec = spec or {}
        self.info_version = (spec.get("info", {}) or {}).get("version", "unknown")
        self._defs = self._schema_defs(spec)
        self.ops = {}
        self._index(spec)

    @staticmethod
    def _schema_defs(spec):
        comps = spec.get("components", {}) or {}
        return comps.get("schemas") or spec.get("definitions") or {}

    def _index(self, spec):
        for path, item in (spec.get("paths") or {}).items():
            if not isinstance(item, dict):
                continue
            shared = item.get("parameters", [])
            for method, op in item.items():
                if method.upper() not in {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD"}:
                    continue
                if not isinstance(op, dict):
                    continue
                op_id = op.get("operationId") or "%s_%s" % (method, path)
                params = self._params(shared, op.get("parameters", []))
                self.ops[op_id] = {
                    "operationId": op_id,
                    "method": method.upper(),
                    "path": path,
                    "summary": op.get("summary", "") or "",
                    "description": op.get("description", "") or "",
                    "tags": op.get("tags", []) or [],
                    "params": params,
                    "requestBody": self._request_body(op),
                    "read": method.upper() in _READ_METHODS,
                }

    def _params(self, shared, own):
        out, seen = [], set()
        for p in list(own) + list(shared):
            if "$ref" in p:
                continue
            key = (p.get("name"), p.get("in"))
            if key in seen:
                continue
            seen.add(key)
            schema = p.get("schema", {})
            out.append({
                "name": p.get("name"),
                "in": p.get("in"),
                "required": bool(p.get("required")),
                "type": schema.get("type") or p.get("type") or "string",
                "description": p.get("description", "") or "",
            })
        return out

    def _request_body(self, op):
        rb = op.get("requestBody")
        if not rb:
            return None
        content = rb.get("content", {})
        ctype = next(iter(content), None)
        schema = (content.get(ctype, {}) or {}).get("schema", {}) if ctype else {}
        return {
            "required": bool(rb.get("required")),
            "contentType": ctype or "application/json",
            "example": _example(schema, self._defs),
        }

    # --- discovery API ----------------------------------------------------- #
    def search(self, query, limit=25, reads_only=False):
        q = (query or "").lower().strip()
        terms = [t for t in re.split(r"\s+", q) if t]
        scored = []
        for op in self.ops.values():
            if reads_only and not op["read"]:
                continue
            hay_id = op["operationId"].lower()
            hay_sum = op["summary"].lower()
            hay_tags = " ".join(op["tags"]).lower()
            hay_path = op["path"].lower()
            score = 0
            for t in terms:
                if t in hay_id:
                    score += 5
                if t in hay_tags:
                    score += 4
                if t in hay_sum:
                    score += 3
                if t in hay_path:
                    score += 2
            if not terms:
                score = 1
            if score:
                scored.append((score, op))
        scored.sort(key=lambda x: (-x[0], x[1]["operationId"]))
        return [self._brief(op) for _, op in scored[:limit]]

    def describe(self, op_id):
        op = self.ops.get(op_id)
        if not op:
            return None
        return {
            "operationId": op["operationId"],
            "method": op["method"],
            "path": op["path"],
            "summary": op["summary"],
            "description": op["description"],
            "tags": op["tags"],
            "access": "read" if op["read"] else "write",
            "parameters": op["params"],
            "requestBody": op["requestBody"],
        }

    def tags(self):
        seen = {}
        for op in self.ops.values():
            for t in op["tags"]:
                seen[t] = seen.get(t, 0) + 1
        return dict(sorted(seen.items()))

    def list_ops(self, reads_only=False, tag=None):
        """Return ALL operations (no cap), sorted by tag then operationId.

        Optionally filter to read-only operations and/or a single tag."""
        tag_l = tag.lower() if tag else None
        out = []
        for op in self.ops.values():
            if reads_only and not op["read"]:
                continue
            if tag_l and tag_l not in [t.lower() for t in op["tags"]]:
                continue
            out.append(self._brief(op))
        out.sort(key=lambda o: ((o["tags"][0].lower() if o["tags"] else "~"),
                                o["operationId"].lower()))
        return out

    def grouped(self, reads_only=False):
        """Return all operations grouped into {tag: [briefs]} (tag-sorted)."""
        groups = {}
        for brief in self.list_ops(reads_only=reads_only):
            key = brief["tags"][0] if brief["tags"] else "(untagged)"
            groups.setdefault(key, []).append(brief)
        return dict(sorted(groups.items()))

    @staticmethod
    def _brief(op):
        return {
            "operationId": op["operationId"],
            "method": op["method"],
            "path": op["path"],
            "summary": op["summary"],
            "tags": op["tags"],
            "access": "read" if op["read"] else "write",
        }


def load_registry(spec_path=None):
    path, spec = resolve_spec(spec_path)
    return Registry(spec, source=path)
