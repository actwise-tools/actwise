"""Pure read-only state normalization for Designer capabilities."""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping


_CAPABILITY = "create_work_item_type"
_ORDERED_LIST_KEYS = {
    "alertTypeFields",
    "customFields",
    "fields",
    "viewFields",
}
_SAFE_PATH_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_INTERNAL_ID = re.compile(r"^(?:-?\d+|id\d+)$", re.IGNORECASE)

__all__ = [
    "diff_documents",
    "export_capability_state",
    "fingerprint_document",
    "normalize_capability_specification",
    "sanitize_transport",
]


def sanitize_transport(value):
    """Remove SOAP and session plumbing without changing semantic list order."""
    if isinstance(value, Mapping):
        sanitized = {}
        multi_refs = []
        for key in sorted(value, key=str):
            item = value[key]
            normalized_key = re.sub(r"[^a-z0-9]", "", str(key).lower())
            if str(key) == "@type":
                continue
            if normalized_key == "id" and _is_internal_id(item):
                continue
            if normalized_key == "href":
                continue
            if normalized_key.startswith("session"):
                continue
            if "cookie" in normalized_key:
                continue
            if normalized_key.startswith("multiref"):
                multi_refs.append(sanitize_transport(item))
                continue
            sanitized[key] = sanitize_transport(item)
        if not sanitized and len(multi_refs) == 1:
            return multi_refs[0]
        return sanitized
    if isinstance(value, (list, tuple)):
        return [sanitize_transport(item) for item in value]
    return value


