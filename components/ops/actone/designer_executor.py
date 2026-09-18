"""Gated execution and verification for capability-oriented Designer plans."""
from __future__ import annotations

from xml.sax.saxutils import escape

from actone.designer import DesignerError
from actone.designer_planner import (
    collect_remove_work_item_presence,
    fingerprint_observation,
    fingerprint_plan,
    owned_work_item_identifiers,
    remove_constraints_status,
)


def _xml(value) -> str:
    return escape("" if value is None else str(value), {'"': "&quot;"})


def _display_name(identifier: str) -> str:
    return identifier.replace("_", " ").replace("-", " ").title()


def _workflow_layout(statuses: list[dict], transitions: list[dict],
                     start_identifier: str) -> dict[str, tuple[float, float, float]]:
    """Assign deterministic left-to-right coordinates for the Designer canvas."""
    outgoing: dict[str, list[str]] = {
        status["identifier"]: [] for status in statuses
    }
    for transition in transitions:
        outgoing[transition["from"]].append(transition["to"])

    depths = {start_identifier: 0}
    queue = [start_identifier]
    while queue:
        source = queue.pop(0)
        for target in outgoing.get(source, []):
            proposed = depths[source] + 1
            if target not in depths or proposed < depths[target]:
                depths[target] = proposed
                queue.append(target)
    next_depth = max(depths.values(), default=-1) + 1
    for status in statuses:
        depths.setdefault(status["identifier"], next_depth)

    layers: dict[int, list[dict]] = {}
    for status in statuses:
        layers.setdefault(depths[status["identifier"]], []).append(status)

    positions = {}
    for depth, layer in layers.items():
        for index, status in enumerate(layer):
            identifier = status["identifier"]
            name = status.get("name") or _display_name(identifier)
            left = 60.0 + depth * 280.0
            top = 180.0 + (index - (len(layer) - 1) / 2) * 100.0
            width = float(max(100, min(250, len(name) * 7 + 35)))
            positions[identifier] = (left, top, width)
    return positions


def _node_designer_cookie(left: float, top: float, width: float) -> str:
    return (
        '<Node>\n  <Bounds Top="%.1f" Left="%.1f" Width="%.1f" '
        'Height="30" />\n</Node>'
        % (top, left, width)
    )


def _status_state(value: str) -> str:
    return "Open" if value == "InProcess" else value


def _workflow_input_xml(input_type: str) -> str:
    return (
        '<item xsi:type="urn:AlertStatusWorkflowInput">'
        '<inputType xsi:type="xsd:string">%s</inputType>'
        '<requiresNoteForward xsi:type="xsd:boolean">false</requiresNoteForward>'
        '<requiresNoteBack xsi:type="xsd:boolean">false</requiresNoteBack>'
        '<allowsBack xsi:type="xsd:boolean">false</allowsBack>'
        '<requireUserAssignment xsi:type="xsd:boolean">false</requireUserAssignment>'
        '<requireBUAssignment xsi:type="xsd:boolean">false</requireBUAssignment>'
        '<autoAssignmentType xsi:type="urn:AutoAssignmentType">None</autoAssignmentType>'
        '</item>' % _xml(input_type)
    )


def _observed_node_cookies(observed_workflow: dict | None) -> dict[str, str]:
    """Extract the live ``designerCookie`` text keyed by statusIdentifier from an
    already-hydrated workflow object, so an additive update can reuse it verbatim
    instead of recomputing a layout position for a node that already exists."""
    cookies: dict[str, str] = {}
    if not isinstance(observed_workflow, dict):
        return cookies
    for node in _array(observed_workflow.get("nodes"), "nodes"):
        if not isinstance(node, dict):
            continue
        status_id = node.get("statusIdentifier")
        cookie = node.get("designerCookie")
        if status_id and cookie:
            cookies[str(status_id)] = str(cookie)
    return cookies


