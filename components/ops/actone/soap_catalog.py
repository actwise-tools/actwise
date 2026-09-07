#!/usr/bin/env python
"""
soap_catalog.py — searchable catalog of the ActOne SOAP surface (Designer + admin).

Where registry.py indexes the runtime **REST** OpenAPI spec, this module loads the
**SOAP** catalog (``actone-catalog.json``) that describes the legacy Axis services:

  * ``services``    — 22 Axis services / 335 operations (each param has a ``mode``:
                      ``in`` / ``out``; ``*Holder`` params are outputs).
  * ``objectTypes`` — 275 Designer object types; 100 are Designer-creatable and
                      carry ``createPaths`` (``via`` = ``generic`` addObject or a
                      ``dedicated`` op, plus the payload ``bean``).
  * ``beans``       — 282 DTOs; ``fields`` (own) + ``flattenedFields`` (own +
                      inherited via ``extends``, each tagged ``declaredIn``).

The catalog is the discovery + schema source for the generalized SOAP engine in
designer.py (which serializes a bean's ``flattenedFields`` into an RPC/encoded
envelope). It is a *data contract*, generated from the ActOne product source
(``platform-rd-rcm``) for a given RCM version.

Source (resolve order):
  1. explicit path (arg / ``ACTONE_CATALOG`` env)
  2. bundled catalog shipped in the wheel (actone/data/actone-catalog.json)

Stdlib only (json). Importable; no top-level work.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from actone.paths import CATALOG

# Java scalar type -> JSON schema kind (for create-field hints in describe_type).
_JSON_SCALAR = {
    "String": "string",
    "int": "integer", "long": "integer", "Integer": "integer", "Long": "integer",
    "short": "integer", "Short": "integer",
    "boolean": "boolean", "Boolean": "boolean",
    "double": "number", "float": "number", "Double": "number", "Float": "number",
}


def _humanize(name: str) -> str:
    """Split a PascalCase/CamelCase type value into spaced words for a docs query
    (``DrillDownQuery`` -> ``Drill Down Query``)."""
    if not name:
        return name
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name)
    s = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", s)
    return s


# Read-verb prefixes (matched as complete camelCase tokens): operations that only
# read state and are therefore safe to run without the write gate. Everything else
# — including unrecognised verbs and capitalised op names — is treated as a WRITE
# so it stays gated (conservative default; never auto-ungate a mutation).
_READ_OP_RE = re.compile(
    r"(get|list|find|search|has|is|count|read|load|lookup|query|fetch|retrieve|"
    r"describe|view|resolve)(?=[A-Z]|$)")


def operation_access(operation: str) -> str:
    """Classify a SOAP operation as ``"read"`` or ``"write"`` by its verb prefix.

    Only unambiguous read verbs, as complete camelCase tokens, count as reads
    (``getObject`` -> read, but ``issueRefund`` -> write because ``is`` is not a
    whole token there). Every other operation is a ``"write"`` and stays gated."""
    return "read" if _READ_OP_RE.match(operation or "") else "write"


# Curated design-time setup *sequences* the catalog cannot express — the documented
# "do X before Y" order, prerequisites, and doc pointers for the highest-value
# creatable types. Surfaced through describe_type's ``grounding`` block so the agent
# reads the procedure before authoring (see _grounding). Version-agnostic: ``docQuery``
# is fed to the docenter docs MCP, which defaults to the latest version; ``docUrl`` is
# a representative page (latest at authoring time) for direct reading.
_SEQUENCES = {
    "AlertType": {
        "steps": [
            "Create any custom fields the alert type needs (REST POST /md/custom-fields, or Designer AlertCustomizedField)",
            "Create the AlertStatusWorkflowDefinition (and its AlertStatus nodes) if usingAlertStatusWorkflow is true",
            "Create the alert type — commonly by CLONING the default alert type, then editing",
            "Create an AlertView for the new type",
            "Configure automatic status transitions",
        ],
        "docQuery": "Set Up Ingested Alerts create alert type",
        "docUrl": "https://docs.niceactimize.com/bundle/Actimize_ActOne_10.2_Extend_Implementer_Guide/page/Content/ERCM/Ingested_Alerts/Ingested_Installation/Set_Up_Ingested_Alerts.htm",
    },
    "CaseType": {
        "steps": [
            "Define case steps and predefined notes",
            "Customize the display titles of the built-in fields",
            "Create the custom fields the case type needs",
            "Create the case steps workflow (CaseStatusWorkflowDefinition) — optional",
            "Create the case type, then define the order of its case views",
        ],
        "docQuery": "Overview of Cases Setup",
        "docUrl": "https://docs.niceactimize.com/bundle/Actimize_ActOne_10.2_Implementer_Guide/page/Content/Platform/RCM/RCM_Implement/Overview_of_Cases_Setup.htm",
    },
    "DrillDownQuery": {
        "steps": [
            "Create the JDBC database connection first — prefer REST "
            "(POST /RCM/api/v1/system/database/connections, addConnection); "
            "the DDQ's connectionId is a FK to it",
            "Create the DrillDownQuery against that connection",
            "Set up the results display (column names) and any logged-in-user parameters",
        ],
        "docQuery": "Define the Database Connection Fields of the Data Source DDQ",
        "docUrl": "https://docs.niceactimize.com/bundle/Actimize_ActOne_10.2_Implementer_Guide/page/Content/Platform/RCM/RCM_DART/DART_Implementation/Defining_the_Database_Connection.htm",
    },
    "Hierarchy": {
        "steps": [
            "Create the business units first (bu.create) — a hierarchy references BU ids",
            "Optionally define business-unit attributes the hierarchy needs",
            "Define the hierarchy and its node tree; assign business units to nodes "
            "(new nodes reference new BUs by a unique NEGATIVE id, resolved on save)",
            "Save the hierarchy together with its new/updated business-unit lists",
        ],
        "docQuery": "Setting up Business Unit Hierarchies",
        "docUrl": "https://docs.niceactimize.com/bundle/Actimize_ActOne_10.2_Implementer_Guide/page/Content/Platform/RCM/RCM_Implement/Setting_up_Business_Unit_Hierarchies.htm",
        "note": "No typed create slice: businessUnitService.addHierarchy is a multi-part op "
                "(a BusinessHierarchy with a nested node tree plus newBusinessUnitList / "
                "updatedBusinessUnitList). Use the generic engine or `designer call "
                "businessUnitService addHierarchy` with the doc's negative-id node convention.",
    },
}


def resolve_catalog(explicit: str | None = None) -> tuple[Path, dict]:
    """Return (path, catalog_dict). Raises FileNotFoundError if nothing is found."""
    candidates = []
    if explicit:
        candidates.append(Path(explicit))
    env = os.environ.get("ACTONE_CATALOG")
    if env:
        candidates.append(Path(env))
    candidates.append(CATALOG)
    for p in candidates:
        if p and p.exists():
            # tolerate a UTF-8 BOM (utf-8-sig) so an externally regenerated catalog
            # written by PowerShell still loads.
            return p, json.loads(p.read_text(encoding="utf-8-sig"))
    raise FileNotFoundError(
        "no SOAP catalog found (looked in --catalog, ACTONE_CATALOG, bundled %s)" % CATALOG)


class SoapCatalog:
    """In-memory index over the SOAP catalog with lookup + discovery helpers."""

    def __init__(self, catalog: dict, source: str | None = None):
        self.source = str(source) if source else None
        self.raw = catalog or {}
        self.meta = self.raw.get("_meta", {}) or {}
        self.summary = self.raw.get("summary", {}) or {}
        self.services = self.raw.get("services", []) or []
        self.object_types = self.raw.get("objectTypes", []) or []
        self.beans = self.raw.get("beans", []) or []
        self._svc = {s.get("name"): s for s in self.services}
        self._type = {t.get("typeValue"): t for t in self.object_types}
        self._bean = {b.get("name"): b for b in self.beans}

    # -- raw lookups ---------------------------------------------------------
    def find_service(self, name: str) -> dict | None:
        return self._svc.get(name)

    def find_operation(self, service: str | dict, operation: str) -> dict | None:
        svc = service if isinstance(service, dict) else self.find_service(service)
        if not svc:
            return None
        for op in svc.get("operations", []) or []:
            if op.get("name") == operation:
                return op
        return None

    def find_type(self, type_value: str) -> dict | None:
        return self._type.get(type_value)

    def find_bean(self, name: str) -> dict | None:
        return self._bean.get(name)

    # -- create-path resolution (mirrors GeneratedTools.pickCreatePath) ------
    @staticmethod
    def pick_create_path(type_entry: dict) -> dict | None:
        """Prefer the generic addObject path; fall back to a dedicated op.
        Skips paths whose bean is empty."""
        fallback = None
        for p in type_entry.get("createPaths", []) or []:
            if not p.get("bean"):
                continue
            if p.get("via") == "generic":
                return p
            fallback = p
        return fallback

    def create_path_for(self, type_value: str) -> dict | None:
        t = self.find_type(type_value)
        return self.pick_create_path(t) if t else None

    def is_creatable(self, type_value: str) -> bool:
        t = self.find_type(type_value)
        if not t or not t.get("exportableToDesigner"):
            return False
        path = self.pick_create_path(t)
        return bool(path and self.find_bean(path.get("bean", "")))

    # -- discovery API -------------------------------------------------------
    def search_services(self, query: str = "", limit: int = 25) -> list[dict]:
        """Rank services/operations by keyword over service+operation names+descriptions.
        Returns brief per-operation hits."""
        q = (query or "").lower().strip()
        terms = [t for t in re.split(r"\s+", q) if t]
        scored = []
        for svc in self.services:
            sname = (svc.get("name") or "").lower()
            for op in svc.get("operations", []) or []:
                oname = (op.get("name") or "").lower()
                odesc = (op.get("description") or "").lower()
                score = 0
                for t in terms:
                    if t in oname:
                        score += 5
                    if t in sname:
                        score += 3
                    if t in odesc:
                        score += 2
                if not terms:
                    score = 1
                if score:
                    scored.append((score, svc, op))
        scored.sort(key=lambda x: (-x[0], x[1].get("name"), x[2].get("name")))
        return [self._op_brief(svc, op) for _, svc, op in scored[:limit]]

    def search_object_types(self, query: str = "", creatable_only: bool = False,
                            limit: int = 50) -> list[dict]:
        q = (query or "").lower().strip()
        terms = [t for t in re.split(r"\s+", q) if t]
        out = []
        for t in self.object_types:
            tv = t.get("typeValue") or ""
            if creatable_only and not self.is_creatable(tv):
                continue
            hay = tv.lower() + " " + (t.get("enumName") or "").lower()
            if terms and not all(term in hay for term in terms):
                continue
            out.append(self._type_brief(t))
        out.sort(key=lambda o: o["typeValue"].lower())
        return out[:limit]

    def describe_service(self, name: str) -> dict | None:
        svc = self.find_service(name)
        if not svc:
            return None
        return {
            "name": svc.get("name"),
            "className": svc.get("className"),
            "operationCount": svc.get("operationCount"),
            "operations": [self._op_detail(op) for op in svc.get("operations", []) or []],
        }

    def describe_operation(self, service: str, operation: str) -> dict | None:
        svc = self.find_service(service)
        op = self.find_operation(svc, operation) if svc else None
        if not op:
            return None
        return {"service": service, **self._op_detail(op)}

    def describe_type(self, type_value: str) -> dict | None:
        t = self.find_type(type_value)
        if not t:
            return None
        path = self.pick_create_path(t)
        bean = self.find_bean(path.get("bean")) if path else None
        out = {
            "typeValue": t.get("typeValue"),
            "enumName": t.get("enumName"),
            "backingHibClass": t.get("backingHibClass"),
            "exportableToDesigner": t.get("exportableToDesigner"),
            "creatable": self.is_creatable(type_value),
            "createPaths": t.get("createPaths", []),
            "createBean": self.describe_bean(bean.get("name")) if bean else None,
        }
        if bean:
            refs, composes = self._relations(bean)
            if refs:
                # foreign keys by identifier: the target must usually pre-exist,
                # so the agent should create referenced objects FIRST.
                out["references"] = refs
            if composes:
                # child objects owned by this one; passed inline (nested object/array)
                out["composes"] = composes
        out["grounding"] = self._grounding(t)
        return out

    def _grounding(self, t: dict) -> dict:
        """Point the agent at the ActWise docs MCP for product knowledge the catalog
        cannot express — the object's setup *sequence*, prerequisites, and any
        server-enforced mandatory fields (e.g. a DrillDownQuery needs an existing
        JDBC connection). The agent has the docenter MCP mounted alongside Ops; it
        should read the docs BEFORE authoring, then create referenced objects first."""
        type_value = t.get("typeValue", "") or t.get("enumName", "")
        label = _humanize(type_value)
        seq = _SEQUENCES.get(type_value)
        out = {
            "note": ("Ground yourself in ActOne product knowledge before authoring: "
                     "use the ActWise docs MCP (docenter — search_docs / get_page, "
                     "aka search_actimize_docs) to learn this object's setup sequence, "
                     "prerequisites, and server-enforced mandatory fields the catalog "
                     "cannot express. Then create any 'references' objects first."),
            "docsMcp": "search_docs / find_bundles / get_page (product='actone')",
            "suggestedQueries": [seq["docQuery"]] if seq else ["Setting up %s" % label, label],
        }
        if seq:
            # Curated documented setup order (do X before Y) for high-value types.
            out["sequence"] = {
                "steps": list(seq["steps"]),
                "docQuery": seq["docQuery"],
                "docUrl": seq["docUrl"],
            }
            if seq.get("note"):
                out["sequence"]["note"] = seq["note"]
        return out

    def _relations(self, bean: dict, _seen: frozenset = frozenset()) -> tuple[list, list]:
        """Split a create bean's fields into reference (FK-by-identifier) and
        composition (owned nested bean) relations, for create guidance."""
        refs, composes = [], []
        for f in bean.get("flattenedFields", []) or []:
            ref_type = f.get("referencesType")
            jtype = f.get("type", "")
            base = jtype[:-2] if jtype.endswith("[]") else jtype
            if ref_type:
                refs.append({
                    "field": f.get("name"),
                    "referencesType": ref_type,
                    "mustPreExist": f.get("mustPreExist", False),
                    "confidence": f.get("refConfidence"),
                    "array": jtype.endswith("[]"),
                })
            elif base in self._bean and base not in _seen:
                composes.append({"field": f.get("name"), "bean": base,
                                 "array": jtype.endswith("[]")})
        return refs, composes

    def describe_bean(self, name: str) -> dict | None:
        b = self.find_bean(name)
        if not b:
            return None
        return {
            "name": b.get("name"),
            "extends": b.get("extends"),
            "kind": b.get("kind"),
            "fields": [self._field_view(f) for f in
                       b.get("flattenedFields", b.get("fields", []))],
        }

    def _field_view(self, f: dict) -> dict:
        """A create-oriented field view: raw type + JSON kind + enum/reference hints."""
        jtype = f.get("type", "")
        base = jtype[:-2] if jtype.endswith("[]") else jtype
        view = {"name": f.get("name"), "type": jtype}
        if f.get("declaredIn"):
            view["declaredIn"] = f["declaredIn"]
        json_kind = _JSON_SCALAR.get(base) or ("string" if base.endswith("Enum") else None)
        if json_kind:
            view["jsonType"] = "array" if jtype.endswith("[]") else json_kind
        elif base in self._bean:
            view["jsonType"] = "array" if jtype.endswith("[]") else "object"
            view["bean"] = base
        if base.endswith("Enum"):
            view["enum"] = True
        if f.get("referencesType"):
            view["referencesType"] = f["referencesType"]
            view["mustPreExist"] = f.get("mustPreExist", False)
        return view

    # -- briefs --------------------------------------------------------------
    @staticmethod
    def _op_brief(svc: dict, op: dict) -> dict:
        params = op.get("parameters", []) or []
        return {
            "service": svc.get("name"),
            "operation": op.get("name"),
            "access": operation_access(op.get("name") or ""),
            "summary": op.get("description", "") or "",
            "inParams": [p.get("name") for p in params if p.get("mode") != "out"],
            "returnType": op.get("returnType"),
        }

    @staticmethod
    def _op_detail(op: dict) -> dict:
        return {
            "operation": op.get("name"),
            "access": operation_access(op.get("name") or ""),
            "description": op.get("description", "") or "",
            "returnType": op.get("returnType"),
            "parameters": op.get("parameters", []) or [],
        }

    def _type_brief(self, t: dict) -> dict:
        tv = t.get("typeValue")
        return {
            "typeValue": tv,
            "enumName": t.get("enumName"),
            "creatable": self.is_creatable(tv),
        }


def load_catalog(catalog_path: str | None = None) -> SoapCatalog:
    path, cat = resolve_catalog(catalog_path)
    return SoapCatalog(cat, source=path)