def fingerprint_document(value) -> str:
    """Return a stable SHA-256 fingerprint for a logical JSON document."""
    canonical = _canonicalize(sanitize_transport(value))
    encoded = json.dumps(
        canonical,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def diff_documents(left, right) -> dict:
    """Return deterministic JSONPath lists for two logical documents."""
    left_value = _canonicalize(sanitize_transport(left))
    right_value = _canonicalize(sanitize_transport(right))
    added: list[str] = []
    removed: list[str] = []
    changed: list[str] = []
    _diff(left_value, right_value, "$", added, removed, changed)
    return {
        "equal": not (added or removed or changed),
        "added": sorted(added),
        "removed": sorted(removed),
        "changed": sorted(changed),
    }


def normalize_capability_specification(
    capability_id: str,
    specification: dict,
) -> dict:
    """Normalize the logical specification for a supported capability."""
    _require_supported(capability_id)
    spec = _require_mapping(specification, "work-item specification")
    identifier = _require_identifier(spec, "work-item type")

    fields = _require_list(spec.get("customFields", []), "customFields")
    normalized_fields = [
        _normalize_custom_field(field) for field in fields
    ]
    _require_unique_identifiers(normalized_fields, "custom field")

    workflow = _require_mapping(spec.get("workflow"), "workflow")
    normalized_workflow = _normalize_workflow(workflow)

    view = _require_mapping(spec.get("view"), "view")
    normalized_view = _normalize_view(view, identifier)

    result = {
        "identifier": identifier,
        "name": str(spec.get("name") or identifier),
        "description": str(spec.get("description") or ""),
        "methodId": _integer(spec.get("methodId", 4), "methodId"),
        "supportManualAlerts": bool(spec.get("supportManualAlerts", False)),
        "category": str(spec.get("category") or "Alerts"),
        "viewType": str(spec.get("viewType") or "tabular"),
        "defaultView": str(spec.get("defaultView") or "tabular"),
        "customFields": normalized_fields,
        "workflow": normalized_workflow,
        "view": normalized_view,
    }
    if "enabledForGlobalSearch" in spec:
        result["enabledForGlobalSearch"] = bool(
            spec["enabledForGlobalSearch"]
        )
    return result


def export_capability_state(
    capability_id: str,
    specification: dict,
    observed: dict,
) -> dict:
    """Export hydrated observed state selected by a capability specification."""
    _require_supported(capability_id)
    selector = _ownership_selector(specification)
    state = _require_mapping(observed, "observed state")

    alert_type = _select_owned(
        state, "AlertType", selector["workItemType"]
    )
    workflow = _select_owned(
        state, "AlertStatusWorkflowDefinition", selector["workflow"]
    )
    view = _select_owned(state, "AlertView", selector["view"])

    workflow_reference = _string_value(
        alert_type, "alertStatusWorkflowDefinitionIdentifier"
    )
    if workflow_reference != selector["workflow"]:
        raise ValueError(
            "Owned AlertType %r references workflow %r, not %r"
            % (
                selector["workItemType"],
                workflow_reference,
                selector["workflow"],
            )
        )

    _require_hydrated_key(
        alert_type, "alertTypeFields", "AlertType", selector["workItemType"]
    )
    assignments = _as_list(alert_type["alertTypeFields"], "alertTypeFields")
    assignment_ids = [
        _require_text(
            assignment.get("customizedFieldIdentifier")
            if isinstance(assignment, Mapping) else None,
            "AlertType field assignment requires customizedFieldIdentifier",
        )
        for assignment in assignments
    ]
    _require_exact_owned(
        "AlertType field assignments",
        assignment_ids,
        selector["customFields"],
    )

    custom_fields = {
        identifier: _select_owned(state, "AlertCustomizedField", identifier)
        for identifier in selector["customFields"]
    }
    physical_fields = _physical_fields_by_id(state)
    field_specs = []
    for assignment, identifier in zip(assignments, assignment_ids):
        custom_field = custom_fields[identifier]
        field_id = _field_id(custom_field)
        sources = physical_fields.get(field_id, [])
        if not sources:
            raise ValueError(
                "Physical field for owned AlertCustomizedField %r "
                "(fieldId %r) is absent" % (identifier, field_id)
            )
        if len(sources) != 1:
            raise ValueError(
                "Physical fieldId %r for owned AlertCustomizedField %r "
                "is ambiguous (%d matches)"
                % (field_id, identifier, len(sources))
            )
        source = sources[0]
        if source.get("dataType") in (None, ""):
            raise ValueError(
                "Physical fieldId %r for owned AlertCustomizedField %r "
                "is missing dataType" % (field_id, identifier)
            )
        if source.get("fieldSize") in (None, ""):
            raise ValueError(
                "Physical fieldId %r for owned AlertCustomizedField %r "
                "is missing fieldSize" % (field_id, identifier)
            )
        field_specs.append({
            "identifier": identifier,
            "label": _string_value(custom_field, "name") or identifier,
            "description": _string_value(custom_field, "description") or "",
            "dataType": str(source["dataType"]).lower(),
            "length": _integer(source["fieldSize"], "fieldSize"),
            "range": bool(custom_field.get("range", False)),
            "mandatory": bool(assignment.get("mandatory", False)),
            "updateMode": str(assignment.get("updatable") or "Updatable"),
            "isCachable": bool(assignment.get("isCachable", False)),
        })

    workflow_spec = _export_workflow(state, workflow, selector)
    view_spec = _export_view(view, selector["workItemType"])
    logical_specification = {
        "identifier": selector["workItemType"],
        "name": _string_value(alert_type, "name")
        or selector["workItemType"],
        "description": _string_value(alert_type, "description") or "",
        "methodId": alert_type.get("methodId", 4),
        "supportManualAlerts": alert_type.get(
            "supportManualAlerts", False
        ),
        "category": alert_type.get(
            "category", alert_type.get("wiCatagory", "Alerts")
        ),
        "viewType": alert_type.get("viewType", "tabular"),
        "defaultView": alert_type.get("defaultView", "tabular"),
        "customFields": field_specs,
        "workflow": workflow_spec,
        "view": view_spec,
    }
    if "enabledForGlobalSearch" in alert_type:
        logical_specification["enabledForGlobalSearch"] = (
            alert_type["enabledForGlobalSearch"]
        )
    normalized = normalize_capability_specification(
        capability_id, logical_specification
    )
    document = {
        "schemaVersion": 1,
        "capability": capability_id,
        "specification": normalized,
    }
    return {**document, "fingerprint": fingerprint_document(document)}


def _canonicalize(value, parent_key: str | None = None):
    if isinstance(value, Mapping):
        return {
            key: _canonicalize(value[key], str(key))
            for key in sorted(value, key=str)
        }
    if isinstance(value, list):
        items = [_canonicalize(item) for item in value]
        if parent_key not in _ORDERED_LIST_KEYS:
            items.sort(key=_canonical_json)
        return items
    return value


def _canonical_json(value) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _diff(left, right, path, added, removed, changed) -> None:
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        left_keys = set(left)
        right_keys = set(right)
        for key in sorted(right_keys - left_keys, key=str):
            added.append(_path_key(path, key))
        for key in sorted(left_keys - right_keys, key=str):
            removed.append(_path_key(path, key))
        for key in sorted(left_keys & right_keys, key=str):
            _diff(
                left[key],
                right[key],
                _path_key(path, key),
                added,
                removed,
                changed,
            )
        return
    if isinstance(left, list) and isinstance(right, list):
        common = min(len(left), len(right))
        for index in range(common):
            _diff(
                left[index],
                right[index],
                f"{path}[{index}]",
                added,
                removed,
                changed,
            )
        added.extend(
            f"{path}[{index}]" for index in range(common, len(right))
        )
        removed.extend(
            f"{path}[{index}]" for index in range(common, len(left))
        )
        return
    if left != right:
        changed.append(path)


def _path_key(path: str, key) -> str:
    text = str(key)
    if _SAFE_PATH_KEY.fullmatch(text):
        return f"{path}.{text}"
    return f"{path}[{json.dumps(text, ensure_ascii=False)}]"


def _is_internal_id(value) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    return isinstance(value, str) and bool(_INTERNAL_ID.fullmatch(value.strip()))


def _require_supported(capability_id: str) -> None:
    if capability_id != _CAPABILITY:
        raise ValueError(
            "Unsupported Designer state capability %r; supported capability is %r"
            % (capability_id, _CAPABILITY)
        )


def _require_mapping(value, label: str) -> Mapping:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def _require_list(value, label: str) -> list:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be an array")
    return value


def _require_text(value, message: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(message)
    return text


def _require_identifier(value: Mapping, label: str) -> str:
    return _require_text(
        value.get("identifier"), f"{label} requires identifier"
    )


def _require_unique_identifiers(items: list[dict], label: str) -> None:
    identifiers = [item["identifier"] for item in items]
    duplicate = next(
        (
            identifier
            for identifier in identifiers
            if identifiers.count(identifier) > 1
        ),
        None,
    )
    if duplicate:
        raise ValueError(f"Duplicate {label} identifier {duplicate!r}")


def _integer(value, label: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be an integer") from exc


def _display_name(identifier: str) -> str:
    return identifier.replace("_", " ").replace("-", " ").title()


def _normalize_custom_field(value) -> dict:
    field = _require_mapping(value, "custom field")
    identifier = _require_identifier(field, "custom field")
    data_type = str(field.get("dataType") or "string").lower()
    if data_type != "string":
        raise ValueError(
            "custom field %r requires supported dataType 'string'"
            % identifier
        )
    length = _integer(field.get("length"), f"custom field {identifier!r} length")
    if length <= 0:
        raise ValueError(
            "custom field %r length must be positive" % identifier
        )
    return {
        "identifier": identifier,
        "label": str(field.get("label") or field.get("name") or identifier),
        "description": str(field.get("description") or ""),
        "dataType": data_type,
        "length": length,
        "range": bool(field.get("range", False)),
        "mandatory": bool(field.get("mandatory", False)),
        "updateMode": str(
            field.get("updateMode") or field.get("updatable") or "Updatable"
        ),
        "isCachable": bool(field.get("isCachable", False)),
    }


def _normalize_workflow(value: Mapping) -> dict:
    identifier = _require_identifier(value, "workflow")
    statuses = [
        _normalize_status(status)
        for status in _require_list(value.get("statuses"), "workflow statuses")
    ]
    if not statuses:
        raise ValueError("workflow requires statuses")
    _require_unique_identifiers(statuses, "workflow status")
    starts = [status["identifier"] for status in statuses if status["start"]]
    if len(starts) != 1:
        raise ValueError("workflow requires exactly one start status")
    statuses.sort(key=lambda status: status["identifier"])
    known = {status["identifier"] for status in statuses}

    transitions = []
    for raw_transition in _require_list(
        value.get("transitions", []), "workflow transitions"
    ):
        transition = _require_mapping(raw_transition, "workflow transition")
        source = _require_text(
            transition.get("from"), "workflow transition requires from"
        )
        target = _require_text(
            transition.get("to"), "workflow transition requires to"
        )
        if source not in known or target not in known:
            raise ValueError(
                "workflow transition %r -> %r references an unknown status"
                % (source, target)
            )
        transitions.append({
            "from": source,
            "to": target,
            "name": str(transition.get("name") or "Transition"),
            "description": str(transition.get("description") or ""),
        })
    transitions.sort(
        key=lambda item: (
            item["from"],
            item["to"],
            item["name"],
            item["description"],
        )
    )
    return {
        "identifier": identifier,
        "name": str(value.get("name") or _display_name(identifier)),
        "description": str(value.get("description") or ""),
        "statuses": statuses,
        "transitions": transitions,
    }


def _normalize_status(value) -> dict:
    status = _require_mapping(value, "workflow status")
    identifier = _require_identifier(status, "workflow status")
    state = str(status.get("state") or "")
    if state == "InProcess":
        state = "Open"
    if not state:
        raise ValueError("workflow status %r requires state" % identifier)
    issue = status.get("issue")
    if issue in (None, "") and state == "Open":
        issue = "No_Determination"
    if issue in (None, "") and state == "Closed":
        raise ValueError(
            "closed workflow status %r requires issue" % identifier
        )
    result = {
        "identifier": identifier,
        "name": str(status.get("name") or _display_name(identifier)),
        "description": str(status.get("description") or ""),
        "state": state,
        "start": bool(status.get("start", False)),
        "deletable": bool(status.get("deletable", True)),
        "scope": str(status.get("scope") or "All"),
    }
    if issue not in (None, ""):
        result["issue"] = str(issue)
    return result


def _normalize_view(value: Mapping, work_item_type: str) -> dict:
    identifier = _require_identifier(value, "view")
    fields = [
        _normalize_view_field(field, position)
        for position, field in enumerate(
            _require_list(value.get("fields", []), "view fields")
        )
    ]
    field_ids = [field["identifier"] for field in fields]
    if len(field_ids) != len(set(field_ids)):
        duplicate = next(
            item for item in field_ids if field_ids.count(item) > 1
        )
        raise ValueError(f"Duplicate view field identifier {duplicate!r}")

    filters = _require_mapping(value.get("filters", {}), "view filters")
    normalized_filters = {
        str(key): str(item) for key, item in filters.items()
    }
    selected_type = normalized_filters.pop("alertTypeIdentifier", None)
    if selected_type is not None and selected_type != work_item_type:
        raise ValueError(
            "view alertTypeIdentifier %r does not match work-item type %r"
            % (selected_type, work_item_type)
        )
    normalized_filters.setdefault("alertArchive", "0")
    normalized_filters.setdefault("deleted", "0")
    normalized_filters = dict(sorted(normalized_filters.items()))
    return {
        "identifier": identifier,
        "name": str(value.get("name") or _display_name(identifier)),
        "description": str(value.get("description") or ""),
        "displayOrder": _integer(
            value.get("displayOrder", -1), "view displayOrder"
        ),
        "visible": bool(value.get("visible", True)),
        "group": str(value.get("group") or "Work Items"),
        "itemView": bool(value.get("itemView", False)),
        "fields": fields,
        "filters": normalized_filters,
    }


def _normalize_view_field(value, position: int) -> dict:
    field = (
        {"identifier": value}
        if isinstance(value, str)
        else _require_mapping(value, "view field")
    )
    identifier = _require_text(
        field.get("identifier") or field.get("fieldIdentifier"),
        "view field requires identifier",
    )
    renderers = {
        "alertId": "alert_details_link_renderer",
        "statusState": "state_icon_renderer",
        "statusId": "issue_icon_renderer",
        "alertDate": "date_renderer",
        "score": "score_renderer",
    }
    widths = {
        "alertId": 70,
        "statusState": 15,
        "statusId": 15,
        "score": 60,
    }
    return {
        "identifier": identifier,
        "visible": bool(field.get("visible", True)),
        "selectable": str(field.get("selectable") or "YesSelected"),
        "sortable": bool(field.get("sortable", True)),
        "filterable": bool(field.get("filterable", True)),
        "exportable": bool(field.get("exportable", True)),
        "rightToLeft": bool(field.get("rightToLeft", False)),
        "alignment": str(field.get("alignment") or "Left"),
        "columnTitleTextWrapping": str(
            field.get("columnTitleTextWrapping") or "Wrap"
        ),
        "columnDataTextWrapping": str(
            field.get("columnDataTextWrapping") or "Cut"
        ),
        "columnDisplayFormatterIdentifier": str(
            field.get("columnDisplayFormatterIdentifier")
            or renderers.get(identifier, "escaped_string_renderer")
        ),
        "columnWidthUnit": str(field.get("columnWidthUnit") or "Pixel"),
        "sortOrder": _integer(field.get("sortOrder", 0), "view field sortOrder"),
        "sortAscending": bool(field.get("sortAscending", True)),
        "columnWidth": _integer(
            field.get("columnWidth", widths.get(identifier, 100)),
            "view field columnWidth",
        ),
        "displayOrder": _integer(
            field.get("displayOrder", position * 10),
            "view field displayOrder",
        ),
    }


def _ownership_selector(specification) -> dict:
    spec = _require_mapping(specification, "work-item specification")
    workflow = _require_mapping(spec.get("workflow"), "workflow")
    view = _require_mapping(spec.get("view"), "view")
    custom_fields = [
        _require_identifier(
            _require_mapping(field, "custom field"), "custom field"
        )
        for field in _require_list(spec.get("customFields", []), "customFields")
    ]
    statuses = [
        _require_identifier(
            _require_mapping(status, "workflow status"), "workflow status"
        )
        for status in _require_list(
            workflow.get("statuses"), "workflow statuses"
        )
    ]
    if not statuses:
        raise ValueError("workflow requires statuses")
    for values, label in (
        (custom_fields, "custom field"),
        (statuses, "workflow status"),
    ):
        if len(values) != len(set(values)):
            duplicate = next(item for item in values if values.count(item) > 1)
            raise ValueError(f"Duplicate {label} identifier {duplicate!r}")
    return {
        "workItemType": _require_identifier(spec, "work-item type"),
        "workflow": _require_identifier(workflow, "workflow"),
        "view": _require_identifier(view, "view"),
        "customFields": custom_fields,
        "statuses": statuses,
    }


def _select_owned(observed: Mapping, type_value: str, identifier: str) -> Mapping:
    items = _as_list(observed.get(type_value), type_value)
    matches = [
        item
        for item in items
        if isinstance(item, Mapping) and _object_identifier(item) == identifier
    ]
    if not matches:
        raise ValueError(
            "Required owned %s %r is absent from hydrated observed state"
            % (type_value, identifier)
        )
    if len(matches) != 1:
        raise ValueError(
            "Required owned %s %r is ambiguous (%d matches)"
            % (type_value, identifier, len(matches))
        )
    return matches[0]


def _object_identifier(value: Mapping) -> str | None:
    object_info = value.get("objectInfo")
    candidates = (
        object_info.get("identifier")
        if isinstance(object_info, Mapping) else None,
        value.get("identifier"),
        value.get("statusIdentifier"),
    )
    return next(
        (str(item) for item in candidates if item not in (None, "")),
        None,
    )


def _string_value(value: Mapping, key: str) -> str | None:
    item = value.get(key)
    if item in (None, ""):
        object_info = value.get("objectInfo")
        if isinstance(object_info, Mapping):
            item = object_info.get(key)
    return None if item in (None, "") else str(item)


def _require_hydrated_key(
    value: Mapping,
    key: str,
    type_value: str,
    identifier: str,
) -> None:
    if key not in value:
        raise ValueError(
            "Required owned %s %r is not hydrated: missing %s"
            % (type_value, identifier, key)
        )


def _as_list(value, wrapper_key: str | None = None) -> list:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, Mapping):
        if wrapper_key and wrapper_key in value:
            return _as_list(value[wrapper_key])
        candidates = [
            item
            for key, item in value.items()
            if key != "@type" and not _is_transport_key(key, item)
        ]
        if len(candidates) == 1:
            return _as_list(candidates[0])
        return [value]
    return [value]


def _is_transport_key(key, value) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
    return (
        normalized == "href"
        or normalized.startswith("multiref")
        or normalized.startswith("session")
        or "cookie" in normalized
        or (normalized == "id" and _is_internal_id(value))
    )


def _field_id(value: Mapping) -> str:
    field_id = value.get("fieldId")
    if field_id in (None, ""):
        raise ValueError(
            "Owned AlertCustomizedField %r is missing fieldId"
            % _object_identifier(value)
        )
    return str(field_id)


def _physical_fields_by_id(observed: Mapping) -> dict[str, list[Mapping]]:
    result: dict[str, list[Mapping]] = {}
    for field in _as_list(observed.get("physicalFields"), "physicalFields"):
        if not isinstance(field, Mapping) or field.get("fieldId") in (None, ""):
            continue
        result.setdefault(str(field["fieldId"]), []).append(field)
    return result


def _require_exact_owned(label: str, actual: list[str], owned: list[str]) -> None:
    if len(actual) != len(set(actual)):
        duplicate = next(item for item in actual if actual.count(item) > 1)
        raise ValueError(f"{label} contain duplicate identifier {duplicate!r}")
    if set(actual) != set(owned):
        missing = sorted(set(owned) - set(actual))
        unexpected = sorted(set(actual) - set(owned))
        raise ValueError(
            "%s do not match specification ownership "
            "(missing=%r, unexpected=%r)" % (label, missing, unexpected)
        )


def _export_workflow(
    observed: Mapping,
    workflow: Mapping,
    selector: dict,
) -> dict:
    _require_hydrated_key(
        workflow, "nodes", "AlertStatusWorkflowDefinition", selector["workflow"]
    )
    _require_hydrated_key(
        workflow,
        "defaultStartNode",
        "AlertStatusWorkflowDefinition",
        selector["workflow"],
    )
    nodes = _as_list(workflow.get("nodes"), "nodes")
    node_by_status: dict[str, Mapping] = {}
    for node in nodes:
        if not isinstance(node, Mapping):
            continue
        status_id = _require_text(
            node.get("statusIdentifier"),
            "Workflow node requires statusIdentifier",
        )
        if status_id in node_by_status:
            raise ValueError(
                "Owned workflow %r has ambiguous node for status %r"
                % (selector["workflow"], status_id)
            )
        node_by_status[status_id] = node
    _require_exact_owned(
        "Workflow nodes", list(node_by_status), selector["statuses"]
    )

    start = workflow.get("defaultStartNode")
    start_id = (
        start.get("statusIdentifier")
        if isinstance(start, Mapping) else None
    )
    start_id = _require_text(
        start_id,
        "Owned workflow %r is missing hydrated defaultStartNode"
        % selector["workflow"],
    )
    if start_id not in node_by_status:
        raise ValueError(
            "Owned workflow %r start status %r is not an owned node"
            % (selector["workflow"], start_id)
        )

    statuses = []
    for status_id in selector["statuses"]:
        status = _select_owned(observed, "AlertStatus", status_id)
        statuses.append({
            "identifier": status_id,
            "name": _string_value(status, "name") or _display_name(status_id),
            "description": _string_value(status, "description") or "",
            "state": _require_text(
                status.get("state"),
                "Owned AlertStatus %r is missing state" % status_id,
            ),
            "issue": status.get("issue"),
            "start": status_id == start_id,
            "deletable": status.get("deletable", True),
            "scope": status.get("scope", "All"),
        })

    transitions = []
    for source_id, node in node_by_status.items():
        for transition in _as_list(
            node.get("outgoingTransitions"), "outgoingTransitions"
        ):
            transition = _require_mapping(
                transition, "workflow transition"
            )
            target = transition.get("targetNode")
            target_id = (
                target.get("statusIdentifier")
                if isinstance(target, Mapping) else None
            )
            target_id = _require_text(
                target_id,
                "Workflow transition from %r requires hydrated targetNode"
                % source_id,
            )
            transitions.append({
                "from": source_id,
                "to": target_id,
                "name": str(transition.get("name") or "Transition"),
                "description": str(transition.get("description") or ""),
            })
    return {
        "identifier": selector["workflow"],
        "name": _string_value(workflow, "name")
        or _display_name(selector["workflow"]),
        "description": _string_value(workflow, "description") or "",
        "statuses": statuses,
        "transitions": transitions,
    }


def _export_view(view: Mapping, work_item_type: str) -> dict:
    identifier = str(_object_identifier(view))
    _require_hydrated_key(view, "viewFields", "AlertView", identifier)
    if "filterPairs" not in view and "filter" not in view:
        raise ValueError(
            "Required owned AlertView %r is not hydrated: missing filter"
            % identifier
        )
    filter_pairs = _view_filter_pairs(view)
    type_filter = filter_pairs.pop("alertTypeIdentifier", None)
    if type_filter != work_item_type:
        raise ValueError(
            "Owned AlertView %r must have alertTypeIdentifier filter %r; "
            "observed %r"
            % (_object_identifier(view), work_item_type, type_filter)
        )
    return {
        "identifier": identifier,
        "name": _string_value(view, "name")
        or _display_name(str(_object_identifier(view))),
        "description": _string_value(view, "description") or "",
        "displayOrder": view.get("displayOrder", -1),
        "visible": view.get("visible", True),
        "group": view.get("group", "Work Items"),
        "itemView": view.get("itemView", False),
        "fields": [
            dict(field)
            for field in _as_list(view.get("viewFields"), "viewFields")
            if isinstance(field, Mapping)
        ],
        "filters": filter_pairs,
    }


def _view_filter_pairs(view: Mapping) -> dict[str, str]:
    pairs = []
    raw_pairs = view.get("filterPairs")
    if isinstance(raw_pairs, list):
        for pair in raw_pairs:
            if isinstance(pair, (list, tuple)) and len(pair) == 2:
                pairs.append((str(pair[0]), str(pair[1])))
            elif isinstance(pair, Mapping):
                key = pair.get("field") or pair.get("identifier")
                if key is not None and "value" in pair:
                    pairs.append((str(key), str(pair["value"])))
    else:
        filter_value = view.get("filter")
        sub_filters = (
            filter_value.get("subFilters")
            if isinstance(filter_value, Mapping) else None
        )
        for comparison in _as_list(sub_filters, "subFilters"):
            if not isinstance(comparison, Mapping):
                continue
            field = None
            item_value = None
            for term in _as_list(comparison.get("terms"), "terms"):
                if not isinstance(term, Mapping):
                    continue
                if term.get("customizedFieldIdentifier") not in (None, ""):
                    field = str(term["customizedFieldIdentifier"])
                if "value" in term:
                    item_value = str(term["value"])
            if field is not None and item_value is not None:
                pairs.append((field, item_value))
    result = {}
    for key, item in pairs:
        if key in result and result[key] != item:
            raise ValueError(
                "Owned AlertView %r has ambiguous values for filter %r"
                % (_object_identifier(view), key)
            )
        result[key] = item
    return result