def build_workflow_xml(catalog, workflow: dict,
                       existing_cookies: dict[str, str] | None = None) -> str:
    """Build the concrete, reference-linked workflow graph Axis expects.

    ``existing_cookies`` (statusIdentifier -> raw ``designerCookie`` XML), when
    given, is reused verbatim for any node already present there -- an additive
    update must not move a manually positioned existing node. Layout positions
    are only computed (deterministically) for nodes absent from it, i.e. newly
    added ones; on create, ``existing_cookies`` is empty/omitted so every node
    gets a computed position, matching prior behavior exactly."""
    if not catalog.find_type("AlertStatusWorkflowDefinition"):
        raise ValueError("AlertStatusWorkflowDefinition is absent from the catalog")
    identifier = str(workflow["identifier"])
    statuses = workflow.get("statuses", []) or []
    transitions = workflow.get("transitions", []) or []
    existing_cookies = existing_cookies or {}
    index = {status["identifier"]: position for position, status in enumerate(statuses)}
    starts = [status for status in statuses if status.get("start") is True]
    if len(starts) != 1:
        raise ValueError("workflow requires exactly one start status")

    outgoing: dict[str, list[dict]] = {status_id: [] for status_id in index}
    for transition in transitions:
        outgoing[transition["from"]].append(transition)
    positions = _workflow_layout(
        statuses, transitions, starts[0]["identifier"]
    )

    nodes = []
    for status_id, position in index.items():
        status = statuses[position]
        if status_id in existing_cookies:
            designer_cookie = existing_cookies[status_id]
        else:
            left, top, width = positions[status_id]
            designer_cookie = _node_designer_cookie(left, top, width)
        transition_xml = []
        for transition in outgoing[status_id]:
            target_position = index[transition["to"]]
            inputs = (
                _workflow_input_xml("WSChangeAlertStatus")
                + _workflow_input_xml("UserChangeAlertStatus")
            )
            transition_xml.append(
                '<item xsi:type="urn:WorkflowTransition">'
                '<name xsi:type="xsd:string">%s</name>'
                '<inputs soapenc:arrayType="urn:WorkflowInput[2]" '
                'xsi:type="soapenc:Array">%s</inputs>'
                '<sourceNode href="#node%d"/>'
                '<targetNode href="#node%d"/>'
                '<description xsi:type="xsd:string">%s</description>'
                '<designerCookie xsi:type="xsd:string"></designerCookie>'
                '<barrierWeight xsi:type="xsd:int">0</barrierWeight>'
                '<transitionType xsi:type="urn:TransitionTypeEnum">transition</transitionType>'
                '<supportsRFIReply xsi:type="xsd:boolean">false</supportsRFIReply>'
                '</item>'
                % (
                    _xml(transition.get("name") or "Transition"),
                    inputs,
                    position,
                    target_position,
                    _xml(transition.get("description", "")),
                )
            )
        outgoing_xml = ""
        if transition_xml:
            outgoing_xml = (
                '<outgoingTransitions soapenc:arrayType="urn:WorkflowTransition[%d]" '
                'xsi:type="soapenc:Array">%s</outgoingTransitions>'
                % (len(transition_xml), "".join(transition_xml))
            )
        nodes.append(
            '<item id="node%d" xsi:type="urn:AlertStatusNode">'
            '<name xsi:type="xsd:string">%s</name>'
            '<startNode xsi:type="xsd:boolean">%s</startNode>'
            '%s'
            '<description xsi:type="xsd:string">%s</description>'
            '<statusIdentifier xsi:type="xsd:string">%s</statusIdentifier>'
            '<designerCookie xsi:type="xsd:string">%s</designerCookie>'
            '</item>'
            % (
                position,
                _xml(status.get("name") or _display_name(status_id)),
                "true" if status.get("start") is True else "false",
                outgoing_xml,
                _xml(status.get("description", "")),
                _xml(status_id),
                _xml(designer_cookie),
            )
        )

    start_position = index[starts[0]["identifier"]]
    return (
        '<newObject xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'xmlns:xsd="http://www.w3.org/2001/XMLSchema" '
        'xmlns:soapenc="http://schemas.xmlsoap.org/soap/encoding/" '
        'xmlns:urn="urn:designerRepositoryService" '
        'xsi:type="urn:AlertStatusWorkflowDefinition">'
        '<objectInfo xsi:type="urn:ACMObjectInfo">'
        '<identifier xsi:type="xsd:string">%s</identifier>'
        '<name xsi:type="xsd:string">%s</name>'
        '<description xsi:type="xsd:string">%s</description>'
        '<id xsi:type="xsd:long">-1</id>'
        '<type xsi:type="xsd:string">AlertStatusWorkflowDefinition</type>'
        '</objectInfo>'
        '<nodes soapenc:arrayType="urn:WorkflowNode[%d]" '
        'xsi:type="soapenc:Array">%s</nodes>'
        '<defaultStartNode href="#node%d"/>'
        '</newObject>'
        % (
            _xml(identifier),
            _xml(workflow.get("name") or _display_name(identifier)),
            _xml(workflow.get("description", "")),
            len(nodes),
            "".join(nodes),
            start_position,
        )
    )


