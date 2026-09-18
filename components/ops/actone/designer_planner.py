"""Read-only capability planning for ActOne Designer authoring."""
from __future__ import annotations

import hashlib
import json
from xml.sax.saxutils import escape

from actone.designer import DesignerError


class DesignerPlanError(ValueError):
    """The requested specification cannot be converted into a safe plan."""


def _result_items(result: dict) -> list[dict]:
    out = result.get("out") if isinstance(result, dict) else None
    if out is None:
        return []
    if isinstance(out, list):
        return [item for item in out if isinstance(item, dict)]
    if isinstance(out, dict):
        for key in (
            "item",
            "fieldList",
            "objectArray",
            "objectInfoArray",
            "alertStatusList",
            "alertTypeList",
            "viewInfoList",
        ):
            value = out.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
            if isinstance(value, dict):
                return [value]
        values = [value for key, value in out.items() if key != "@type"]
        if len(values) == 1:
            value = values[0]
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
            if isinstance(value, dict):
                return [value]
        return [out]
    return []


def collect_work_item_observation(designer_client, specification: dict | None = None,
                                  alert_type_usage: dict | None = None) -> dict:
    """Read the minimum Designer state needed by the work-item planner.

    ``alert_type_usage`` is an optional, already-computed normalized runtime-use
    fact (``alertTypeInUse`` / ``alertTypeUseCount`` / ``alertTypeUseEvidence``,
    see :func:`alert_type_usage_from_dart_rows`). It is obtained by MCP/CLI
    orchestration via the REST Extend API *before* calling this function, and is
    merged in as plain data here -- this observation collector (and the planner
    it feeds) never instantiates a REST client itself. Omitting it (the default)
    leaves the fact unknown. The planner treats unknown as blocking only when an
    existing AlertType actually requires mutation."""
    observed = {
        "physicalFields": _result_items(designer_client.call_operation(
            "alertDesignService",
            "getAlertFields",
            out_param="fieldListHolder",
        )),
        "AlertCustomizedField": _result_items(
            designer_client.get_object_list("AlertCustomizedField")
        ),
        "AlertView": _result_items(designer_client.call_operation(
            "alertDesignService",
            "getListAlertViewInfo",
            out_param="viewInfoList",
        )),
        "AlertStatus": _result_items(designer_client.call_operation(
            "alertDesignService",
            "getListAlertStatus",
            out_param="alertStatusList",
        )),
        "AlertType": _result_items(designer_client.call_operation(
            "alertDesignService",
            "getListAlertTypeInfo",
            out_param="alertTypeList",
        )),
    }
    observed["AlertStatusWorkflowDefinition"] = _result_items(
        designer_client.get_object_info_list("AlertStatusWorkflowDefinition")
    )
    if specification:
        _hydrate_work_item_objects(designer_client, specification, observed)
    if alert_type_usage:
        observed.update(alert_type_usage)
    return observed


def owned_work_item_identifiers(specification: dict) -> dict[str, list[str]]:
    """Return only the identifiers explicitly owned by a family specification."""
    if not isinstance(specification, dict):
        raise DesignerPlanError("work-item specification must be an object")
    work_item_id = _require_identifier(specification, "work-item type")
    workflow = specification.get("workflow")
    view = specification.get("view")
    if not isinstance(workflow, dict):
        raise DesignerPlanError("work-item type requires workflow")
    if not isinstance(view, dict):
        raise DesignerPlanError("work-item type requires view")
    workflow_id = _require_identifier(workflow, "workflow")
    view_id = _require_identifier(view, "view")
    status_ids = sorted({
        _require_identifier(status, "workflow status")
        for status in workflow.get("statuses", []) or []
    })
    field_ids = sorted({
        _require_identifier(field, "custom field")
        for field in specification.get("customFields", []) or []
    })
    return {
        "AlertView": [view_id],
        "AlertType": [work_item_id],
        "AlertStatusWorkflowDefinition": [workflow_id],
        "AlertStatus": status_ids,
        "AlertCustomizedField": field_ids,
    }


def collect_remove_work_item_presence(designer_client,
                                      specification: dict) -> dict:
    """Read only the exact family-owned identifiers used by removal/verification."""
    owned = owned_work_item_identifiers(specification)
    observed = {
        "AlertCustomizedField": _result_items(
            designer_client.get_object_list("AlertCustomizedField")
        ),
        "AlertStatus": _result_items(designer_client.call_operation(
            "alertDesignService",
            "getListAlertStatus",
            out_param="alertStatusList",
        )),
        "AlertStatusWorkflowDefinition": _result_items(
            designer_client.get_object_info_list("AlertStatusWorkflowDefinition")
        ),
        "AlertType": _result_items(designer_client.call_operation(
            "alertDesignService",
            "getListAlertTypeInfo",
            out_param="alertTypeList",
        )),
        "AlertView": _result_items(designer_client.call_operation(
            "alertDesignService",
            "getListAlertViewInfo",
            out_param="viewInfoList",
        )),
    }
    for type_value, identifiers in owned.items():
        requested = set(identifiers)
        observed[type_value] = [
            item for item in observed[type_value]
            if _identifier(item) in requested
        ]
    _hydrate_work_item_objects(designer_client, specification, observed)
    for identifier in owned["AlertCustomizedField"]:
        if identifier in _by_identifier(observed["AlertCustomizedField"]):
            full = _out(designer_client.get_object(
                "AlertCustomizedField", identifier
            ))
            if isinstance(full, dict):
                _replace_by_identifier(
                    observed["AlertCustomizedField"], identifier, full
                )
    return observed


