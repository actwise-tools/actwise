"""Pure planning and verification for modern work-item presentation metadata."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping

from actone.invoke import InvokeError, invoke


CAPABILITY_ID = "configure_work_item_presentation"
LEGACY_OBJECT_TYPE = "CaseType"
FIELD_UPDATE_LIMIT = 20
_DEFAULT_ENVIRONMENT = "default"
_UNKNOWN_BUILD = "unknown"

_FIELD_POLICY_KEYS = {
    "fieldIdentifier",
    "fieldType",
    "mandatory",
    "fieldEditPolicy",
}
_ALERT_FIELD_KEYS = {
    "fieldIdentifier",
    "mandatory",
    "updatable",
    "defaultValue",
    "isCachable",
    "consolidationAggregationType",
}
_WIDGET_KEYS = {
    "fieldIdentifier",
    "columnDisplayFormatterIdentifier",
    "columnFormat",
    "displayOrder",
}
_RELATION_KEYS = {
    "childTypeIdentifier",
    "relationTypeIdentifier",
    "relationsAudit",
    "isConsolidatingPair",
    "consolidationMode",
}
_CUSTOM_POLICIES = {
    "Updatable",
    "Not_Updatable",
    "Hidden",
    "Updatable_on_Creation",
    "Hide_on_Edit",
}
_VIRTUAL_POLICIES = {"Hide_on_Edit", "External_Data"}

__all__ = [
    "CAPABILITY_ID",
    "apply_work_item_presentation_plan",
    "collect_work_item_presentation_observation",
    "fingerprint_presentation_plan",
    "plan_work_item_presentation",
    "required_presentation_routes",
    "verify_work_item_presentation",
]


def required_presentation_routes(
    work_item_type_identifier: str | None = None,
) -> dict:
    """Describe the REST evidence and mutation routes needed by an orchestrator."""
    identifier = work_item_type_identifier or "{workItemTypeIdentifier}"
    base = f"/RCM/api/v1/md/work-item-types/{identifier}"
    return {
        "reads": {
            "workItemTypes": {
                "operationId": "getWorkItemTypes",
                "method": "GET",
                "path": "/RCM/api/v1/md/work-item-types",
                "required": True,
            },
            "fields": {
                "operationId": "getworkItemTypesFields",
                "method": "GET",
                "path": f"{base}/fields",
                "required": True,
            },
            "relations": {
                "operationId": "getWorkItemTypesRelations",
                "method": "GET",
                "path": f"{base}/mapping-relations",
                "required": True,
            },
            "rendererDiscovery": {
                "operationId": None,
                "method": None,
                "path": None,
                "required": "when renderer references are requested",
                "suppliedByOrchestrator": True,
            },
        },
        "writes": {
            "presentation": {
                "operationId": "updateWorkItemType",
                "method": "POST",
                "path": base,
            },
            "fields": {
                "operationId": "updateWorkItemTypeFields",
                "method": "PUT",
                "path": (
                    "/RCM/api/v2/md/work-item-types/"
                    f"{identifier}/fields"
                ),
                "maximumFields": FIELD_UPDATE_LIMIT,
            },
        },
    }


def fingerprint_presentation_plan(plan: Mapping) -> str:
    """Recompute the immutable fingerprint of a presentation plan."""
    payload = {
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
    return _fingerprint(payload)


def plan_work_item_presentation(
    specification: Mapping,
    observation: Mapping,
    environment: str | None = None,
    target_build: str | None = None,
) -> dict:
    """Return a deterministic, fail-closed REST mutation plan without doing I/O."""
    errors: list[dict] = []
    conflicts: list[dict] = []
    changes = {
        "create": [],
        "reuse": [],
        "update": [],
        "conflict": conflicts,
    }
    spec = _normalize_specification(specification, errors)
    observed = _normalize_observation(observation, errors)
    specification_value = (
        specification if isinstance(specification, Mapping) else {}
    )
    if environment is not None:
        observed["environment"] = _text(environment) or _DEFAULT_ENVIRONMENT
    elif specification_value.get("environment") is not None:
        observed["environment"] = (
            _text(specification_value.get("environment"))
            or _DEFAULT_ENVIRONMENT
        )
    if target_build is not None:
        observed["targetBuild"] = _text(target_build) or _UNKNOWN_BUILD
    elif specification_value.get("targetBuild") is not None:
        observed["targetBuild"] = (
            _text(specification_value.get("targetBuild")) or _UNKNOWN_BUILD
        )
    identifier = spec.get("workItemTypeIdentifier", "")
    routing = required_presentation_routes(identifier or None)

    _validate_evidence(spec, observed, errors)
    work_item_type = _find_work_item_type(spec, observed, errors)
    fields = {
        field["fieldIdentifier"]: field
        for field in observed["fields"]
        if field.get("fieldIdentifier")
    }
    _validate_observed_widget_fields(observed, fields, errors)
    _validate_references(spec, observed, conflicts)
    _validate_desired_fields(spec, fields, conflicts)
    _validate_widget_formatter_rules(spec, observed, conflicts)
    _validate_details_widget_support(
        spec, observed, work_item_type, conflicts
    )

    presentation_body: dict = {}
    if not errors:
        widget_change = _plan_widget(spec, observed, changes)
        if widget_change:
            presentation_body["detailsWidgetDisplay"] = widget_change
            presentation_body["detailsWidgetDisplayExists"] = True

        relation_change = _plan_relations(spec, observed, changes)
        if relation_change:
            presentation_body["relatedItemTypes"] = relation_change

    field_updates: dict[str, dict] = {}
    if len(spec["fieldPolicies"]) > FIELD_UPDATE_LIMIT:
        errors.append({
            "code": "field_update_limit_exceeded",
            "message": (
                "updateWorkItemTypeFields accepts at most 20 fields"
            ),
            "actual": len(spec["fieldPolicies"]),
            "maximum": FIELD_UPDATE_LIMIT,
        })
    elif not errors:
        _plan_field_policies(
            spec["fieldPolicies"],
            fields,
            changes,
            conflicts,
            field_updates,
        )

    if not errors:
        alert_additions = _plan_alert_type_fields(
            spec["alertTypeFields"],
            fields,
            work_item_type,
            changes,
            conflicts,
        )
        if alert_additions:
            presentation_body["alertTypeFields"] = {"add": alert_additions}
            presentation_body["alertTypeFieldsExists"] = True

    steps = []
    if not errors and not conflicts:
        if presentation_body:
            steps.append({
                "id": "work-item-type.presentation",
                "adapter": "extend-rest",
                "operationId": "updateWorkItemType",
                "method": "POST",
                "path": routing["writes"]["presentation"]["path"],
                "body": presentation_body,
                "dependsOn": [],
                "verification": [
                    _presentation_verification_text(presentation_body)
                ],
            })
        field_body = _field_update_body(field_updates)
        if field_body:
            steps.append({
                "id": "work-item-type.fields",
                "adapter": "extend-rest",
                "operationId": "updateWorkItemTypeFields",
                "method": "PUT",
                "path": routing["writes"]["fields"]["path"],
                "body": field_body,
                "dependsOn": (
                    ["work-item-type.presentation"]
                    if presentation_body else []
                ),
                "verification": [
                    "specified field policy attributes match desired values"
                ],
            })

    observation_fingerprint = _fingerprint(observed)
    plan = {
        "capability": CAPABILITY_ID,
        "environment": observed["environment"],
        "targetBuild": observed["targetBuild"],
        "specification": spec,
        "observationFingerprint": observation_fingerprint,
        "applicable": not errors and not conflicts,
        "routing": routing,
        "changes": changes,
        "steps": steps if not errors and not conflicts else [],
        "errors": errors,
    }
    fingerprint = fingerprint_presentation_plan(plan)
    return {
        "planId": fingerprint[:16],
        "fingerprint": fingerprint,
        **plan,
    }


def collect_work_item_presentation_observation(
    rest_registry,
    rest_client,
    specification,
    renderer_inventory=None,
) -> dict:
    """Collect and conservatively normalize the REST evidence for a plan."""
    specification_value = (
        specification if isinstance(specification, Mapping) else {}
    )
    identifier = _text(
        specification_value.get("workItemTypeIdentifier")
    )
    work_item_result = invoke(
        rest_registry,
        rest_client,
        "getWorkItemTypes",
        params={},
    )
    field_result = invoke(
        rest_registry,
        rest_client,
        "getworkItemTypesFields",
        params={
            "workItemTypeIdentifier": identifier,
            "unusedFields": "false",
            "fieldType": "both",
        },
    )
    relation_result = invoke(
        rest_registry,
        rest_client,
        "getWorkItemTypesRelations",
        params={"workItemTypeIdentifier": identifier},
    )

    work_item_types_ok, work_item_types = _normalize_work_item_type_response(
        work_item_result
    )
    fields_ok, fields = _normalize_field_response(field_result)
    relations_ok, relations = _normalize_relation_response(
        relation_result,
        identifier,
    )
    renderer_evidence = isinstance(renderer_inventory, list)
    client_environment = (
        getattr(rest_client, "environment", None)
        or getattr(rest_client, "env", None)
    )
    client_build = getattr(rest_client, "version", None)
    return {
        "environment": (
            _text(client_environment)
            or _text(specification_value.get("environment"))
            or _DEFAULT_ENVIRONMENT
        ),
        "targetBuild": (
            _text(client_build)
            or _text(specification_value.get("targetBuild"))
            or _UNKNOWN_BUILD
        ),
        "evidence": {
            "getWorkItemTypes": work_item_types_ok,
            "getworkItemTypesFields": fields_ok,
            "getWorkItemTypesRelations": relations_ok,
            "rendererDiscovery": renderer_evidence,
        },
        "workItemTypes": work_item_types,
        "fields": fields,
        "detailsWidgetFields": _widget_from_fields(fields),
        "relations": relations,
        "renderers": (
            _normalize_reference_list(renderer_inventory)
            if renderer_evidence else []
        ),
    }


def apply_work_item_presentation_plan(
    plan,
    rest_registry,
    rest_client,
    current_observation,
) -> dict:
    """Apply an intact, current REST plan and verify it from fresh evidence."""
    if plan.get("capability") != CAPABILITY_ID:
        return {"ok": False, "error": "unsupported_capability"}
    if fingerprint_presentation_plan(plan) != plan.get("fingerprint"):
        return {
            "ok": False,
            "error": "plan_tampered",
            "planId": plan.get("planId"),
        }

    current_errors: list[dict] = []
    normalized_current = _normalize_observation(
        current_observation,
        current_errors,
    )
    current_fingerprint = _fingerprint(normalized_current)
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

    ordered_steps, route_error = _validated_presentation_steps(plan)
    if route_error:
        return {
            "ok": False,
            "error": route_error["code"],
            "planId": plan.get("planId"),
            "message": route_error["message"],
        }

    identifier = plan["specification"]["workItemTypeIdentifier"]
    completed = []
    for step in ordered_steps:
        try:
            result = invoke(
                rest_registry,
                rest_client,
                step["operationId"],
                params={
                    "workItemTypeIdentifier": identifier,
                    "body": step["body"],
                },
                allow_write=True,
            )
        except InvokeError as exc:
            return {
                "ok": False,
                "error": "step_failed",
                "planId": plan.get("planId"),
                "failedStep": step.get("id"),
                "message": str(exc),
                "completedSteps": completed,
            }
        if not isinstance(result, Mapping) or result.get("ok") is not True:
            return {
                "ok": False,
                "error": "step_failed",
                "planId": plan.get("planId"),
                "failedStep": step.get("id"),
                "message": (
                    result.get("error")
                    if isinstance(result, Mapping) and result.get("error")
                    else (
                        f"{step['operationId']} returned an unsuccessful "
                        "response"
                    )
                ),
                "completedSteps": completed,
            }
        completed.append({"id": step["id"], "result": dict(result)})

    renderer_inventory = (
        normalized_current["renderers"]
        if normalized_current["evidence"]["rendererDiscovery"] else None
    )
    collection_specification = {
        **plan["specification"],
        "environment": plan.get("environment"),
        "targetBuild": plan.get("targetBuild"),
    }
    post_observation = collect_work_item_presentation_observation(
        rest_registry,
        rest_client,
        collection_specification,
        renderer_inventory=renderer_inventory,
    )
    verification = verify_work_item_presentation(plan, post_observation)
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


def verify_work_item_presentation(plan: Mapping, post_observation: Mapping) -> dict:
    """Compare supplied read-back evidence with an intact plan and desired spec."""
    if plan.get("capability") != CAPABILITY_ID:
        return {"ok": False, "error": "unsupported_capability"}
    if fingerprint_presentation_plan(plan) != plan.get("fingerprint"):
        return {
            "ok": False,
            "error": "plan_tampered",
            "planId": plan.get("planId"),
        }
    if not plan.get("applicable"):
        return {
            "ok": False,
            "error": "plan_not_applicable",
            "planId": plan.get("planId"),
        }

    readback_plan = plan_work_item_presentation(
        plan.get("specification", {}),
        post_observation,
    )
    residual = (
        readback_plan["changes"]["create"]
        + readback_plan["changes"]["update"]
        + readback_plan["changes"]["conflict"]
    )
    assertions = [
        {
            "name": "target-identity-unchanged",
            "passed": (
                readback_plan["environment"] == plan.get("environment")
                and readback_plan["targetBuild"] == plan.get("targetBuild")
            ),
            "expected": {
                "environment": plan.get("environment"),
                "targetBuild": plan.get("targetBuild"),
            },
            "actual": {
                "environment": readback_plan["environment"],
                "targetBuild": readback_plan["targetBuild"],
            },
        },
        {
            "name": "read-evidence-complete",
            "passed": not readback_plan["errors"],
            "expected": [],
            "actual": readback_plan["errors"],
        },
        {
            "name": "desired-presentation-observed",
            "passed": not residual,
            "expected": [],
            "actual": residual,
        },
    ]
    failures = [item for item in assertions if not item["passed"]]
    return {
        "ok": not failures,
        "assertions": assertions,
        "failures": failures,
    }


def _successful_body(result) -> tuple[bool, object]:
    if not isinstance(result, Mapping) or result.get("ok") is not True:
        return False, None
    return True, result.get("body")


def _list_envelope(value, keys: tuple[str, ...], depth: int = 0) -> tuple[bool, list]:
    if isinstance(value, list):
        return True, value
    if not isinstance(value, Mapping) or depth >= 3:
        return False, []
    for key in keys:
        if key not in value:
            continue
        recognized, items = _list_envelope(value[key], keys, depth + 1)
        if recognized:
            return True, items
    return False, []


def _object_envelope(
    value,
    keys: tuple[str, ...],
    depth: int = 0,
) -> Mapping | None:
    if not isinstance(value, Mapping) or depth >= 3:
        return None
    for key in keys:
        nested = value.get(key)
        if isinstance(nested, Mapping):
            return _object_envelope(nested, keys, depth + 1) or nested
    return value


def _normalize_work_item_type_response(result) -> tuple[bool, list[dict]]:
    successful, body = _successful_body(result)
    if not successful:
        return False, []
    recognized, items = _list_envelope(
        body,
        ("workItemTypes", "items", "content", "data", "result"),
    )
    if not recognized:
        return False, []
    normalized = []
    for item in items:
        if not isinstance(item, Mapping) or not _text(item.get("identifier")):
            return False, []
        projected = dict(item)
        projected["identifier"] = _text(item.get("identifier"))
        projected["category"] = _text(
            item.get("category") or item.get("wiCategory")
        )
        normalized.append(projected)
    return True, normalized


def _normalize_field_response(result) -> tuple[bool, list[dict]]:
    successful, body = _successful_body(result)
    if not successful:
        return False, []
    recognized, items = _list_envelope(
        body,
        ("workItemTypeFields", "fields", "items", "content", "data", "result"),
    )
    if not recognized:
        envelope = _object_envelope(
            body,
            ("workItemTypeFields", "fields", "content", "data", "result"),
        )
        if not isinstance(envelope, Mapping):
            return False, []
        grouped = []
        group_found = False
        for key, field_type in (
            ("customFields", "custom"),
            ("virtualFields", "virtual"),
        ):
            if key not in envelope:
                continue
            group_found = True
            values = envelope[key]
            if not isinstance(values, list):
                return False, []
            for value in values:
                if not isinstance(value, Mapping):
                    return False, []
                grouped.append({**value, "fieldType": field_type})
        if not group_found:
            return False, []
        items = grouped
    normalized = []
    for item in items:
        if not isinstance(item, Mapping):
            return False, []
        identifier = _text(
            item.get("fieldIdentifier") or item.get("identifier")
        )
        if not identifier:
            return False, []
        projected = dict(item)
        projected["fieldIdentifier"] = identifier
        field_type = _field_type(item)
        if field_type:
            projected["fieldType"] = field_type
        if "fieldEditPolicy" not in projected and "updateMode" in item:
            projected["fieldEditPolicy"] = item.get("updateMode")
        projected["associated"] = bool(item.get("associated", True))
        normalized.append(projected)
    return True, normalized


def _normalize_relation_response(
    result,
    work_item_type_identifier: str,
) -> tuple[bool, list[dict]]:
    successful, body = _successful_body(result)
    if not successful:
        if (
            isinstance(result, Mapping)
            and result.get("status") == 400
            and isinstance(body := result.get("body"), Mapping)
            and body.get("errorMessages")
            == ["The work item type does not have a defined network"]
        ):
            return True, []
        return False, []
    recognized, items = _list_envelope(
        body,
        ("relations", "relatedItemTypes", "items", "content", "data", "result"),
    )
    if recognized:
        relations = []
        for item in items:
            if (
                not isinstance(item, Mapping)
                or not _text(item.get("childTypeIdentifier"))
                or not _text(item.get("relationTypeIdentifier"))
            ):
                return False, []
            relations.append(dict(item))
        return True, relations

    graph = _object_envelope(body, ("content", "data", "result"))
    if not isinstance(graph, Mapping):
        return False, []
    nodes = graph.get("nodes")
    edges = graph.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        return False, []
    node_by_id = {}
    matching_root_ids = []
    for node in nodes:
        if (
            not isinstance(node, Mapping)
            or "nodeId" not in node
            or not _text(node.get("identifier"))
        ):
            return False, []
        node_id = node["nodeId"]
        if node_id in node_by_id:
            return False, []
        node_by_id[node_id] = node
        if _text(node.get("identifier")) == work_item_type_identifier:
            matching_root_ids.append(node_id)
    root_id = graph.get("rootId")
    if root_id not in node_by_id:
        if len(matching_root_ids) != 1:
            return False, []
        root_id = matching_root_ids[0]

    relations = []
    for edge in edges:
        if not isinstance(edge, Mapping):
            return False, []
        if edge.get("from") != root_id:
            continue
        child = node_by_id.get(edge.get("to"))
        relation_identifier = _text(
            edge.get("relationTypeIdentifier") or edge.get("relationId")
        )
        if child is None or not relation_identifier:
            return False, []
        relation = {
            "childTypeIdentifier": _text(child.get("identifier")),
            "relationTypeIdentifier": relation_identifier,
        }
        for key in (
            "relationsAudit",
            "isConsolidatingPair",
            "consolidationMode",
        ):
            if key in edge:
                relation[key] = edge[key]
        relations.append(relation)
    return True, relations


def _validated_presentation_steps(plan: Mapping) -> tuple[list[dict], dict | None]:
    steps = plan.get("steps")
    if not isinstance(steps, list):
        return [], {
            "code": "invalid_step_route",
            "message": "plan steps must be a list",
        }
    identifier = _text(
        plan.get("specification", {}).get("workItemTypeIdentifier")
        if isinstance(plan.get("specification"), Mapping) else None
    )
    routes = required_presentation_routes(identifier or None)["writes"]
    allowed = {
        "work-item-type.presentation": {
            "operationId": "updateWorkItemType",
            "method": "POST",
            "path": routes["presentation"]["path"],
        },
        "work-item-type.fields": {
            "operationId": "updateWorkItemTypeFields",
            "method": "PUT",
            "path": routes["fields"]["path"],
        },
    }
    ids = []
    for step in steps:
        if not isinstance(step, Mapping):
            return [], {
                "code": "invalid_step_route",
                "message": "each plan step must be an object",
            }
        step_id = step.get("id")
        expected = allowed.get(step_id)
        if expected is None or step_id in ids:
            return [], {
                "code": "invalid_step_route",
                "message": "plan contains an unsupported or duplicate step",
            }
        if (
            step.get("adapter") != "extend-rest"
            or any(step.get(key) != value for key, value in expected.items())
            or not isinstance(step.get("body"), Mapping)
        ):
            return [], {
                "code": "invalid_step_route",
                "message": f"step {step_id!r} is outside the REST route allowlist",
            }
        ids.append(step_id)

    canonical_ids = [
        step_id for step_id in allowed
        if step_id in ids
    ]
    if ids != canonical_ids:
        return [], {
            "code": "invalid_step_order",
            "message": (
                "updateWorkItemType must precede updateWorkItemTypeFields"
            ),
        }
    expected_dependencies = {
        "work-item-type.presentation": [],
        "work-item-type.fields": (
            ["work-item-type.presentation"]
            if "work-item-type.presentation" in ids else []
        ),
    }
    for step in steps:
        if step.get("dependsOn") != expected_dependencies[step["id"]]:
            return [], {
                "code": "invalid_step_order",
                "message": (
                    f"step {step['id']!r} has invalid dependencies"
                ),
            }
    field_step = next(
        (
            step for step in steps
            if step["id"] == "work-item-type.fields"
        ),
        None,
    )
    if field_step is not None:
        body = field_step["body"]
        field_count = sum(
            len(body.get(key, []))
            for key in ("customFields", "virtualFields")
            if isinstance(body.get(key, []), list)
        )
        if field_count > FIELD_UPDATE_LIMIT:
            return [], {
                "code": "invalid_step_route",
                "message": (
                    "updateWorkItemTypeFields exceeds the 20-field limit"
                ),
            }
    return [dict(step) for step in steps], None


def _normalize_specification(value: Mapping, errors: list[dict]) -> dict:
    if not isinstance(value, Mapping):
        errors.append({
            "code": "invalid_specification",
            "message": "specification must be an object",
        })
        value = {}
    identifier = _text(value.get("workItemTypeIdentifier"))
    if _has_legacy_case_type_marker(value):
        errors.append({
            "code": "legacy_case_type_unsupported",
            "message": "legacy CaseType metadata is not supported",
        })
    if not identifier:
        errors.append({
            "code": "missing_work_item_type_identifier",
            "message": "workItemTypeIdentifier is required",
        })

    widget = _normalize_widget_list(
        value.get("detailsWidgetFields", []),
        errors,
        "specification.detailsWidgetFields",
        assign_order=True,
    )
    relations = _normalize_relation_list(
        value.get("relatedItemTypes", []),
        errors,
        "specification.relatedItemTypes",
    )
    policies = _normalize_policy_list(value.get("fieldPolicies", []), errors)
    alert_fields = _normalize_alert_field_list(
        value.get("alertTypeFields", []), errors
    )
    return {
        "workItemTypeIdentifier": identifier,
        "detailsWidgetFields": widget,
        "relatedItemTypes": relations,
        "fieldPolicies": policies,
        "alertTypeFields": alert_fields,
    }


def _normalize_observation(value: Mapping, errors: list[dict]) -> dict:
    if not isinstance(value, Mapping):
        errors.append({
            "code": "invalid_observation",
            "message": "observation must be an object",
        })
        value = {}
    evidence_value = value.get("evidence")
    evidence = dict(evidence_value) if isinstance(evidence_value, Mapping) else {}
    work_item_types = []
    for item in _list(value.get("workItemTypes")):
        if not isinstance(item, Mapping):
            continue
        nested_flags = (
            item.get("flags")
            if isinstance(item.get("flags"), Mapping) else {}
        )
        flags = {
            key: (
                item[key]
                if key in item else nested_flags[key]
            )
            for key in (
                "isCaseItem",
                "isConsolidating",
                "isMappingRoot",
                "isRelatable",
            )
            if key in item or key in nested_flags
        }
        work_item_types.append({
            "identifier": _text(item.get("identifier")),
            "category": _text(
                item.get("category") or item.get("wiCategory")
            ),
            "flags": flags,
            "legacyCaseType": _has_legacy_case_type_marker(item),
            "supportsAlertTypeFields": bool(
                item.get("supportsAlertTypeFields", False)
            ),
            "supportsVisualStory": (
                item.get("supportsVisualStory")
                if isinstance(item.get("supportsVisualStory"), bool)
                else None
            ),
        })
    work_item_types.sort(key=lambda item: (
        item["identifier"],
        item["category"],
    ))

    fields = []
    for item in _list(value.get("fields")):
        if not isinstance(item, Mapping):
            continue
        field_type = _field_type(item)
        fields.append({
            "fieldIdentifier": _text(
                item.get("fieldIdentifier") or item.get("identifier")
            ),
            "fieldType": field_type,
            "mandatory": item.get("mandatory"),
            "fieldEditPolicy": (
                item.get("fieldEditPolicy")
                if "fieldEditPolicy" in item
                else item.get("updateMode")
            ),
            "updatable": item.get("updatable"),
            "associated": bool(item.get("associated", True)),
            "defaultValue": item.get("defaultValue"),
            "isCachable": item.get("isCachable"),
            "consolidationAggregationType": item.get(
                "consolidationAggregationType"
            ),
        })
    fields.sort(key=lambda item: item["fieldIdentifier"])

    widget_source = value.get("detailsWidgetFields")
    if widget_source is None:
        widget_source = _widget_from_fields(value.get("fields"))
    widget_errors: list[dict] = []
    widget = _normalize_widget_list(
        widget_source or [],
        widget_errors,
        "observation.detailsWidgetFields",
        assign_order=False,
    )
    if widget_errors and evidence.get("getworkItemTypesFields"):
        errors.extend(widget_errors)

    relations = _normalize_relation_list(
        value.get("relations", []),
        errors if evidence.get("getWorkItemTypesRelations") else [],
        "observation.relations",
    )
    return {
        "environment": (
            _text(value.get("environment")) or _DEFAULT_ENVIRONMENT
        ),
        "targetBuild": (
            _text(value.get("targetBuild")) or _UNKNOWN_BUILD
        ),
        "evidence": {
            "getWorkItemTypes": evidence.get("getWorkItemTypes") is True,
            "getworkItemTypesFields": (
                evidence.get("getworkItemTypesFields") is True
            ),
            "getWorkItemTypesRelations": (
                evidence.get("getWorkItemTypesRelations") is True
            ),
            "rendererDiscovery": evidence.get("rendererDiscovery") is True,
        },
        "workItemTypes": work_item_types,
        "fields": fields,
        "detailsWidgetFields": widget,
        "relations": relations,
        "renderers": _normalize_reference_list(value.get("renderers")),
    }


def _validate_evidence(spec: dict, observed: dict, errors: list[dict]) -> None:
    evidence = observed["evidence"]
    required = [
        ("getWorkItemTypes", "unknown_work_item_types_state"),
        ("getworkItemTypesFields", "unknown_fields_state"),
        ("getWorkItemTypesRelations", "unknown_relations_state"),
    ]
    for evidence_name, code in required:
        if not evidence[evidence_name]:
            errors.append({
                "code": code,
                "message": f"{evidence_name} evidence is missing or incomplete",
            })
    has_references = any(
        item.get("columnDisplayFormatterIdentifier")
        for item in spec["detailsWidgetFields"]
    )
    if has_references and not evidence["rendererDiscovery"]:
        errors.append({
            "code": "unknown_renderer_state",
            "message": (
                "renderer discovery evidence is required for renderer "
                "references"
            ),
        })


def _find_work_item_type(
    spec: dict,
    observed: dict,
    errors: list[dict],
) -> dict | None:
    if not observed["evidence"]["getWorkItemTypes"]:
        return None
    matches = [
        item for item in observed["workItemTypes"]
        if item["identifier"] == spec["workItemTypeIdentifier"]
    ]
    if len(matches) != 1:
        errors.append({
            "code": "work_item_type_not_confirmed",
            "message": "work item type must exist exactly once in observation",
            "identifier": spec["workItemTypeIdentifier"],
            "matches": len(matches),
        })
        return None
    if matches[0]["legacyCaseType"]:
        errors.append({
            "code": "legacy_case_type_unsupported",
            "message": "observed work item is a legacy CaseType",
        })
    return matches[0]


def _validate_observed_widget_fields(
    observed: dict,
    fields: dict[str, dict],
    errors: list[dict],
) -> None:
    if not observed["evidence"]["getworkItemTypesFields"]:
        return
    inconsistent = sorted(
        item["fieldIdentifier"]
        for item in observed["detailsWidgetFields"]
        if item["fieldIdentifier"] not in fields
    )
    if inconsistent:
        errors.append({
            "code": "inconsistent_fields_observation",
            "message": "details widget contains fields absent from field evidence",
            "fields": inconsistent,
        })


def _validate_references(
    spec: dict,
    observed: dict,
    conflicts: list[dict],
) -> None:
    if not observed["evidence"]["rendererDiscovery"]:
        return
    renderers = set(observed["renderers"])
    for item in spec["detailsWidgetFields"]:
        renderer = item.get("columnDisplayFormatterIdentifier")
        if renderer and renderer not in renderers:
            conflicts.append({
                "component": "detailsWidgetDisplay",
                "fieldIdentifier": item["fieldIdentifier"],
                "reason": "renderer reference is not confirmed by observation",
                "reference": renderer,
            })


def _validate_widget_formatter_rules(
    spec: dict,
    observed: dict,
    conflicts: list[dict],
) -> None:
    current = {
        item["fieldIdentifier"]
        for item in observed["detailsWidgetFields"]
    }
    for item in spec["detailsWidgetFields"]:
        if (
            item["fieldIdentifier"] not in current
            and not item.get("columnDisplayFormatterIdentifier")
        ):
            conflicts.append({
                "component": "detailsWidgetDisplay",
                "fieldIdentifier": item["fieldIdentifier"],
                "reason": (
                    "columnDisplayFormatterIdentifier is required when "
                    "adding a details widget field"
                ),
            })


def _validate_details_widget_support(
    spec: dict,
    observed: dict,
    work_item_type: dict | None,
    conflicts: list[dict],
) -> None:
    desired = spec["detailsWidgetFields"]
    current = observed["detailsWidgetFields"]
    if (
        desired != current
        and isinstance(work_item_type, Mapping)
        and work_item_type.get("supportsVisualStory") is False
    ):
        conflicts.append({
            "component": "detailsWidgetDisplay",
            "reason": (
                "work item type does not have Entity Insights/Details widget "
                "enabled"
            ),
        })


def _validate_desired_fields(
    spec: dict,
    fields: dict[str, dict],
    conflicts: list[dict],
) -> None:
    components = [
        ("detailsWidgetDisplay", spec["detailsWidgetFields"]),
        ("fieldPolicy", spec["fieldPolicies"]),
        ("alertTypeFields", spec["alertTypeFields"]),
    ]
    seen = set()
    for component, items in components:
        for item in items:
            key = (component, item["fieldIdentifier"])
            if key in seen or item["fieldIdentifier"] in fields:
                seen.add(key)
                continue
            conflicts.append({
                "component": component,
                "fieldIdentifier": item["fieldIdentifier"],
                "reason": "field is not confirmed on the work item type",
            })
            seen.add(key)


def _plan_widget(
    spec: dict,
    observed: dict,
    changes: dict,
) -> dict:
    desired = {
        item["fieldIdentifier"]: item
        for item in spec["detailsWidgetFields"]
    }
    current = {
        item["fieldIdentifier"]: item
        for item in observed["detailsWidgetFields"]
    }
    for identifier in sorted(set(current) - set(desired)):
        changes["conflict"].append({
            "component": "detailsWidgetDisplay",
            "fieldIdentifier": identifier,
            "reason": "details widget field removal is not supported",
        })

    additions = []
    updates = []
    for identifier in sorted(desired):
        expected = desired[identifier]
        actual = current.get(identifier)
        if actual is None:
            changes["create"].append({
                "component": "detailsWidgetDisplay",
                "fieldIdentifier": identifier,
            })
            additions.append(dict(expected))
            continue
        changed_attributes = [
            key for key in (
                "columnDisplayFormatterIdentifier",
                "columnFormat",
                "displayOrder",
            )
            if key in expected and expected.get(key) != actual.get(key)
        ]
        if not changed_attributes:
            changes["reuse"].append({
                "component": "detailsWidgetDisplay",
                "fieldIdentifier": identifier,
            })
            continue
        changes["update"].append({
            "component": "detailsWidgetDisplay",
            "fieldIdentifier": identifier,
            "attributes": changed_attributes,
        })
        update = {"fieldIdentifier": identifier}
        for key in changed_attributes:
            update[key] = expected.get(key)
        updates.append(update)
    result = {}
    if additions:
        result["add"] = additions
    if updates:
        result["update"] = updates
    return result


def _plan_relations(
    spec: dict,
    observed: dict,
    changes: dict,
) -> dict:
    desired = {_relation_identity(item): item for item in spec["relatedItemTypes"]}
    current = {_relation_identity(item): item for item in observed["relations"]}
    desired_by_child = {
        item["childTypeIdentifier"]: item
        for item in spec["relatedItemTypes"]
    }
    current_by_child = {
        item["childTypeIdentifier"]: item
        for item in observed["relations"]
    }

    identity_conflicts = set()
    for identity, actual in sorted(current.items()):
        if identity in desired:
            continue
        child = actual["childTypeIdentifier"]
        if child in desired_by_child:
            expected = desired_by_child[child]
            changes["conflict"].append({
                "component": "relatedItemTypes",
                "childTypeIdentifier": child,
                "relationTypeIdentifier": actual["relationTypeIdentifier"],
                "desiredRelationTypeIdentifier": expected[
                    "relationTypeIdentifier"
                ],
                "reason": "changing relation identity is not supported",
            })
            identity_conflicts.add(child)
        else:
            changes["conflict"].append({
                "component": "relatedItemTypes",
                "childTypeIdentifier": child,
                "relationTypeIdentifier": actual["relationTypeIdentifier"],
                "reason": "relation removal is not supported",
            })

    additions = []
    for identity, expected in sorted(desired.items()):
        child = expected["childTypeIdentifier"]
        actual = current.get(identity)
        if actual is None:
            if child not in identity_conflicts and child not in current_by_child:
                changes["create"].append({
                    "component": "relatedItemTypes",
                    "childTypeIdentifier": child,
                    "relationTypeIdentifier": expected[
                        "relationTypeIdentifier"
                    ],
                })
                additions.append(dict(expected))
            continue
        changed_attributes = [
            key for key in (
                "relationsAudit",
                "isConsolidatingPair",
                "consolidationMode",
            )
            if expected.get(key) != actual.get(key)
        ]
        if changed_attributes:
            changes["conflict"].append({
                "component": "relatedItemTypes",
                "childTypeIdentifier": child,
                "relationTypeIdentifier": expected["relationTypeIdentifier"],
                "reason": "existing relation attributes cannot be updated additively",
                "attributes": changed_attributes,
            })
        else:
            changes["reuse"].append({
                "component": "relatedItemTypes",
                "childTypeIdentifier": child,
                "relationTypeIdentifier": expected["relationTypeIdentifier"],
            })
    return {"add": additions} if additions else {}


def _plan_field_policies(
    policies: list[dict],
    fields: dict[str, dict],
    changes: dict,
    conflicts: list[dict],
    updates: dict[str, dict],
) -> None:
    for policy in policies:
        identifier = policy["fieldIdentifier"]
        current = fields.get(identifier)
        if current is None:
            continue
        if policy["fieldType"] != current["fieldType"]:
            conflicts.append({
                "component": "fieldPolicy",
                "fieldIdentifier": identifier,
                "reason": "desired field type does not match observed field type",
                "expected": policy["fieldType"],
                "actual": current["fieldType"],
            })
            continue
        changed_attributes = [
            key for key in ("fieldEditPolicy", "mandatory")
            if key in policy and policy[key] != current.get(key)
        ]
        if not changed_attributes:
            changes["reuse"].append({
                "component": "fieldPolicy",
                "fieldIdentifier": identifier,
            })
            continue
        changes["update"].append({
            "component": "fieldPolicy",
            "fieldIdentifier": identifier,
            "attributes": changed_attributes,
        })
        updates[identifier] = dict(policy)


def _plan_alert_type_fields(
    desired_fields: list[dict],
    fields: dict[str, dict],
    work_item_type: dict | None,
    changes: dict,
    conflicts: list[dict],
) -> list[dict]:
    if desired_fields and not (
        work_item_type
        and work_item_type.get("supportsAlertTypeFields")
    ):
        conflicts.append({
            "component": "alertTypeFields",
            "reason": (
                "alertTypeFields are not applicable to this work item type"
            ),
        })
        return []

    additions = []
    for desired in desired_fields:
        identifier = desired["fieldIdentifier"]
        current = fields.get(identifier)
        if current is None:
            continue
        if not current["associated"]:
            if current["fieldType"] != "custom":
                conflicts.append({
                    "component": "alertTypeFields",
                    "fieldIdentifier": identifier,
                    "reason": (
                        "only existing custom fields can be associated "
                        "through alertTypeFields"
                    ),
                })
                continue
            changes["create"].append({
                "component": "alertTypeFields",
                "fieldIdentifier": identifier,
            })
            addition = {"customizedFieldIdentifier": identifier}
            addition.update({
                key: value
                for key, value in desired.items()
                if key != "fieldIdentifier"
            })
            additions.append(addition)
            continue

        changed_attributes = [
            key for key in (
                "updatable",
                "mandatory",
                "defaultValue",
                "isCachable",
                "consolidationAggregationType",
            )
            if key in desired and desired[key] != current.get(key)
        ]
        if changed_attributes:
            conflicts.append({
                "component": "alertTypeFields",
                "fieldIdentifier": identifier,
                "reason": (
                    "existing alert type field attributes cannot be changed "
                    "by the additive operation"
                ),
                "attributes": changed_attributes,
            })
        else:
            changes["reuse"].append({
                "component": "alertTypeFields",
                "fieldIdentifier": identifier,
            })
    return additions


def _field_update_body(updates: dict[str, dict]) -> dict:
    grouped = {"customFields": [], "virtualFields": []}
    for identifier in sorted(updates):
        update = updates[identifier]
        item = {"fieldIdentifier": identifier}
        for key in ("mandatory", "fieldEditPolicy"):
            if key in update:
                item[key] = update[key]
        key = (
            "virtualFields"
            if update.get("fieldType") == "virtual"
            else "customFields"
        )
        grouped[key].append(item)
    return {key: value for key, value in grouped.items() if value}


def _normalize_widget_list(
    value,
    errors: list[dict],
    location: str,
    *,
    assign_order: bool,
) -> list[dict]:
    result = []
    seen = set()
    seen_orders = set()
    for index, raw in enumerate(_list(value), 1):
        if not isinstance(raw, Mapping):
            errors.append({
                "code": "invalid_widget_field",
                "message": f"{location}[{index - 1}] must be an object",
            })
            continue
        unknown = sorted(set(raw) - _WIDGET_KEYS)
        if unknown:
            errors.append({
                "code": "unsupported_widget_attributes",
                "message": "details widget contains unsupported attributes",
                "attributes": unknown,
            })
        identifier = _text(raw.get("fieldIdentifier"))
        if not identifier or identifier in seen:
            errors.append({
                "code": "invalid_widget_field_identifier",
                "message": "details widget field identifiers must be unique",
                "fieldIdentifier": identifier or None,
            })
            continue
        order = raw.get("displayOrder")
        if order is None and assign_order:
            order = index
        if not isinstance(order, int) or isinstance(order, bool) or order < 1:
            errors.append({
                "code": "invalid_widget_display_order",
                "message": "displayOrder must be a positive integer",
                "fieldIdentifier": identifier,
            })
            continue
        if order in seen_orders:
            errors.append({
                "code": "duplicate_widget_display_order",
                "message": "details widget displayOrder values must be unique",
                "displayOrder": order,
            })
            continue
        item = {"fieldIdentifier": identifier}
        for key in (
            "columnDisplayFormatterIdentifier",
            "columnFormat",
        ):
            if raw.get(key) not in (None, ""):
                item[key] = _text(raw.get(key))
        item["displayOrder"] = order
        result.append(item)
        seen.add(identifier)
        seen_orders.add(order)
    return sorted(result, key=lambda item: (
        item["fieldIdentifier"],
        item["displayOrder"],
    ))


def _normalize_relation_list(
    value,
    errors: list[dict],
    location: str,
) -> list[dict]:
    result = []
    identities = set()
    children = set()
    for index, raw in enumerate(_list(value)):
        if not isinstance(raw, Mapping):
            errors.append({
                "code": "invalid_relation",
                "message": f"{location}[{index}] must be an object",
            })
            continue
        unknown = sorted(set(raw) - _RELATION_KEYS)
        if unknown:
            errors.append({
                "code": "unsupported_relation_attributes",
                "message": "relation contains unsupported attributes",
                "attributes": unknown,
            })
        item = {
            "childTypeIdentifier": _text(
                raw.get("childTypeIdentifier")
            ),
            "relationTypeIdentifier": _text(
                raw.get("relationTypeIdentifier")
            ),
            "relationsAudit": _text(
                raw.get("relationsAudit") or "Both"
            ),
            "isConsolidatingPair": bool(
                raw.get("isConsolidatingPair", False)
            ),
            "consolidationMode": _text(
                raw.get("consolidationMode") or "NONE"
            ),
        }
        identity = _relation_identity(item)
        child = item["childTypeIdentifier"]
        if not all(identity):
            errors.append({
                "code": "invalid_relation_identity",
                "message": (
                    "childTypeIdentifier and relationTypeIdentifier are required"
                ),
            })
            continue
        if identity in identities or child in children:
            errors.append({
                "code": "duplicate_relation_identity",
                "message": (
                    "each child type may have one desired relation identity"
                ),
                "childTypeIdentifier": child,
            })
            continue
        if item["relationsAudit"] not in {"Both", "Parent", "Child", "None"}:
            errors.append({
                "code": "invalid_relations_audit",
                "message": "relationsAudit is not supported",
                "actual": item["relationsAudit"],
            })
        identities.add(identity)
        children.add(child)
        result.append(item)
    return sorted(result, key=_relation_identity)


def _normalize_policy_list(value, errors: list[dict]) -> list[dict]:
    result = []
    seen = set()
    for index, raw in enumerate(_list(value)):
        if not isinstance(raw, Mapping):
            errors.append({
                "code": "invalid_field_policy",
                "message": f"fieldPolicies[{index}] must be an object",
            })
            continue
        unknown = sorted(set(raw) - _FIELD_POLICY_KEYS)
        if unknown:
            errors.append({
                "code": "unsupported_field_policy_attributes",
                "message": (
                    "only mandatory and fieldEditPolicy may be changed"
                ),
                "attributes": unknown,
            })
        identifier = _text(raw.get("fieldIdentifier"))
        field_type = _text(raw.get("fieldType")).lower()
        if not identifier or identifier in seen:
            errors.append({
                "code": "invalid_field_policy_identifier",
                "message": "field policy identifiers must be present and unique",
                "fieldIdentifier": identifier or None,
            })
            continue
        if field_type not in {"custom", "virtual"}:
            errors.append({
                "code": "invalid_field_type",
                "message": "fieldType must be custom or virtual",
                "fieldIdentifier": identifier,
            })
        item = {
            "fieldIdentifier": identifier,
            "fieldType": field_type,
        }
        for key in ("mandatory", "fieldEditPolicy"):
            if key in raw:
                item[key] = raw[key]
        if len(item) == 2:
            errors.append({
                "code": "empty_field_policy_update",
                "message": (
                    "mandatory or fieldEditPolicy is required for each field"
                ),
                "fieldIdentifier": identifier,
            })
        _validate_policy_values(item, errors)
        result.append(item)
        seen.add(identifier)
    return sorted(result, key=lambda item: item["fieldIdentifier"])


def _normalize_alert_field_list(value, errors: list[dict]) -> list[dict]:
    result = []
    seen = set()
    for index, raw in enumerate(_list(value)):
        if not isinstance(raw, Mapping):
            errors.append({
                "code": "invalid_alert_type_field",
                "message": f"alertTypeFields[{index}] must be an object",
            })
            continue
        unknown = sorted(set(raw) - _ALERT_FIELD_KEYS)
        if unknown:
            errors.append({
                "code": "unsupported_alert_type_field_attributes",
                "message": "alert type field contains unsupported attributes",
                "attributes": unknown,
            })
        identifier = _text(raw.get("fieldIdentifier"))
        if not identifier or identifier in seen:
            errors.append({
                "code": "invalid_alert_type_field_identifier",
                "message": (
                    "alert type field identifiers must be present and unique"
                ),
                "fieldIdentifier": identifier or None,
            })
            continue
        item = {"fieldIdentifier": identifier}
        for key in sorted(_ALERT_FIELD_KEYS - {"fieldIdentifier"}):
            if key in raw:
                item[key] = raw[key]
        result.append(item)
        seen.add(identifier)
    return sorted(result, key=lambda item: item["fieldIdentifier"])


def _validate_policy_values(item: dict, errors: list[dict]) -> None:
    identifier = item["fieldIdentifier"]
    if "mandatory" in item and not isinstance(item["mandatory"], bool):
        errors.append({
            "code": "invalid_mandatory_value",
            "message": "mandatory must be boolean",
            "fieldIdentifier": identifier,
        })
    if item["fieldType"] == "virtual" and "mandatory" in item:
        errors.append({
            "code": "virtual_field_mandatory_unsupported",
            "message": "mandatory is not supported for virtual fields",
            "fieldIdentifier": identifier,
        })
    if "fieldEditPolicy" not in item:
        return
    allowed = (
        _VIRTUAL_POLICIES
        if item["fieldType"] == "virtual"
        else _CUSTOM_POLICIES
    )
    if item["fieldEditPolicy"] not in allowed:
        errors.append({
            "code": "invalid_field_edit_policy",
            "message": "fieldEditPolicy is not supported for this field type",
            "fieldIdentifier": identifier,
            "actual": item["fieldEditPolicy"],
        })


def _widget_from_fields(value) -> list:
    result = []
    for raw in _list(value):
        if not isinstance(raw, Mapping):
            continue
        display = raw.get("detailsWidgetDisplay")
        if not isinstance(display, Mapping):
            continue
        if display.get("visible") is False:
            continue
        item = {
            "fieldIdentifier": (
                raw.get("fieldIdentifier") or raw.get("identifier")
            ),
            "displayOrder": (
                display.get("displayOrder")
                if "displayOrder" in display
                else display.get("order")
            ),
        }
        for key in (
            "columnDisplayFormatterIdentifier",
            "columnFormat",
        ):
            if key in display:
                item[key] = display[key]
        if "format" in display and "columnFormat" not in item:
            item["columnFormat"] = display["format"]
        result.append(item)
    return result


def _normalize_reference_list(value) -> list[str]:
    references = set()
    for item in _list(value):
        if isinstance(item, Mapping):
            identifier = _text(
                item.get("identifier")
                or item.get("name")
                or item.get("value")
            )
        else:
            identifier = _text(item)
        if identifier:
            references.add(identifier)
    return sorted(references)


def _field_type(item: Mapping) -> str:
    explicit = _text(item.get("fieldType")).lower()
    if explicit:
        return explicit
    if item.get("virtual") is True:
        return "virtual"
    if item.get("custom") is True:
        return "custom"
    return ""


def _has_legacy_case_type_marker(value: Mapping) -> bool:
    if value.get("legacyCaseType") is True:
        return True
    return any(
        _text(value.get(key)) == LEGACY_OBJECT_TYPE
        for key in ("legacyType", "objectType", "schemaType", "type")
    )


def _presentation_verification_text(body: dict) -> str:
    if "detailsWidgetDisplay" in body:
        return "details widget fields exactly match desired presentation"
    if "relatedItemTypes" in body:
        return "desired relation identities and attributes are present"
    return "desired alert type field associations are present"


def _relation_identity(item: Mapping) -> tuple[str, str]:
    return (
        _text(item.get("childTypeIdentifier")),
        _text(item.get("relationTypeIdentifier")),
    )


def _fingerprint(value) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _list(value) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _text(value) -> str:
    return str(value).strip() if value is not None else ""
