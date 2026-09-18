"""Deep schema and item lifecycle capability for ActOne Platform Lists."""
from __future__ import annotations

import json

from actone.designer import DesignerError
from actone.designer_executor import PlanDependencyError, validated_step_order
from actone.designer_planner import (
    DesignerPlanError,
    fingerprint_observation,
    fingerprint_plan,
)
from actone.invoke import InvokeError, invoke

CAPABILITY_ID = "manage_platform_list"
DEFINITION_TYPE = "InternalList"
SOURCE_TYPE = "InternalListCustomizedField"
ITEM_READ_OPERATION = "getFilteredListData"
ITEM_CREATE_OPERATION = "addItemsToList"
ITEM_UPDATE_OPERATION = "updateItems"
MAX_ITEM_MUTATIONS = 25_000
MAX_FILTERED_RESULTS = 500_000
_SUPPORTED_VALUE_TYPES = frozenset({"None", "BU_PICKER"})
FILTERED_READ_DOC_URL = (
    "https://docs.niceactimize.com/bundle/"
    "Actimize_ActOne_10.2_Extend_Implementer_Guide/page/Content/Platform/"
    "ActOne/ActOne_Self_Developers_Guide/Get_Filtered_Data_REST_API.htm"
)

_FIELD_KEYS = (
    "aisFieldIdentifier",
    "listCustomizedFieldIdentifier",
    "displayName",
    "keyOrder",
    "valueType",
    "valueIdentifier",
    "exposeInWebService",
    "isRange",
)
_VIEW_FIELD_KEYS = (
    "visible",
    "selectable",
    "sortable",
    "filterable",
    "exportable",
    "fieldIdentifier",
    "rightToLeft",
    "alignment",
    "columnTitleTextWrapping",
    "columnDataTextWrapping",
    "columnDisplayFormatterIdentifier",
    "columnWidthUnit",
    "sortOrder",
    "sortAscending",
    "columnWidth",
    "displayOrder",
)


def _required_text(value: dict, key: str, label: str) -> str:
    text = str(value.get(key) or "").strip()
    if not text:
        raise DesignerPlanError("%s requires %s" % (label, key))
    return text


def _array(value, key: str | None = None) -> list:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        if key and key in value:
            return _array(value[key])
        candidates = [item for name, item in value.items() if name != "@type"]
        if len(candidates) == 1:
            return _array(candidates[0])
        return [value]
    return [value]


def _result_items(result: dict) -> list[dict]:
    out = result.get("out") if isinstance(result, dict) else None
    return [
        item for item in _array(out)
        if isinstance(item, dict)
    ]


def _identifier(item: dict) -> str | None:
    info = item.get("objectInfo")
    if isinstance(info, dict) and info.get("identifier") is not None:
        return str(info["identifier"])
    value = item.get("identifier")
    return str(value) if value is not None else None


def _bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() in {"true", "false"}:
        return value.lower() == "true"
    return value


def _int(value):
    if value is None or isinstance(value, bool):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        return value


