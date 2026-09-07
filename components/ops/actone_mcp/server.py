"""ActWise — ActOne Ops MCP discovery server.

Exposes the **runtime ActOne Extend REST API** to any MCP client (GitHub Copilot
CLI / VS Code, Claude Code, Copilot Studio) as a small set of *discovery* tools
rather than 149 static tools. The agent discovers operations on demand:

    search_ops  -> describe_op -> invoke_op

Discovery keeps the model's tool-selection context flat regardless of how large the
ActOne surface is, and tracks whatever the target instance actually exposes (the
registry is built from the live/cached/bundled OpenAPI spec).

Safety
------
P1 is **read-only**: `invoke_op` runs only operations the registry classifies as
reads (GET/HEAD). Writes are refused until the attribution-wall decision (P2).

Spec source: cached spec under <workdir>/postman/specs, else the bundled current
spec (see actone.registry.resolve_spec). Credentials: the built-in `default`
environment reads <workdir>/.env (ACTONE_URL/ACTONE_USER/ACTONE_PASSWORD) — only
needed for invoke_op. Additional named ActOne instances are defined in
actone-ops.yaml (passwords in actone-ops.secrets.yaml); list them with
`list_environments` and target one via the `env` argument of invoke_op.

Run (stdio, for local MCP clients — Copilot CLI, VS Code, Claude):
    py -m actone_mcp.server

Run (Streamable HTTP, for containers / remote MCP clients / Copilot Studio):
    py -m uvicorn actone_mcp.server:app --host 0.0.0.0 --port 8765
    # endpoint: http://localhost:8765/mcp   health: http://localhost:8765/healthz
    # optional shared secret: set ACTONE_PROXY_API_KEY (header X-API-Key).
"""
from __future__ import annotations

import hmac
import os
import threading
from typing import Optional

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import JSONResponse

from actone.registry import load_registry
from actone.invoke import invoke, precheck, make_client, InvokeError, writes_enabled

SERVER_NAME = "actwise-actone-ops"
API_KEY_ENV = "ACTONE_PROXY_API_KEY"

mcp = FastMCP(
    SERVER_NAME,
    stateless_http=True,
    # The MCP StreamableHTTP transport enables DNS-rebinding protection by default,
    # which rejects any request whose Host header isn't localhost ("Invalid Host
    # header"). This server runs behind a container / tunnel / ingress (variable
    # Host) and access is already gated by the X-API-Key auth gate, so disable the
    # Host/Origin check. (Mirrors docenter_mcp.)
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)

_lock = threading.Lock()
_registry = None
_clients: dict[str, object] = {}
_soap_catalog = None
_designers: dict[str, object] = {}


def _reg():
    global _registry
    with _lock:
        if _registry is None:
            _registry = load_registry(os.environ.get("ACTONE_SPEC"))
        return _registry


def _get_client(env: Optional[str] = None):
    """Lazily login once per environment; reuse across invoke_op calls."""
    key = env or "default"
    with _lock:
        c = _clients.get(key)
        if c is None:
            c = make_client(env=env)
            c.login()
            c.detect_version()
            _clients[key] = c
        return c


def _get_designer(env: Optional[str] = None):
    """Lazily build a catalog-driven Designer SOAP client per environment,
    reusing the same authenticated session as the REST/curated-SOAP ops."""
    from actone.designer import DesignerClient
    from actone.soap_catalog import load_catalog
    global _soap_catalog
    key = env or "default"
    with _lock:
        if _soap_catalog is None:
            _soap_catalog = load_catalog()
        d = _designers.get(key)
    if d is None:
        d = DesignerClient(_get_client(env), _soap_catalog)
        with _lock:
            _designers[key] = d
    return d


@mcp.tool()
def search_ops(query: str = "", limit: int = 25, reads_only: bool = False) -> dict:
    """Discover ActOne operations by keyword (operationId / summary / tags / path).

    Start here, then call describe_op on a result before invoke_op. An empty query
    lists everything (ranked alphabetically).

    Args:
        query: Keywords, e.g. "alert details", "policy manager", "diagnostics".
        limit: Max results (1-500). For the full surface, prefer list_ops.
        reads_only: When true, only return read (GET) operations.

    Returns:
        dict with `specVersion`, `count` (total ops), and `results`
        (operationId, method, path, summary, tags, access).
    """
    reg = _reg()
    limit = max(1, min(500, limit))
    return {"specVersion": reg.info_version, "source": reg.source,
            "count": len(reg.ops), "results": reg.search(query, limit, reads_only)}


