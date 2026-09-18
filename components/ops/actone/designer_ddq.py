"""Pure planning and verification for ActOne DrillDownQuery definitions."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from xml.sax.saxutils import escape
from xml.etree import ElementTree


CAPABILITY_ID = "manage_drill_down_query"
OBJECT_TYPE = "DrillDownQuery"

_SUPPORTED_EXTRAS = {
    "defaultValues",
    "prepared",
    "searchParameters",
    "subTitle",
    "webUiConfigurable",
}
_BOOLEAN_FIELDS = {
    "prepared",
    "secured",
    "sortable",
    "webAccessible",
    "webUiConfigurable",
}
_INTEGER_FIELDS = {"connectionId", "pageSize", "rowFormat"}

__all__ = [
    "CAPABILITY_ID",
    "DrillDownQueryPlanError",
    "apply_drill_down_query_plan",
    "build_ddq_reference_evidence",
    "collect_drill_down_query_observation",
    "fingerprint_drill_down_query_plan",
    "manage_drill_down_query",
    "merge_ddq_apply_evidence",
    "normalize_ddq_fields",
    "normalize_ddq_specification",
    "plan_drill_down_query",
    "verify_drill_down_query",
    "verify_drill_down_query_plan",
]


class DrillDownQueryPlanError(ValueError):
    """The desired DDQ specification is invalid."""


_INTERNAL_CONNECTION_SOURCES = {"documented", "live-evidenced"}
_REST_CONNECTION_OPERATIONS = {"getConnection", "getConnections"}


def normalize_ddq_fields(fields: dict) -> dict:
    """Apply the runtime-required DDQ display defaults in place."""
    fields.setdefault("rowFormat", 0)
    fields.setdefault("sortable", False)
    columns = [
        value.strip()
        for value in str(fields.get("columnNames", "")).split(",")
        if value.strip()
    ]
    if columns and not str(fields.get("columnWidths", "")).strip():
        fields["columnWidths"] = ",".join(["100"] * len(columns))
    return fields


def normalize_ddq_specification(specification: Mapping) -> dict:
    """Validate and canonicalize a domain-level DDQ specification."""
    if not isinstance(specification, Mapping):
        raise DrillDownQueryPlanError("DDQ specification must be an object")

    allowed = {
        "identifier",
        "name",
        "description",
        "sqlQuery",
        "connectionId",
        "connectionIdentifier",
        "pageTitle",
        "parameterNames",
        "parameters",
        "parameterTypes",
        "columnNames",
        "columnWidths",
        "pageSize",
        "webAccessible",
        "secured",
        "sortable",
        "rowFormat",
        "extras",
        *_SUPPORTED_EXTRAS,
    }
    unknown = sorted(set(specification) - allowed)
    if unknown:
        raise DrillDownQueryPlanError(
            "unsupported DDQ fields: %s" % ", ".join(map(str, unknown))
        )

    identifier = _required_text(specification, "identifier")
    sql_query = _required_text(specification, "sqlQuery")
    connection_id = specification.get("connectionId")
    if isinstance(connection_id, bool) or not isinstance(connection_id, int):
        raise DrillDownQueryPlanError("DDQ requires integer connectionId")

    parameter_names = _csv_text(
        specification.get("parameterNames", specification.get("parameters", ""))
    )
    parameter_types = _csv_text(specification.get("parameterTypes", ""))
    if _csv_values(parameter_names) or _csv_values(parameter_types):
        if len(_csv_values(parameter_names)) != len(_csv_values(parameter_types)):
            raise DrillDownQueryPlanError(
                "parameterNames and parameterTypes must have equal element counts"
            )

    column_names = _csv_text(specification.get("columnNames", ""))
    column_widths = _csv_text(specification.get("columnWidths", ""))
    display_fields = normalize_ddq_fields(
        {
            "columnNames": column_names,
            "columnWidths": column_widths,
            "rowFormat": specification.get("rowFormat", 0),
            "sortable": specification.get("sortable", False),
        }
    )
    if _csv_values(display_fields["columnWidths"]) and (
        len(_csv_values(display_fields["columnWidths"]))
        != len(_csv_values(display_fields["columnNames"]))
    ):
        raise DrillDownQueryPlanError(
            "columnWidths must have the same element count as columnNames"
        )

    result = {
        "identifier": identifier,
        "name": str(specification.get("name") or identifier),
        "description": str(specification.get("description") or ""),
        "sqlQuery": sql_query,
        "connectionId": connection_id,
        "pageTitle": str(specification.get("pageTitle") or ""),
        "parameterNames": parameter_names,
        "parameterTypes": parameter_types,
        "columnNames": display_fields["columnNames"],
        "columnWidths": display_fields["columnWidths"],
        "webAccessible": _required_bool(
            specification.get("webAccessible", True), "webAccessible"
        ),
        "secured": _required_bool(specification.get("secured", False), "secured"),
        "sortable": _required_bool(display_fields["sortable"], "sortable"),
        "rowFormat": _required_int(display_fields["rowFormat"], "rowFormat"),
    }
    if "connectionIdentifier" in specification:
        result["connectionIdentifier"] = _required_text(
            specification, "connectionIdentifier"
        )
    if "pageSize" in specification:
        result["pageSize"] = _required_int(specification["pageSize"], "pageSize")

    raw_extras = specification.get("extras", {})
    if raw_extras is None:
        raw_extras = {}
    if not isinstance(raw_extras, Mapping):
        raise DrillDownQueryPlanError("DDQ extras must be an object")
    unknown_extras = sorted(set(raw_extras) - _SUPPORTED_EXTRAS)
    if unknown_extras:
        raise DrillDownQueryPlanError(
            "unsupported DDQ extras: %s" % ", ".join(unknown_extras)
        )
    extras = {
        key: specification[key] for key in _SUPPORTED_EXTRAS if key in specification
    }
    extras.update(raw_extras)
    for key in sorted(extras):
        value = extras[key]
        if key in _BOOLEAN_FIELDS:
            result[key] = _required_bool(value, key)
        else:
            result[key] = str(value or "")
    return result


def collect_drill_down_query_observation(
    designer_client,
    rest_registry,
    rest_client,
    specification,
    reference_evidence=None,
) -> dict:
    """Collect the normalized, secret-free state required by the DDQ planner.

    ``reference_evidence`` may be a direct ``{"known", "count"}`` reference
    fact, or an envelope containing ``references`` and ``connection``. External
    connection evidence requires ``connectionId``, ``trusted=True``, and a
    non-REST ``source``. The built-in ``-1`` connection instead requires
    ``internal=True`` and ``source`` equal to ``documented`` or
    ``live-evidenced``; valid internal evidence is authoritative and bypasses
    the external REST connection lookup.
    """
    spec = normalize_ddq_specification(specification)
    logical_identifier = spec.get("connectionIdentifier")
    if spec["connectionId"] != -1 and not logical_identifier:
        raise DrillDownQueryPlanError(
            "observation collection requires connectionIdentifier"
        )

    infos = _result_items(designer_client.get_object_info_list(OBJECT_TYPE))
    present = spec["identifier"] in {
        identifier for item in infos if (identifier := _identifier(item))
    }
    query = None
    if present:
        query_result = designer_client.get_object(OBJECT_TYPE, spec["identifier"])
        query = _result_out(query_result)
        if not isinstance(query, Mapping):
            raise DrillDownQueryPlanError(
                "DrillDownQuery %r read returned no object" % spec["identifier"]
            )
        query = dict(query)

    references, numeric_evidence = _split_reference_evidence(reference_evidence)

    if spec["connectionId"] == -1:
        if _valid_internal_connection_evidence(numeric_evidence):
            internal_source = numeric_evidence.get(
                "numericIdSource", numeric_evidence.get("source")
            )
            connection = {
                "exists": True,
                "identifier": logical_identifier,
                "source": internal_source,
                "connectionId": -1,
                "internal": True,
                "numericIdTrusted": True,
                "numericIdSource": internal_source,
            }
        else:
            connection = {
                "exists": None,
                "identifier": logical_identifier,
                "source": None,
            }
    else:
        rest_connection = _read_rest_connection(
            rest_registry,
            rest_client,
            logical_identifier,
        )
        connection = {
            "exists": rest_connection["exists"],
            "identifier": logical_identifier,
            "source": rest_connection.get("source"),
        }
        trusted = _trusted_external_connection_evidence(numeric_evidence)
        if trusted is None and isinstance(query, Mapping):
            readback_id = _numeric_id(query.get("connectionId"))
            if readback_id is not None:
                trusted = {
                    "connectionId": readback_id,
                    "source": "designer-getObject",
                }
        if trusted is not None:
            connection.update(
                {
                    "connectionId": trusted["connectionId"],
                    "numericIdTrusted": True,
                    "numericIdSource": trusted["source"],
                }
            )

    observation = {"connection": connection, "query": query}
    if references is not None:
        observation["references"] = references
    return observation


def build_ddq_reference_evidence(
    specification,
    reference_evidence=None,
    *,
    internal_connection_evidence: bool = False,
    internal_connection_evidence_source: str | None = None,
):
    """Validate caller evidence and optionally add explicit internal-connection proof."""
    spec = normalize_ddq_specification(specification)
    if reference_evidence is None:
        evidence = {}
    elif isinstance(reference_evidence, Mapping):
        evidence = dict(reference_evidence)
    else:
        raise DrillDownQueryPlanError("DDQ reference evidence must be an object")

    references, connection = _split_reference_evidence(evidence)
    if "references" in evidence and not isinstance(evidence["references"], Mapping):
        raise DrillDownQueryPlanError("DDQ references evidence must be an object")
    if "connection" in evidence and not isinstance(evidence["connection"], Mapping):
        raise DrillDownQueryPlanError("DDQ connection evidence must be an object")
    if references is not None:
        known = references.get("known")
        count = references.get("count")
        if known not in (True, False, None):
            raise DrillDownQueryPlanError(
                "DDQ references known must be a boolean"
            )
        if known is True and (
            isinstance(count, bool)
            or not isinstance(count, int)
            or count < 0
        ):
            raise DrillDownQueryPlanError(
                "known DDQ reference evidence requires a non-negative count"
            )
    if connection is not None:
        connection_id = connection.get("connectionId")
        if connection_id is not None and _numeric_id(connection_id) is None:
            raise DrillDownQueryPlanError(
                "DDQ connection evidence connectionId must be an integer"
            )
        for key in ("trusted", "numericIdTrusted", "internal"):
            if key in connection and not isinstance(connection[key], bool):
                raise DrillDownQueryPlanError(
                    f"DDQ connection evidence {key} must be a boolean"
                )
        source = connection.get(
            "numericIdSource", connection.get("source")
        )
        if source is not None and (
            not isinstance(source, str) or not source.strip()
        ):
            raise DrillDownQueryPlanError(
                "DDQ connection evidence source must be non-empty text"
            )

    if internal_connection_evidence_source and not internal_connection_evidence:
        raise DrillDownQueryPlanError(
            "internal connection evidence source requires the explicit "
            "internal_connection_evidence flag"
        )
    if internal_connection_evidence:
        if spec["connectionId"] != -1:
            raise DrillDownQueryPlanError(
                "internal connection evidence is valid only for connectionId -1"
            )
        if connection is not None:
            raise DrillDownQueryPlanError(
                "provide either structured connection evidence or the explicit "
                "internal connection evidence flag, not both"
            )
        source = internal_connection_evidence_source or "documented"
        if source not in _INTERNAL_CONNECTION_SOURCES:
            raise DrillDownQueryPlanError(
                "internal connection evidence source must be documented or "
                "live-evidenced"
            )
        evidence["connection"] = {
            "connectionId": -1,
            "internal": True,
            "source": source,
        }
    return evidence or None


def _plan_fingerprint_payload(plan: Mapping) -> dict:
    return {
        key: value
        for key, value in plan.items()
        if key not in {
            "fingerprint",
            "planId",
            "warnings",
            "capabilityMaturity",
            "buildStatus",
            "contractStatus",
            "liveCertificationStatus",
        }
    }


def fingerprint_drill_down_query_plan(plan: Mapping) -> str:
    """Recompute the immutable fingerprint of a DDQ capability plan."""
    return _fingerprint(_plan_fingerprint_payload(plan))


def manage_drill_down_query(
    specification: Mapping,
    observation: Mapping,
    *,
    environment: str = "default",
    target_build: str = "unknown",
) -> dict:
    """Return a deterministic create/reuse/update/conflict DDQ plan."""
    spec = normalize_ddq_specification(specification)
    observed = observation if isinstance(observation, Mapping) else {}
    errors: list[dict] = []
    changes = {"create": [], "reuse": [], "update": [], "conflict": []}
    steps: list[dict] = []

    connection_evidence = _connection_evidence(spec, observed, errors)
    query_known, current = _observed_query(observed)
    if not query_known:
        errors.append(
            {
                "code": "query_observation_unknown",
                "message": "DDQ presence must be positively observed before planning",
            }
        )
    elif current is not None and not isinstance(current, Mapping):
        errors.append(
            {
                "code": "query_observation_malformed",
                "message": "observed query must be an object or null",
            }
        )

    desired_fields = _bean_fields(spec)
    if query_known and current is None:
        changes["create"].append(
            {
                "type": OBJECT_TYPE,
                "identifier": spec["identifier"],
            }
        )
        steps.append(_write_step("create", spec["identifier"], desired_fields))
    elif isinstance(current, Mapping):
        current_identifier = _identifier(current)
        if current_identifier and current_identifier != spec["identifier"]:
            changes["conflict"].append(
                {
                    "code": "identifier_mismatch",
                    "type": OBJECT_TYPE,
                    "identifier": spec["identifier"],
                    "reason": "observed DDQ has a different identifier",
                    "actualIdentifier": current_identifier,
                }
            )
        else:
            actual_fields = _project_saved_fields(current, desired_fields)
            differences = _field_differences(desired_fields, actual_fields)
            if not differences:
                changes["reuse"].append(
                    {
                        "type": OBJECT_TYPE,
                        "identifier": spec["identifier"],
                    }
                )
            elif "connectionId" in differences:
                changes["conflict"].append(
                    {
                        "code": "connection_change_unsupported",
                        "type": OBJECT_TYPE,
                        "identifier": spec["identifier"],
                        "reason": (
                            "changing an existing DDQ connection is not a safe update"
                        ),
                        "fields": ["connectionId"],
                    }
                )
            else:
                classifications = sorted(
                    {_change_classification(field) for field in differences}
                )
                references = _reference_safety(observed)
                update = {
                    "type": OBJECT_TYPE,
                    "identifier": spec["identifier"],
                    "fields": differences,
                    "classification": (
                        classifications[0] if len(classifications) == 1 else "mixed"
                    ),
                    "classifications": classifications,
                    "sqlChanged": "sqlQuery" in differences,
                }
                if references["known"] and references["count"] == 0:
                    changes["update"].append(update)
                    steps.append(
                        _write_step("update", spec["identifier"], desired_fields)
                    )
                else:
                    reason = (
                        "DDQ references are not positively known"
                        if not references["known"]
                        else "the existing DDQ has runtime or object references"
                    )
                    changes["conflict"].append(
                        {
                            "code": (
                                "reference_safety_unknown"
                                if not references["known"]
                                else "ddq_referenced"
                            ),
                            **update,
                            "reason": reason,
                            "referenceCount": references["count"],
                        }
                    )

    applicable = not errors and not changes["conflict"]
    if not applicable:
        steps = []
    observation_fingerprint = _fingerprint(_semantic_observation(spec, observed))
    plan_core = {
        "capability": CAPABILITY_ID,
        "environment": environment,
        "targetBuild": target_build,
        "specification": spec,
        "observationFingerprint": observation_fingerprint,
        "applicable": applicable,
        "routing": _routing(),
        "connectionEvidence": connection_evidence,
        "changes": changes,
        "steps": steps,
        "errors": errors,
    }
    fingerprint = fingerprint_drill_down_query_plan(plan_core)
    return {
        "planId": fingerprint[:16],
        "fingerprint": fingerprint,
        **plan_core,
        "warnings": [
            "The referenced JDBC connection is inspected and reused, never created.",
            "Updates require positive evidence of zero runtime/object references.",
        ],
    }


plan_drill_down_query = manage_drill_down_query


def apply_drill_down_query_plan(
    plan,
    designer_client,
    rest_registry,
    rest_client,
    environment,
    target_build,
    reference_evidence=None,
    runtime_request=None,
) -> dict:
    """Apply an intact, current DDQ plan and perform fresh readback checks."""
    from actone.designer import DesignerError
    from actone.invoke import InvokeError

    integrity_error = _plan_integrity_error(plan)
    if integrity_error:
        return {
            "ok": False,
            "error": "plan_tampered",
            "message": integrity_error,
            "planId": plan.get("planId") if isinstance(plan, Mapping) else None,
        }
    if plan.get("capability") != CAPABILITY_ID:
        return {"ok": False, "error": "unsupported_capability"}
    if (
        not isinstance(environment, str)
        or not environment
        or not isinstance(target_build, str)
        or not target_build
        or environment != plan.get("environment")
        or target_build != plan.get("targetBuild")
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
    conflicts = plan.get("changes", {}).get("conflict", [])
    errors = plan.get("errors", [])
    if plan.get("applicable") is not True or conflicts or errors:
        return {
            "ok": False,
            "error": "plan_not_applicable",
            "planId": plan.get("planId"),
            "errors": errors,
            "conflicts": conflicts,
        }
    route_error = _route_allowlist_error(plan)
    if route_error:
        return {
            "ok": False,
            "error": "unsupported_route",
            "message": route_error,
            "planId": plan.get("planId"),
        }
    try:
        run_params = _runtime_parameters(runtime_request, plan["specification"])
        effective_reference_evidence = merge_ddq_apply_evidence(
            plan, reference_evidence
        )
    except DrillDownQueryPlanError as exc:
        return {
            "ok": False,
            "error": "apply_input_invalid",
            "message": str(exc),
            "planId": plan.get("planId"),
        }

    try:
        current = collect_drill_down_query_observation(
            designer_client,
            rest_registry,
            rest_client,
            plan["specification"],
            reference_evidence=effective_reference_evidence,
        )
    except (
        DesignerError,
        InvokeError,
        DrillDownQueryPlanError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        return {
            "ok": False,
            "error": "observation_failed",
            "message": str(exc),
            "planId": plan.get("planId"),
        }
    current_fingerprint = _fingerprint(
        _semantic_observation(plan["specification"], current)
    )
    if current_fingerprint != plan.get("observationFingerprint"):
        return {
            "ok": False,
            "error": "plan_stale",
            "planId": plan.get("planId"),
            "expectedObservationFingerprint": plan.get("observationFingerprint"),
            "actualObservationFingerprint": current_fingerprint,
        }

    completed = []
    try:
        for step in plan.get("steps", []):
            if step["action"] == "create":
                result = designer_client.create_object(
                    OBJECT_TYPE, dict(step["fields"])
                )
            else:
                result = designer_client.update_typed_object(
                    OBJECT_TYPE,
                    step["identifier"],
                    dict(step["fields"]),
                )
            completed.append({"id": step["id"], "result": result})

        verification = _verify_drill_down_query_readback(
            plan,
            designer_client,
            rest_registry,
            rest_client,
            run_params,
        )
    except (
        DesignerError,
        InvokeError,
        DrillDownQueryPlanError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        return {
            "ok": False,
            "error": "verification_failed",
            "message": str(exc),
            "planId": plan.get("planId"),
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


def _verify_drill_down_query_readback(
    plan,
    designer_client,
    rest_registry,
    rest_client,
    run_params: Mapping,
) -> dict:
    identifier = plan["specification"]["identifier"]
    readback = _result_out(designer_client.get_object(OBJECT_TYPE, identifier))
    if not isinstance(readback, Mapping):
        raise DrillDownQueryPlanError(
            "fresh DrillDownQuery readback returned no object"
        )
    metadata_result = designer_client.call_operation(
        "commonService",
        "getDrillDownQueryMetadata",
        (
            '<drillDownQueryIdentifier xsi:type="xsd:string">%s'
            "</drillDownQueryIdentifier>"
        )
        % escape(identifier),
        out_param="metadataXML",
    )
    metadata = _result_out(metadata_result, "metadataXML")
    runtime = _invoke_rest(
        rest_registry,
        rest_client,
        "runDDQ",
        {
            "ddqIdentifier": identifier,
            **run_params,
        },
    )
    return verify_drill_down_query(
        plan,
        {"query": dict(readback), "metadata": metadata},
        runtime,
    )


def verify_drill_down_query_plan(
    plan,
    designer_client,
    rest_registry,
    rest_client,
    environment: str,
    target_build: str,
    runtime_request=None,
) -> dict:
    """Perform target-bound saved-definition, metadata, and runtime verification."""
    from actone.designer import DesignerError
    from actone.invoke import InvokeError

    integrity_error = _plan_integrity_error(plan)
    if integrity_error:
        return {
            "ok": False,
            "error": "plan_tampered",
            "message": integrity_error,
            "planId": plan.get("planId") if isinstance(plan, Mapping) else None,
        }
    if plan.get("capability") != CAPABILITY_ID:
        return {"ok": False, "error": "unsupported_capability"}
    if (
        not environment
        or not target_build
        or environment != plan.get("environment")
        or target_build != plan.get("targetBuild")
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
    if not plan.get("applicable"):
        return {
            "ok": False,
            "error": "plan_not_applicable",
            "planId": plan.get("planId"),
        }
    route_error = _route_allowlist_error(plan)
    if route_error:
        return {
            "ok": False,
            "error": "unsupported_route",
            "message": route_error,
            "planId": plan.get("planId"),
        }
    try:
        run_params = _runtime_parameters(runtime_request, plan["specification"])
        verification = _verify_drill_down_query_readback(
            plan,
            designer_client,
            rest_registry,
            rest_client,
            run_params,
        )
    except (
        DesignerError,
        DrillDownQueryPlanError,
        InvokeError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        return {
            "ok": False,
            "error": "verification_failed",
            "message": str(exc),
            "planId": plan.get("planId"),
        }
    return {
        **verification,
        "planId": plan.get("planId"),
    }


def verify_drill_down_query(
    plan: Mapping,
    post_observation: Mapping,
    runtime_result: Mapping | None = None,
) -> dict:
    """Verify saved DDQ fields, metadata columns, and optional runDDQ shape."""
    if not isinstance(plan, Mapping) or "specification" not in plan:
        raise DrillDownQueryPlanError(
            "verification requires a DDQ plan with specification"
        )
    integrity_error = _plan_integrity_error(plan)
    if integrity_error:
        raise DrillDownQueryPlanError(integrity_error)
    if plan.get("applicable") is not True:
        raise DrillDownQueryPlanError("plan is not applicable and cannot be verified")
    spec = normalize_ddq_specification(plan["specification"])
    observation = post_observation if isinstance(post_observation, Mapping) else {}
    desired_fields = _bean_fields(spec)
    assertions: list[dict] = []

    _, saved = _observed_query(observation)
    if isinstance(saved, Mapping):
        actual_fields = _project_saved_fields(saved, desired_fields)
        for field in desired_fields:
            _assertion(
                assertions,
                "saved.%s" % field,
                _comparable(field, desired_fields[field]),
                _comparable(field, actual_fields.get(field)),
            )
    else:
        _assertion(assertions, "saved.query", "present", "missing")

    expected_columns = _csv_values(desired_fields.get("columnNames", ""))
    if "metadata" in observation or "metadataColumns" in observation:
        metadata = observation.get("metadataColumns", observation.get("metadata"))
        _assertion(
            assertions,
            "metadata.columns",
            expected_columns,
            _metadata_columns(metadata),
        )
    else:
        _assertion(
            assertions,
            "metadata.columns",
            expected_columns,
            None,
        )

    if runtime_result is not None:
        valid, summary = _runtime_shape(runtime_result)
        assertions.append(
            {
                "name": "runtime.runDDQ.shape",
                "passed": valid,
                "expected": {
                    "successful": True,
                    "rows": "list[object]",
                    "hasMoreResults": "boolean",
                },
                "actual": summary,
            }
        )

    failures = [item for item in assertions if not item["passed"]]
    return {
        "ok": not failures,
        "assertions": assertions,
        "failures": failures,
        "routing": _routing()["verification"],
    }


def _routing() -> dict:
    return {
        "connectionRead": {
            "preferred": {
                "adapter": "extend-rest",
                "operationId": "getConnection",
            },
            "fallback": {
                "adapter": "extend-rest",
                "operationId": "getConnections",
            },
            "write": {
                "enabled": False,
                "reason": "connection lifecycle and credentials are out of scope",
            },
        },
        "definitionRead": {
            "adapter": "designer-soap",
            "service": "designerRepositoryService",
            "operation": "getObject",
            "objectType": OBJECT_TYPE,
        },
        "definitionCreate": {
            "adapter": "designer-soap",
            "service": "designerRepositoryService",
            "operation": "addObject",
            "objectType": OBJECT_TYPE,
        },
        "definitionUpdate": {
            "adapter": "designer-soap",
            "service": "designerRepositoryService",
            "operation": "updateObject",
            "objectType": OBJECT_TYPE,
        },
        "verification": {
            "runtimePreferred": {
                "adapter": "extend-rest",
                "operationId": "runDDQ",
            },
            "runtimeFallback": {
                "adapter": "soap",
                "service": "commonService",
                "operation": "runDrillDownQuery",
            },
            "metadataRead": {
                "adapter": "soap",
                "service": "commonService",
                "operation": "getDrillDownQueryMetadata",
            },
        },
    }


def _write_step(action: str, identifier: str, fields: dict) -> dict:
    operation = "addObject" if action == "create" else "updateObject"
    return {
        "id": "drill-down-query.%s" % identifier,
        "adapter": "designer-soap",
        "service": "designerRepositoryService",
        "operation": operation,
        "action": action,
        "type": OBJECT_TYPE,
        "identifier": identifier,
        "fields": fields,
        "dependsOn": [],
        "verification": [
            "saved DDQ fields match the desired definition",
            "metadata columns match columnNames",
            "runDDQ returns rows and hasMoreResults",
        ],
    }


def _bean_fields(spec: Mapping) -> dict:
    fields = {
        "identifier": spec["identifier"],
        "name": spec["name"],
        "description": spec["description"],
        "sqlQuery": spec["sqlQuery"],
        "connectionId": spec["connectionId"],
        "pageTitle": spec["pageTitle"],
        "parameters": spec["parameterNames"],
        "parameterTypes": spec["parameterTypes"],
        "columnNames": spec["columnNames"],
        "columnWidths": spec["columnWidths"],
        "webAccessible": spec["webAccessible"],
        "secured": spec["secured"],
        "sortable": spec["sortable"],
        "rowFormat": spec["rowFormat"],
    }
    for key in ("pageSize", *_SUPPORTED_EXTRAS):
        if key in spec:
            fields[key] = spec[key]
    return fields


def _result_items(result) -> list[Mapping]:
    value = _result_out(result)
    if value is None:
        return []
    if isinstance(value, list):
        return [item for item in value if isinstance(item, Mapping)]
    if isinstance(value, Mapping):
        for key in ("item", "objectInfoArray", "objectArray"):
            if key in value:
                return _result_items({"out": value[key]})
        candidates = [item for key, item in value.items() if key != "@type"]
        if len(candidates) == 1 and isinstance(candidates[0], (list, Mapping)):
            return _result_items({"out": candidates[0]})
        return [value]
    return []


def _result_out(result, wrapper_key: str | None = None):
    if not isinstance(result, Mapping):
        return None
    value = result.get("out")
    if wrapper_key and isinstance(value, Mapping) and wrapper_key in value:
        return value[wrapper_key]
    return value


def _invoke_rest(rest_registry, rest_client, operation_id: str, params: dict):
    from actone.invoke import invoke

    return invoke(
        rest_registry,
        rest_client,
        operation_id,
        params=params,
    )


def _read_rest_connection(rest_registry, rest_client, logical_identifier: str) -> dict:
    from actone.invoke import InvokeError

    confirmed_absent = False
    try:
        result = _invoke_rest(
            rest_registry,
            rest_client,
            "getConnection",
            {"connectionName": logical_identifier},
        )
        body = result.get("body") if isinstance(result, Mapping) else None
        if result.get("ok") and isinstance(body, Mapping):
            actual = _logical_connection_identifier(body)
            if actual == logical_identifier:
                return {"exists": True, "source": "getConnection"}
        confirmed_absent = result.get("status") == 404
    except InvokeError:
        pass

    try:
        result = _invoke_rest(
            rest_registry,
            rest_client,
            "getConnections",
            {},
        )
        body = result.get("body") if isinstance(result, Mapping) else None
        if result.get("ok") and isinstance(body, list):
            found = any(
                isinstance(item, Mapping)
                and _logical_connection_identifier(item) == logical_identifier
                for item in body
            )
            return {"exists": found, "source": "getConnections"}
    except InvokeError:
        pass
    return {
        "exists": False if confirmed_absent else None,
        "source": "getConnection" if confirmed_absent else None,
    }


def _logical_connection_identifier(connection: Mapping) -> str | None:
    for key in ("name", "identifier", "connectionName"):
        if connection.get(key) not in (None, ""):
            return str(connection[key])
    return None


def _split_reference_evidence(value) -> tuple[dict | None, dict | None]:
    if not isinstance(value, Mapping):
        return None, None
    references = value.get("references")
    connection = value.get("connection")
    if not isinstance(references, Mapping) and ("known" in value or "count" in value):
        references = {
            "known": value.get("known"),
            "count": value.get("count"),
        }
    connection_keys = {
        "connectionId",
        "internal",
        "numericIdSource",
        "numericIdTrusted",
        "source",
        "trusted",
    }
    if not isinstance(connection, Mapping) and connection_keys & set(value):
        connection = {key: value[key] for key in connection_keys if key in value}
    return (
        dict(references) if isinstance(references, Mapping) else None,
        dict(connection) if isinstance(connection, Mapping) else None,
    )


def _valid_internal_connection_evidence(evidence) -> bool:
    if not isinstance(evidence, Mapping):
        return False
    source = evidence.get("numericIdSource", evidence.get("source"))
    evidence_id = evidence.get("connectionId")
    return (
        evidence.get("internal") is True
        and (evidence_id is None or _numeric_id(evidence_id) == -1)
        and source in _INTERNAL_CONNECTION_SOURCES
    )


def _trusted_external_connection_evidence(evidence) -> dict | None:
    if not isinstance(evidence, Mapping):
        return None
    connection_id = _numeric_id(evidence.get("connectionId"))
    source = evidence.get("numericIdSource", evidence.get("source"))
    trusted = (
        evidence.get("numericIdTrusted") is True or evidence.get("trusted") is True
    )
    if (
        connection_id is None
        or connection_id == -1
        or not trusted
        or not isinstance(source, str)
        or not source
        or source in _REST_CONNECTION_OPERATIONS
    ):
        return None
    return {"connectionId": connection_id, "source": source}


def _plan_integrity_error(plan) -> str | None:
    if not isinstance(plan, Mapping):
        return "plan integrity check failed: plan is not an object"
    expected = fingerprint_drill_down_query_plan(plan)
    if plan.get("fingerprint") != expected or plan.get("planId") != expected[:16]:
        return "plan integrity check failed: fingerprint does not match stored plan"
    return None


def merge_ddq_apply_evidence(plan: Mapping, supplied=None):
    """Merge caller references with only trusted plan-stored connection evidence.

    Reference evidence is never inferred. A missing caller ``references`` block
    therefore remains missing, preserving update staleness/reference checks.
    """
    evidence = build_ddq_reference_evidence(
        plan.get("specification", {}),
        supplied,
    )
    result = dict(evidence or {})
    _, supplied_connection = _split_reference_evidence(result)
    if supplied_connection is not None:
        return result

    saved = plan.get("connectionEvidence")
    if not isinstance(saved, Mapping) or saved.get("exists") is not True:
        return result or None
    connection_id = _numeric_id(saved.get("connectionId"))
    source = saved.get("numericIdSource")
    if connection_id == -1 and source in _INTERNAL_CONNECTION_SOURCES:
        result["connection"] = {
            "connectionId": -1,
            "internal": True,
            "source": source,
        }
    elif (
        connection_id is not None
        and connection_id != -1
        and isinstance(source, str)
        and source
        and source not in _REST_CONNECTION_OPERATIONS
    ):
        result["connection"] = {
            "connectionId": connection_id,
            "trusted": True,
            "source": source,
        }
    return result or None


def _route_allowlist_error(plan: Mapping) -> str | None:
    steps = plan.get("steps")
    if not isinstance(steps, list) or len(steps) > 1:
        return "DDQ plan must contain zero or one write step"
    expected_identifier = plan.get("specification", {}).get("identifier")
    allowed = {
        ("create", "addObject"),
        ("update", "updateObject"),
    }
    for step in steps:
        if not isinstance(step, Mapping):
            return "DDQ step must be an object"
        if (
            (step.get("action"), step.get("operation")) not in allowed
            or step.get("adapter") != "designer-soap"
            or step.get("service") != "designerRepositoryService"
            or step.get("type") != OBJECT_TYPE
            or step.get("identifier") != expected_identifier
            or step.get("dependsOn") != []
            or not isinstance(step.get("fields"), Mapping)
        ):
            return "DDQ step route is not allowlisted"
    return None


def _runtime_parameters(value, specification: Mapping) -> dict:
    if value is None:
        value = {}
    if not isinstance(value, Mapping):
        raise DrillDownQueryPlanError("runtime_request must be an object")
    allowed = {
        "ddqParams",
        "startIndex",
        "maxNumOfRows",
        "timeoutInSeconds",
    }
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise DrillDownQueryPlanError(
            "unsupported runtime request fields: %s" % ", ".join(unknown)
        )
    result = {
        "ddqParams": value.get("ddqParams", ""),
        "startIndex": value.get("startIndex", 0),
        "maxNumOfRows": value.get("maxNumOfRows", specification.get("pageSize", 100)),
        "timeoutInSeconds": value.get("timeoutInSeconds", 30),
    }
    if not isinstance(result["ddqParams"], str):
        raise DrillDownQueryPlanError("ddqParams must be a string")
    for key in ("startIndex", "maxNumOfRows", "timeoutInSeconds"):
        item = result[key]
        if isinstance(item, bool) or not isinstance(item, int):
            raise DrillDownQueryPlanError("%s must be an integer" % key)
    if result["startIndex"] < 0:
        raise DrillDownQueryPlanError("startIndex must be non-negative")
    if result["maxNumOfRows"] <= 0 or result["timeoutInSeconds"] <= 0:
        raise DrillDownQueryPlanError(
            "maxNumOfRows and timeoutInSeconds must be positive"
        )
    return result


def _connection_evidence(spec: Mapping, observed: Mapping, errors: list[dict]) -> dict:
    connection = observed.get("connection")
    initial_error_count = len(errors)
    evidence = {
        "exists": False,
        "connectionId": spec["connectionId"],
        "connectionIdentifier": spec.get("connectionIdentifier"),
        "lookupSource": (
            connection.get("source") if isinstance(connection, Mapping) else None
        ),
    }
    if not isinstance(connection, Mapping) or connection.get("exists") is not True:
        errors.append(
            {
                "code": (
                    "connection_missing"
                    if isinstance(connection, Mapping)
                    and connection.get("exists") is False
                    else "connection_unverified"
                ),
                "message": (
                    "the JDBC connection must be positively observed as existing"
                ),
            }
        )
        return evidence

    observed_id = connection.get("connectionId", connection.get("id"))
    observed_identifier = connection.get(
        "connectionIdentifier",
        connection.get("identifier", connection.get("name")),
    )
    normalized_id = _numeric_id(observed_id)
    numeric_source = connection.get("numericIdSource")
    if normalized_id is None:
        errors.append(
            {
                "code": "connection_id_unverified",
                "message": (
                    "observed JDBC connection must contain a numeric connectionId"
                ),
            }
        )
    elif normalized_id != spec["connectionId"]:
        errors.append(
            {
                "code": "connection_id_mismatch",
                "message": "observed JDBC connectionId does not match the DDQ",
            }
        )
    elif normalized_id == -1:
        if (
            connection.get("internal") is not True
            or numeric_source not in _INTERNAL_CONNECTION_SOURCES
        ):
            errors.append(
                {
                    "code": "internal_connection_evidence_unverified",
                    "message": (
                        "connectionId -1 requires explicit internal evidence "
                        "from documented or live-evidenced source"
                    ),
                }
            )
    elif (
        connection.get("numericIdTrusted") is not True
        or not isinstance(numeric_source, str)
        or not numeric_source
        or numeric_source in _REST_CONNECTION_OPERATIONS
    ):
        errors.append(
            {
                "code": "connection_id_untrusted",
                "message": (
                    "external connectionId requires a trusted non-REST "
                    "numeric evidence source"
                ),
            }
        )
    logical_identifier = spec.get("connectionIdentifier")
    if logical_identifier and str(observed_identifier or "") != logical_identifier:
        errors.append(
            {
                "code": "connection_identifier_mismatch",
                "message": (
                    "observed JDBC connection identifier does not match the DDQ"
                ),
            }
        )
    evidence["exists"] = len(errors) == initial_error_count
    evidence["numericIdSource"] = numeric_source
    evidence["internal"] = connection.get("internal") is True
    if observed_identifier is not None:
        evidence["observedIdentifier"] = str(observed_identifier)
    return evidence


def _reference_safety(observed: Mapping) -> dict:
    references = observed.get("references", observed.get("referenceConstraints"))
    if not isinstance(references, Mapping) and (
        "referencesKnown" in observed or "referenceCount" in observed
    ):
        references = {
            "known": observed.get("referencesKnown"),
            "count": observed.get("referenceCount"),
        }
    if not isinstance(references, Mapping):
        return {"known": False, "count": None}
    known = references.get("known") is True
    count = _as_int(references.get("count")) if known else None
    if known and (not isinstance(count, int) or count < 0):
        return {"known": False, "count": None}
    return {"known": known, "count": count}


def _semantic_observation(spec: Mapping, observed: Mapping) -> dict:
    connection = observed.get("connection")
    query_known, current = _observed_query(observed)
    safe_connection = None
    if isinstance(connection, Mapping):
        safe_connection = {
            "exists": connection.get("exists"),
            "connectionId": connection.get("connectionId", connection.get("id")),
            "connectionIdentifier": connection.get(
                "connectionIdentifier",
                connection.get("identifier", connection.get("name")),
            ),
            "internal": connection.get("internal"),
            "numericIdTrusted": connection.get("numericIdTrusted"),
            "numericIdSource": connection.get("numericIdSource"),
        }
        if isinstance(connection.get("source"), str):
            safe_connection["source"] = connection["source"]
    safe_query = (
        {
            "identifier": _identifier(current),
            "fields": _project_saved_fields(current, _bean_fields(spec)),
        }
        if isinstance(current, Mapping)
        else current
        if query_known
        else "<unknown>"
    )
    return {
        "connection": safe_connection,
        "query": safe_query,
        "references": _reference_safety(observed),
        "managedIdentifier": spec["identifier"],
    }


def _observed_query(observed: Mapping) -> tuple[bool, object]:
    for key in ("query", "drillDownQuery", "definition"):
        if key in observed:
            return True, observed[key]
    return False, None


def _project_saved_fields(current: Mapping, desired_fields: Mapping) -> dict:
    info = current.get("objectInfo")
    info = info if isinstance(info, Mapping) else {}
    projected = {}
    for field in desired_fields:
        value = current.get(field, info.get(field))
        projected[field] = value
    return projected


def _field_differences(expected: Mapping, actual: Mapping) -> list[str]:
    return sorted(
        field
        for field in expected
        if _comparable(field, expected[field]) != _comparable(field, actual.get(field))
    )


def _change_classification(field: str) -> str:
    if field == "sqlQuery":
        return "sql"
    if field in {
        "defaultValues",
        "parameterTypes",
        "parameters",
        "prepared",
        "searchParameters",
    }:
        return "parameter-metadata"
    return "display"


def _comparable(field: str, value):
    if field in _BOOLEAN_FIELDS:
        return _as_bool(value)
    if field in _INTEGER_FIELDS:
        return _as_int(value)
    if field in {"columnNames", "columnWidths", "parameters", "parameterTypes"}:
        return _csv_text(value)
    if value is None:
        return None
    return str(value).strip() if field == "sqlQuery" else str(value)


def _metadata_columns(metadata) -> list[str] | None:
    if isinstance(metadata, str):
        text = metadata.strip()
        if not text:
            return []
        if text.startswith("<"):
            try:
                root = ElementTree.fromstring(text)
            except ElementTree.ParseError:
                return None
            columns = []
            for element in root.iter():
                tag = element.tag.rsplit("}", 1)[-1].lower()
                if "column" not in tag:
                    continue
                value = (
                    element.get("name")
                    or element.get("columnName")
                    or (element.text or "").strip()
                )
                if value:
                    columns.append(str(value))
            return columns
        return _csv_values(text)
    if isinstance(metadata, Mapping):
        for key in ("columns", "columnNames", "metadataColumns"):
            if key in metadata:
                return _metadata_columns(metadata[key])
        return None
    if isinstance(metadata, Sequence) and not isinstance(
        metadata, (str, bytes, bytearray)
    ):
        columns = []
        for item in metadata:
            if isinstance(item, Mapping):
                value = (
                    item.get("name")
                    or item.get("columnName")
                    or item.get("identifier")
                    or item.get("label")
                )
            else:
                value = item
            if value is None:
                return None
            columns.append(str(value))
        return columns
    return None


def _runtime_shape(result: Mapping) -> tuple[bool, dict]:
    if not isinstance(result, Mapping):
        return False, {"successful": False, "reason": "response is not an object"}
    body = result.get("body", result)
    status = _as_int(result.get("status"))
    transport_ok = result.get("ok") is not False and (
        status is None or 200 <= status < 300
    )
    if not isinstance(body, Mapping):
        return False, {
            "successful": False,
            "status": status,
            "reason": "response body is not an object",
        }
    rows = body.get("rows")
    has_more = body.get("hasMoreResults")
    rows_valid = isinstance(rows, list) and all(
        isinstance(row, Mapping) for row in rows
    )
    has_more_valid = isinstance(has_more, bool)
    valid = transport_ok and rows_valid and has_more_valid
    return valid, {
        "successful": transport_ok,
        "status": status,
        "rowCount": len(rows) if isinstance(rows, list) else None,
        "rowsAreObjects": rows_valid,
        "hasMoreResults": has_more if has_more_valid else None,
    }


def _assertion(assertions: list[dict], name: str, expected, actual) -> None:
    assertions.append(
        {
            "name": name,
            "passed": expected == actual,
            "expected": expected,
            "actual": actual,
        }
    )


def _required_text(value: Mapping, key: str) -> str:
    text = str(value.get(key) or "").strip()
    if not text:
        raise DrillDownQueryPlanError("DDQ requires %s" % key)
    return text


def _required_bool(value, field: str) -> bool:
    if not isinstance(value, bool):
        raise DrillDownQueryPlanError("%s must be boolean" % field)
    return value


def _required_int(value, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise DrillDownQueryPlanError("%s must be an integer" % field)
    return value


def _csv_text(value) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return ",".join(str(item).strip() for item in value)
    return ",".join(part.strip() for part in str(value).split(","))


def _csv_values(value) -> list[str]:
    return [part for part in _csv_text(value).split(",") if part]


def _identifier(value: Mapping) -> str | None:
    info = value.get("objectInfo")
    if isinstance(info, Mapping) and info.get("identifier") is not None:
        return str(info["identifier"])
    identifier = value.get("identifier")
    return str(identifier) if identifier is not None else None


def _as_bool(value):
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, str) and value.lower() in {"true", "false"}:
        return value.lower() == "true"
    return value


def _as_int(value):
    if value is None or isinstance(value, bool):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        return value


def _numeric_id(value) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip()
        if text and text.lstrip("-").isdigit():
            return int(text)
    return None


def _fingerprint(value) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