def _comparison_filter_xml(field_identifier: str, value) -> str:
    return (
        '<item xsi:type="cb:ComparisonFilter">'
        '<secondary xsi:type="xsd:boolean">false</secondary>'
        '<operator xsi:type="cb:ComparisonOperatorEnum">EQ</operator>'
        '<terms soapenc:arrayType="cb:Term[2]" xsi:type="soapenc:Array">'
        '<item xsi:type="cb:FieldTerm">'
        '<customizedFieldIdentifier xsi:type="xsd:string">%s</customizedFieldIdentifier>'
        '</item>'
        '<item xsi:type="cb:ValueTerm">'
        '<value xsi:type="xsd:string">%s</value>'
        '<dynamic xsi:type="xsd:boolean">false</dynamic>'
        '</item>'
        '</terms>'
        '</item>'
        % (_xml(field_identifier), _xml(value))
    )


def _view_field(field, position: int) -> dict:
    if isinstance(field, str):
        field = {"identifier": field}
    identifier = field.get("identifier") or field.get("fieldIdentifier")
    if not identifier:
        raise ValueError("view field requires identifier")
    renderers = {
        "alertId": "alert_details_link_renderer",
        "statusState": "state_icon_renderer",
        "statusId": "issue_icon_renderer",
        "alertDate": "date_renderer",
        "score": "score_renderer",
    }
    widths = {"alertId": 70, "statusState": 15, "statusId": 15, "score": 60}
    return {
        "visible": field.get("visible", True),
        "selectable": field.get("selectable", "YesSelected"),
        "sortable": field.get("sortable", True),
        "filterable": field.get("filterable", True),
        "exportable": field.get("exportable", True),
        "fieldIdentifier": identifier,
        "rightToLeft": field.get("rightToLeft", False),
        "alignment": field.get("alignment", "Left"),
        "columnTitleTextWrapping": field.get("columnTitleTextWrapping", "Wrap"),
        "columnDataTextWrapping": field.get("columnDataTextWrapping", "Cut"),
        "columnDisplayFormatterIdentifier": field.get(
            "columnDisplayFormatterIdentifier",
            renderers.get(identifier, "escaped_string_renderer"),
        ),
        "columnWidthUnit": field.get("columnWidthUnit", "Pixel"),
        "sortOrder": field.get("sortOrder", 0),
        "sortAscending": field.get("sortAscending", True),
        "columnWidth": field.get("columnWidth", widths.get(identifier, 100)),
        "displayOrder": field.get("displayOrder", position * 10),
    }


def build_alert_view_fields(view: dict, work_item_type: str) -> dict:
    """Build the dedicated AlertView payload with commonBeans filter types."""
    identifier = str(view["identifier"])
    requested_filters = dict(view.get("filters", {}) or {})
    filters = [
        ("alertArchive", requested_filters.pop("alertArchive", 0)),
        ("deleted", requested_filters.pop("deleted", 0)),
        *requested_filters.items(),
        ("alertTypeIdentifier", work_item_type),
    ]
    filter_items = "".join(_comparison_filter_xml(key, value) for key, value in filters)
    filter_xml = (
        '<filter xmlns:cb="urn:commonBeans" xsi:type="cb:BooleanFilter">'
        '<secondary xsi:type="xsd:boolean">false</secondary>'
        '<operator xsi:type="cb:BooleanOperatorEnum">and</operator>'
        '<subFilters soapenc:arrayType="cb:DataFilter[%d]" '
        'xsi:type="soapenc:Array">%s</subFilters>'
        '</filter>' % (len(filters), filter_items)
    )
    return {
        "id": -1,
        "identifier": identifier,
        "name": view.get("name") or _display_name(identifier),
        "description": view.get("description", ""),
        "systemView": False,
        "displayOrder": view.get("displayOrder", -1),
        "visible": view.get("visible", True),
        "group": view.get("group", "Work Items"),
        "itemView": view.get("itemView", False),
        "filter_xml": filter_xml,
        "viewFields": [
            _view_field(field, position)
            for position, field in enumerate(view.get("fields", []) or [])
        ],
    }


def _status_fields(status: dict) -> dict:
    identifier = status["identifier"]
    state = _status_state(status["state"])
    issue = status.get("issue")
    if not issue and state == "Open":
        issue = "No_Determination"
    return {
        "statusIdentifier": identifier,
        "statusName": status.get("name") or _display_name(identifier),
        "description": status.get("description", ""),
        "deletable": status.get("deletable", True),
        "state": state,
        "issue": issue,
        "scope": status.get("scope", "All"),
    }