def collect_remove_work_item_observation(designer_client,
                                         specification: dict) -> dict:
    """Read exact family-owned objects and their current remove constraints."""
    owned = owned_work_item_identifiers(specification)
    observed = collect_remove_work_item_presence(designer_client, specification)

    constraints = {}
    for type_value, identifiers in owned.items():
        existing = _by_identifier(observed[type_value])
        constraints[type_value] = {}
        for identifier in identifiers:
            if identifier in existing:
                try:
                    result = designer_client.get_remove_constraints(
                        type_value, identifier
                    )
                    constraints[type_value][identifier] = {
                        "established": (
                            isinstance(result, dict) and "out" in result
                        ),
                        "value": (
                            _sanitize_snapshot(result.get("out"))
                            if isinstance(result, dict) and "out" in result
                            else None
                        ),
                    }
                except DesignerError as exc:
                    constraints[type_value][identifier] = {
                        "established": False,
                        "value": None,
                        "error": str(exc),
                    }
    observed["removeConstraints"] = constraints
    return observed


def alert_type_usage_from_dart_rows(rows, data_source_identifier: str,
                                    alert_type_identifier: str | None = None,
                                    sample_limit: int = 5,
                                    operation_id: str = "getDartResultsGet",
                                    source_parameter: str = "dataSourceIdentifier") -> dict:
    """Normalize a REST DART row payload into the runtime-use fact.

    This is the REST-first evidence backing the ``create_work_item_type``
    conservative-update preflight: ActOne's own AlertType update rejects a live
    alert type that "is found in one or more alerts", so MCP/CLI orchestration
    executes the bundled Extend REST operation ``getDartResultsGet`` (``GET
    /RCM/api/v1/dart/{dataSourceIdentifier}``, ``filter=alertTypeIdentifier=<id>``)
    against a pre-provisioned DART data source and passes the resulting rows
    here. ``rows`` is ``None`` when the check could not be performed (no data
    source configured, request failure, ...) -- that keeps the fact unknown
    instead of fabricating a false "not in use" negative. Unknown usage blocks
    an existing AlertType mutation in :func:`plan_work_item_type`."""
    if rows is None:
        return {}
    items = [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
    count = len(items)
    sample_ids = [
        row.get("alertId") or row.get("alert_id")
        or row.get("identifier") or row.get("id")
        for row in items[:sample_limit]
    ]
    evidence = {
        "operationId": operation_id,
        source_parameter: data_source_identifier,
    }
    if alert_type_identifier:
        evidence["alertTypeIdentifier"] = alert_type_identifier
    if sample_ids:
        evidence["sampleIdentifiers"] = sample_ids
    return {
        "alertTypeInUse": count > 0,
        "alertTypeUseCount": count,
        "alertTypeUseEvidence": evidence,
    }


def _identifier(item: dict) -> str | None:
    info = item.get("objectInfo")
    if isinstance(info, dict) and info.get("identifier"):
        return str(info["identifier"])
    value = item.get("identifier")
    return str(value) if value is not None else None


def _by_identifier(items: list[dict]) -> dict[str, dict]:
    return {
        identifier: item
        for item in items
        if isinstance(item, dict) and (identifier := _identifier(item))
    }


def _out(result: dict):
    return result.get("out") if isinstance(result, dict) else None


def _replace_by_identifier(items: list[dict], identifier: str, value: dict) -> None:
    for index, item in enumerate(items):
        if _identifier(item) == identifier:
            items[index] = value
            return


def _hydrate_work_item_objects(designer_client, specification: dict,
                               observed: dict) -> None:
    """Replace matching list summaries with full objects needed for comparison."""
    workflow = specification.get("workflow") or {}
    view = specification.get("view") or {}
    requested = {
        "AlertStatus": [
            item.get("identifier")
            for item in workflow.get("statuses", []) or []
            if isinstance(item, dict) and item.get("identifier")
        ],
        "AlertStatusWorkflowDefinition": [workflow.get("identifier")],
        "AlertType": [specification.get("identifier")],
        "AlertView": [view.get("identifier")],
    }
    existing = {
        type_value: set(_by_identifier(observed.get(type_value, []) or []))
        for type_value in requested
    }
    for identifier in requested["AlertStatus"]:
        if identifier in existing["AlertStatus"]:
            full = _out(designer_client.call_operation(
                "alertDesignService",
                "getAlertStatus",
                "<alertStatusIdentifier>%s</alertStatusIdentifier>"
                % escape(str(identifier)),
                "alertStatus",
            ))
            if isinstance(full, dict):
                _replace_by_identifier(observed["AlertStatus"], identifier, full)
    for type_value in ("AlertStatusWorkflowDefinition", "AlertType"):
        identifier = requested[type_value][0]
        if identifier and identifier in existing[type_value]:
            full = _out(designer_client.get_object(type_value, identifier))
            if isinstance(full, dict):
                _replace_by_identifier(observed[type_value], identifier, full)
    identifier = requested["AlertView"][0]
    if identifier and identifier in existing["AlertView"]:
        full = _out(designer_client.call_operation(
            "alertDesignService",
            "getAlertView",
            "<viewIdentifier>%s</viewIdentifier>" % escape(str(identifier)),
            "view",
        ))
        if isinstance(full, dict):
            _replace_by_identifier(observed["AlertView"], identifier, full)


def _as_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return value


def _select_string_source(physical_fields: list[dict], used_ids: set,
                          length: int) -> dict | None:
    candidates = []
    for field in physical_fields:
        field_id = _as_int(field.get("fieldId"))
        property_path = str(field.get("propertyPath") or "")
        data_type = str(field.get("dataType") or "").lower()
        field_size = _as_int(field.get("fieldSize"))
        if (
            property_path.startswith("ext_")
            and data_type == "string"
            and isinstance(field_size, int)
            and field_size >= length
            and field_id not in used_ids
        ):
            candidates.append((field_size, property_path, field_id, field))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1], str(item[2])))
    return candidates[0][3]