def normalize_platform_list_specification(specification: dict) -> dict:
    """Validate and canonicalize the domain-level Platform List specification."""
    if not isinstance(specification, dict):
        raise DesignerPlanError("platform-list specification must be an object")
    identifier = _required_text(specification, "identifier", "platform list")
    name = _required_text(specification, "name", "platform list")
    raw_fields = specification.get("fields")
    if not isinstance(raw_fields, list) or not raw_fields:
        raise DesignerPlanError("platform list requires at least one field")

    fields = []
    ais_ids = set()
    source_ids = set()
    key_orders = set()
    for index, raw in enumerate(raw_fields):
        label = "platform-list field %d" % (index + 1)
        if not isinstance(raw, dict):
            raise DesignerPlanError("%s must be an object" % label)
        missing = [key for key in _FIELD_KEYS if key not in raw]
        if missing:
            raise DesignerPlanError(
                "%s requires explicit %s" % (label, ", ".join(missing))
            )
        ais_identifier = _required_text(raw, "aisFieldIdentifier", label)
        source_identifier = _required_text(
            raw, "listCustomizedFieldIdentifier", label
        )
        display_name = _required_text(raw, "displayName", label)
        value_type = _required_text(raw, "valueType", label)
        if value_type not in _SUPPORTED_VALUE_TYPES:
            raise DesignerPlanError(
                "%s valueType %r is not live-evidenced; supported values are %s"
                % (
                    label,
                    value_type,
                    ", ".join(sorted(_SUPPORTED_VALUE_TYPES)),
                )
            )
        value_identifier = raw.get("valueIdentifier")
        if value_identifier is not None and not isinstance(value_identifier, str):
            raise DesignerPlanError("%s valueIdentifier must be a string or null" % label)
        key_order = raw.get("keyOrder")
        if key_order is not None and (
            isinstance(key_order, bool)
            or not isinstance(key_order, int)
            or key_order < 0
        ):
            raise DesignerPlanError(
                "%s keyOrder must be a non-negative integer or null" % label
            )
        for key in ("exposeInWebService", "isRange"):
            if not isinstance(raw.get(key), bool):
                raise DesignerPlanError("%s %s must be boolean" % (label, key))
        if ais_identifier in ais_ids:
            raise DesignerPlanError(
                "duplicate aisFieldIdentifier %r" % ais_identifier
            )
        if source_identifier in source_ids:
            raise DesignerPlanError(
                "shared source %r cannot back two fields in one list"
                % source_identifier
            )
        if key_order is not None:
            if key_order in key_orders:
                raise DesignerPlanError("duplicate keyOrder %d" % key_order)
            key_orders.add(key_order)
        ais_ids.add(ais_identifier)
        source_ids.add(source_identifier)
        fields.append({
            "aisFieldIdentifier": ais_identifier,
            "listCustomizedFieldIdentifier": source_identifier,
            "displayName": display_name,
            "keyOrder": key_order,
            "valueType": value_type,
            "valueIdentifier": value_identifier,
            "exposeInWebService": raw["exposeInWebService"],
            "isRange": raw["isRange"],
        })
    if not key_orders:
        raise DesignerPlanError("platform list requires at least one key field")

    raw_options = specification.get("options", {})
    if raw_options is None:
        raw_options = {}
    if not isinstance(raw_options, dict):
        raise DesignerPlanError("platform-list options must be an object")
    allowed_options = {
        "aisConnectionIdentifier",
        "isFourEyeReviewEnabled",
        "isMultiTenantEnabled",
        "supportsTestValues",
        "listType",
        "nestedListsIdentifiers",
    }
    unknown_options = sorted(set(raw_options) - allowed_options)
    if unknown_options:
        raise DesignerPlanError(
            "unknown platform-list options: %s" % ", ".join(unknown_options)
        )
    options = {
        "aisConnectionIdentifier": str(
            raw_options.get("aisConnectionIdentifier") or ""
        ),
        "isFourEyeReviewEnabled": raw_options.get(
            "isFourEyeReviewEnabled", False
        ),
        "isMultiTenantEnabled": raw_options.get("isMultiTenantEnabled", False),
        "supportsTestValues": raw_options.get("supportsTestValues", False),
        "listType": str(raw_options.get("listType") or "RCMBased"),
        "nestedListsIdentifiers": list(
            raw_options.get("nestedListsIdentifiers") or []
        ),
    }
    for key in (
        "isFourEyeReviewEnabled",
        "isMultiTenantEnabled",
        "supportsTestValues",
    ):
        if not isinstance(options[key], bool):
            raise DesignerPlanError("platform-list option %s must be boolean" % key)
    if options["listType"] != "RCMBased":
        raise DesignerPlanError(
            "this increment supports only listType RCMBased"
        )
    if options["nestedListsIdentifiers"]:
        raise DesignerPlanError(
            "this increment does not support nested Platform Lists; nested designs "
            "require maximum depth 5, no self-cycle, child keys beginning with all "
            "parent keys in the same order, and supportsTestValues on parent/child"
        )

    field_ids = {field["aisFieldIdentifier"] for field in fields}
    key_fields = [
        field["aisFieldIdentifier"]
        for field in sorted(
            (item for item in fields if item["keyOrder"] is not None),
            key=lambda item: item["keyOrder"],
        )
    ]
    raw_items = specification.get("items", []) or []
    if not isinstance(raw_items, list):
        raise DesignerPlanError("platform-list items must be an array")
    if len(raw_items) > MAX_ITEM_MUTATIONS:
        raise DesignerPlanError(
            "platform-list items exceed the REST mutation limit of %s"
            % f"{MAX_ITEM_MUTATIONS:,}"
        )
    items = []
    item_keys = set()
    for index, raw in enumerate(raw_items):
        label = "platform-list item %d" % (index + 1)
        if not isinstance(raw, dict):
            raise DesignerPlanError("%s must be an object" % label)
        values = raw.get("values")
        if not isinstance(values, dict):
            raise DesignerPlanError("%s requires values object" % label)
        missing_values = sorted(field_ids - set(values))
        extra_values = sorted(set(values) - field_ids)
        if missing_values or extra_values:
            raise DesignerPlanError(
                "%s values must exactly match list fields; missing=%s extra=%s"
                % (label, missing_values, extra_values)
            )
        missing_keys = [key for key in key_fields if values.get(key) is None]
        if missing_keys:
            raise DesignerPlanError(
                "%s requires non-null key values for %s"
                % (label, ", ".join(missing_keys))
            )
        for field_identifier, value in values.items():
            if value is not None and not isinstance(
                value, (str, int, float, bool)
            ):
                raise DesignerPlanError(
                    "%s value for %s must be a JSON scalar or null"
                    % (label, field_identifier)
                )
        key_token = json.dumps(
            [values[key] for key in key_fields],
            separators=(",", ":"),
            ensure_ascii=False,
        )
        if key_token in item_keys:
            raise DesignerPlanError(
                "%s duplicates an earlier item key" % label
            )
        item_keys.add(key_token)
        item = {
            "values": {
                field["aisFieldIdentifier"]: values[field["aisFieldIdentifier"]]
                for field in fields
            },
        }
        if options["isFourEyeReviewEnabled"] and "active" not in raw:
            raise DesignerPlanError(
                "%s requires explicit active for a four-eye-review list" % label
            )
        if "active" in raw and not isinstance(raw["active"], bool):
            raise DesignerPlanError("%s active must be boolean" % label)
        item["active"] = raw.get("active", True)
        items.append(item)

    projected = {
        "identifier": identifier,
        "name": name,
        "description": str(specification.get("description") or ""),
        "fields": fields,
        "options": options,
        "items": items,
    }
    return projected