def _merge_status_update(observed: dict, status_spec: dict) -> dict:
    """Merge only the approved name/description change into the observed
    AlertStatus snapshot. Everything else the update route can carry --
    deletable, scope, state, issue -- is preserved from the live object
    exactly as read, rather than being reconstructed from specification
    defaults (which would silently reset unspecified live configuration)."""
    identifier = status_spec["identifier"]
    state = observed.get("state") or _status_state(status_spec.get("state", ""))
    issue = observed.get("issue")
    if issue is None:
        issue = status_spec.get("issue")
        if not issue and state == "Open":
            issue = "No_Determination"
    return {
        "statusIdentifier": identifier,
        "statusName": status_spec.get("name") or _display_name(identifier),
        "description": status_spec.get("description", ""),
        "deletable": observed.get("deletable", True),
        "state": state,
        "issue": issue,
        "scope": observed.get("scope", "All"),
    }


def _alert_type_fields(specification: dict) -> dict:
    workflow = specification["workflow"]
    fields = {
        "identifier": specification["identifier"],
        "name": specification.get("name") or specification["identifier"],
        "description": specification.get("description", ""),
        "methodId": specification.get("methodId", 4),
        "supportManualAlerts": specification.get("supportManualAlerts", False),
        "usingAlertStatusWorkflow": True,
        "alertStatusWorkflowDefinitionIdentifier": workflow["identifier"],
        "alertTypeFields": [{
            "customizedFieldIdentifier": field["identifier"],
            "mandatory": field.get("mandatory", False),
            "updatable": field.get("updateMode", "Updatable"),
            "isCachable": field.get("isCachable", False),
        } for field in specification.get("customFields", []) or []],
        "category": specification.get("category", "Alerts"),
        "wiCatagory": specification.get("category", "Alerts"),
        "viewType": specification.get("viewType", "tabular"),
        "defaultView": specification.get("defaultView", "tabular"),
    }
    if "enabledForGlobalSearch" in specification:
        fields["enabledForGlobalSearch"] = specification["enabledForGlobalSearch"]
    return fields


def _merge_alert_type_update(observed: dict, specification: dict) -> dict:
    """Merge only the additive alertTypeFields assignment into the observed
    AlertType snapshot. Every other catalog-recognized field (methodId,
    category/wiCatagory, manual-alert/global-search flags, view/default view,
    name/description) is preserved from the live object; only fields absent
    from the fixture's ``customFields`` are added, and every existing field
    assignment keeps its own mandatory/updatable/isCachable attributes."""
    existing_field_map = {
        item.get("customizedFieldIdentifier"): item
        for item in _array(observed.get("alertTypeFields"), "alertTypeFields")
        if isinstance(item, dict) and item.get("customizedFieldIdentifier")
    }
    merged_fields = list(existing_field_map.values())
    for field in specification.get("customFields", []) or []:
        identifier = field.get("identifier")
        if identifier and identifier not in existing_field_map:
            merged_fields.append({
                "customizedFieldIdentifier": identifier,
                "mandatory": field.get("mandatory", False),
                "updatable": field.get("updateMode", "Updatable"),
                "isCachable": field.get("isCachable", False),
            })
    object_info = observed.get("objectInfo")
    object_info = object_info if isinstance(object_info, dict) else {}
    identifier = (
        object_info.get("identifier")
        or observed.get("identifier")
        or specification["identifier"]
    )
    fields = {
        "identifier": identifier,
        "name": observed.get("name", specification.get("name") or identifier),
        "description": observed.get(
            "description", specification.get("description", "")
        ),
        "methodId": observed.get("methodId", specification.get("methodId", 4)),
        "supportManualAlerts": observed.get(
            "supportManualAlerts", specification.get("supportManualAlerts", False)
        ),
        "usingAlertStatusWorkflow": observed.get("usingAlertStatusWorkflow", True),
        "alertStatusWorkflowDefinitionIdentifier": observed.get(
            "alertStatusWorkflowDefinitionIdentifier",
            specification["workflow"]["identifier"],
        ),
        "alertTypeFields": merged_fields,
        "category": observed.get("category", specification.get("category", "Alerts")),
        "wiCatagory": observed.get(
            "wiCatagory", specification.get("category", "Alerts")
        ),
        "viewType": observed.get("viewType", specification.get("viewType", "tabular")),
        "defaultView": observed.get(
            "defaultView", specification.get("defaultView", "tabular")
        ),
    }
    if "enabledForGlobalSearch" in observed:
        fields["enabledForGlobalSearch"] = observed["enabledForGlobalSearch"]
    elif "enabledForGlobalSearch" in specification:
        fields["enabledForGlobalSearch"] = specification["enabledForGlobalSearch"]
    return fields