@mcp.tool()
def describe_op(operation_id: str) -> dict:
    """Show full detail for one operation: method, path, parameters, request-body
    example, and read/write access.

    Use the `parameters` and `requestBody.example` to assemble the `params` for
    invoke_op. Path params are required; a request body is passed under "body".

    Args:
        operation_id: An operationId from search_ops.

    Returns:
        The operation detail dict, or `error`/`suggestions` if unknown.
    """
    reg = _reg()
    info = reg.describe(operation_id)
    if not info:
        return {"error": "unknown_operation", "operationId": operation_id,
                "suggestions": [o["operationId"] for o in reg.search(operation_id, 5)]}
    return info


@mcp.tool()
def invoke_op(operation_id: str, params: Optional[dict] = None,
              env: Optional[str] = None) -> dict:
    """Invoke an ActOne operation live and return the response.

    Read (GET) operations always run. Write operations (POST/PUT/DELETE/PATCH)
    are refused unless the operator opted in by setting ACTONE_ALLOW_WRITES to a
    truthy value (1/true/yes/on) in the server's environment — the model cannot
    lift the gate itself. Build `params` from describe_op — path/query/header
    params by their spec name, and a request body (when needed) under the reserved
    key "body".

    Args:
        operation_id: An operationId from search_ops/describe_op.
        params: Flat dict of parameter values (plus optional "body").
        env: Named ActOne environment to run against (see list_environments).
            Omit to use the default (`.env`) instance.

    Returns:
        dict with `status`, `ok`, `url`, `content_type`, and `body` (the response),
        or `error` for unknown/gated/missing-param cases.
    """
    reg = _reg()
    aw = writes_enabled(env)
    try:
        precheck(reg, operation_id, allow_write=aw)  # gate fires before any login
        return invoke(reg, _get_client(env), operation_id, params or {}, allow_write=aw)
    except InvokeError as e:
        return {"error": str(e), "operationId": operation_id, "env": env or "default"}


@mcp.tool()
def list_soap_operations() -> dict:
    """List the curated ActOne **SOAP** operations (offline).

    These cover the legacy Axis admin surface the Extend REST API does not — most
    importantly creating a **Business Unit** (there is no create-BU REST op), which
    is the prerequisite for seeding work items on a fresh instance. Each entry has
    `operationId`, `service`, `operation`, `access` (read|write), `summary`, and
    `params`. Invoke one via `invoke_soap_operation`.
    """
    from actone.soap import list_operations
    ops = list_operations()
    return {"count": len(ops), "operations": ops}


@mcp.tool()
def invoke_soap_operation(operation_id: str, params: Optional[dict] = None,
                          env: Optional[str] = None) -> dict:
    """Invoke a curated ActOne SOAP operation live (see list_soap_operations).

    Read operations always run. Write operations (create/remove) are refused unless
    the target environment permits writes — a named environment must set
    `allow_writes: true` in actone-ops.yaml (the built-in `default` environment uses
    ACTONE_ALLOW_WRITES). The model cannot lift the gate itself. Reuses the same
    authenticated session as the REST ops (the login cookie authorizes the SOAP
    services), so the same `env` names apply.

    Args:
        operation_id: A curated SOAP opId, e.g. "bu.list", "bu.get", "bu.create".
        params: Flat dict of argument values (see the op's `params` from
            list_soap_operations), e.g. {"identifier": "MY_BU", "name": "My BU"}.
        env: Named ActOne environment (see list_environments). Omit for default.

    Returns:
        dict with `ok`, `status`, `messages`, `records`, and `result_scalar`
        (e.g. the new BU id from bu.create), or `error` for unknown/gated ops.
    """
    from actone.soap import SOAP_OPS, SoapClient, SoapError
    spec = SOAP_OPS.get(operation_id)
    if not spec:
        return {"error": "unknown_soap_operation", "operationId": operation_id,
                "known": list(SOAP_OPS)}
    if spec["access"] == "write" and not writes_enabled(env):
        return {"error": "operation %r is a WRITE (%s.%s) but writes are disabled for "
                         "environment %r; set `allow_writes: true` for it in "
                         "actone-ops.yaml (or ACTONE_ALLOW_WRITES=true for the default "
                         "environment) to enable"
                         % (operation_id, spec["service"], spec["operation"],
                            env or "default"),
                "operationId": operation_id, "env": env or "default"}
    try:
        return SoapClient(_get_client(env)).call(operation_id, params or {})
    except SoapError as e:
        return {"error": str(e), "operationId": operation_id, "env": env or "default"}