def _view_field(source_identifier: str, position: int) -> dict:
    return {
        "visible": True,
        "selectable": "YesSelected",
        "sortable": True,
        "filterable": True,
        "exportable": True,
        "fieldIdentifier": source_identifier,
        "rightToLeft": False,
        "alignment": "Left",
        "columnTitleTextWrapping": "Wrap",
        "columnDataTextWrapping": "Cut",
        "columnDisplayFormatterIdentifier": "escaped_string_renderer",
        "columnWidthUnit": "Pixel",
        "sortOrder": 0,
        "sortAscending": True,
        "columnWidth": 100,
        "displayOrder": position * 10,
    }


def build_platform_list_definition(specification: dict) -> dict:
    """Build the deterministic nested InternalList definition."""
    spec = normalize_platform_list_specification(specification)
    identifier = spec["identifier"]
    options = spec["options"]
    return {
        "identifier": identifier,
        "name": spec["name"],
        "description": spec["description"],
        "listView": {
            "id": -1,
            "identifier": "%s_view" % identifier,
            "name": "%s View" % spec["name"],
            "systemView": False,
            "displayOrder": -1,
            "visible": True,
            "group": "Platform Lists",
            "itemView": False,
            "description": spec["description"],
            "viewFields": [
                _view_field(field["listCustomizedFieldIdentifier"], position)
                for position, field in enumerate(spec["fields"])
            ],
        },
        "fields": [dict(field) for field in spec["fields"]],
        "aisConnectionIdentifier": options["aisConnectionIdentifier"],
        "isFourEyeReviewEnabled": options["isFourEyeReviewEnabled"],
        "isMultiTenantEnabled": options["isMultiTenantEnabled"],
        "supportsTestValues": options["supportsTestValues"],
        "listType": options["listType"],
        "nestedListsIdentidiers": [
            {"identifier": value}
            for value in options["nestedListsIdentifiers"]
        ],
    }