def _require_identifier(value: dict, label: str) -> str:
    identifier = str(value.get("identifier") or "").strip()
    if not identifier:
        raise DesignerPlanError("%s requires identifier" % label)
    return identifier


def _canonical_fingerprint(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


_TRANSPORT_KEYS = {"@type", "id"}


def _sanitize_snapshot(value):
    """Strip transport-only metadata (SOAP ``@type`` markers, internal numeric
    ``id``) from an observed object before it is embedded in a plan step, so the
    step carries the live object without leaking wire/transport plumbing."""
    if isinstance(value, dict):
        return {
            key: _sanitize_snapshot(val)
            for key, val in value.items()
            if key not in _TRANSPORT_KEYS
        }
    if isinstance(value, list):
        return [_sanitize_snapshot(item) for item in value]
    return value


def _canonicalize_observation(value, parent_key: str | None = None):
    if isinstance(value, dict):
        return {
            key: _canonicalize_observation(item, key)
            for key, item in value.items()
        }
    if isinstance(value, list):
        items = [
            _canonicalize_observation(item, parent_key)
            for item in value
        ]
        if parent_key == "inputs" and all(
            isinstance(item, dict) and item.get("inputType")
            for item in items
        ):
            return sorted(items, key=lambda item: str(item["inputType"]))
        return items
    return value


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


def _status_state(value: str) -> str:
    return "Open" if value == "InProcess" else value


def _display_name(identifier: str) -> str:
    return identifier.replace("_", " ").replace("-", " ").title()


def _status_name(status: dict) -> str:
    identifier = str(status.get("identifier") or "")
    return str(status.get("name") or _display_name(identifier))


def _expected_status(status: dict) -> tuple[str, str | None]:
    state = _status_state(str(status.get("state") or ""))
    issue = status.get("issue")
    if not issue and state == "Open":
        issue = "No_Determination"
    return state, issue


def _workflow_shape(workflow: dict) -> tuple[set[str], str | None,
                                             set[tuple[str, str]]]:
    nodes = _array(workflow.get("nodes"), "nodes")
    node_ids = {
        str(node["statusIdentifier"])
        for node in nodes
        if isinstance(node, dict) and node.get("statusIdentifier")
    }
    start = workflow.get("defaultStartNode")
    start_id = (
        str(start.get("statusIdentifier"))
        if isinstance(start, dict) and start.get("statusIdentifier") else None
    )
    edges = set()
    for node in nodes:
        if not isinstance(node, dict) or not node.get("statusIdentifier"):
            continue
        source = str(node["statusIdentifier"])
        for transition in _array(
            node.get("outgoingTransitions"), "outgoingTransitions"
        ):
            target = transition.get("targetNode") if isinstance(transition, dict) else None
            if isinstance(target, dict) and target.get("statusIdentifier"):
                edges.add((source, str(target["statusIdentifier"])))
    return node_ids, start_id, edges


def _view_filter_pairs(view: dict) -> set[tuple[str, str]]:
    if isinstance(view.get("filterPairs"), list):
        return {
            (str(item[0]), str(item[1]))
            for item in view["filterPairs"]
            if isinstance(item, (list, tuple)) and len(item) == 2
        }
    filter_value = view.get("filter")
    pairs = set()
    for comparison in _array(
        filter_value.get("subFilters") if isinstance(filter_value, dict) else None,
        "subFilters",
    ):
        terms = _array(
            comparison.get("terms") if isinstance(comparison, dict) else None,
            "terms",
        )
        field = next(
            (term.get("customizedFieldIdentifier") for term in terms
             if isinstance(term, dict) and term.get("customizedFieldIdentifier")),
            None,
        )
        value = next(
            (term.get("value") for term in terms
             if isinstance(term, dict) and "value" in term),
            None,
        )
        if field is not None and value is not None:
            pairs.add((str(field), str(value)))
    return pairs


def fingerprint_observation(observed: dict) -> str:
    """Fingerprint the read-only environment state used to build a plan."""
    return _canonical_fingerprint(_canonicalize_observation(observed))


def fingerprint_plan(plan: dict) -> str:
    """Recompute the immutable portion of a serialized capability plan."""
    return _canonical_fingerprint(_canonicalize_observation({
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
    }))


def _constraint_is_empty(value) -> bool:
    if value in (None, "", False):
        return True
    if isinstance(value, list):
        return all(_constraint_is_empty(item) for item in value)
    if isinstance(value, dict):
        return all(
            _constraint_is_empty(item)
            for key, item in value.items()
            if key != "@type"
        )
    return False


def _constraint_entries(value) -> list[dict]:
    if isinstance(value, list):
        return [
            entry
            for item in value
            for entry in _constraint_entries(item)
        ]
    if not isinstance(value, dict):
        return []
    if "objectInfo" in value or "numberOfInstances" in value:
        return [value]
    return [
        entry
        for key, item in value.items()
        if key != "@type"
        for entry in _constraint_entries(item)
    ]


def _constraint_established(observation: dict | None) -> bool:
    """Whether a per-object remove-constraint read produced usable evidence.

    The generic ``getRemoveConstraints`` op is not available for work-item
    family object types on any live build (it fails with "<Type> is not
    supported for this operation"), so the collector records
    ``established: False`` for them. When constraints are unavailable the
    planner does not hard-block; it plans the delete and relies on the
    authoritative fail-closed ``removeAlert*``/``removeObject`` op to refuse a
    still-referenced object at apply time. Established evidence (from a build or
    object that does support the read) is still honored."""
    return bool(isinstance(observation, dict) and observation.get("established"))


def remove_constraints_status(
    observation: dict | None,
    allowed_references: set[tuple[str, str]] | None = None,
) -> tuple[bool, str]:
    """Return whether constraints are empty or only name earlier owned objects."""
    if not isinstance(observation, dict) or not observation.get("established"):
        return False, "remove constraints could not be established"
    value = observation.get("value")
    if _constraint_is_empty(value):
        return True, ""
    entries = _constraint_entries(value)
    if not entries:
        return False, "remove constraints are present but could not be interpreted"
    allowed_references = allowed_references or set()
    for entry in entries:
        if "numberOfInstances" in entry:
            try:
                if int(entry.get("numberOfInstances") or 0) == 0:
                    continue
            except (TypeError, ValueError):
                pass
            return False, "runtime instances block removal"
        info = entry.get("objectInfo")
        if not isinstance(info, dict):
            return False, "remove constraints are present but could not be interpreted"
        reference = (
            str(info.get("type") or ""),
            str(info.get("identifier") or ""),
        )
        if not all(reference) or reference not in allowed_references:
            return False, "an external or shared object references this object"
    return True, ""


def plan_remove_work_item_type(specification: dict, observed: dict,
                               environment: str, target_build: str) -> dict:
    """Plan exact, reverse-dependency removal of a work-item family."""
    owned = owned_work_item_identifiers(specification)
    existing = {
        type_value: _by_identifier(observed.get(type_value, []) or [])
        for type_value in owned
    }
    changes = {"remove": [], "absent": [], "blocked": []}
    steps = []
    previous_step = None
    earlier_owned = set()
    for type_value in (
        "AlertView",
        "AlertType",
        "AlertStatusWorkflowDefinition",
        "AlertStatus",
        "AlertCustomizedField",
    ):
        for identifier in owned[type_value]:
            entry = {"type": type_value, "identifier": identifier}
            if identifier not in existing[type_value]:
                changes["absent"].append(entry)
                earlier_owned.add((type_value, identifier))
                continue
            constraint = (
                observed.get("removeConstraints", {})
                .get(type_value, {})
                .get(identifier)
            )
            if _constraint_established(constraint):
                removable, reason = remove_constraints_status(
                    constraint, allowed_references=earlier_owned
                )
                if not removable:
                    changes["blocked"].append({
                        **entry,
                        "reason": reason,
                        "constraints": constraint.get("value"),
                    })
                    earlier_owned.add((type_value, identifier))
                    continue
            changes["remove"].append(entry)
            step_id = "remove.%s.%s" % (type_value, identifier)
            steps.append({
                "id": step_id,
                "adapter": "soap",
                "action": "remove",
                "type": type_value,
                "identifier": identifier,
                "dependsOn": [previous_step] if previous_step else [],
                "verification": ["object identifier is absent"],
            })
            previous_step = step_id
            earlier_owned.add((type_value, identifier))

    observation_fingerprint = fingerprint_observation(observed)
    applicable = not changes["blocked"]
    plan = {
        "capability": "remove_work_item_type",
        "environment": environment,
        "targetBuild": target_build,
        "specification": specification,
        "observationFingerprint": observation_fingerprint,
        "applicable": applicable,
        "changes": changes,
        "steps": steps,
        "errors": [],
    }
    fingerprint = fingerprint_plan(plan)
    return {
        "planId": fingerprint[:16],
        "fingerprint": fingerprint,
        **plan,
        "warnings": [],
    }


def plan_work_item_type(specification: dict, observed: dict, environment: str,
                        target_build: str) -> dict:
    """Plan the create-work-item-type capability without performing writes."""
    if not isinstance(specification, dict):
        raise DesignerPlanError("work-item specification must be an object")
    work_item_id = _require_identifier(specification, "work-item type")
    workflow = specification.get("workflow")
    view = specification.get("view")
    if not isinstance(workflow, dict):
        raise DesignerPlanError("work-item type requires workflow")
    if not isinstance(view, dict):
        raise DesignerPlanError("work-item type requires view")
    workflow_id = _require_identifier(workflow, "workflow")
    view_id = _require_identifier(view, "view")

    statuses = workflow.get("statuses", []) or []
    transitions = workflow.get("transitions", []) or []
    if not statuses:
        raise DesignerPlanError("workflow requires statuses")
    status_ids = [_require_identifier(status, "workflow status") for status in statuses]
    for status_id, status in zip(status_ids, statuses):
        state = str(status.get("state") or "")
        if state == "Closed" and not status.get("issue"):
            raise DesignerPlanError(
                "closed workflow status %r requires issue (Issue or Non_Issue)"
                % status_id
            )
    starts = [
        status_id for status_id, status in zip(status_ids, statuses)
        if status.get("start") is True
    ]
    if len(starts) != 1:
        raise DesignerPlanError("workflow requires exactly one start status")
    known_statuses = set(status_ids)
    for transition in transitions:
        source = transition.get("from")
        target = transition.get("to")
        if source not in known_statuses or target not in known_statuses:
            raise DesignerPlanError(
                "workflow transition %r -> %r references an unknown status"
                % (source, target)
            )

    existing = {
        type_value: _by_identifier(observed.get(type_value, []) or [])
        for type_value in (
            "AlertCustomizedField",
            "AlertStatus",
            "AlertStatusWorkflowDefinition",
            "AlertType",
            "AlertView",
        )
    }
    used_field_ids = {
        _as_int(item.get("fieldId"))
        for item in observed.get("AlertCustomizedField", []) or []
        if isinstance(item, dict) and item.get("fieldId") is not None
    }
    physical_by_id = {
        _as_int(item.get("fieldId")): item
        for item in observed.get("physicalFields", []) or []
        if isinstance(item, dict) and item.get("fieldId") is not None
    }

    changes = {"create": [], "reuse": [], "update": [], "conflict": []}
    steps = []
    errors = []
    warnings = []
    custom_dependencies = []

    for field in specification.get("customFields", []) or []:
        field_id = _require_identifier(field, "custom field")
        data_type = str(field.get("dataType") or "").lower()
        length = _as_int(field.get("length"))
        if data_type != "string" or not isinstance(length, int) or length <= 0:
            errors.append({
                "code": "unsupported_field_specification",
                "field": field_id,
                "message": "This increment supports string fields with a positive length",
            })
            continue
        if field_id in existing["AlertCustomizedField"]:
            existing_field = existing["AlertCustomizedField"][field_id]
            source = physical_by_id.get(_as_int(existing_field.get("fieldId")))
            compatible = (
                isinstance(source, dict)
                and str(source.get("propertyPath") or "").startswith("ext_")
                and str(source.get("dataType") or "").lower() == "string"
                and isinstance(_as_int(source.get("fieldSize")), int)
                and _as_int(source.get("fieldSize")) >= length
            )
            if not compatible:
                changes["conflict"].append({
                    "type": "AlertCustomizedField",
                    "identifier": field_id,
                    "reason": (
                        "existing physical Source is incompatible with String(%d)"
                        % length
                    ),
                })
                continue
            changes["reuse"].append({
                "type": "AlertCustomizedField",
                "identifier": field_id,
            })
            continue
        source = _select_string_source(
            observed.get("physicalFields", []) or [],
            used_field_ids,
            length,
        )
        if not source:
            errors.append({
                "code": "source_exhausted",
                "field": field_id,
                "message": "No unused customer String Source can store length %d" % length,
            })
            continue
        source_id = _as_int(source.get("fieldId"))
        used_field_ids.add(source_id)
        change = {
            "type": "AlertCustomizedField",
            "identifier": field_id,
            "physicalSource": source.get("propertyPath"),
            "fieldId": source_id,
        }
        changes["create"].append(change)
        step_id = "custom-field.%s" % field_id
        custom_dependencies.append(step_id)
        steps.append({
            "id": step_id,
            "adapter": "soap",
            "action": "create",
            "type": "AlertCustomizedField",
            "dependsOn": [],
            "fields": {
                "identifier": field_id,
                "name": field.get("label") or field_id,
                "description": field.get("description", ""),
                "fieldId": source_id,
                "range": bool(field.get("range", False)),
            },
            "verification": [
                "field identifier exists",
                "fieldId equals %s" % source_id,
                "physical Source equals %s" % source.get("propertyPath"),
            ],
        })

    status_dependencies = []
    status_update_steps = []
    existing_status_names = {
        str(item.get("name")): identifier
        for identifier, item in existing["AlertStatus"].items()
        if item.get("name")
    }
    for status_id, status in zip(status_ids, statuses):
        requested_name = _status_name(status)
        name_owner = existing_status_names.get(requested_name)
        if name_owner and name_owner != status_id:
            changes["conflict"].append({
                "type": "AlertStatus",
                "identifier": status_id,
                "reason": "status name %r is already used by %r"
                % (requested_name, name_owner),
            })
            continue
        if status_id in existing["AlertStatus"]:
            existing_status = existing["AlertStatus"][status_id]
            expected_state, expected_issue = _expected_status(status)
            if (
                existing_status.get("state") != expected_state
                or existing_status.get("issue") != expected_issue
            ):
                # State/issue are core status identity, not presentation, so a
                # mismatch here can never be a safe update -- only name/description
                # (metadata) may differ and still be applied as an update below.
                changes["conflict"].append({
                    "type": "AlertStatus",
                    "identifier": status_id,
                    "reason": (
                        "existing status name/state/issue differs from requested "
                        "definition"
                    ),
                })
                continue
            requested_description = str(status.get("description") or "")
            existing_description = str(existing_status.get("description") or "")
            if (
                existing_status.get("name") == requested_name
                and existing_description == requested_description
            ):
                changes["reuse"].append({
                    "type": "AlertStatus",
                    "identifier": status_id,
                })
                continue
            changes["update"].append({
                "type": "AlertStatus",
                "identifier": status_id,
                "fields": ["name", "description"],
            })
            step_id = "status.%s" % status_id
            status_update_steps.append(step_id)
            steps.append({
                "id": step_id,
                "adapter": "soap",
                "action": "update",
                "type": "AlertStatus",
                "dependsOn": [],
                "fields": dict(status),
                "observed": _sanitize_snapshot(existing_status),
                "verification": ["status name/description match"],
            })
            continue
        changes["create"].append({"type": "AlertStatus", "identifier": status_id})
        step_id = "status.%s" % status_id
        status_dependencies.append(step_id)
        steps.append({
            "id": step_id,
            "adapter": "soap",
            "action": "create",
            "type": "AlertStatus",
            "dependsOn": [],
            "fields": dict(status),
            "verification": ["status identifier and state match"],
        })

    workflow_step = None
    if workflow_id in existing["AlertStatusWorkflowDefinition"]:
        existing_nodes, existing_start, existing_edges = _workflow_shape(
            existing["AlertStatusWorkflowDefinition"][workflow_id]
        )
        expected_nodes = set(status_ids)
        expected_edges = {
            (str(transition["from"]), str(transition["to"]))
            for transition in transitions
        }
        if (
            existing_nodes == expected_nodes
            and existing_start == starts[0]
            and existing_edges == expected_edges
        ):
            changes["reuse"].append({
                "type": "AlertStatusWorkflowDefinition",
                "identifier": workflow_id,
            })
        elif existing_start != starts[0]:
            # The default start node is a structural identity property, not an
            # additive change -- changing it is never a safe update.
            changes["conflict"].append({
                "type": "AlertStatusWorkflowDefinition",
                "identifier": workflow_id,
                "reason": "workflow start status changes are not supported",
            })
        elif not existing_nodes <= expected_nodes:
            # Every existing node must still be present; the requested graph may
            # only add nodes, never drop one.
            changes["conflict"].append({
                "type": "AlertStatusWorkflowDefinition",
                "identifier": workflow_id,
                "reason": "workflow node/status removal is not supported",
            })
        elif not existing_edges <= expected_edges:
            # Every existing transition must still be present with the same
            # source/target; removing or re-targeting ("re-parenting") an
            # existing edge is never a safe update, only adding new edges is.
            changes["conflict"].append({
                "type": "AlertStatusWorkflowDefinition",
                "identifier": workflow_id,
                "reason": (
                    "workflow transition removal or re-parenting is not supported"
                ),
            })
        else:
            changes["update"].append({
                "type": "AlertStatusWorkflowDefinition",
                "identifier": workflow_id,
                "fields": ["nodes", "transitions"],
            })
            workflow_step = "workflow.%s" % workflow_id
            steps.append({
                "id": workflow_step,
                "adapter": "soap",
                "action": "update",
                "type": "AlertStatusWorkflowDefinition",
                "dependsOn": status_dependencies + status_update_steps,
                "specification": {
                    "identifier": workflow_id,
                    "statuses": statuses,
                    "transitions": transitions,
                    "startStatus": starts[0],
                },
                "observed": _sanitize_snapshot(
                    existing["AlertStatusWorkflowDefinition"][workflow_id]
                ),
                "verification": [
                    "existing nodes and transitions are retained",
                    "new nodes and transitions are present",
                ],
            })
    else:
        changes["create"].append({
            "type": "AlertStatusWorkflowDefinition",
            "identifier": workflow_id,
        })
        workflow_step = "workflow.%s" % workflow_id
        steps.append({
            "id": workflow_step,
            "adapter": "soap",
            "action": "create",
            "type": "AlertStatusWorkflowDefinition",
            "dependsOn": status_dependencies,
            "specification": {
                "identifier": workflow_id,
                "statuses": statuses,
                "transitions": transitions,
                "startStatus": starts[0],
            },
            "verification": [
                "exactly one start node",
                "node identifiers and transition graph match",
            ],
        })

    type_step = None
    type_mutation_blocked = False
    if work_item_id in existing["AlertType"]:
        existing_type = existing["AlertType"][work_item_id]
        existing_fields = {
            item.get("customizedFieldIdentifier")
            for item in _array(
                existing_type.get("alertTypeFields"), "alertTypeFields"
            )
            if isinstance(item, dict) and item.get("customizedFieldIdentifier")
        }
        requested_fields = {
            _require_identifier(field, "custom field")
            for field in specification.get("customFields", []) or []
        }
        if existing_type.get("alertStatusWorkflowDefinitionIdentifier") != workflow_id:
            # Reassigning the work-item type to a different workflow is a
            # structural re-parenting, not an additive change.
            changes["conflict"].append({
                "type": "AlertType",
                "identifier": work_item_id,
                "reason": "work-item type workflow assignment cannot be changed",
            })
            type_mutation_blocked = True
        elif not existing_fields <= requested_fields:
            changes["conflict"].append({
                "type": "AlertType",
                "identifier": work_item_id,
                "reason": "custom-field removal is not supported",
            })
            type_mutation_blocked = True
        elif existing_fields == requested_fields:
            changes["reuse"].append({
                "type": "AlertType",
                "identifier": work_item_id,
            })
        elif "alertTypeInUse" not in observed:
            changes["conflict"].append({
                "type": "AlertType",
                "identifier": work_item_id,
                "reason": (
                    "runtime usage could not be established; configure a supported "
                    "AlertType usage query before updating this work-item type"
                ),
            })
            type_mutation_blocked = True
        elif observed.get("alertTypeInUse") is True:
            # Live ActOne rejects AlertType updates once runtime alerts exist
            # for the type ("Alert type [...] is found in one or more
            # alerts"). Block the update up front instead of discovering this
            # mid-apply after earlier steps already mutated state. The runtime-
            # use fact is supplied by MCP/CLI orchestration after a supported
            # read-only query.
            conflict = {
                "type": "AlertType",
                "identifier": work_item_id,
                "reason": (
                    "existing runtime alerts reference this work-item type; "
                    "AlertType updates are blocked while alerts exist"
                ),
            }
            count = observed.get("alertTypeUseCount")
            if count is not None:
                conflict["count"] = count
            evidence = observed.get("alertTypeUseEvidence")
            if evidence is not None:
                conflict["evidence"] = evidence
            changes["conflict"].append(conflict)
            type_mutation_blocked = True
        else:
            changes["update"].append({
                "type": "AlertType",
                "identifier": work_item_id,
                "fields": ["alertTypeFields"],
            })
            type_step = "work-item-type.%s" % work_item_id
            dependencies = list(custom_dependencies)
            if workflow_step:
                dependencies.append(workflow_step)
            steps.append({
                "id": type_step,
                "adapter": "soap",
                "action": "update",
                "type": "AlertType",
                "dependsOn": dependencies,
                "specification": {
                    "identifier": work_item_id,
                    "name": specification.get("name") or work_item_id,
                    "description": specification.get("description", ""),
                    "customFields": [
                        _require_identifier(field, "custom field")
                        for field in specification.get("customFields", []) or []
                    ],
                    "workflow": workflow_id,
                },
                "observed": _sanitize_snapshot(existing_type),
                "verification": ["additive custom-field assignments are present"],
            })
    else:
        changes["create"].append({"type": "AlertType", "identifier": work_item_id})
        type_step = "work-item-type.%s" % work_item_id
        dependencies = list(custom_dependencies)
        if workflow_step:
            dependencies.append(workflow_step)
        steps.append({
            "id": type_step,
            "adapter": "soap",
            "action": "create",
            "type": "AlertType",
            "dependsOn": dependencies,
            "specification": {
                "identifier": work_item_id,
                "name": specification.get("name") or work_item_id,
                "description": specification.get("description", ""),
                "customFields": [
                    _require_identifier(field, "custom field")
                    for field in specification.get("customFields", []) or []
                ],
                "workflow": workflow_id,
            },
            "verification": ["custom-field assignments and workflow reference match"],
        })

    if view_id in existing["AlertView"]:
        existing_view = existing["AlertView"][view_id]
        existing_view_fields = {
            item.get("fieldIdentifier")
            for item in _array(existing_view.get("viewFields"), "viewFields")
            if isinstance(item, dict) and item.get("fieldIdentifier")
        }
        requested_view_fields = {
            field if isinstance(field, str) else (
                field.get("identifier") or field.get("fieldIdentifier")
            )
            for field in view.get("fields", []) or []
        }
        requested_filter_pairs = {
            ("alertArchive", "0"),
            ("deleted", "0"),
            ("alertTypeIdentifier", work_item_id),
            *(
                (str(key), str(value))
                for key, value in (view.get("filters", {}) or {}).items()
            ),
        }
        if _view_filter_pairs(existing_view) != requested_filter_pairs:
            # Filters are logical/behavioral, not presentational, so any
            # difference is blocked rather than treated as a safe update.
            changes["conflict"].append({
                "type": "AlertView",
                "identifier": view_id,
                "reason": "view filter changes are not supported",
            })
        elif not existing_view_fields <= requested_view_fields:
            changes["conflict"].append({
                "type": "AlertView",
                "identifier": view_id,
                "reason": "view field removal is not supported",
            })
        elif existing_view_fields == requested_view_fields:
            changes["reuse"].append({"type": "AlertView", "identifier": view_id})
        elif type_mutation_blocked:
            changes["conflict"].append({
                "type": "AlertView",
                "identifier": view_id,
                "reason": "view mutation depends on the blocked AlertType update",
            })
        else:
            changes["update"].append({
                "type": "AlertView",
                "identifier": view_id,
                "fields": ["viewFields"],
            })
            steps.append({
                "id": "view.%s" % view_id,
                "adapter": "soap",
                "action": "update",
                "type": "AlertView",
                "dependsOn": [type_step] if type_step else [],
                "specification": {
                    **dict(view),
                    "workItemType": work_item_id,
                },
                "observed": _sanitize_snapshot(existing_view),
                "verification": [
                    "additive view fields are present",
                    "logical filters are unchanged",
                ],
            })
    elif type_mutation_blocked:
        changes["conflict"].append({
            "type": "AlertView",
            "identifier": view_id,
            "reason": "view mutation depends on the blocked AlertType update",
        })
    else:
        changes["create"].append({"type": "AlertView", "identifier": view_id})
        steps.append({
            "id": "view.%s" % view_id,
            "adapter": "soap",
            "action": "create",
            "type": "AlertView",
            "dependsOn": [type_step] if type_step else [],
            "specification": {
                **dict(view),
                "workItemType": work_item_id,
            },
            "verification": ["view fields and logical filters match"],
        })

    observation_fingerprint = fingerprint_observation(observed)
    applicable = not errors and not changes["conflict"]
    if not applicable:
        steps = []
    plan = {
        "capability": "create_work_item_type",
        "environment": environment,
        "targetBuild": target_build,
        "specification": specification,
        "observationFingerprint": observation_fingerprint,
        "applicable": applicable,
        "changes": changes,
        "steps": steps,
        "errors": errors,
    }
    fingerprint = fingerprint_plan(plan)
    return {
        "planId": fingerprint[:16],
        "fingerprint": fingerprint,
        "observationFingerprint": observation_fingerprint,
        "capability": "create_work_item_type",
        "environment": environment,
        "targetBuild": target_build,
        "specification": specification,
        "applicable": applicable,
        "changes": changes,
        "steps": steps,
        "errors": errors,
        "warnings": warnings,
    }
