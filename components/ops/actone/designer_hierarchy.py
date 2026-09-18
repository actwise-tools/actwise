"""Pure planning and verification for ActOne business-unit hierarchies."""
from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping
from typing import Any


CAPABILITY_ID = "manage_business_unit_hierarchy"
SERVICE = "businessUnitService"
CREATE_OPERATION = "addHierarchy"
UPDATE_OPERATION = "updateHierarchy"
OFFICIAL_SOURCE_URL = (
    "https://docs.niceactimize.com/bundle/"
    "Actimize_ActOne_10.2_Extend_Implementer_Guide/page/Content/Platform/"
    "ActOne/ActOne_Self_Developers_Guide/"
    "Web_Services_for_Business_Hierarchy.htm"
)

_INPUT_CONTRACT = [
    {"name": "businessHierarchy", "type": "BusinessHierarchy"},
    {"name": "newBusinessUnitList", "type": "BusinessUnit[]"},
    {"name": "updatedBusinessUnitList", "type": "BusinessUnit[]"},
]
_CREATE_OUTPUT_CONTRACT = [
    {"name": "businessHierarchyId", "type": "IntHolder"},
    {"name": "newBusinessUnitIdList", "type": "IntListHolder"},
]
_UPDATE_OUTPUT_CONTRACT = [
    {"name": "newBusinessUnitIdList", "type": "IntListHolder"},
]
_TEMP_ID_KEYS = ("_id", "id", "temporaryId", "tempId")

__all__ = [
    "CAPABILITY_ID",
    "HierarchyPlanError",
    "apply_business_unit_hierarchy_plan",
    "collect_business_unit_hierarchy_observation",
    "fingerprint_hierarchy_plan",
    "hierarchy_route_metadata_from_catalog",
    "normalize_hierarchy_observation",
    "normalize_hierarchy_specification",
    "plan_business_unit_hierarchy",
    "validate_hierarchy_plan",
    "verify_business_unit_hierarchy",
]


class HierarchyPlanError(ValueError):
    """The requested hierarchy cannot be represented safely."""


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _required_text(value: dict, key: str, label: str) -> str:
    text = value.get(key)
    if text is None and not key.startswith("_"):
        text = value.get("_" + key)
    text = str(text or "").strip()
    if not text:
        raise HierarchyPlanError(f"{label} requires {key}")
    return text


def _optional_text(value: dict, key: str) -> str:
    result = value.get(key)
    if result is None and not key.startswith("_"):
        result = value.get("_" + key)
    return str(result or "")


def _boolean(value: dict, key: str, label: str) -> bool:
    result = value.get(key)
    if result is None and not key.startswith("_"):
        result = value.get("_" + key)
    if isinstance(result, str) and result.lower() in {"true", "false"}:
        return result.lower() == "true"
    if not isinstance(result, bool):
        raise HierarchyPlanError(f"{label} requires boolean {key}")
    return result