def _key_values(specification: dict, item: dict) -> dict:
    key_fields = sorted(
        (
            field for field in specification["fields"]
            if field["keyOrder"] is not None
        ),
        key=lambda field: field["keyOrder"],
    )
    return {
        field["aisFieldIdentifier"]: item["values"][field["aisFieldIdentifier"]]
        for field in key_fields
    }


def _read_item_matches(rest_registry, rest_client, specification: dict,
                       item: dict) -> dict:
    key_values = _key_values(specification, item)
    params = {
        "platformListIdentifier": specification["identifier"],
        **key_values,
    }
    try:
        result = invoke(
            rest_registry,
            rest_client,
            ITEM_READ_OPERATION,
            params=params,
        )
    except InvokeError as exc:
        return {
            "keyValues": key_values,
            "normalized": False,
            "error": str(exc),
            "items": [],
        }
    body = result.get("body") if isinstance(result, dict) else None
    if not result.get("ok") or not isinstance(body, list):
        return {
            "keyValues": key_values,
            "normalized": False,
            "error": (
                result.get("error")
                or "getFilteredListData did not return a JSON array"
            ),
            "items": [],
        }
    if len(body) > MAX_FILTERED_RESULTS:
        return {
            "keyValues": key_values,
            "normalized": False,
            "error": (
                "getFilteredListData exceeded the maximum normalized result "
                "count of %d" % MAX_FILTERED_RESULTS
            ),
            "items": [],
        }
    normalized = []
    for value in body:
        if not isinstance(value, dict) or not isinstance(value.get("values"), dict):
            return {
                "keyValues": key_values,
                "normalized": False,
                "error": "getFilteredListData returned an unrecognized item",
                "items": [],
            }
        candidate = {"values": dict(value["values"])}
        if "identifier" in value:
            identifier = str(value.get("identifier") or "").strip()
            if not identifier:
                return {
                    "keyValues": key_values,
                    "normalized": False,
                    "error": (
                        "getFilteredListData returned an invalid item identifier"
                    ),
                    "items": [],
                }
            candidate["identifier"] = identifier
        if "active" in value:
            if not isinstance(value["active"], bool):
                return {
                    "keyValues": key_values,
                    "normalized": False,
                    "error": "getFilteredListData returned non-boolean active",
                    "items": [],
                }
            candidate["active"] = value["active"]
        normalized.append(candidate)
    return {
        "keyValues": key_values,
        "normalized": True,
        "items": normalized,
    }


