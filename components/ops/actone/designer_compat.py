"""Compatibility adapters for deprecated Designer authoring surfaces."""
from __future__ import annotations

from copy import deepcopy


LEGACY_ALERT_TYPE_REQUIRED_FIELDS = [
    "identifier",
    "customFields",
    "workflow.identifier",
    "workflow.statuses",
    "workflow.transitions",
    "view.identifier",
    "view.fields",
]


class LegacyAlertTypeMigrationError(ValueError):
    """The legacy AlertType inputs cannot safely express the certified recipe."""


def legacy_alert_type_metadata() -> dict:
    return {
        "deprecated": True,
        "surface": "create_alert_type",
        "replacementCapability": "create_work_item_type",
        "behavior": "plan_apply_verify",
    }


def legacy_alert_type_migration_result(message: str) -> dict:
    return {
        "ok": False,
        "error": "migration_required",
        "message": message,
        "requiredFields": list(LEGACY_ALERT_TYPE_REQUIRED_FIELDS),
        "compatibility": legacy_alert_type_metadata(),
    }


def mark_legacy_alert_type_result(result: dict) -> dict:
    marked = dict(result)
    marked["compatibility"] = legacy_alert_type_metadata()
    return marked


def adapt_legacy_alert_type_specification(
    identifier: str,
    *,
    name: str | None = None,
    description: str = "",
    alert_status_workflow_definition_identifier: str | None = None,
    assigned_status_identifiers: str = "",
    method_id: int = 4,
    support_manual_alerts: bool = False,
    enabled_for_global_search: bool = False,
    extra_fields: dict | None = None,
    specification: dict | None = None,
) -> dict:
    """Return a complete create_work_item_type specification or fail closed."""
    if extra_fields is not None and not isinstance(extra_fields, dict):
        raise LegacyAlertTypeMigrationError(
            "extra_fields must be an object containing only "
            "workItemTypeSpecification"
        )
    extras = dict(extra_fields or {})
    embedded = extras.pop("workItemTypeSpecification", None)
    if specification is not None and embedded is not None:
        raise LegacyAlertTypeMigrationError(
            "provide the work-item specification once, either as `specification` "
            "or `extra_fields.workItemTypeSpecification`"
        )
    candidate = specification if specification is not None else embedded
    if not isinstance(candidate, dict):
        raise LegacyAlertTypeMigrationError(
            "create_alert_type is deprecated and its legacy AlertType-only inputs "
            "cannot safely create statuses, a workflow, and a Workbench view. "
            "Provide a complete create_work_item_type specification."
        )
    if extras:
        raise LegacyAlertTypeMigrationError(
            "legacy extra_fields cannot be applied independently; move the desired "
            "configuration into the create_work_item_type specification"
        )
    if method_id != 4 or support_manual_alerts or enabled_for_global_search:
        raise LegacyAlertTypeMigrationError(
            "method_id, support_manual_alerts, and enabled_for_global_search are "
            "not independently configurable through the certified "
            "create_work_item_type recipe"
        )

    desired = deepcopy(candidate)
    specified_identifier = str(desired.get("identifier") or "").strip()
    if specified_identifier and specified_identifier != identifier:
        raise LegacyAlertTypeMigrationError(
            "legacy identifier %r does not match specification identifier %r"
            % (identifier, specified_identifier)
        )
    desired["identifier"] = identifier

    if name is not None:
        specified_name = desired.get("name")
        if specified_name is not None and specified_name != name:
            raise LegacyAlertTypeMigrationError(
                "legacy name %r does not match specification name %r"
                % (name, specified_name)
            )
        desired["name"] = name
    if description:
        specified_description = desired.get("description")
        if specified_description is not None and specified_description != description:
            raise LegacyAlertTypeMigrationError(
                "legacy description does not match specification description"
            )
        desired["description"] = description

    missing = []
    if "customFields" not in desired or not isinstance(desired.get("customFields"), list):
        missing.append("customFields")
    elif any(
        not isinstance(field, dict) or not field.get("identifier")
        for field in desired["customFields"]
    ):
        missing.append("customFields[].identifier")
    workflow = desired.get("workflow")
    if not isinstance(workflow, dict):
        missing.extend([
            "workflow.identifier",
            "workflow.statuses",
            "workflow.transitions",
        ])
    else:
        if not workflow.get("identifier"):
            missing.append("workflow.identifier")
        if not isinstance(workflow.get("statuses"), list) or not workflow["statuses"]:
            missing.append("workflow.statuses")
        elif any(
            not isinstance(status, dict)
            or not status.get("identifier")
            or not status.get("state")
            for status in workflow["statuses"]
        ):
            missing.append("workflow.statuses[].identifier/state")
        if not isinstance(workflow.get("transitions"), list):
            missing.append("workflow.transitions")
        elif any(
            not isinstance(transition, dict)
            or not transition.get("from")
            or not transition.get("to")
            for transition in workflow["transitions"]
        ):
            missing.append("workflow.transitions[].from/to")
    view = desired.get("view")
    if not isinstance(view, dict):
        missing.extend(["view.identifier", "view.fields"])
    else:
        if not view.get("identifier"):
            missing.append("view.identifier")
        if not isinstance(view.get("fields"), list):
            missing.append("view.fields")
    if missing:
        raise LegacyAlertTypeMigrationError(
            "complete create_work_item_type specification required; missing: %s"
            % ", ".join(missing)
        )

    if alert_status_workflow_definition_identifier:
        workflow_identifier = str(workflow.get("identifier") or "")
        if workflow_identifier != alert_status_workflow_definition_identifier:
            raise LegacyAlertTypeMigrationError(
                "legacy workflow definition %r does not match specification "
                "workflow.identifier %r"
                % (
                    alert_status_workflow_definition_identifier,
                    workflow_identifier,
                )
            )
    assigned = {
        item.strip()
        for item in (assigned_status_identifiers or "").split(",")
        if item.strip()
    }
    if assigned:
        specified_statuses = {
            str(item.get("identifier") or "")
            for item in workflow["statuses"]
            if isinstance(item, dict)
        }
        if assigned != specified_statuses:
            raise LegacyAlertTypeMigrationError(
                "legacy assigned statuses do not match specification "
                "workflow.statuses"
            )
    return desired