def _positive_integer(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return value > 0
    return isinstance(value, str) and value.isdigit() and int(value) > 0


def _first_present(value: dict, names: tuple[str, ...]) -> Any:
    for name in names:
        if name in value:
            return value[name]
    return None


def _reject_role_authoring(value: dict, label: str) -> None:
    role_fields = sorted(
        key for key in value if "role" in str(key).lower()
    )
    if role_fields:
        raise HierarchyPlanError(
            f"{label} role authoring is not supported: {', '.join(role_fields)}"
        )


def _record_supplied_temp_ids(value: dict, label: str, used: set[int]) -> None:
    supplied = [value[key] for key in _TEMP_ID_KEYS if key in value]
    if not supplied:
        return
    if len(supplied) > 1 and len(set(supplied)) != 1:
        raise HierarchyPlanError(f"{label} has conflicting temporary IDs")
    temp_id = supplied[0]
    if (
        not isinstance(temp_id, int)
        or isinstance(temp_id, bool)
        or temp_id >= 0
    ):
        raise HierarchyPlanError(f"{label} temporary ID must be a negative integer")
    if temp_id in used:
        raise HierarchyPlanError(f"non-unique temporary ID {temp_id}")
    used.add(temp_id)


def _normalize_business_unit(value: Any, label: str, used_ids: set[int]) -> dict:
    if not isinstance(value, dict):
        raise HierarchyPlanError(f"{label} requires a business-unit definition")
    if any(
        key in value
        for key in ("reference", "ref", "businessUnitReference", "existingIdentifier")
    ):
        raise HierarchyPlanError(
            f"{label} references an existing/shared business unit; "
            "this increment creates exclusively owned business units only"
        )
    definition = value.get("definition", value)
    if not isinstance(definition, dict):
        raise HierarchyPlanError(f"{label} business-unit definition must be an object")
    _reject_role_authoring(definition, f"{label} business unit")
    _record_supplied_temp_ids(definition, f"{label} business unit", used_ids)
    attributes = _first_present(
        definition, ("attributeValues", "_attributeValues")
    )
    if attributes is None:
        attributes = []
    if not isinstance(attributes, list):
        raise HierarchyPlanError(f"{label} attributeValues must be an array")
    return {
        "identifier": _required_text(definition, "identifier", label),
        "name": _required_text(definition, "name", label),
        "description": _optional_text(definition, "description"),
        "attributeValues": copy.deepcopy(attributes),
    }


def normalize_hierarchy_specification(specification: dict) -> dict:
    """Validate and canonicalize the desired nested hierarchy specification.

    The domain root is ``rootNode`` (``root`` is accepted as an alias). Each
    node has ``businessUnit`` and a ``children`` array. Business-unit references
    are deliberately rejected in this create/reuse-only increment.
    """
    if not isinstance(specification, dict):
        raise HierarchyPlanError("hierarchy specification must be an object")
    _reject_role_authoring(specification, "hierarchy")

    supplied_ids: set[int] = set()
    _record_supplied_temp_ids(specification, "hierarchy", supplied_ids)
    root = _first_present(specification, ("rootNode", "root"))
    if root is None:
        raise HierarchyPlanError("hierarchy must not be empty")

    hierarchy = {
        "identifier": _required_text(specification, "identifier", "hierarchy"),
        "name": _required_text(specification, "name", "hierarchy"),
        "description": _optional_text(specification, "description"),
        "showInACM": _boolean(specification, "showInACM", "hierarchy"),
    }

    active: set[int] = set()
    visited: set[int] = set()
    identifiers: set[str] = set()

    def visit(raw: Any, path: str) -> dict:
        if not isinstance(raw, dict):
            raise HierarchyPlanError(f"{path} must be an object")
        _reject_role_authoring(raw, path)
        object_id = id(raw)
        if object_id in active:
            raise HierarchyPlanError(f"cycle detected at {path}")
        if object_id in visited:
            raise HierarchyPlanError(f"multiple parents detected at {path}")
        active.add(object_id)
        visited.add(object_id)

        reference = _first_present(
            raw,
            ("businessUnitReference", "businessUnitRef", "businessUnitIdentifier"),
        )
        if reference is not None:
            raise HierarchyPlanError(
                f"{path} references existing/shared business unit {reference!r}"
            )
        business_unit = _normalize_business_unit(
            raw.get("businessUnit"), path, supplied_ids
        )
        identifier = business_unit["identifier"]
        if identifier in identifiers:
            raise HierarchyPlanError(
                f"duplicate business-unit identifier {identifier!r}"
            )
        identifiers.add(identifier)

        children = raw.get("children", [])
        if not isinstance(children, list):
            raise HierarchyPlanError(f"{path} children must be an array")
        normalized_children = [
            visit(child, f"{path}.children[{index}]")
            for index, child in enumerate(children)
        ]
        active.remove(object_id)
        return {
            "businessUnit": business_unit,
            "children": normalized_children,
        }

    normalized_root = visit(root, "rootNode")
    inventory = specification.get("nodes")
    if inventory is not None:
        if not isinstance(inventory, list):
            raise HierarchyPlanError("hierarchy nodes inventory must be an array")
        disconnected = [
            index for index, node in enumerate(inventory)
            if not isinstance(node, dict) or id(node) not in visited
        ]
        if disconnected:
            raise HierarchyPlanError(
                "disconnected nodes in inventory at indexes "
                + ", ".join(str(index) for index in disconnected)
            )

    hierarchy["rootNode"] = normalized_root
    return hierarchy


def _observation_collection(
    observed: dict,
    collection_name: str,
    established_names: tuple[str, ...],
) -> list[dict]:
    structured = observed.get(collection_name)
    established = None
    items = None
    if isinstance(structured, dict):
        established = _first_present(
            structured, ("established", "known", "normalized")
        )
        items = _first_present(structured, ("items", "values"))
    if items is None:
        items = observed.get(collection_name)
    if established is None:
        established = _first_present(observed, established_names)
    if established is not True:
        raise HierarchyPlanError(
            f"observation does not positively establish {collection_name}"
        )
    if not isinstance(items, list) or not all(
        isinstance(item, dict) for item in items
    ):
        raise HierarchyPlanError(
            f"normalized observation {collection_name} must be an array of objects"
        )
    return items


def normalize_hierarchy_observation(observed: dict) -> dict:
    """Validate the normalized read model required by the pure planner."""
    if not isinstance(observed, dict):
        raise HierarchyPlanError("hierarchy observation must be an object")
    hierarchy_source = dict(observed)
    if "hierarchies" not in hierarchy_source and "hierarchyList" in observed:
        hierarchy_source["hierarchies"] = observed["hierarchyList"]
    hierarchies = _observation_collection(
        hierarchy_source,
        "hierarchies",
        (
            "hierarchyListEstablished",
            "hierarchiesEstablished",
            "hierarchiesKnown",
        ),
    )
    business_unit_source = dict(observed)
    if (
        "businessUnits" not in business_unit_source
        and "businessUnitIdentifiers" in observed
    ):
        business_unit_source["businessUnits"] = observed[
            "businessUnitIdentifiers"
        ]
    business_units = _observation_collection(
        business_unit_source,
        "businessUnits",
        (
            "businessUnitIdentifiersEstablished",
            "businessUnitsEstablished",
            "businessUnitIdentifiersKnown",
        ),
    )
    identifiers: set[str] = set()
    for index, business_unit in enumerate(business_units):
        identifier = _required_text(
            business_unit, "identifier", f"observed business unit {index}"
        )
        if identifier in identifiers:
            raise HierarchyPlanError(
                f"observation has duplicate business-unit identifier {identifier!r}"
            )
        identifiers.add(identifier)
    return {
        "hierarchies": hierarchies,
        "businessUnits": business_units,
    }


def _normalize_route_metadata(route_metadata: dict | None) -> dict:
    if not isinstance(route_metadata, dict):
        raise HierarchyPlanError(
            "route metadata must explicitly provide the hierarchy-node "
            "child-array wire name"
        )
    wire_name = _first_present(
        route_metadata,
        (
            "childArrayWireName",
            "nodeChildrenWireName",
            "businessHierarchyNodeChildArray",
        ),
    )
    wire_name = str(wire_name or "").strip()
    if not wire_name:
        raise HierarchyPlanError(
            "route metadata lacks the hierarchy-node child-array wire name"
        )
    service = route_metadata.get("service", SERVICE)
    if service != SERVICE:
        raise HierarchyPlanError(
            f"SOAP route service must be {SERVICE}, not {service}"
        )
    return {
        "adapter": "designer-soap",
        "service": SERVICE,
        "operations": {
            "create": {
                "operation": CREATE_OPERATION,
                "inputs": [dict(item) for item in _INPUT_CONTRACT],
                "outputs": [
                    dict(item) for item in _CREATE_OUTPUT_CONTRACT
                ],
                "returnType": "ACMResult",
            },
            "update": {
                "operation": UPDATE_OPERATION,
                "inputs": [dict(item) for item in _INPUT_CONTRACT],
                "outputs": [
                    dict(item) for item in _UPDATE_OUTPUT_CONTRACT
                ],
                "returnType": "ACMResult",
            },
        },
        "childArrayWireName": wire_name,
        "evidence": {
            "catalog": str(
                route_metadata.get("source") or "explicit route metadata"
            ),
            "officialDocumentation": OFFICIAL_SOURCE_URL,
            "parentNodeSerialization": (
                "omitted or null; child arrays define the tree"
            ),
        },
    }


def hierarchy_route_metadata_from_catalog(catalog) -> dict:
    """Derive and validate the hierarchy route from the loaded SOAP catalog."""
    if catalog is None or not callable(getattr(catalog, "find_bean", None)):
        raise HierarchyPlanError("a loaded SOAP catalog is required")
    node = catalog.find_bean("BusinessHierarchyNode")
    if not isinstance(node, Mapping):
        raise HierarchyPlanError(
            "SOAP catalog lacks the BusinessHierarchyNode bean"
        )
    child_fields = [
        field
        for field in node.get("flattenedFields", []) or []
        if isinstance(field, Mapping)
        and field.get("type") == "BusinessHierarchyNode[]"
    ]
    if len(child_fields) != 1:
        raise HierarchyPlanError(
            "BusinessHierarchyNode must declare exactly one child-node array"
        )
    child_wire_name = str(child_fields[0].get("name") or "").strip()
    if child_wire_name != "emptyHierArray":
        raise HierarchyPlanError(
            "BusinessHierarchyNode child array must be emptyHierArray; "
            f"catalog declares {child_wire_name!r}"
        )

    expected_operations = {
        "getHierarchyList": [
            ("businessHierarchyInfoList", "BusinessHierarchyInfoListHolder", "out"),
        ],
        "getAllBusinessUnits": [
            ("businessUnitList", "BusinessUnitListHolder", "out"),
        ],
        "getHierarchy": [
            ("hierarchyId", "int", "in"),
            ("businessHierarchy", "BusinessHierarchyHolder", "out"),
        ],
        "getHierarchyBusinessUnits": [
            ("hierarchyId", "int", "in"),
            ("businessUnitList", "BusinessUnitListHolder", "out"),
        ],
        "getBusinessUnitAllHierarchies": [
            ("businessUnitId", "int", "in"),
            (
                "businessUnitHierarchyList",
                "BusinessHierarchyInfoListHolder",
                "out",
            ),
        ],
        CREATE_OPERATION: [
            ("businessHierarchy", "BusinessHierarchy", "in"),
            ("newBusinessUnitList", "BusinessUnit[]", "in"),
            ("updatedBusinessUnitList", "BusinessUnit[]", "in"),
            ("businessHierarchyId", "IntHolder", "out"),
            ("newBusinessUnitIdList", "IntListHolder", "out"),
        ],
    }
    for operation, expected in expected_operations.items():
        entry = catalog.find_operation(SERVICE, operation)
        actual = [
            (item.get("name"), item.get("type"), item.get("mode"))
            for item in (entry or {}).get("parameters", []) or []
        ]
        if actual != expected:
            raise HierarchyPlanError(
                f"SOAP catalog contract mismatch for {SERVICE}.{operation}"
            )
    return {
        "service": SERVICE,
        "childArrayWireName": child_wire_name,
        "source": (
            f"SOAP catalog {catalog.source}"
            if getattr(catalog, "source", None)
            else "loaded SOAP catalog"
        ),
    }


def _operation_output(result, output_name: str):
    if not isinstance(result, Mapping) or result.get("ok") is False:
        raise HierarchyPlanError(
            f"{output_name} SOAP response was unsuccessful or malformed"
        )
    outputs = result.get("outputs")
    if isinstance(outputs, Mapping):
        if output_name not in outputs:
            raise HierarchyPlanError(
                f"{output_name} SOAP response omitted its output holder"
            )
        return outputs[output_name]
    if "out" in result:
        return result["out"]
    raise HierarchyPlanError(
        f"{output_name} SOAP response omitted its output holder"
    )


def _list_output(result, output_name: str) -> list[dict]:
    value = _operation_output(result, output_name)
    if value is None:
        return []
    if isinstance(value, Mapping):
        if not set(value) <= {"@type", "item"}:
            raise HierarchyPlanError(
                f"{output_name} SOAP response has an unknown list envelope"
            )
        value = value.get("item", [])
        if isinstance(value, Mapping):
            value = [value]
    if not isinstance(value, list) or not all(
        isinstance(item, Mapping) for item in value
    ):
        raise HierarchyPlanError(
            f"{output_name} SOAP response has an unknown list envelope"
        )
    return [dict(item) for item in value]


def _object_output(result, output_name: str) -> dict:
    value = _operation_output(result, output_name)
    if not isinstance(value, Mapping):
        raise HierarchyPlanError(
            f"{output_name} SOAP response has an unknown object envelope"
        )
    return dict(value)


def _graph_business_unit_identifiers(
    hierarchy: dict,
    business_units: list[dict],
    child_wire_name: str,
) -> set[str]:
    projection, definitions, id_errors = _actual_hierarchy_projection(
        hierarchy,
        business_units,
        child_wire_name,
        require_positive_ids=True,
    )
    if id_errors:
        raise HierarchyPlanError("; ".join(id_errors))
    identifiers: set[str] = set()

    def visit(node: dict) -> None:
        identifiers.add(node["businessUnitIdentifier"])
        for child in node["children"]:
            visit(child)

    visit(projection["rootNode"])
    if identifiers != set(definitions):
        raise HierarchyPlanError(
            "getHierarchyBusinessUnits does not exactly match the hierarchy graph"
        )
    return identifiers


def _require_exclusive_hierarchy_membership(
    designer_client,
    hierarchy_id: int,
    business_units: list[dict],
) -> None:
    for business_unit in business_units:
        business_unit_id = _first_present(business_unit, ("_id", "id"))
        identifier = _required_text(
            business_unit, "identifier", "hierarchy business unit"
        )
        if not _positive_integer(business_unit_id):
            raise HierarchyPlanError(
                f"business unit {identifier!r} lacks a positive ID"
            )
        memberships = _list_output(
            designer_client.call_typed_operation(
                SERVICE,
                "getBusinessUnitAllHierarchies",
                {"businessUnitId": business_unit_id},
            ),
            "businessUnitHierarchyList",
        )
        membership_ids = []
        for membership in memberships:
            membership_id = _first_present(membership, ("_id", "id"))
            if not _positive_integer(membership_id):
                raise HierarchyPlanError(
                    f"business unit {identifier!r} hierarchy membership "
                    "is malformed"
                )
            membership_ids.append(membership_id)
        if membership_ids != [hierarchy_id]:
            raise HierarchyPlanError(
                f"business unit {identifier!r} is not exclusively owned by "
                f"hierarchy ID {hierarchy_id}; memberships={membership_ids}"
            )


def collect_business_unit_hierarchy_observation(
    designer_client,
    specification,
) -> dict:
    """Collect list state and hydrate the exact matching hierarchy graph."""
    normalized = normalize_hierarchy_specification(specification)
    route_metadata = hierarchy_route_metadata_from_catalog(
        getattr(designer_client, "catalog", None)
    )
    hierarchy_infos = _list_output(
        designer_client.call_typed_operation(
            SERVICE, "getHierarchyList", {}
        ),
        "businessHierarchyInfoList",
    )
    all_business_units = _list_output(
        designer_client.call_typed_operation(
            SERVICE, "getAllBusinessUnits", {}
        ),
        "businessUnitList",
    )
    identifier = normalized["identifier"]
    matches = [
        item
        for item in hierarchy_infos
        if _optional_text(item, "identifier") == identifier
    ]
    if len(matches) > 1:
        raise HierarchyPlanError(
            f"multiple hierarchies use identifier {identifier!r}"
        )
    if matches:
        hierarchy_id = _first_present(matches[0], ("_id", "id"))
        if not _positive_integer(hierarchy_id):
            raise HierarchyPlanError(
                f"hierarchy {identifier!r} lacks a positive ID"
            )
        hierarchy = _object_output(
            designer_client.call_typed_operation(
                SERVICE, "getHierarchy", {"hierarchyId": hierarchy_id}
            ),
            "businessHierarchy",
        )
        if _optional_text(hierarchy, "identifier") != identifier:
            raise HierarchyPlanError(
                "getHierarchy returned a different hierarchy identifier"
            )
        hierarchy_business_units = _list_output(
            designer_client.call_typed_operation(
                SERVICE,
                "getHierarchyBusinessUnits",
                {"hierarchyId": hierarchy_id},
            ),
            "businessUnitList",
        )
        owned_identifiers = _graph_business_unit_identifiers(
            hierarchy,
            hierarchy_business_units,
            route_metadata["childArrayWireName"],
        )
        _require_exclusive_hierarchy_membership(
            designer_client,
            hierarchy_id,
            hierarchy_business_units,
        )
        global_by_id = {}
        for item in all_business_units:
            unit_id = _first_present(item, ("_id", "id"))
            if not _positive_integer(unit_id):
                raise HierarchyPlanError(
                    "getAllBusinessUnits returned a non-positive or missing ID"
                )
            if unit_id in global_by_id:
                raise HierarchyPlanError(
                    f"getAllBusinessUnits returned duplicate ID {unit_id}"
                )
            global_by_id[unit_id] = item
        for item in hierarchy_business_units:
            unit_id = _first_present(item, ("_id", "id"))
            if (
                unit_id not in global_by_id
                or _business_unit_projection(global_by_id[unit_id])
                != _business_unit_projection(item)
            ):
                raise HierarchyPlanError(
                    "hierarchy business-unit readback does not match "
                    "getAllBusinessUnits"
                )
        hierarchy.update({
            "fullyNormalized": True,
            "exclusiveOwned": True,
            "ownershipEstablished": True,
            "ownedBusinessUnitIdentifiers": sorted(owned_identifiers),
        })
        hierarchy_infos = [
            item for item in hierarchy_infos
            if _optional_text(item, "identifier") != identifier
        ] + [hierarchy]

    return {
        "hierarchyListEstablished": True,
        "hierarchies": hierarchy_infos,
        "businessUnitIdentifiersEstablished": True,
        "businessUnits": all_business_units,
        "routeMetadata": route_metadata,
    }


def _allocate_payload(specification: dict, child_wire_name: str) -> dict:
    next_id = -2
    business_units = []

    def allocate(node: dict) -> dict:
        nonlocal next_id
        business_unit_id = next_id
        next_id -= 1
        definition = node["businessUnit"]
        business_units.append({
            "_id": business_unit_id,
            "_identifier": definition["identifier"],
            "_name": definition["name"],
            "_description": definition["description"],
            "_attributeValues": definition["attributeValues"],
        })
        return {
            "_businessUnitId": business_unit_id,
            "_parentNode": None,
            child_wire_name: [
                allocate(child) for child in node["children"]
            ],
        }

    hierarchy = {
        "_id": -1,
        "_identifier": specification["identifier"],
        "_name": specification["name"],
        "_description": specification["description"],
        "_rootNode": allocate(specification["rootNode"]),
        "_showInACM": specification["showInACM"],
    }
    return {
        "businessHierarchy": hierarchy,
        "newBusinessUnitList": business_units,
        "updatedBusinessUnitList": [],
    }


def _business_unit_projection(value: dict) -> dict:
    attributes = _first_present(value, ("attributeValues", "_attributeValues"))
    if not isinstance(attributes, list):
        raise HierarchyPlanError("observed business-unit attributeValues is not an array")
    return {
        "identifier": _required_text(value, "identifier", "observed business unit"),
        "name": _required_text(value, "name", "observed business unit"),
        "description": _optional_text(value, "description"),
        "attributeValues": attributes,
    }


def _expected_business_units(specification: dict) -> dict[str, dict]:
    result = {}

    def visit(node: dict) -> None:
        unit = node["businessUnit"]
        result[unit["identifier"]] = unit
        for child in node["children"]:
            visit(child)

    visit(specification["rootNode"])
    return result


def _actual_hierarchy_projection(
    hierarchy: dict,
    business_units: list[dict],
    child_wire_name: str,
    *,
    require_positive_ids: bool,
) -> tuple[dict, dict[str, dict], list[str]]:
    units_by_id = {}
    unit_definitions = {}
    id_errors = []
    for unit in business_units:
        unit_id = _first_present(unit, ("_id", "id"))
        identifier = _required_text(unit, "identifier", "observed business unit")
        if unit_id is None:
            continue
        if require_positive_ids and not _positive_integer(unit_id):
            id_errors.append(f"business unit {identifier!r} ID is not positive")
        if unit_id in units_by_id:
            raise HierarchyPlanError(
                f"observation has duplicate business-unit ID {unit_id!r}"
            )
        units_by_id[unit_id] = unit
        unit_definitions[identifier] = _business_unit_projection(unit)

    hierarchy_id = _first_present(hierarchy, ("_id", "id"))
    if require_positive_ids and not _positive_integer(hierarchy_id):
        id_errors.append("hierarchy ID is not positive")
    root = _first_present(hierarchy, ("_rootNode", "rootNode", "root"))
    if not isinstance(root, dict):
        raise HierarchyPlanError("fully normalized hierarchy lacks rootNode")

    active: set[int] = set()
    seen: set[int] = set()

    def visit(node: dict, path: str) -> dict:
        object_id = id(node)
        if object_id in active:
            raise HierarchyPlanError(f"observed hierarchy cycle at {path}")
        if object_id in seen:
            raise HierarchyPlanError(f"observed hierarchy has multiple parents at {path}")
        active.add(object_id)
        seen.add(object_id)
        if node.get("_parentNode") is not None:
            raise HierarchyPlanError(
                f"{path} has a non-null parent reference without an established "
                "safe serializer representation"
            )
        business_unit_id = _first_present(
            node, ("_businessUnitId", "businessUnitId")
        )
        if require_positive_ids and not _positive_integer(business_unit_id):
            id_errors.append(f"{path} business-unit binding ID is not positive")
        unit = units_by_id.get(business_unit_id)
        if unit is None:
            raise HierarchyPlanError(
                f"{path} references unknown business-unit ID {business_unit_id!r}"
            )
        children = _first_present(
            node, ("children", "childNodes", child_wire_name)
        )
        if children is None:
            children = []
        if not isinstance(children, list) or not all(
            isinstance(child, dict) for child in children
        ):
            raise HierarchyPlanError(f"{path} child array is not normalized")
        projected = {
            "businessUnitIdentifier": _required_text(
                unit, "identifier", f"{path} business unit"
            ),
            "children": [
                visit(child, f"{path}.children[{index}]")
                for index, child in enumerate(children)
            ],
        }
        active.remove(object_id)
        return projected

    projection = {
        "identifier": _required_text(hierarchy, "identifier", "observed hierarchy"),
        "name": _required_text(hierarchy, "name", "observed hierarchy"),
        "description": _optional_text(hierarchy, "description"),
        "showInACM": _boolean(hierarchy, "showInACM", "observed hierarchy"),
        "rootNode": visit(root, "rootNode"),
    }
    return projection, unit_definitions, id_errors


def _expected_hierarchy_projection(specification: dict) -> dict:
    def visit(node: dict) -> dict:
        return {
            "businessUnitIdentifier": node["businessUnit"]["identifier"],
            "children": [visit(child) for child in node["children"]],
        }

    return {
        "identifier": specification["identifier"],
        "name": specification["name"],
        "description": specification["description"],
        "showInACM": specification["showInACM"],
        "rootNode": visit(specification["rootNode"]),
    }


def _exclusive_ownership_established(
    hierarchy: dict, expected_identifiers: set[str]
) -> bool:
    if hierarchy.get("exclusiveOwned") is True:
        return True
    if hierarchy.get("exclusivelyOwned") is True:
        return True
    if hierarchy.get("ownership") == "exclusive":
        return True
    owned = hierarchy.get("ownedBusinessUnitIdentifiers")
    return (
        hierarchy.get("ownershipEstablished") is True
        and isinstance(owned, list)
        and set(owned) == expected_identifiers
        and len(owned) == len(expected_identifiers)
    )


def _route_from_inputs(observed: dict, route_metadata: dict | None) -> dict:
    if route_metadata is None and isinstance(observed, dict):
        route_metadata = observed.get("routeMetadata")
    return _normalize_route_metadata(route_metadata)


def _plan_fingerprint_payload(plan: dict) -> dict:
    return {
        "capability": plan.get("capability"),
        "environment": plan.get("environment"),
        "targetBuild": plan.get("targetBuild"),
        "specification": plan.get("specification"),
        "observationFingerprint": plan.get("observationFingerprint"),
        "applicable": plan.get("applicable"),
        "routing": plan.get("routing"),
        "changes": plan.get("changes"),
        "steps": plan.get("steps"),
        "errors": plan.get("errors"),
    }


def fingerprint_hierarchy_plan(plan: dict) -> str:
    """Recompute the immutable fingerprint of a hierarchy plan."""
    return _fingerprint(_plan_fingerprint_payload(plan))


def validate_hierarchy_plan(plan: dict) -> dict:
    """Return a machine-readable fingerprint/tamper validation result."""
    if not isinstance(plan, dict) or plan.get("capability") != CAPABILITY_ID:
        return {"ok": False, "error": "unsupported_capability"}
    actual = fingerprint_hierarchy_plan(plan)
    expected = plan.get("fingerprint")
    if actual != expected:
        return {
            "ok": False,
            "error": "plan_tampered",
            "expectedFingerprint": expected,
            "actualFingerprint": actual,
        }
    return {"ok": True}


def _finish_plan(plan: dict) -> dict:
    fingerprint = fingerprint_hierarchy_plan(plan)
    return {
        "planId": fingerprint[:16],
        "fingerprint": fingerprint,
        **plan,
        "warnings": [
            (
                "The BusinessHierarchyNode child-array wire name comes only from "
                "validated SOAP catalog metadata; no caller-supplied label is assumed."
            ),
            (
                "This increment creates exclusively owned business units and does "
                "not author roles or permissions."
            ),
        ],
    }


def plan_business_unit_hierarchy(
    specification: dict,
    observed: dict,
    environment: str = "",
    target_build: str = "",
    route_metadata: dict | None = None,
) -> dict:
    """Return a deterministic create/reuse-only hierarchy plan.

    Recommended observation shape::

        {
            "hierarchyListEstablished": True,
            "hierarchies": [...],
            "businessUnitIdentifiersEstablished": True,
            "businessUnits": [...],
        }

    ``route_metadata`` is normally supplied by the observation collector from the
    loaded SOAP catalog. Unknown observations and all conflicts produce no
    executable steps.
    """
    errors = []
    conflicts = []
    normalized_specification = {}
    normalized_observation = {}
    routing = None

    try:
        normalized_specification = normalize_hierarchy_specification(specification)
    except (HierarchyPlanError, RecursionError) as exc:
        errors.append({
            "code": "invalid_specification",
            "message": str(exc) or "hierarchy specification recursion is invalid",
        })
    try:
        normalized_observation = normalize_hierarchy_observation(observed)
    except HierarchyPlanError as exc:
        errors.append({
            "code": "unknown_observation",
            "message": str(exc),
        })
    try:
        routing = _route_from_inputs(observed, route_metadata)
    except HierarchyPlanError as exc:
        errors.append({
            "code": "route_metadata_missing_or_invalid",
            "message": str(exc),
        })

    changes = {"create": [], "reuse": [], "conflict": conflicts}
    steps = []
    if not errors:
        identifier = normalized_specification["identifier"]
        matching_hierarchies = [
            item for item in normalized_observation["hierarchies"]
            if _optional_text(item, "identifier") == identifier
        ]
        expected_units = _expected_business_units(normalized_specification)
        expected_unit_ids = set(expected_units)

        if len(matching_hierarchies) > 1:
            conflicts.append({
                "code": "ambiguous_hierarchy",
                "identifier": identifier,
                "message": "multiple observed hierarchies use the desired identifier",
            })
        elif matching_hierarchies:
            hierarchy = matching_hierarchies[0]
            if hierarchy.get("fullyNormalized") is not True:
                conflicts.append({
                    "code": "hierarchy_not_fully_normalized",
                    "identifier": identifier,
                    "message": (
                        "existing hierarchy cannot be reused without a positively "
                        "established fully normalized graph"
                    ),
                })
            elif not _exclusive_ownership_established(
                hierarchy, expected_unit_ids
            ):
                conflicts.append({
                    "code": "business_units_not_exclusively_owned",
                    "identifier": identifier,
                    "message": (
                        "existing/shared business units cannot be reused by this "
                        "increment"
                    ),
                })
            else:
                try:
                    actual_hierarchy, actual_units, id_errors = (
                        _actual_hierarchy_projection(
                            hierarchy,
                            normalized_observation["businessUnits"],
                            routing["childArrayWireName"],
                            require_positive_ids=True,
                        )
                    )
                except HierarchyPlanError as exc:
                    conflicts.append({
                        "code": "existing_hierarchy_not_normalized",
                        "identifier": identifier,
                        "message": str(exc),
                    })
                else:
                    expected_hierarchy = _expected_hierarchy_projection(
                        normalized_specification
                    )
                    if (
                        id_errors
                        or actual_hierarchy != expected_hierarchy
                        or {
                            key: actual_units.get(key)
                            for key in expected_unit_ids
                        } != expected_units
                    ):
                        conflicts.append({
                            "code": "existing_hierarchy_differs",
                            "identifier": identifier,
                            "message": (
                                "existing hierarchy graph or business-unit "
                                "definitions differ; updates are not supported"
                            ),
                        })
                    else:
                        changes["reuse"].append({
                            "type": "BusinessHierarchy",
                            "identifier": identifier,
                        })
        else:
            observed_unit_ids = {
                _required_text(item, "identifier", "observed business unit")
                for item in normalized_observation["businessUnits"]
            }
            collisions = sorted(expected_unit_ids & observed_unit_ids)
            if collisions:
                conflicts.append({
                    "code": "existing_or_shared_business_units",
                    "identifiers": collisions,
                    "message": (
                        "desired business-unit identifiers already exist and cannot "
                        "be reused by a new exclusively owned hierarchy"
                    ),
                })
            else:
                payload = _allocate_payload(
                    normalized_specification,
                    routing["childArrayWireName"],
                )
                changes["create"].append({
                    "type": "BusinessHierarchy",
                    "identifier": identifier,
                    "businessUnitIdentifiers": sorted(expected_unit_ids),
                })
                steps.append({
                    "id": f"business-unit-hierarchy.{identifier}",
                    "adapter": "designer-soap",
                    "service": SERVICE,
                    "operation": CREATE_OPERATION,
                    "action": "create",
                    "inputs": payload,
                    "outputs": [
                        dict(item) for item in _CREATE_OUTPUT_CONTRACT
                    ],
                    "dependsOn": [],
                    "verification": [
                        "hierarchy identifier and fields equal the desired state",
                        "tree and business-unit definitions equal the desired state",
                        "hierarchy and business-unit IDs are positive",
                    ],
                })

    if errors or conflicts:
        steps = []
        changes["create"] = []
        changes["reuse"] = []
    observation_fingerprint = (
        _fingerprint(normalized_observation)
        if normalized_observation else None
    )
    return _finish_plan({
        "capability": CAPABILITY_ID,
        "environment": environment,
        "targetBuild": target_build,
        "specification": normalized_specification,
        "observationFingerprint": observation_fingerprint,
        "applicable": not errors and not conflicts,
        "routing": routing,
        "changes": changes,
        "steps": steps,
        "errors": errors,
    })


def _assertion(
    assertions: list[dict],
    name: str,
    expected: Any,
    actual: Any,
) -> None:
    assertions.append({
        "name": name,
        "passed": expected == actual,
        "expected": expected,
        "actual": actual,
    })


def verify_business_unit_hierarchy(plan: dict, post_observation: dict) -> dict:
    """Verify an intact plan against a fully normalized post-save observation."""
    integrity = validate_hierarchy_plan(plan)
    if not integrity["ok"]:
        return integrity
    if not plan.get("applicable"):
        return {"ok": False, "error": "plan_not_applicable"}

    try:
        observed = normalize_hierarchy_observation(post_observation)
        specification = normalize_hierarchy_specification(plan["specification"])
        route = plan["routing"]
        identifier = specification["identifier"]
        matches = [
            item for item in observed["hierarchies"]
            if _optional_text(item, "identifier") == identifier
        ]
        if len(matches) != 1:
            return {
                "ok": False,
                "error": "hierarchy_missing_or_ambiguous",
                "identifier": identifier,
                "matchCount": len(matches),
            }
        actual_hierarchy, actual_units, id_errors = _actual_hierarchy_projection(
            matches[0],
            observed["businessUnits"],
            route["childArrayWireName"],
            require_positive_ids=True,
        )
    except (HierarchyPlanError, KeyError, TypeError) as exc:
        return {
            "ok": False,
            "error": "post_observation_not_normalized",
            "message": str(exc),
        }

    expected_hierarchy = _expected_hierarchy_projection(specification)
    expected_units = _expected_business_units(specification)
    assertions = []
    _assertion(
        assertions,
        "business-hierarchy.definition-and-tree",
        expected_hierarchy,
        actual_hierarchy,
    )
    _assertion(
        assertions,
        "business-hierarchy.business-units",
        expected_units,
        {
            identifier: actual_units.get(identifier)
            for identifier in expected_units
        },
    )
    _assertion(
        assertions,
        "business-hierarchy.resolved-positive-ids",
        [],
        id_errors,
    )
    failures = [assertion for assertion in assertions if not assertion["passed"]]
    return {
        "ok": not failures,
        "assertions": assertions,
        "failures": failures,
    }


def _hierarchy_target_error(
    plan: Mapping,
    environment: str,
    target_build: str,
) -> dict | None:
    if (
        not environment
        or not target_build
        or plan.get("environment") != environment
        or plan.get("targetBuild") != target_build
    ):
        return {
            "ok": False,
            "error": "target_mismatch",
            "planId": plan.get("planId"),
            "expectedEnvironment": plan.get("environment"),
            "expectedTargetBuild": plan.get("targetBuild"),
            "actualEnvironment": environment,
            "actualTargetBuild": target_build,
        }
    return None


def _hierarchy_step_error(plan: Mapping) -> str | None:
    steps = plan.get("steps")
    if not isinstance(steps, list) or len(steps) > 1:
        return "hierarchy plan must contain zero or one create step"
    if not steps:
        return None
    step = steps[0]
    identifier = plan.get("specification", {}).get("identifier")
    if (
        not isinstance(step, Mapping)
        or step.get("id") != f"business-unit-hierarchy.{identifier}"
        or step.get("adapter") != "designer-soap"
        or step.get("service") != SERVICE
        or step.get("operation") != CREATE_OPERATION
        or step.get("action") != "create"
        or step.get("dependsOn") != []
        or not isinstance(step.get("inputs"), Mapping)
        or set(step["inputs"]) != {
            "businessHierarchy",
            "newBusinessUnitList",
            "updatedBusinessUnitList",
        }
        or step["inputs"].get("updatedBusinessUnitList") != []
        or step.get("outputs") != _CREATE_OUTPUT_CONTRACT
    ):
        return "hierarchy create step is outside the typed route allowlist"
    return None


def apply_business_unit_hierarchy_plan(
    plan,
    designer_client,
    environment: str,
    target_build: str,
) -> dict:
    """Apply an intact create/reuse plan, then verify and re-plan to zero writes."""
    from actone.designer import DesignerError

    integrity = validate_hierarchy_plan(plan)
    if not integrity["ok"]:
        return {
            **integrity,
            "planId": plan.get("planId") if isinstance(plan, Mapping) else None,
        }
    target_error = _hierarchy_target_error(plan, environment, target_build)
    if target_error:
        return target_error
    if not plan.get("applicable"):
        return {
            "ok": False,
            "error": "plan_not_applicable",
            "planId": plan.get("planId"),
            "errors": plan.get("errors", []),
            "conflicts": plan.get("changes", {}).get("conflict", []),
        }
    step_error = _hierarchy_step_error(plan)
    if step_error:
        return {
            "ok": False,
            "error": "unsupported_route",
            "message": step_error,
            "planId": plan.get("planId"),
        }

    try:
        current = collect_business_unit_hierarchy_observation(
            designer_client, plan["specification"]
        )
        current_normalized = normalize_hierarchy_observation(current)
    except (DesignerError, HierarchyPlanError, KeyError, TypeError) as exc:
        return {
            "ok": False,
            "error": "observation_failed",
            "message": str(exc),
            "planId": plan.get("planId"),
        }
    current_fingerprint = _fingerprint(current_normalized)
    if current_fingerprint != plan.get("observationFingerprint"):
        return {
            "ok": False,
            "error": "plan_stale",
            "planId": plan.get("planId"),
            "expectedObservationFingerprint": plan.get(
                "observationFingerprint"
            ),
            "actualObservationFingerprint": current_fingerprint,
        }

    completed = []
    try:
        for step in plan["steps"]:
            result = designer_client.call_typed_operation(
                SERVICE,
                CREATE_OPERATION,
                dict(step["inputs"]),
            )
            if not isinstance(result, Mapping) or result.get("ok") is not True:
                return {
                    "ok": False,
                    "error": "step_failed",
                    "planId": plan.get("planId"),
                    "failedStep": step["id"],
                    "result": result,
                    "completedSteps": completed,
                }
            completed.append({"id": step["id"], "result": dict(result)})

        post_observation = collect_business_unit_hierarchy_observation(
            designer_client, plan["specification"]
        )
        verification = verify_business_unit_hierarchy(plan, post_observation)
        zero_mutation_plan = plan_business_unit_hierarchy(
            plan["specification"],
            post_observation,
            environment=environment,
            target_build=target_build,
        )
    except (DesignerError, HierarchyPlanError, KeyError, TypeError) as exc:
        return {
            "ok": False,
            "error": "verification_failed",
            "message": str(exc),
            "planId": plan.get("planId"),
            "completedSteps": completed,
        }

    zero_mutation = (
        zero_mutation_plan.get("applicable") is True
        and zero_mutation_plan.get("steps") == []
        and zero_mutation_plan.get("changes", {}).get("create") == []
        and zero_mutation_plan.get("changes", {}).get("conflict") == []
        and zero_mutation_plan.get("changes", {}).get("reuse") == [{
            "type": "BusinessHierarchy",
            "identifier": plan["specification"]["identifier"],
        }]
    )
    verification["zeroMutationReplan"] = {
        "passed": zero_mutation,
        "planId": zero_mutation_plan.get("planId"),
        "changes": zero_mutation_plan.get("changes"),
        "errors": zero_mutation_plan.get("errors"),
    }
    if not verification.get("ok") or not zero_mutation:
        return {
            "ok": False,
            "error": "verification_failed",
            "planId": plan.get("planId"),
            "completedSteps": completed,
            "verification": verification,
        }
    return {
        "ok": True,
        "planId": plan.get("planId"),
        "completedSteps": completed,
        "verification": verification,
    }