def collect_platform_list_observation(designer_client, rest_registry, rest_client,
                                      specification: dict) -> dict:
    """Read shared sources, the requested list definition, and matching items."""
    spec = normalize_platform_list_specification(specification)
    sources = _result_items(designer_client.get_object_list(SOURCE_TYPE))
    list_infos = _result_items(designer_client.get_object_info_list(DEFINITION_TYPE))
    present = spec["identifier"] in {
        identifier for item in list_infos
        if (identifier := _identifier(item))
    }
    definition = None
    if present:
        definition = (
            designer_client.get_object(DEFINITION_TYPE, spec["identifier"])
            .get("out")
        )
        if not isinstance(definition, dict):
            raise DesignerError(
                "InternalList %r read returned no object" % spec["identifier"]
            )
    item_matches = []
    for item in spec["items"]:
        if present:
            item_matches.append(
                _read_item_matches(rest_registry, rest_client, spec, item)
            )
        else:
            item_matches.append({
                "keyValues": _key_values(spec, item),
                "normalized": True,
                "listAbsent": True,
                "items": [],
            })
    return {
        "sharedSources": sources,
        "definition": definition,
        "itemMatches": item_matches,
    }


def _project_view_field(field: dict) -> dict:
    projected = {
        key: field.get(key)
        for key in _VIEW_FIELD_KEYS
    }
    for key in (
        "visible",
        "sortable",
        "filterable",
        "exportable",
        "rightToLeft",
        "sortAscending",
    ):
        projected[key] = _bool(projected[key])
    for key in ("sortOrder", "columnWidth", "displayOrder"):
        projected[key] = _int(projected[key])
    return projected


def _project_definition(definition: dict | None) -> dict | None:
    if not isinstance(definition, dict):
        return None
    info = definition.get("objectInfo")
    if not isinstance(info, dict):
        info = {}
    view = definition.get("listView")
    if not isinstance(view, dict):
        view = {}
    projected = {
        "identifier": info.get("identifier") or definition.get("identifier"),
        "name": info.get("name") or definition.get("name"),
        "description": info.get("description") or definition.get("description") or "",
        "fields": [
            {
                key: field.get(key)
                for key in _FIELD_KEYS
            }
            for field in _array(definition.get("fields"), "fields")
            if isinstance(field, dict)
        ],
        "options": {
            "aisConnectionIdentifier": definition.get("aisConnectionIdentifier") or "",
            "isFourEyeReviewEnabled": _bool(
                definition.get("isFourEyeReviewEnabled"), False
            ),
            "isMultiTenantEnabled": _bool(
                definition.get("isMultiTenantEnabled"), False
            ),
            "supportsTestValues": _bool(
                definition.get("supportsTestValues"), False
            ),
            "listType": definition.get("listType"),
            "nestedListsIdentidiers": [
                item.get("identifier") if isinstance(item, dict) else item
                for item in _array(
                    definition.get("nestedListsIdentidiers"),
                    "nestedListsIdentidiers",
                )
            ],
        },
        "listView": {
            "id": -1,
            "identifier": view.get("identifier"),
            "name": view.get("name"),
            "systemView": _bool(view.get("systemView"), False),
            "displayOrder": _int(view.get("displayOrder")),
            "visible": _bool(view.get("visible"), False),
            "group": view.get("group"),
            "itemView": _bool(view.get("itemView"), False),
            "description": view.get("description") or "",
            "viewFields": [
                _project_view_field(item)
                for item in _array(view.get("viewFields"), "viewFields")
                if isinstance(item, dict)
            ],
        },
    }
    for field in projected["fields"]:
        field["keyOrder"] = _int(field["keyOrder"])
        field["exposeInWebService"] = _bool(field["exposeInWebService"])
        field["isRange"] = _bool(field["isRange"])
    return projected


def _expected_projection(specification: dict) -> dict:
    definition = build_platform_list_definition(specification)
    return {
        "identifier": definition["identifier"],
        "name": definition["name"],
        "description": definition["description"],
        "fields": [dict(field) for field in definition["fields"]],
        "options": {
            "aisConnectionIdentifier": definition["aisConnectionIdentifier"],
            "isFourEyeReviewEnabled": definition["isFourEyeReviewEnabled"],
            "isMultiTenantEnabled": definition["isMultiTenantEnabled"],
            "supportsTestValues": definition["supportsTestValues"],
            "listType": definition["listType"],
            "nestedListsIdentidiers": [],
        },
        "listView": dict(definition["listView"]),
    }