def _designer_write_guard(env: Optional[str], operation: str) -> Optional[dict]:
    """Return a gate-error dict when the target env forbids writes, else None."""
    if not writes_enabled(env):
        return {"error": "operation %r is a Designer WRITE but writes are disabled for "
                         "environment %r; set `allow_writes: true` for it in "
                         "actone-ops.yaml (or ACTONE_ALLOW_WRITES=true for the default "
                         "environment) to enable" % (operation, env or "default"),
                "operation": operation, "env": env or "default"}
    return None


@mcp.tool()
def designer_search_types(query: str = "", creatable_only: bool = False,
                          limit: int = 50) -> dict:
    """Discover ActOne **Designer object types** (the catalog of configurable
    artifacts: alert types, case types, queries incl. DrillDownQuery, workflows,
    policies, lists, views, ...).

    CONVENTION — REST-first: the Designer/SOAP tools are for the **design-time
    config surface the Extend REST API does not cover**. If an equivalent runtime
    operation exists in REST (search_ops / describe_op / invoke_op), prefer REST;
    use these designer_* tools only when REST has no equivalent.

    Each result has `typeValue` (the wire name used everywhere else),
    `enumName`, and `creatable` (whether a create path + payload bean exists).
    Follow up with designer_describe_type for the create schema.

    Args:
        query: Keywords, e.g. "query", "alert", "drill down".
        creatable_only: When true, only types that can be created via Designer.
        limit: Max results.
    """
    from actone.soap_catalog import load_catalog
    global _soap_catalog
    with _lock:
        if _soap_catalog is None:
            _soap_catalog = load_catalog()
        cat = _soap_catalog
    types = cat.search_object_types(query, creatable_only=creatable_only, limit=limit)
    return {"source": cat.source, "count": len(types), "types": types}


@mcp.tool()
def designer_describe_type(type_value: str) -> dict:
    """Show a Designer object type's create path and full payload-bean field schema.

    Use the returned `createBean.fields` (name/type, plus `declaredIn`) to assemble
    the `fields` argument for designer_create_object. `identifier`/`name`/
    `description` populate the object's identity (objectInfo). Scalar fields map to
    JSON scalars; nested-bean fields take a JSON object/array.

    GROUNDING — the response includes a `grounding` block. The catalog gives the
    field *shape*, but not the product *procedure*: the setup sequence, prerequisites
    (e.g. a DrillDownQuery needs an existing JDBC connection), and server-enforced
    mandatory fields. Before authoring, follow `grounding.suggestedQueries` into the
    ActWise docs MCP (docenter search_docs / get_page) to learn the sequence, and
    create any `references` objects first.

    Args:
        type_value: A `typeValue` from designer_search_types (e.g. "DrillDownQuery").
    """
    from actone.soap_catalog import load_catalog
    global _soap_catalog
    with _lock:
        if _soap_catalog is None:
            _soap_catalog = load_catalog()
        cat = _soap_catalog
    info = cat.describe_type(type_value)
    if not info:
        return {"error": "unknown_type", "typeValue": type_value,
                "suggestions": [t["typeValue"] for t in cat.search_object_types(type_value, limit=5)]}
    return info


@mcp.tool()
def designer_search_operations(query: str = "", limit: int = 25) -> dict:
    """Discover raw ActOne **SOAP operations** across the 22 Axis services (the
    lower-level surface behind the Designer object model). Use this for operations
    not covered by the typed designer_* tools; invoke via designer_call_operation.

    Args:
        query: Keywords, e.g. "hierarchy", "workflow", "connection".
        limit: Max results.
    """
    from actone.soap_catalog import load_catalog
    global _soap_catalog
    with _lock:
        if _soap_catalog is None:
            _soap_catalog = load_catalog()
        cat = _soap_catalog
    return {"source": cat.source, "operations": cat.search_services(query, limit)}


