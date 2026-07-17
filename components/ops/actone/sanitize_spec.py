#!/usr/bin/env python
"""
sanitize_spec.py — Produce a portman/parser-friendly copy of an ActOne OpenAPI spec.

Two classes of problems are fixed:

1. Java enums rendered as self-referential object schemas, e.g.
       DuplicatesFilePolicyEnum:
         properties: { OVERWRITE: { $ref: '#/.../DuplicatesFilePolicyEnum' }, ... }
   -> rewritten to a plain string enum.

2. Genuinely recursive schemas (e.g. FormSetDto.instances -> ... -> FormSetDto).
   Strict dereferencers (portman / swagger-parser) crash on ANY circular $ref.
   We walk the schema reference graph and break each back-edge (a $ref that points
   at a schema already on the current resolution stack) by replacing it with a
   generic `{ type: object }`, leaving forward references untouched.

Usage:
  python sanitize_spec.py --in ../docs/components/ops/ActOne_Extend_Rest_APIs.yaml \
                          --out specs/ActOne_Extend_Rest_APIs.portman.yaml
"""
import argparse, sys
from pathlib import Path
import yaml
from actone.paths import BUNDLED, workdir

WORKDIR = workdir()
PREFIX = "#/components/schemas/"


def is_self_ref_enum(name, schema):
    if not isinstance(schema, dict) or schema.get("type") != "object":
        return False
    props = schema.get("properties")
    if not isinstance(props, dict):
        return False
    self_ref = PREFIX + name
    return any(isinstance(p, dict) and p.get("$ref") == self_ref for p in props.values())


def ref_name(node):
    if isinstance(node, dict):
        r = node.get("$ref")
        if isinstance(r, str) and r.startswith(PREFIX):
            return r[len(PREFIX):]
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default=str(BUNDLED))
    ap.add_argument("--out", dest="out", default=str(WORKDIR / "specs" / "ActOne_Extend_Rest_APIs.portman.yaml"))
    args = ap.parse_args()

    spec = yaml.safe_load(Path(args.inp).read_text(encoding="utf-8"))
    schemas = (spec.get("components") or {}).get("schemas") or {}

    # --- pass 1: self-referential enums -> string enums ---
    enum_fixed = []
    for name, schema in list(schemas.items()):
        if is_self_ref_enum(name, schema):
            props = schema.get("properties", {})
            values = [k for k in props.keys() if k != "$VALUES"]
            schemas[name] = {
                "type": "string",
                "enum": values,
                "description": schema.get("description", "%s model" % name),
            }
            enum_fixed.append(name)

    # --- pass 2: break circular $ref cycles ---
    broken = []          # (owner schema, target) edges broken
    done = set()         # schema names whose subtree is confirmed cycle-free

    def walk(node, stack):
        """Walk an arbitrary schema node; break back-edge $refs in place."""
        if isinstance(node, list):
            for item in node:
                walk(item, stack)
            return
        if not isinstance(node, dict):
            return
        tgt = ref_name(node)
        if tgt is not None:
            if tgt in stack:
                node.clear()
                node["type"] = "object"
                node["description"] = "recursive reference to %s (flattened for tooling)" % tgt
                broken.append((stack[-1], tgt))
                return
            if tgt in done or tgt not in schemas:
                return
            walk(schemas[tgt], stack + [tgt])
            return
        for v in node.values():
            walk(v, stack)

    for name in list(schemas.keys()):
        walk(schemas[name], [name])
        done.add(name)

    outp = Path(args.out)
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(yaml.safe_dump(spec, sort_keys=False, allow_unicode=True), encoding="utf-8")
    sys.stderr.write("Enums flattened: %d; circular edges broken: %d -> %s\n"
                     % (len(enum_fixed), len(broken), outp))
    if enum_fixed:
        sys.stderr.write("  enums: " + ", ".join(enum_fixed) + "\n")
    if broken:
        uniq = sorted(set("%s->%s" % (a, b) for a, b in broken))
        sys.stderr.write("  cycles: " + ", ".join(uniq) + "\n")


if __name__ == "__main__":
    main()