def _routing() -> dict:
    return {
        "definition": {
            "adapter": "designer-soap",
            "service": "designerRepositoryService",
            "operation": "addObject",
            "type": DEFINITION_TYPE,
        },
        "itemsRead": {
            "adapter": "extend-rest",
            "operationId": ITEM_READ_OPERATION,
            "filter": (
                "dynamic field-name query parameters; the bundled OpenAPI "
                "filterFields parameter is synthetic"
            ),
            "documentation": FILTERED_READ_DOC_URL,
            "maxResults": MAX_FILTERED_RESULTS,
        },
        "itemsCreate": {
            "adapter": "extend-rest",
            "operationId": ITEM_CREATE_OPERATION,
            "maxItemsPerRequest": MAX_ITEM_MUTATIONS,
        },
        "itemsUpdate": {
            "adapter": "extend-rest",
            "operationId": ITEM_UPDATE_OPERATION,
            "enabled": True,
            "maxItemsPerRequest": MAX_ITEM_MUTATIONS,
            "requires": (
                "one normalized key match with a non-empty item identifier"
            ),
        },
    }


def plan_platform_list(specification: dict, observed: dict,
                       environment: str, target_build: str) -> dict:
    """Create a deterministic schema create/reuse plus REST item lifecycle plan."""
    spec = normalize_platform_list_specification(specification)
    changes = {
        "create": [],
        "reuse": [],
        "addItems": [],
        "updateItems": [],
        "conflict": [],
    }
    errors = []
    steps = []
    create_batch = []
    create_evidence = []
    update_batch = []
    update_evidence = []

    source_ids = {
        identifier for item in observed.get("sharedSources", []) or []
        if isinstance(item, dict) and (identifier := _identifier(item))
    }
    for field in spec["fields"]:
        source_identifier = field["listCustomizedFieldIdentifier"]
        if source_identifier not in source_ids:
            errors.append({
                "code": "source_missing",
                "field": field["aisFieldIdentifier"],
                "source": source_identifier,
                "message": (
                    "shared InternalListCustomizedField source does not exist"
                ),
            })

    definition = observed.get("definition")
    schema_step_id = None
    if definition is None:
        changes["create"].append({
            "type": DEFINITION_TYPE,
            "identifier": spec["identifier"],
        })
        schema_step_id = "platform-list.%s" % spec["identifier"]
        steps.append({
            "id": schema_step_id,
            "adapter": "designer-soap",
            "service": "designerRepositoryService",
            "operation": "addObject",
            "action": "create",
            "type": DEFINITION_TYPE,
            "identifier": spec["identifier"],
            "definition": build_platform_list_definition(spec),
            "dependsOn": [],
            "verification": ["complete InternalList schema equals desired definition"],
        })
    else:
        expected = _expected_projection(spec)
        actual = _project_definition(definition)
        if actual == expected:
            changes["reuse"].append({
                "type": DEFINITION_TYPE,
                "identifier": spec["identifier"],
            })
        else:
            changes["conflict"].append({
                "type": DEFINITION_TYPE,
                "identifier": spec["identifier"],
                "reason": (
                    "existing schema/options/key/order/source/valueType/view "
                    "differs; structural updates are not supported"
                ),
                "expected": expected,
                "actual": actual,
            })

    for index, item in enumerate(spec["items"]):
        match = (
            observed.get("itemMatches", [])[index]
            if index < len(observed.get("itemMatches", []))
            else None
        )
        key_values = _key_values(spec, item)
        if not isinstance(match, dict) or not match.get("normalized"):
            errors.append({
                "code": "item_read_not_normalized",
                "keyValues": key_values,
                "message": (
                    match.get("error")
                    if isinstance(match, dict)
                    else "missing getFilteredListData observation"
                ),
            })
            continue
        matches = match.get("items", [])
        if matches == []:
            changes["addItems"].append({
                "itemIndex": index,
                "keyValues": key_values,
                "item": item,
            })
            create_batch.append(item)
            create_evidence.append({
                "itemIndex": index,
                "keyValues": key_values,
                "assertion": (
                    "getFilteredListData returns exactly the desired item"
                ),
            })
        elif len(matches) == 1:
            existing_item = matches[0]
            existing_content = {
                key: existing_item[key]
                for key in ("values", "active")
                if key in existing_item
            }
            if existing_content == item:
                changes["reuse"].append({
                    "type": "PlatformListItem",
                    "keyValues": key_values,
                })
                continue
            actual_keys = {
                key: existing_item.get("values", {}).get(key)
                for key in key_values
            }
            item_identifier = existing_item.get("identifier")
            if actual_keys != key_values or not item_identifier:
                changes["conflict"].append({
                    "type": "PlatformListItem",
                    "keyValues": key_values,
                    "reason": (
                        "existing item differs but getFilteredListData did not "
                        "provide one reliable identifier with the exact key"
                    ),
                    "matches": matches,
                })
                continue
            update_body = {
                "identifier": item_identifier,
                **item,
            }
            changes["updateItems"].append({
                "itemIndex": index,
                "keyValues": key_values,
                "item": update_body,
            })
            update_batch.append(update_body)
            update_evidence.append({
                "itemIndex": index,
                "keyValues": key_values,
                "assertion": (
                    "getFilteredListData returns exactly the desired item"
                ),
            })
        else:
            changes["conflict"].append({
                "type": "PlatformListItem",
                "keyValues": key_values,
                "reason": (
                    "existing key match is ambiguous; item mutation is unsafe"
                ),
                "matches": matches,
            })

    if not errors and not changes["conflict"]:
        create_step_id = None
        if create_batch:
            create_step_id = "platform-list-items.create"
            steps.append({
                "id": create_step_id,
                "adapter": "extend-rest",
                "operationId": ITEM_CREATE_OPERATION,
                "action": "create",
                "identifier": spec["identifier"],
                "body": create_batch,
                "dependsOn": [schema_step_id] if schema_step_id else [],
                "verification": create_evidence,
            })
        if update_batch:
            update_dependencies = []
            if schema_step_id:
                update_dependencies.append(schema_step_id)
            if create_step_id:
                update_dependencies.append(create_step_id)
            steps.append({
                "id": "platform-list-items.update",
                "adapter": "extend-rest",
                "operationId": ITEM_UPDATE_OPERATION,
                "action": "update",
                "identifier": spec["identifier"],
                "body": update_batch,
                "dependsOn": update_dependencies,
                "verification": update_evidence,
            })
    else:
        steps = []
    observation_fingerprint = fingerprint_observation(observed)
    plan = {
        "capability": CAPABILITY_ID,
        "environment": environment,
        "targetBuild": target_build,
        "specification": spec,
        "observationFingerprint": observation_fingerprint,
        "applicable": not errors and not changes["conflict"],
        "routing": _routing(),
        "changes": changes,
        "steps": steps,
        "errors": errors,
    }
    fingerprint = fingerprint_plan(plan)
    return {
        "planId": fingerprint[:16],
        "fingerprint": fingerprint,
        **plan,
        "warnings": [
            "Shared InternalListCustomizedField sources are reused, never created.",
            "Definition updates/removals and item removals are blocked.",
            (
                "REST limits: at most 25,000 creates/updates per request and "
                "500,000 filtered results."
            ),
        ],
    }