@mcp.tool()
def designer_list_objects(type_value: str, full: bool = False,
                          env: Optional[str] = None) -> dict:
    """List existing Designer objects of one type (READ).

    By default returns the lightweight info list (identifiers + names); set
    `full=True` for the complete object graph of each. Reads always run.

    Args:
        type_value: A `typeValue` (see designer_search_types).
        full: When true, return full objects instead of the info list.
        env: Named ActOne environment (see list_environments).
    """
    from actone.designer import DesignerError
    try:
        d = _get_designer(env)
        res = d.get_object_list(type_value) if full else d.get_object_info_list(type_value)
        return res
    except DesignerError as e:
        return {"error": str(e), "typeValue": type_value, "env": env or "default"}


@mcp.tool()
def designer_get_object(type_value: str, identifier: str,
                        env: Optional[str] = None) -> dict:
    """Fetch one Designer object by type + identifier (READ).

    Args:
        type_value: A `typeValue` (see designer_search_types).
        identifier: The object's identifier (see designer_list_objects).
        env: Named ActOne environment (see list_environments).
    """
    from actone.designer import DesignerError
    try:
        return _get_designer(env).get_object(type_value, identifier)
    except DesignerError as e:
        return {"error": str(e), "typeValue": type_value, "identifier": identifier,
                "env": env or "default"}


@mcp.tool()
def designer_get_remove_constraints(type_value: str, identifier: str,
                                    env: Optional[str] = None) -> dict:
    """List what depends on a Designer object before deleting it (READ).

    Args:
        type_value: A `typeValue` (see designer_search_types).
        identifier: The object's identifier.
        env: Named ActOne environment.
    """
    from actone.designer import DesignerError
    try:
        return _get_designer(env).get_remove_constraints(type_value, identifier)
    except DesignerError as e:
        return {"error": str(e), "typeValue": type_value, "identifier": identifier,
                "env": env or "default"}


@mcp.tool()
def designer_create_object(type_value: str, fields: dict,
                           env: Optional[str] = None) -> dict:
    """Create a Designer object of any creatable type (WRITE, gated).

    Build `fields` from designer_describe_type: bean fields by name, plus
    `identifier`/`name`/`description` for the object identity. Nested-bean fields
    take a JSON object; arrays take a JSON list. Referenced objects (foreign keys
    by identifier) must already exist.

    GROUNDING — call designer_describe_type first and read its `grounding` block:
    consult the ActWise docs MCP (docenter) for this type's setup sequence and
    prerequisites, so you supply server-mandatory fields (e.g. connectionId) and
    create referenced objects in the right order.

    Refused unless the target environment permits writes (default-deny; the model
    cannot lift the gate). Returns the new object's identification.

    Args:
        type_value: A creatable `typeValue` (see designer_search_types creatable_only=true).
        fields: Flat dict of bean fields + identifier/name/description.
        env: Named ActOne environment (see list_environments).
    """
    gate = _designer_write_guard(env, "%s.create" % type_value)
    if gate:
        return gate
    from actone.designer import DesignerError
    try:
        return _get_designer(env).create_object(type_value, fields or {})
    except DesignerError as e:
        return {"error": str(e), "typeValue": type_value, "env": env or "default"}