def _merge_alert_view_update(observed: dict, view_spec: dict,
                             work_item_type: str) -> dict:
    """Merge only additive (new) ViewFields into the observed AlertView
    snapshot. Every existing ViewField keeps every one of its live
    formatting/width/sort/visibility attributes untouched; defaults are only
    computed for fields that don't exist yet. Top-level presentation settings
    (name/description/displayOrder/visible/group/itemView) are preserved from
    the live object. Filters are frozen by policy for updates -- the planner
    only reaches this path once the live filter pairs already match the
    requested ones -- so the live raw filter is reused verbatim when captured,
    and rebuilt from the (already-equivalent) spec filters otherwise."""
    existing_field_map = {
        item.get("fieldIdentifier"): item
        for item in _array(observed.get("viewFields"), "viewFields")
        if isinstance(item, dict) and item.get("fieldIdentifier")
    }
    merged_fields = list(existing_field_map.values())
    position = len(merged_fields)
    for field in view_spec.get("fields", []) or []:
        identifier = field if isinstance(field, str) else (
            field.get("identifier") or field.get("fieldIdentifier")
        )
        if identifier and identifier not in existing_field_map:
            spec_field = field if isinstance(field, dict) else {"identifier": identifier}
            merged_fields.append(_view_field(spec_field, position))
            position += 1
    identifier = observed.get("identifier") or view_spec["identifier"]
    result = {
        "id": observed.get("id", -1),
        "identifier": identifier,
        "name": observed.get("name", view_spec.get("name") or _display_name(identifier)),
        "description": observed.get("description", view_spec.get("description", "")),
        "systemView": observed.get("systemView", False),
        "displayOrder": observed.get(
            "displayOrder", view_spec.get("displayOrder", -1)
        ),
        "visible": observed.get("visible", view_spec.get("visible", True)),
        "group": observed.get("group", view_spec.get("group", "Work Items")),
        "itemView": observed.get("itemView", view_spec.get("itemView", False)),
        "viewFields": merged_fields,
    }
    if isinstance(observed.get("filter_xml"), str):
        result["filter_xml"] = observed["filter_xml"]
    else:
        result["filter_xml"] = build_alert_view_fields(
            view_spec, work_item_type
        )["filter_xml"]
    return result


def _apply_step(step: dict, plan: dict, designer_client) -> dict:
    if step.get("action") == "update":
        return _apply_update_step(step, plan, designer_client)
    type_value = step["type"]
    if type_value == "AlertStatusWorkflowDefinition":
        xml = build_workflow_xml(
            designer_client.catalog,
            step["specification"],
        )
        return designer_client.add_object(xml)
    if type_value == "AlertType":
        return designer_client.create_object(
            "AlertType",
            _alert_type_fields(plan["specification"]),
        )
    if type_value == "AlertView":
        return designer_client.create_object(
            "AlertView",
            build_alert_view_fields(
                step["specification"],
                plan["specification"]["identifier"],
            ),
        )
    if type_value == "AlertStatus":
        return designer_client.create_object("AlertStatus", _status_fields(step["fields"]))
    return designer_client.create_object(type_value, step["fields"])


def _apply_update_step(step: dict, plan: dict, designer_client) -> dict:
    """Apply a safe (additive/metadata-only) update through the correct lifecycle
    route for each type: AlertStatusWorkflowDefinition/AlertType use the generic
    updateObject route (they are created generically too); AlertStatus/AlertView
    use their dedicated update op (mirroring their dedicated create op).

    Every payload is built by merging only the approved change onto the
    observed snapshot captured in the plan step (``step["observed"]``), never
    by reconstructing the whole object from specification defaults -- that
    would silently reset unspecified live configuration."""
    type_value = step["type"]
    observed = step.get("observed") or {}
    if type_value == "AlertStatusWorkflowDefinition":
        xml = build_workflow_xml(
            designer_client.catalog,
            step["specification"],
            existing_cookies=_observed_node_cookies(observed),
        )
        return designer_client.update_object(
            "AlertStatusWorkflowDefinition",
            step["specification"]["identifier"],
            xml,
        )
    if type_value == "AlertType":
        return designer_client.update_typed_object(
            "AlertType",
            plan["specification"]["identifier"],
            _merge_alert_type_update(observed, plan["specification"]),
        )
    if type_value == "AlertView":
        return designer_client.update_typed_object(
            "AlertView",
            step["specification"]["identifier"],
            _merge_alert_view_update(
                observed,
                step["specification"],
                plan["specification"]["identifier"],
            ),
        )
    if type_value == "AlertStatus":
        return designer_client.update_typed_object(
            "AlertStatus",
            step["fields"]["identifier"],
            _merge_status_update(observed, step["fields"]),
        )
    raise ValueError("unsupported update type %r" % type_value)


def _out(result: dict):
    return result.get("out") if isinstance(result, dict) else None


def _array(value, key: str | None = None) -> list:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        if key and key in value:
            return _array(value[key])
        candidates = [
            item for name, item in value.items()
            if name != "@type"
        ]
        if len(candidates) == 1:
            return _array(candidates[0])
        return [value]
    return [value]