def _assertion(assertions: list, name: str, expected, actual) -> None:
    assertions.append({
        "name": name,
        "passed": expected == actual,
        "expected": expected,
        "actual": actual,
    })


def verify_platform_list(plan: dict, designer_client, rest_registry,
                         rest_client) -> dict:
    """Verify the complete list definition and every desired item."""
    spec = normalize_platform_list_specification(plan["specification"])
    assertions = []
    definition_result = designer_client.get_object(
        DEFINITION_TYPE, spec["identifier"]
    )
    actual_definition = _project_definition(definition_result.get("out"))
    _assertion(
        assertions,
        "platform-list.definition",
        _expected_projection(spec),
        actual_definition,
    )
    for index, item in enumerate(spec["items"]):
        match = _read_item_matches(rest_registry, rest_client, spec, item)
        actual = (
            [
                {
                    key: candidate[key]
                    for key in ("values", "active")
                    if key in candidate
                }
                for candidate in match.get("items", [])
            ]
            if match.get("normalized") else None
        )
        _assertion(
            assertions,
            "platform-list.item.%04d" % index,
            [item],
            actual,
        )
    failures = [item for item in assertions if not item["passed"]]
    return {
        "ok": not failures,
        "assertions": assertions,
        "failures": failures,
    }


def apply_platform_list_plan(plan: dict, designer_client, rest_registry,
                             rest_client, current_observed: dict) -> dict:
    """Apply an intact plan: SOAP definition first, then REST item mutations."""
    if plan.get("capability") != CAPABILITY_ID:
        return {"ok": False, "error": "unsupported_capability"}
    if fingerprint_plan(plan) != plan.get("fingerprint"):
        return {
            "ok": False,
            "error": "plan_tampered",
            "planId": plan.get("planId"),
        }
    current_fingerprint = fingerprint_observation(current_observed)
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
    conflicts = plan.get("changes", {}).get("conflict", [])
    errors = plan.get("errors", [])
    if not plan.get("applicable") or errors or conflicts:
        return {
            "ok": False,
            "error": "plan_not_applicable",
            "planId": plan.get("planId"),
            "errors": errors,
            "conflicts": conflicts,
        }
    try:
        ordered_steps = validated_step_order(plan.get("steps", []))
    except PlanDependencyError as exc:
        return {
            "ok": False,
            "error": "invalid_step_dependencies",
            "planId": plan.get("planId"),
            "message": str(exc),
        }

    completed = []
    for step in ordered_steps:
        try:
            if step.get("adapter") == "designer-soap":
                result = designer_client.create_object(
                    DEFINITION_TYPE, step["definition"]
                )
            elif (
                step.get("adapter") == "extend-rest"
                and step.get("operationId") in {
                    ITEM_CREATE_OPERATION,
                    ITEM_UPDATE_OPERATION,
                }
            ):
                operation_id = step["operationId"]
                result = invoke(
                    rest_registry,
                    rest_client,
                    operation_id,
                    params={
                        "platformListIdentifier": step["identifier"],
                        "body": step["body"],
                    },
                    allow_write=True,
                )
                if not result.get("ok"):
                    raise InvokeError(
                        result.get("error")
                        or "%s returned an unsuccessful response" % operation_id
                    )
            else:
                raise ValueError("unsupported Platform List step route")
        except (DesignerError, InvokeError, ValueError, KeyError, TypeError) as exc:
            return {
                "ok": False,
                "error": "step_failed",
                "planId": plan.get("planId"),
                "failedStep": step.get("id"),
                "message": str(exc),
                "completedSteps": completed,
            }
        completed.append({"id": step["id"], "result": result})

    try:
        verification = verify_platform_list(
            plan, designer_client, rest_registry, rest_client
        )
    except (DesignerError, InvokeError, ValueError, KeyError, TypeError) as exc:
        return {
            "ok": False,
            "error": "verification_failed",
            "planId": plan.get("planId"),
            "message": str(exc),
            "completedSteps": completed,
        }
    if not verification["ok"]:
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