@mcp.tool()
def create_drill_down_query(identifier: str, sql_query: str, name: Optional[str] = None,
                            description: str = "", page_title: str = "",
                            connection_id: Optional[int] = None,
                            column_names: str = "", parameters: str = "",
                            parameter_types: str = "", page_size: Optional[int] = None,
                            web_accessible: bool = True, secured: bool = False,
                            extra_fields: Optional[dict] = None,
                            env: Optional[str] = None) -> dict:
    """Create a **Drill Down Query (DDQ)** in ActOne Designer (WRITE, gated).

    A DDQ (objectType `DrillDownQuery`) is a saved parameterized SQL query surfaced
    as a drill-down page. This is a convenience wrapper over designer_create_object;
    for the full DrillDownQuery field set see designer_describe_type("DrillDownQuery")
    and pass anything extra via `extra_fields`.

    GROUNDING — a DDQ requires an existing JDBC **connection** (`connection_id`); the
    server rejects a null connection. For the full setup sequence (define the
    connection, define the query, set up results display, add logged-in-user
    parameters) consult the ActWise docs MCP (docenter): "Setting up Drill-Down
    Queries". Prefer running an existing DDQ over the REST API when you only need to
    execute one — author via Designer only to create/edit the definition.

    Refused unless the target environment permits writes (default-deny).

    Args:
        identifier: Unique DDQ identifier.
        sql_query: The SQL the drill-down runs.
        name: Display name (defaults to identifier).
        description: Optional description.
        page_title: Drill-down page title.
        connection_id: JDBC connection id the query runs against.
        column_names: Comma-separated display column names.
        parameters: Query parameter definition string.
        parameter_types: Parameter types string (parallel to parameters).
        page_size: Rows per page.
        web_accessible: Whether the DDQ is web-accessible (default true).
        secured: Whether the DDQ is access-secured (default false).
        extra_fields: Any additional DrillDownQuery bean fields.
        env: Named ActOne environment (see list_environments).
    """
    gate = _designer_write_guard(env, "DrillDownQuery.create")
    if gate:
        return gate
    fields: dict = {
        "identifier": identifier,
        "name": name or identifier,
        "description": description,
        "pageTitle": page_title,
        "sqlQuery": sql_query,
        "columnNames": column_names,
        "parameters": parameters,
        "parameterTypes": parameter_types,
        "webAccessible": web_accessible,
        "secured": secured,
    }
    if connection_id is not None:
        fields["connectionId"] = connection_id
    if page_size is not None:
        fields["pageSize"] = page_size
    if extra_fields:
        fields.update(extra_fields)
    from actone.designer import DesignerError
    try:
        return _get_designer(env).create_object("DrillDownQuery", fields)
    except DesignerError as e:
        return {"error": str(e), "identifier": identifier, "env": env or "default"}


def _csv_list(value: str) -> list:
    """Split a comma-separated option string into a trimmed, non-empty list."""
    return [s.strip() for s in (value or "").split(",") if s.strip()]


@mcp.tool()
def create_alert_type(identifier: str, name: Optional[str] = None, description: str = "",
                      alert_status_workflow_definition_identifier: Optional[str] = None,
                      using_alert_status_workflow: bool = False,
                      assigned_status_identifiers: str = "",
                      method_id: int = 4,
                      support_manual_alerts: bool = False,
                      enabled_for_global_search: bool = False,
                      extra_fields: Optional[dict] = None,
                      env: Optional[str] = None) -> dict:
    """Create an **Alert Type** in ActOne Designer (WRITE, gated).

    An AlertType (objectType `AlertType`) is a design-time alert definition. REST can
    edit an existing type's fields but cannot create the type — this is Designer-only.
    Convenience wrapper over designer_create_object (generic addObject, AlertType2
    bean); pass any additional bean field (view, alertTypeFields, formMapping, ...) via
    `extra_fields`. For the full field set see designer_describe_type("AlertType").

    GROUNDING — read designer_describe_type("AlertType").grounding.sequence first. The
    documented order is: create required custom fields → create the
    AlertStatusWorkflowDefinition (if using a workflow) → create the alert type
    (commonly by CLONING the default, then editing) → create an AlertView → configure
    status transitions. `alertStatusWorkflowDefinitionIdentifier` must reference an
    existing workflow definition. Prefer REST for anything it already covers.

    Refused unless the target environment permits writes (default-deny).

    Args:
        identifier: Unique alert-type identifier.
        name: Display name (defaults to identifier).
        description: Optional description.
        alert_status_workflow_definition_identifier: FK to an existing
            AlertStatusWorkflowDefinition (required when using a status workflow).
        using_alert_status_workflow: Whether the type uses a status workflow.
        assigned_status_identifiers: Comma-separated AlertStatus identifiers to assign.
            Omit when using_alert_status_workflow is true — the workflow supplies them
            (the server rejects assigning an "all"-scope status alongside a workflow).
        method_id: Alert display/render method (server-mandatory). Defaults to 4
            (XML-from-DB), the modern default; rarely needs changing.
        support_manual_alerts: Whether manual alert creation is supported.
        enabled_for_global_search: Whether the type is enabled for global search.
        extra_fields: Any additional AlertType2 bean fields (nested as JSON).
        env: Named ActOne environment (see list_environments).
    """
    gate = _designer_write_guard(env, "AlertType.create")
    if gate:
        return gate
    fields: dict = {
        "identifier": identifier,
        "name": name or identifier,
        "description": description,
        "usingAlertStatusWorkflow": using_alert_status_workflow,
        "methodId": method_id,
        "supportManualAlerts": support_manual_alerts,
        "enabledForGlobalSearch": enabled_for_global_search,
    }
    if alert_status_workflow_definition_identifier:
        fields["alertStatusWorkflowDefinitionIdentifier"] = alert_status_workflow_definition_identifier
    statuses = _csv_list(assigned_status_identifiers)
    if statuses:
        fields["assignedStatusIdentifiersList"] = statuses
    if extra_fields:
        fields.update(extra_fields)
    from actone.designer import DesignerError
    try:
        return _get_designer(env).create_object("AlertType", fields)
    except DesignerError as e:
        return {"error": str(e), "identifier": identifier, "env": env or "default"}