def _assertion(assertions: list, name: str, expected, actual) -> None:
    assertions.append({
        "name": name,
        "passed": expected == actual,
        "expected": expected,
        "actual": actual,
    })


def _workflow_edges(workflow_object: dict) -> set[tuple[str, str]]:
    edges = set()
    for node in _array(workflow_object.get("nodes"), "nodes"):
        if not isinstance(node, dict):
            continue
        source = node.get("statusIdentifier")
        for transition in _array(
            node.get("outgoingTransitions"), "outgoingTransitions"
        ):
            if not isinstance(transition, dict):
                continue
            target = transition.get("targetNode")
            if isinstance(target, dict) and target.get("statusIdentifier"):
                edges.add((source, target["statusIdentifier"]))
    return edges


def _view_filter_pairs(view_object: dict) -> set[tuple[str, str]]:
    filter_value = view_object.get("filter")
    if isinstance(filter_value, str):
        return set()
    pairs = set()
    for comparison in _array(
        (filter_value or {}).get("subFilters") if isinstance(filter_value, dict) else None,
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


def verify_work_item_type(plan: dict, designer_client) -> dict:
    """Read back every object and evaluate the work-item recipe postconditions."""
    specification = plan["specification"]
    assertions = []

    field_steps = {
        step["fields"]["identifier"]: step
        for step in plan.get("steps", [])
        if step.get("type") == "AlertCustomizedField"
    }
    for field in specification.get("customFields", []) or []:
        identifier = field["identifier"]
        obj = _out(designer_client.get_object("AlertCustomizedField", identifier)) or {}
        object_info = obj.get("objectInfo") if isinstance(obj, dict) else {}
        _assertion(
            assertions,
            "custom-field.%s.exists" % identifier,
            identifier,
            (object_info or {}).get("identifier"),
        )
        if identifier in field_steps:
            _assertion(
                assertions,
                "custom-field.%s.fieldId" % identifier,
                str(field_steps[identifier]["fields"]["fieldId"]),
                str(obj.get("fieldId")),
            )

    for status in specification["workflow"]["statuses"]:
        identifier = status["identifier"]
        obj = _out(designer_client.call_operation(
            "alertDesignService",
            "getAlertStatus",
            "<alertStatusIdentifier>%s</alertStatusIdentifier>" % _xml(identifier),
            "alertStatus",
        )) or {}
        _assertion(
            assertions,
            "status.%s.state" % identifier,
            _status_state(status["state"]),
            obj.get("state"),
        )
        expected_issue = status.get("issue")
        if not expected_issue and _status_state(status["state"]) == "Open":
            expected_issue = "No_Determination"
        _assertion(
            assertions,
            "status.%s.issue" % identifier,
            expected_issue,
            obj.get("issue"),
        )

    workflow_spec = specification["workflow"]
    workflow = _out(designer_client.get_object(
        "AlertStatusWorkflowDefinition",
        workflow_spec["identifier"],
    )) or {}
    actual_nodes = {
        node.get("statusIdentifier")
        for node in _array(workflow.get("nodes"), "nodes")
        if isinstance(node, dict) and node.get("statusIdentifier")
    }
    expected_nodes = {
        status["identifier"] for status in workflow_spec["statuses"]
    }
    _assertion(assertions, "workflow.nodes", expected_nodes, actual_nodes)
    start_node = workflow.get("defaultStartNode")
    actual_start = (
        start_node.get("statusIdentifier")
        if isinstance(start_node, dict) else None
    )
    expected_start = next(
        status["identifier"]
        for status in workflow_spec["statuses"]
        if status.get("start") is True
    )
    _assertion(assertions, "workflow.start", expected_start, actual_start)
    expected_edges = {
        (transition["from"], transition["to"])
        for transition in workflow_spec.get("transitions", []) or []
    }
    _assertion(
        assertions,
        "workflow.transitions",
        expected_edges,
        _workflow_edges(workflow),
    )

    type_identifier = specification["identifier"]
    alert_type = _out(designer_client.get_object("AlertType", type_identifier)) or {}
    _assertion(
        assertions,
        "work-item-type.workflow",
        workflow_spec["identifier"],
        alert_type.get("alertStatusWorkflowDefinitionIdentifier"),
    )
    actual_fields = {
        item.get("customizedFieldIdentifier")
        for item in _array(alert_type.get("alertTypeFields"), "alertTypeFields")
        if isinstance(item, dict) and item.get("customizedFieldIdentifier")
    }
    expected_fields = {
        field["identifier"] for field in specification.get("customFields", []) or []
    }
    _assertion(
        assertions,
        "work-item-type.custom-fields",
        expected_fields,
        actual_fields,
    )

    view_spec = specification["view"]
    view = _out(designer_client.call_operation(
        "alertDesignService",
        "getAlertView",
        "<viewIdentifier>%s</viewIdentifier>" % _xml(view_spec["identifier"]),
        "view",
    )) or {}
    actual_view_fields = {
        item.get("fieldIdentifier")
        for item in _array(view.get("viewFields"), "viewFields")
        if isinstance(item, dict) and item.get("fieldIdentifier")
    }
    expected_view_fields = {
        field if isinstance(field, str) else (
            field.get("identifier") or field.get("fieldIdentifier")
        )
        for field in view_spec.get("fields", []) or []
    }
    _assertion(
        assertions,
        "view.fields",
        expected_view_fields,
        actual_view_fields,
    )
    expected_filter_pairs = {
        ("alertArchive", "0"),
        ("deleted", "0"),
        ("alertTypeIdentifier", type_identifier),
        *(
            (str(key), str(value))
            for key, value in (view_spec.get("filters", {}) or {}).items()
        ),
    }
    if isinstance(view.get("filter_xml"), str):
        raw_filter = view["filter_xml"]
        actual_filter_pairs = {
            pair for pair in expected_filter_pairs
            if pair[0] in raw_filter and pair[1] in raw_filter
        }
    else:
        actual_filter_pairs = _view_filter_pairs(view)
    _assertion(
        assertions,
        "view.filters",
        expected_filter_pairs,
        actual_filter_pairs,
    )

    failures = [item for item in assertions if not item["passed"]]
    return {
        "ok": not failures,
        "assertions": assertions,
        "failures": failures,
    }


def verify_remove_work_item_type(plan: dict, designer_client) -> dict:
    """Confirm that every identifier explicitly owned by the plan is absent."""
    observed = collect_remove_work_item_presence(
        designer_client, plan["specification"]
    )
    owned = owned_work_item_identifiers(plan["specification"])
    assertions = []
    for type_value in (
        "AlertView",
        "AlertType",
        "AlertStatusWorkflowDefinition",
        "AlertStatus",
        "AlertCustomizedField",
    ):
        present = {
            (
                (item.get("objectInfo") or {}).get("identifier")
                if isinstance(item.get("objectInfo"), dict)
                else item.get("identifier")
            )
            for item in observed.get(type_value, [])
            if isinstance(item, dict)
        }
        for identifier in owned[type_value]:
            _assertion(
                assertions,
                "remove.%s.%s.absent" % (type_value, identifier),
                False,
                identifier in present,
            )
    failures = [item for item in assertions if not item["passed"]]
    return {
        "ok": not failures,
        "assertions": assertions,
        "failures": failures,
    }


class PlanDependencyError(ValueError):
    """A plan's ``dependsOn`` graph is not a valid DAG: an unknown dependency
    id or a cycle was found."""


def validated_step_order(steps: list[dict]) -> list[dict]:
    """Topologically order ``steps`` by ``dependsOn``, failing explicitly (and
    before any write happens) on a dependency that names a step id absent from
    the plan, or on a dependency cycle. Execution must follow this validated
    order rather than trusting the incidental order steps happen to appear in
    the plan's step list."""
    by_id = {}
    for step in steps:
        step_id = step["id"]
        if step_id in by_id:
            raise PlanDependencyError("duplicate step id %r" % step_id)
        by_id[step_id] = step
    for step in steps:
        for dep in step.get("dependsOn", []) or []:
            if dep not in by_id:
                raise PlanDependencyError(
                    "step %r depends on unknown step %r" % (step["id"], dep)
                )

    ordered: list[dict] = []
    visited: set[str] = set()
    visiting: set[str] = set()

    def visit(step_id: str) -> None:
        if step_id in visited:
            return
        if step_id in visiting:
            raise PlanDependencyError(
                "circular dependency detected at step %r" % step_id
            )
        visiting.add(step_id)
        for dep in by_id[step_id].get("dependsOn", []) or []:
            visit(dep)
        visiting.discard(step_id)
        visited.add(step_id)
        ordered.append(by_id[step_id])

    for step in steps:
        visit(step["id"])
    return ordered


def apply_work_item_plan(plan: dict, designer_client,
                         current_observed: dict) -> dict:
    """Apply an intact, current work-item plan and return explicit partial progress."""
    if plan.get("capability") != "create_work_item_type":
        return {"ok": False, "error": "unsupported_capability"}
    if fingerprint_plan(plan) != plan.get("fingerprint"):
        return {"ok": False, "error": "plan_tampered", "planId": plan.get("planId")}
    current_fingerprint = fingerprint_observation(current_observed)
    if current_fingerprint != plan.get("observationFingerprint"):
        return {
            "ok": False,
            "error": "plan_stale",
            "planId": plan.get("planId"),
            "expectedObservationFingerprint": plan.get("observationFingerprint"),
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
            result = _apply_step(step, plan, designer_client)
        except (DesignerError, ValueError, KeyError, TypeError) as exc:
            return {
                "ok": False,
                "error": "step_failed",
                "planId": plan.get("planId"),
                "failedStep": step["id"],
                "message": str(exc),
                "completedSteps": completed,
            }
        completed.append({"id": step["id"], "result": result})
    try:
        verification = verify_work_item_type(plan, designer_client)
    except (DesignerError, ValueError, KeyError, TypeError) as exc:
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


def _apply_time_remove_constraint(designer_client, type_value: str,
                                  identifier: str) -> dict:
    """Best-effort apply-time remove-constraint read.

    Returns ``{"established": bool, "value": ...}``. The generic
    ``getRemoveConstraints`` op is unavailable for work-item family object types
    on live builds and raises :class:`DesignerError`; that is not a step
    failure -- the delete then relies on the authoritative fail-closed
    ``removeAlert*``/``removeObject`` op to refuse a still-referenced object.
    Established evidence, when a build/object does support the read, is still
    honored by the caller."""
    try:
        result = designer_client.get_remove_constraints(type_value, identifier)
    except DesignerError:
        return {"established": False, "value": None}
    if isinstance(result, dict) and "out" in result:
        return {"established": True, "value": result["out"]}
    return {"established": False, "value": None}


def apply_remove_work_item_plan(plan: dict, designer_client,
                                current_observed: dict) -> dict:
    """Apply a current removal plan, stopping at the first unsafe/failed step."""
    if plan.get("capability") != "remove_work_item_type":
        return {"ok": False, "error": "unsupported_capability"}
    if fingerprint_plan(plan) != plan.get("fingerprint"):
        return {"ok": False, "error": "plan_tampered", "planId": plan.get("planId")}
    current_fingerprint = fingerprint_observation(current_observed)
    if current_fingerprint != plan.get("observationFingerprint"):
        return {
            "ok": False,
            "error": "plan_stale",
            "planId": plan.get("planId"),
            "expectedObservationFingerprint": plan.get("observationFingerprint"),
            "actualObservationFingerprint": current_fingerprint,
        }
    blocked = plan.get("changes", {}).get("blocked", [])
    if not plan.get("applicable") or blocked:
        return {
            "ok": False,
            "error": "plan_not_applicable",
            "planId": plan.get("planId"),
            "blocked": blocked,
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
    for index, step in enumerate(ordered_steps):
        pending = [item["id"] for item in ordered_steps[index + 1:]]
        constraint = _apply_time_remove_constraint(
            designer_client, step["type"], step["identifier"]
        )
        if constraint["established"]:
            removable, reason = remove_constraints_status(constraint)
            if not removable:
                return {
                    "ok": False,
                    "error": "step_failed",
                    "planId": plan.get("planId"),
                    "failedStep": {
                        "id": step["id"],
                        "type": step["type"],
                        "identifier": step["identifier"],
                        "reason": reason,
                        "constraints": constraint.get("value"),
                    },
                    "completedSteps": completed,
                    "pendingSteps": pending,
                }
        try:
            result = designer_client.remove_work_item_object(
                step["type"], step["identifier"]
            )
        except (DesignerError, ValueError, KeyError, TypeError) as exc:
            return {
                "ok": False,
                "error": "step_failed",
                "planId": plan.get("planId"),
                "failedStep": {
                    "id": step["id"],
                    "type": step.get("type"),
                    "identifier": step.get("identifier"),
                    "message": str(exc),
                },
                "completedSteps": completed,
                "pendingSteps": pending,
            }
        completed.append({"id": step["id"], "result": result})
    try:
        verification = verify_remove_work_item_type(plan, designer_client)
    except (DesignerError, ValueError, KeyError, TypeError) as exc:
        return {
            "ok": False,
            "error": "verification_failed",
            "planId": plan.get("planId"),
            "message": str(exc),
            "completedSteps": completed,
            "pendingSteps": [],
        }
    if not verification["ok"]:
        return {
            "ok": False,
            "error": "verification_failed",
            "planId": plan.get("planId"),
            "completedSteps": completed,
            "pendingSteps": [],
            "verification": verification,
        }
    return {
        "ok": True,
        "planId": plan.get("planId"),
        "completedSteps": completed,
        "pendingSteps": [],
        "verification": verification,
    }
