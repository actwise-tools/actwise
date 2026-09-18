"""Capability maturity and build evidence for ActOne Designer authoring."""
from __future__ import annotations

import os
from pathlib import Path

import yaml

from actone.paths import CAPABILITIES

_MATURITY_ORDER = {
    "catalog_only": 0,
    "experimental": 1,
    "verified_read_only": 2,
    "certified": 3,
}
_CAPABILITIES_CACHE = None

PLANNABLE_CAPABILITY_IDS = frozenset({
    "manage_platform_list",
    "manage_drill_down_query",
    "configure_work_item_presentation",
    "manage_business_unit_hierarchy",
    "create_work_item_type",
    "remove_work_item_type",
})


class DesignerCapabilityRegistry:
    """Searchable capability registry shared by catalog, CLI, and MCP callers."""

    def __init__(self, document: dict, source: str | None = None):
        self.source = str(source) if source else None
        self.version = document.get("version")
        self.promotion_rules = dict(document.get("promotionRules", {}) or {})
        capabilities = document.get("capabilities", []) or []
        self._capabilities = {}
        self._by_type: dict[str, list[dict]] = {}
        for capability in capabilities:
            item = dict(capability)
            capability_id = item.get("id")
            maturity = item.get("maturity")
            if not capability_id:
                raise ValueError("Designer capability is missing id")
            if maturity not in _MATURITY_ORDER:
                raise ValueError(
                    "Designer capability %r has invalid maturity %r"
                    % (capability_id, maturity)
                )
            if capability_id in self._capabilities:
                raise ValueError("Duplicate Designer capability id %r" % capability_id)
            item.setdefault("objectTypes", [])
            item.setdefault("verifiedBuilds", [])
            item.setdefault("offlineContractBuilds", [])
            item.setdefault("buildEvidence", {})
            item.setdefault("supports", {})
            self._capabilities[capability_id] = item
            for type_value in item["objectTypes"]:
                self._by_type.setdefault(type_value, []).append(item)

    def search(self, query: str = "", maturity: str | None = None,
               limit: int = 25) -> list[dict]:
        """Return capability summaries matching all query terms."""
        if maturity is not None and maturity not in _MATURITY_ORDER:
            raise ValueError("Unknown Designer capability maturity %r" % maturity)
        terms = [term for term in (query or "").lower().split() if term]
        matches = []
        for capability in self._capabilities.values():
            if maturity and capability["maturity"] != maturity:
                continue
            haystack = " ".join([
                capability["id"],
                capability.get("displayName", ""),
                capability.get("summary", ""),
                " ".join(capability.get("objectTypes", [])),
            ]).lower()
            if terms and not all(term in haystack for term in terms):
                continue
            matches.append(self._brief(capability))
        matches.sort(key=lambda item: (item.get("deprecated", False), item["id"]))
        return matches[:max(0, limit)]

    def describe(self, capability_id: str) -> dict | None:
        capability = self._capabilities.get(capability_id)
        return dict(capability) if capability else None

    def inspect(self, capability_id: str, target_build: str | None = None) -> dict | None:
        """Describe a capability and compare a target build with verified evidence."""
        capability = self.describe(capability_id)
        if not capability:
            return None
        capability["targetBuild"] = target_build
        capability["targetBuildEvidence"] = dict(
            capability.get("buildEvidence", {}).get(target_build, {})
            if target_build else {}
        )
        capability["promotionRequirements"] = list(
            self.promotion_rules.get(capability["maturity"], {}).get(
                "requiredEvidence", []
            )
        )
        if not target_build:
            capability["buildStatus"] = "not_checked"
        elif target_build == "unknown":
            capability["buildStatus"] = "unknown"
        elif target_build in capability.get("verifiedBuilds", []):
            capability["buildStatus"] = "verified"
        else:
            capability["buildStatus"] = "unverified"
        if not target_build:
            capability["contractStatus"] = "not_checked"
        elif target_build == "unknown":
            capability["contractStatus"] = "unknown"
        elif target_build in capability.get("offlineContractBuilds", []):
            capability["contractStatus"] = "offline_verified"
        else:
            capability["contractStatus"] = "unverified"
        if (
            target_build in capability.get("verifiedBuilds", [])
            and capability.get("maturity") == "certified"
        ):
            capability["liveCertificationStatus"] = "certified"
        elif target_build in capability.get("verifiedBuilds", []):
            capability["liveCertificationStatus"] = "live_evidence_only"
        else:
            capability["liveCertificationStatus"] = "not_live_certified"
        return capability

    def for_type(self, type_value: str) -> dict:
        capabilities = self._by_type.get(type_value, [])
        if not capabilities:
            return {"maturity": "catalog_only", "capabilities": []}
        maturity = max(
            (item["maturity"] for item in capabilities),
            key=lambda value: _MATURITY_ORDER[value],
        )
        return {
            "maturity": maturity,
            "capabilities": sorted(item["id"] for item in capabilities),
        }

    @staticmethod
    def _brief(capability: dict) -> dict:
        brief = {
            "id": capability["id"],
            "displayName": capability.get("displayName"),
            "summary": capability.get("summary", ""),
            "maturity": capability["maturity"],
            "objectTypes": list(capability.get("objectTypes", [])),
            "verifiedBuilds": list(capability.get("verifiedBuilds", [])),
            "offlineContractBuilds": list(
                capability.get("offlineContractBuilds", [])
            ),
            "evidenceBuilds": sorted(capability.get("buildEvidence", {})),
            "supports": dict(capability.get("supports", {})),
        }
        if capability.get("deprecated"):
            brief["deprecated"] = True
            brief["replacementCapability"] = capability.get(
                "replacementCapability"
            )
        return brief


def load_capabilities(path: str | None = None) -> DesignerCapabilityRegistry:
    """Load the bundled capability registry or an explicit/environment override."""
    global _CAPABILITIES_CACHE
    explicit = path or os.environ.get("ACTONE_DESIGNER_CAPABILITIES")
    if explicit:
        resolved = Path(explicit)
        document = yaml.safe_load(resolved.read_text(encoding="utf-8")) or {}
        return DesignerCapabilityRegistry(document, source=resolved)
    if _CAPABILITIES_CACHE is None:
        document = yaml.safe_load(CAPABILITIES.read_text(encoding="utf-8")) or {}
        _CAPABILITIES_CACHE = DesignerCapabilityRegistry(document, source=CAPABILITIES)
    return _CAPABILITIES_CACHE


def fingerprint_capability_plan(plan: dict) -> str:
    """Recompute a plan fingerprint through its capability-owned contract."""
    capability_id = plan.get("capability") if isinstance(plan, dict) else None
    if capability_id == "manage_drill_down_query":
        from actone.designer_ddq import fingerprint_drill_down_query_plan

        return fingerprint_drill_down_query_plan(plan)
    if capability_id == "configure_work_item_presentation":
        from actone.designer_presentation import fingerprint_presentation_plan

        return fingerprint_presentation_plan(plan)
    if capability_id == "manage_business_unit_hierarchy":
        from actone.designer_hierarchy import fingerprint_hierarchy_plan

        return fingerprint_hierarchy_plan(plan)
    from actone.designer_planner import fingerprint_plan

    return fingerprint_plan(plan)