@mcp.tool()
def create_case_type(identifier: str, name: Optional[str] = None, description: str = "",
                     case_status_workflow_definition_identifier: Optional[str] = None,
                     using_case_status_workflow: bool = False,
                     case_status_identifiers: str = "",
                     pre_defined_note_identifiers: str = "",
                     extra_fields: Optional[dict] = None,
                     env: Optional[str] = None) -> dict:
    """Create a **Case Type** in ActOne Designer (WRITE, gated).

    A CaseType (objectType `CaseType`) is a design-time case definition. REST cannot
    create the type — this is Designer-only. Convenience wrapper over
    designer_create_object (generic addObject, CaseType bean); pass additional bean
    fields (m_caseTypeFields, additionalWorkflowAssociations, ...) via `extra_fields`.
    For the full field set see designer_describe_type("CaseType").

    GROUNDING — read designer_describe_type("CaseType").grounding.sequence first. The
    documented order is: define case steps + predefined notes → customize built-in
    field titles → create custom fields → create the case steps workflow (optional) →
    create the case type → define case-view order.
    `caseStatusWorkflowDefinitionIdentifier` must reference an existing workflow
    definition. Prefer REST for anything it already covers.

    Refused unless the target environment permits writes (default-deny).

    Args:
        identifier: Unique case-type identifier.
        name: Display name (defaults to identifier).
        description: Optional description.
        case_status_workflow_definition_identifier: FK to an existing
            CaseStatusWorkflowDefinition (required when using a status workflow).
        using_case_status_workflow: Whether the type uses a status workflow.
        case_status_identifiers: Comma-separated CaseStatus identifiers to assign.
        pre_defined_note_identifiers: Comma-separated predefined-note identifiers.
        extra_fields: Any additional CaseType bean fields (nested as JSON).
        env: Named ActOne environment (see list_environments).
    """
    gate = _designer_write_guard(env, "CaseType.create")
    if gate:
        return gate
    fields: dict = {
        "identifier": identifier,
        "name": name or identifier,
        "description": description,
        "usingCaseStatusWorkflow": using_case_status_workflow,
    }
    if case_status_workflow_definition_identifier:
        fields["caseStatusWorkflowDefinitionIdentifier"] = case_status_workflow_definition_identifier
    statuses = _csv_list(case_status_identifiers)
    if statuses:
        fields["caseStatuses"] = statuses
    notes = _csv_list(pre_defined_note_identifiers)
    if notes:
        fields["preDefinedNotes"] = notes
    if extra_fields:
        fields.update(extra_fields)
    from actone.designer import DesignerError
    try:
        return _get_designer(env).create_object("CaseType", fields)
    except DesignerError as e:
        return {"error": str(e), "identifier": identifier, "env": env or "default"}


@mcp.tool()
def designer_clone_object(type_value: str, source_identifier: str,
                          new_identifier: str, overrides: Optional[dict] = None,
                          env: Optional[str] = None) -> dict:
    """Create a copy of an existing Designer object under a new identifier (WRITE, gated).

    Fetches the source, drops its internal id, applies `overrides`, and creates the
    copy. Referenced objects (foreign keys by identifier) are copied by identifier,
    so they must already exist on the target. Refused unless the environment permits
    writes.

    Args:
        type_value: The object's `typeValue`.
        source_identifier: Identifier of the object to copy.
        new_identifier: Identifier for the new object.
        overrides: Optional field values to override on the copy.
        env: Named ActOne environment.
    """
    gate = _designer_write_guard(env, "%s.clone" % type_value)
    if gate:
        return gate
    from actone.designer import DesignerError
    try:
        return _get_designer(env).clone_object(type_value, source_identifier,
                                               new_identifier, overrides or {})
    except DesignerError as e:
        return {"error": str(e), "typeValue": type_value,
                "sourceIdentifier": source_identifier, "env": env or "default"}


@mcp.tool()
def designer_update_object(type_value: str, identifier: str, object_xml: str,
                           env: Optional[str] = None) -> dict:
    """Save a modified Designer object payload (WRITE, gated).

    Typical flow: designer_get_object to fetch, adjust fields, then pass the object
    payload XML here. Refused unless the environment permits writes.

    Args:
        type_value: The object's `typeValue`.
        identifier: The object's identifier.
        object_xml: The full object payload XML (root attributes incl. xsi:type preserved).
        env: Named ActOne environment.
    """
    gate = _designer_write_guard(env, "%s.update" % type_value)
    if gate:
        return gate
    from actone.designer import DesignerError
    try:
        return _get_designer(env).update_object(type_value, identifier, object_xml)
    except DesignerError as e:
        return {"error": str(e), "typeValue": type_value, "identifier": identifier,
                "env": env or "default"}


@mcp.tool()
def designer_remove_object(type_value: str, identifier: str,
                           env: Optional[str] = None) -> dict:
    """Delete a Designer object by type + identifier (WRITE, gated).

    Check designer_get_remove_constraints first. Refused unless the environment
    permits writes.

    Args:
        type_value: The object's `typeValue`.
        identifier: The object's identifier.
        env: Named ActOne environment.
    """
    gate = _designer_write_guard(env, "%s.remove" % type_value)
    if gate:
        return gate
    from actone.designer import DesignerError
    try:
        return _get_designer(env).remove_object(type_value, identifier)
    except DesignerError as e:
        return {"error": str(e), "typeValue": type_value, "identifier": identifier,
                "env": env or "default"}


@mcp.tool()
def designer_validate_object(type_value: str, identifier: str, object_xml: str,
                             env: Optional[str] = None) -> dict:
    """Server-side validation of a Designer object payload WITHOUT saving (READ).

    Returns `messages` (empty = valid). Safe to run regardless of the write gate.

    Args:
        type_value: The object's `typeValue`.
        identifier: The object's identifier.
        object_xml: The object payload XML to validate.
        env: Named ActOne environment.
    """
    from actone.designer import DesignerError
    try:
        return _get_designer(env).validate_object(type_value, identifier, object_xml)
    except DesignerError as e:
        return {"error": str(e), "typeValue": type_value, "identifier": identifier,
                "env": env or "default"}


@mcp.tool()
def designer_call_operation(service: str, operation: str, inner_xml: str = "",
                            out_param: Optional[str] = None,
                            env: Optional[str] = None) -> dict:
    """Escape hatch: invoke ANY catalog SOAP operation with a raw inner-XML param
    list (for operations not covered by the typed designer_* tools).

    Discover operations with designer_search_operations (each hit carries an
    `access` field). Read operations (get*/list*/find*/has*/count* ...) run freely;
    writes and unrecognised verbs are refused unless the environment permits writes.
    `inner_xml` is the encoded parameter list (each element with its xsi:type).

    Args:
        service: Axis service name (e.g. "businessUnitService").
        operation: Operation name (e.g. "getAllBusinessUnits").
        inner_xml: Encoded parameter list (may be empty).
        out_param: Name of the response out-parameter to extract, if known.
        env: Named ActOne environment.
    """
    from actone.soap_catalog import operation_access
    if operation_access(operation) == "write":
        gate = _designer_write_guard(env, "%s.%s" % (service, operation))
        if gate:
            return gate
    from actone.designer import DesignerError
    try:
        return _get_designer(env).call_operation(service, operation, inner_xml or "", out_param)
    except DesignerError as e:
        return {"error": str(e), "service": service, "operation": operation,
                "env": env or "default"}


@mcp.tool()
def list_environments() -> dict:
    """List the **live ActOne administration (OPS) environments** — server instances for operations and writes.

    These are the **live-administration** environments and are DISTINCT from the Data
    MCP's database/query environments. Use this ONLY for live ActOne operations; for
    read-only database reporting use the Data server's ``list_environments`` instead.
    Each entry has `name`, `url`, `user`, `context_root`, `requires_vpn`,
    `allow_writes`, `notes`, `password_configured`, and `is_default` — **never the
    password**. Pass a `name` as the `env` argument of invoke_op to run against that
    instance. `allow_writes` reflects whether live writes are currently permitted
    for that environment (config-driven, default-deny). Environments come from
    `actone-ops.yaml`; the built-in `default` reads the server's `.env` / process env.

    Note: environments flagged `requires_vpn=true` (e.g. AWS-internal instances)
    are only reachable when the server host is on the corporate VPN.
    """
    from actone.ops_config import list_environments as _list_envs
    envs = _list_envs()
    return {"count": len(envs), "environments": envs}


@mcp.tool()
def list_tags() -> dict:
    """List the operation tags (functional domains) and their operation counts."""
    return _reg().tags()


@mcp.tool()
def list_ops(reads_only: bool = False, tag: Optional[str] = None,
             group: bool = False, offset: int = 0, limit: int = 50) -> dict:
    """List the ActOne operation surface, **paginated**.

    Enumerates operations (optionally filtered by `tag` / `reads_only`). Results
    are PAGED so a single response stays small enough for remote/gateway MCP
    transports (e.g. Copilot Studio behind a proxy, which rejects large streamed
    responses). Walk the full set with `offset`/`limit`, or narrow with `tag`.
    Prefer `search_ops` (keyword) or `list_tags` (domain counts) when you don't
    need a raw enumeration.

    Args:
        reads_only: When true, only include read (GET) operations.
        tag: Optional single tag/domain to filter to (ignored when group=True).
        group: When true, return {tag: [operations]} grouped by tag instead of a
            paged flat list. NOTE: grouped returns the full set in one response —
            prefer the paged flat form (or a `tag` filter) on large surfaces.
        offset: Zero-based start index into the (filtered) flat list.
        limit: Max operations to return in this page (1-200, default 50).

    Returns:
        dict with `specVersion`, `count` (total ops on the instance), and either
        `groups` (when group=True) or a page: `operations`, `returned`, `total`
        (matching the filter), `offset`, and `next_offset` (null when exhausted).
    """
    reg = _reg()
    base = {"specVersion": reg.info_version, "source": reg.source,
            "count": len(reg.ops)}
    if group:
        base["groups"] = reg.grouped(reads_only=reads_only)
        return base
    limit = max(1, min(200, limit))
    offset = max(0, offset)
    ops = reg.list_ops(reads_only=reads_only, tag=tag)
    page = ops[offset:offset + limit]
    nxt = offset + limit
    base["total"] = len(ops)
    base["operations"] = page
    base["returned"] = len(page)
    base["offset"] = offset
    base["next_offset"] = nxt if nxt < len(ops) else None
    return base


# ── ASGI app: auth gate + health, wrapping the Streamable-HTTP MCP ────────────
class _AuthGate:
    """Pure-ASGI middleware: serves /healthz, enforces X-API-Key when configured.

    Pure ASGI (not BaseHTTPMiddleware) so it never buffers the MCP stream and
    passes lifespan events straight through to the FastMCP session manager. When
    ACTONE_PROXY_API_KEY is unset the server runs open (convenient for local
    proving); set it for any shared / tunnelled / cloud deployment."""

    def __init__(self, app, api_key: Optional[str]):
        self.app = app
        self.api_key = api_key

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        if path == "/healthz":
            await JSONResponse({"status": "ok", "server": SERVER_NAME})(scope, receive, send)
            return
        if self.api_key:
            headers = dict(scope.get("headers") or [])
            provided = headers.get(b"x-api-key", b"").decode()
            if not (provided and hmac.compare_digest(provided, self.api_key)):
                await JSONResponse({"error": "unauthorized"}, status_code=401)(scope, receive, send)
                return
        await self.app(scope, receive, send)


# ASGI entrypoint for uvicorn (Streamable HTTP):
#   py -m uvicorn actone_mcp.server:app --host 0.0.0.0 --port 8765
#   endpoint: http://localhost:8765/mcp   health: http://localhost:8765/healthz
app = _AuthGate(mcp.streamable_http_app(), os.environ.get(API_KEY_ENV))


def main() -> None:
    """Run as a stdio MCP server (local clients: Copilot CLI, VS Code, Claude)."""
    mcp.run()


if __name__ == "__main__":
    main()
