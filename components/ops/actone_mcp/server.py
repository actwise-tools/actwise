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
_DESIGNER_STATE_CAPABILITY = "create_work_item_type"


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


def _designer_state_document(exported: dict, label: str) -> tuple[dict, str]:
    """Validate and extract the logical portion of a Designer state export."""
    from actone.designer_state import fingerprint_document

    if not isinstance(exported, dict):
        raise ValueError("%s must be an exported JSON object" % label)
    document = {
        "schemaVersion": exported.get("schemaVersion"),
        "capability": exported.get("capability"),
        "specification": exported.get("specification"),
    }
    if document["schemaVersion"] != 1:
        raise ValueError("%s has unsupported schemaVersion" % label)
    if document["capability"] != _DESIGNER_STATE_CAPABILITY:
        raise ValueError(
            "%s must export capability %r"
            % (label, _DESIGNER_STATE_CAPABILITY)
        )
    if not isinstance(document["specification"], dict):
        raise ValueError("%s is missing specification" % label)
    fingerprint = fingerprint_document(document)
    if exported.get("fingerprint") != fingerprint:
        raise ValueError("%s fingerprint does not match its logical state" % label)
    return document, fingerprint


def _desired_designer_state(specification: dict) -> tuple[dict, str]:
    from actone.designer_state import (
        fingerprint_document,
        normalize_capability_specification,
    )

    document = {
        "schemaVersion": 1,
        "capability": _DESIGNER_STATE_CAPABILITY,
        "specification": normalize_capability_specification(
            _DESIGNER_STATE_CAPABILITY, specification
        ),
    }
    return document, fingerprint_document(document)


def _collect_designer_state(specification: dict,
                            env: Optional[str] = None) -> dict:
    """Collect and export one verified build's logical work-item state."""
    from actone.designer_capabilities import load_capabilities
    from actone.designer_planner import collect_work_item_observation
    from actone.designer_state import export_capability_state

    environment = env or "default"
    client = _get_client(env)
    target_build = getattr(client, "version", None) or client.detect_version()
    build_info = load_capabilities().inspect(
        _DESIGNER_STATE_CAPABILITY, target_build
    )
    if not build_info or build_info["buildStatus"] != "verified":
        return {
            "error": "unsupported_build",
            "capability": _DESIGNER_STATE_CAPABILITY,
            "sourceEnvironment": environment,
            "sourceBuild": target_build,
            "verifiedBuilds": (
                build_info.get("verifiedBuilds", []) if build_info else []
            ),
        }
    observed = collect_work_item_observation(
        _get_designer(env), specification
    )
    exported = export_capability_state(
        _DESIGNER_STATE_CAPABILITY, specification, observed
    )
    return {
        "sourceEnvironment": environment,
        "sourceBuild": target_build,
        **exported,
    }


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


def _dart_rows(body) -> Optional[list]:
    """Best-effort extraction of a row list from a DART REST response body.
    Returns None (not an empty list) when no row list could be found, so the
    caller can tell "confirmed empty" apart from "couldn't parse"."""
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        data = body.get("data")
        if isinstance(data, dict):
            records = data.get("records")
            if isinstance(records, list):
                if records:
                    return records
                info = data.get("info")
                if isinstance(info, dict) and info.get("moreExist") is False:
                    return []
                return None
        for key in ("rows", "data", "results", "records"):
            value = body.get(key)
            if isinstance(value, list):
                if key == "rows" and not value and body.get("hasMoreResults") is not False:
                    return None
                return value
    return None


def _collect_alert_type_usage(client, identifier: Optional[str],
                              data_source_identifier: Optional[str],
                              ddq_identifier: Optional[str] = None) -> dict:
    """REST-first runtime-use preflight for the `create_work_item_type`
    conservative-update slice.

    Executes the bundled Extend REST operation `getDartResultsGet`
    (`GET /RCM/api/v1/dart/{dataSourceIdentifier}`, filtered with
    `filter=alertTypeIdentifier=<identifier>`) against a pre-provisioned DART
    data source and normalizes the row payload into the alertTypeInUse /
    alertTypeUseCount / alertTypeUseEvidence fact consumed by plan_work_item_type.

    Returns {} (unknown) when no data source is configured, no work-item
    identifier is known yet, or the REST call fails. Unknown usage deliberately
    blocks an existing AlertType mutation, but does not affect create or reuse.
    Callers never instantiate a client here beyond the one already handed in."""
    if not identifier or not (data_source_identifier or ddq_identifier):
        return {}
    from actone.designer_planner import alert_type_usage_from_dart_rows
    operation_id = "runDDQ" if ddq_identifier else "getDartResultsGet"
    source_identifier = ddq_identifier or data_source_identifier
    params = (
        {
            "ddqIdentifier": ddq_identifier,
            "ddqParams": identifier,
            "maxNumOfRows": 1,
            "startIndex": 0,
            "timeoutInSeconds": 30,
        }
        if ddq_identifier else
        {
            "dataSourceIdentifier": data_source_identifier,
            "filter": "alertTypeIdentifier=%s" % identifier,
        }
    )
    try:
        result = invoke(_reg(), client, operation_id, params=params)
    except InvokeError:
        return {}
    if not result.get("ok"):
        return {}
    return alert_type_usage_from_dart_rows(
        _dart_rows(result.get("body")),
        source_identifier,
        identifier,
        operation_id=operation_id,
        source_parameter=(
            "ddqIdentifier" if ddq_identifier else "dataSourceIdentifier"
        ),
    )


@mcp.tool()
def designer_search_capabilities(query: str = "", maturity: Optional[str] = None,
                                 limit: int = 25) -> dict:
    """Discover capability-oriented ActOne Designer operations and their maturity.

    Start here for design-time authoring. A capability reports supported actions,
    related catalog object types, and builds with live evidence. Maturity values:
    `certified`, `verified_read_only`, `experimental`, and `catalog_only`.

    Args:
        query: Intent keywords such as "work item", "workflow", "view", or "DDQ".
        maturity: Optional exact maturity filter.
        limit: Maximum results.
    """
    from actone.designer_capabilities import load_capabilities

    registry = load_capabilities()
    try:
        capabilities = registry.search(query, maturity=maturity, limit=limit)
    except ValueError as exc:
        return {"error": "invalid_maturity", "message": str(exc)}
    return {
        "source": registry.source,
        "registryVersion": registry.version,
        "count": len(capabilities),
        "capabilities": capabilities,
    }


@mcp.tool()
def designer_inspect(capability_id: str, env: Optional[str] = None) -> dict:
    """Inspect one Designer capability against the target ActOne build (READ).

    This first inspection increment reports capability maturity, supported actions,
    recorded build evidence, and whether the detected target build is verified. It
    does not plan or apply mutations.

    Args:
        capability_id: ID returned by designer_search_capabilities.
        env: Named ActOne environment (see list_environments).
    """
    from actone.designer_capabilities import load_capabilities

    registry = load_capabilities()
    capability = registry.describe(capability_id)
    if not capability:
        return {
            "error": "unknown_capability",
            "capabilityId": capability_id,
            "suggestions": [
                item["id"] for item in registry.search(capability_id, limit=5)
            ],
        }
    client = _get_client(env)
    target_build = getattr(client, "version", None) or "unknown"
    result = registry.inspect(capability_id, target_build)
    result["environment"] = env or "default"
    return result


@mcp.tool()
def designer_export_state(specification: dict,
                          env: Optional[str] = None) -> dict:
    """Export normalized `create_work_item_type` state from one environment.

    The specification selects the exact owned work-item type, workflow, statuses,
    custom fields, and view to hydrate. The target build must be verified for the
    capability. The result contains only logical state plus source environment,
    build, and a stable fingerprint; SOAP/session plumbing is redacted.

    Args:
        specification: Work-item specification identifying the owned objects.
        env: Named ActOne environment (see list_environments).
    """
    from actone.designer import DesignerError

    try:
        return _collect_designer_state(specification, env)
    except (DesignerError, InvokeError, ValueError) as exc:
        return {
            "error": "state_export_failed",
            "capability": _DESIGNER_STATE_CAPABILITY,
            "sourceEnvironment": env or "default",
            "message": str(exc),
        }


@mcp.tool()
def designer_compare_state(specification: dict,
                           env: Optional[str] = None) -> dict:
    """Compare verified environment state with a desired work-item specification.

    Performs read-only hydration and normalization, then reports deterministic
    JSONPath differences. Missing or incomplete owned objects fail closed.

    Args:
        specification: Complete desired `create_work_item_type` specification.
        env: Named ActOne environment (see list_environments).
    """
    from actone.designer import DesignerError
    from actone.designer_state import diff_documents

    try:
        desired, desired_fingerprint = _desired_designer_state(specification)
        exported = _collect_designer_state(specification, env)
        if "error" in exported:
            return exported
        actual, actual_fingerprint = _designer_state_document(
            exported, "environment export"
        )
        return {
            "sourceEnvironment": exported["sourceEnvironment"],
            "sourceBuild": exported["sourceBuild"],
            "sourceFingerprint": actual_fingerprint,
            "desiredFingerprint": desired_fingerprint,
            "diff": diff_documents(actual, desired),
        }
    except (DesignerError, InvokeError, ValueError) as exc:
        return {
            "error": "state_compare_failed",
            "capability": _DESIGNER_STATE_CAPABILITY,
            "sourceEnvironment": env or "default",
            "message": str(exc),
        }


@mcp.tool()
def designer_diff_exports(source_export: dict, target_export: dict) -> dict:
    """Diff two exported Designer JSON documents without logging in.

    Both inputs must be intact outputs of designer_export_state. Source metadata
    outside the logical document is ignored, so environment names, builds,
    numeric transport IDs, cookies, and secrets are never compared.

    Args:
        source_export: First exported JSON document.
        target_export: Second exported JSON document.
    """
    from actone.designer_state import diff_documents

    try:
        source, source_fingerprint = _designer_state_document(
            source_export, "source export"
        )
        target, target_fingerprint = _designer_state_document(
            target_export, "target export"
        )
        return {
            "sourceFingerprint": source_fingerprint,
            "targetFingerprint": target_fingerprint,
            "diff": diff_documents(source, target),
        }
    except ValueError as exc:
        return {
            "error": "invalid_state_export",
            "capability": _DESIGNER_STATE_CAPABILITY,
            "message": str(exc),
        }


@mcp.tool()
def designer_compare_environments(specification: dict, source_env: str,
                                  target_env: str) -> dict:
    """Compare independently collected work-item exports from two environments.

    Both targets must run a build verified for `create_work_item_type`. Each
    environment is hydrated separately; only normalized logical documents are
    compared.

    Args:
        specification: Work-item specification selecting the owned objects.
        source_env: Named source ActOne environment.
        target_env: Named target ActOne environment.
    """
    from actone.designer import DesignerError
    from actone.designer_state import diff_documents

    try:
        source_export = _collect_designer_state(specification, source_env)
        target_export = _collect_designer_state(specification, target_env)
        if "error" in source_export:
            return source_export
        if "error" in target_export:
            return target_export
        source, source_fingerprint = _designer_state_document(
            source_export, "source environment export"
        )
        target, target_fingerprint = _designer_state_document(
            target_export, "target environment export"
        )
        return {
            "sourceEnvironment": source_export["sourceEnvironment"],
            "sourceBuild": source_export["sourceBuild"],
            "sourceFingerprint": source_fingerprint,
            "targetEnvironment": target_export["sourceEnvironment"],
            "targetBuild": target_export["sourceBuild"],
            "targetFingerprint": target_fingerprint,
            "diff": diff_documents(source, target),
        }
    except (DesignerError, InvokeError, ValueError) as exc:
        return {
            "error": "environment_compare_failed",
            "capability": _DESIGNER_STATE_CAPABILITY,
            "sourceEnvironment": source_env,
            "targetEnvironment": target_env,
            "message": str(exc),
        }


@mcp.tool()
def designer_plan(capability_id: str, specification: dict,
                  env: Optional[str] = None,
                  alert_type_usage_data_source: Optional[str] = None,
                  alert_type_usage_ddq: Optional[str] = None,
                  ddq_reference_evidence: Optional[dict] = None,
                  internal_connection_evidence: bool = False,
                  internal_connection_evidence_source: Optional[str] = None,
                  renderer_inventory: Optional[list[str]] = None) -> dict:
    """Build a deterministic, read-only Designer mutation plan.

    Supported recipes include Platform Lists, complete work-item families, DDQs,
    modern work-item presentation, and create/exact-reuse business-unit
    hierarchies. This tool performs reads only and never applies returned steps.

    Args:
        capability_id: Capability ID from designer_search_capabilities.
        specification: Domain-level desired configuration; no SOAP XML.
        env: Named ActOne environment.
        alert_type_usage_data_source: Optional DART data source identifier used to
            REST-preflight whether runtime alerts already exist for the requested
            work-item type (`getDartResultsGet`, filtered by alertTypeIdentifier).
            When set and alerts are found, any proposed AlertType update becomes an
            explicit conflict instead of a step -- live ActOne rejects AlertType
            updates once alerts reference the type. If an existing AlertType
            needs mutation, omission or query failure blocks the plan because
            zero runtime references have not been established.
        alert_type_usage_ddq: Preferred parameterized DDQ identifier. The DDQ
            receives the work-item type identifier as its sole `ddqParams` value
            and should return an `alert_id` row for each runtime reference.
        ddq_reference_evidence: Structured DDQ connection/reference evidence.
            External numeric connection IDs require a trusted non-REST source.
        internal_connection_evidence: Explicitly authorize documented evidence
            for the built-in DDQ connectionId=-1. It is never inferred.
        internal_connection_evidence_source: `documented` (default when the flag
            is set) or `live-evidenced`.
        renderer_inventory: Known formatter/renderer identifiers. Required when
            work-item presentation requests formatter references.
    """
    from actone.designer import DesignerError
    from actone.designer_capabilities import (
        PLANNABLE_CAPABILITY_IDS,
        load_capabilities,
    )
    from actone.designer_ddq import (
        DrillDownQueryPlanError,
        build_ddq_reference_evidence,
        collect_drill_down_query_observation,
        manage_drill_down_query,
    )
    from actone.designer_hierarchy import (
        HierarchyPlanError,
        collect_business_unit_hierarchy_observation,
        plan_business_unit_hierarchy,
    )
    from actone.designer_planner import (
        DesignerPlanError,
        collect_remove_work_item_observation,
        collect_work_item_observation,
        plan_remove_work_item_type,
        plan_work_item_type,
    )
    from actone.designer_presentation import (
        collect_work_item_presentation_observation,
        plan_work_item_presentation,
    )
    from actone.invoke import InvokeError
    from actone.platform_list_capability import (
        collect_platform_list_observation,
        plan_platform_list,
    )

    registry = load_capabilities()
    capability = registry.describe(capability_id)
    if not capability:
        return {"error": "unknown_capability", "capabilityId": capability_id}
    if capability_id not in PLANNABLE_CAPABILITY_IDS:
        return {
            "error": "planning_not_supported",
            "capabilityId": capability_id,
            "maturity": capability["maturity"],
        }
    evidence = ddq_reference_evidence
    if capability_id == "manage_drill_down_query":
        try:
            evidence = build_ddq_reference_evidence(
                specification,
                ddq_reference_evidence,
                internal_connection_evidence=internal_connection_evidence,
                internal_connection_evidence_source=(
                    internal_connection_evidence_source
                ),
            )
        except DrillDownQueryPlanError as exc:
            return {
                "error": "invalid_evidence",
                "capabilityId": capability_id,
                "message": str(exc),
            }
    if (
        capability_id == "configure_work_item_presentation"
        and renderer_inventory is not None
        and not isinstance(renderer_inventory, list)
    ):
        return {
            "error": "invalid_renderer_inventory",
            "capabilityId": capability_id,
            "message": "renderer_inventory must be a JSON array",
        }
    try:
        client = _get_client(env)
        target_build = getattr(client, "version", None) or "unknown"
        designer = _get_designer(env)
        if capability_id == "manage_platform_list":
            observed = collect_platform_list_observation(
                designer, _reg(), client, specification
            )
            plan = plan_platform_list(
                specification,
                observed,
                environment=env or "default",
                target_build=target_build,
            )
        elif capability_id == "manage_drill_down_query":
            observed = collect_drill_down_query_observation(
                designer,
                _reg(),
                client,
                specification,
                reference_evidence=evidence,
            )
            plan = manage_drill_down_query(
                specification,
                observed,
                environment=env or "default",
                target_build=target_build,
            )
        elif capability_id == "configure_work_item_presentation":
            observed = collect_work_item_presentation_observation(
                _reg(),
                client,
                specification,
                renderer_inventory=renderer_inventory,
            )
            plan = plan_work_item_presentation(
                specification,
                observed,
                environment=env or "default",
                target_build=target_build,
            )
        elif capability_id == "manage_business_unit_hierarchy":
            observed = collect_business_unit_hierarchy_observation(
                designer, specification
            )
            plan = plan_business_unit_hierarchy(
                specification,
                observed,
                environment=env or "default",
                target_build=target_build,
            )
        elif capability_id == "create_work_item_type":
            identifier = (
                specification.get("identifier")
                if isinstance(specification, dict) else None
            )
            usage = _collect_alert_type_usage(
                client, identifier, alert_type_usage_data_source, alert_type_usage_ddq
            )
            observed = collect_work_item_observation(
                designer, specification, alert_type_usage=usage
            )
            plan = plan_work_item_type(
                specification,
                observed,
                environment=env or "default",
                target_build=target_build,
            )
        else:
            observed = collect_remove_work_item_observation(
                designer, specification
            )
            plan = plan_remove_work_item_type(
                specification,
                observed,
                environment=env or "default",
                target_build=target_build,
            )
        build_info = registry.inspect(capability_id, target_build)
        plan["capabilityMaturity"] = capability["maturity"]
        plan["buildStatus"] = build_info["buildStatus"]
        plan["contractStatus"] = build_info["contractStatus"]
        plan["liveCertificationStatus"] = build_info[
            "liveCertificationStatus"
        ]
        return plan
    except (DesignerPlanError, DrillDownQueryPlanError, HierarchyPlanError) as exc:
        return {
            "error": "invalid_specification",
            "capabilityId": capability_id,
            "message": str(exc),
        }
    except (DesignerError, InvokeError) as exc:
        return {
            "error": "inspection_failed",
            "capabilityId": capability_id,
            "environment": env or "default",
            "message": str(exc),
        }


@mcp.tool()
def designer_apply(plan: dict, env: Optional[str] = None,
                   alert_type_usage_data_source: Optional[str] = None,
                   alert_type_usage_ddq: Optional[str] = None,
                   ddq_reference_evidence: Optional[dict] = None,
                   ddq_runtime_request: Optional[dict] = None,
                   renderer_inventory: Optional[list[str]] = None) -> dict:
    """Apply and verify an approved Designer plan (WRITE, gated).

    The plan must be the unmodified output of designer_plan, target the selected
    environment/build, and still match the current environment observation. The
    operation stops on the first failed step and reports completed steps explicitly;
    it never claims rollback unless compensating removals actually occur.

    Args:
        plan: Complete plan returned by designer_plan.
        env: Named ActOne environment; must match the plan environment.
        alert_type_usage_data_source: Same REST runtime-use preflight as
            designer_plan (see there). Pass the same value used to build `plan`
            so the re-observed state -- and therefore the staleness check -- is
            computed the same way; a changed/newly-detected runtime use makes the
            observation fingerprint mismatch and the apply is refused as stale.
        alert_type_usage_ddq: Same preferred parameterized DDQ used during plan.
        ddq_reference_evidence: Same reference evidence used for a DDQ update.
            Safe connection evidence is reconstructed from the intact plan when
            possible, but zero-reference evidence is never invented.
        ddq_runtime_request: Optional runDDQ verification parameters.
        renderer_inventory: Same renderer inventory used for presentation
            planning when formatter references are present.
    """
    gate = _designer_write_guard(env, "designer_apply")
    if gate:
        return gate
    from actone.designer import DesignerError
    from actone.designer_capabilities import (
        PLANNABLE_CAPABILITY_IDS,
        fingerprint_capability_plan,
        load_capabilities,
    )
    from actone.designer_ddq import (
        DrillDownQueryPlanError,
        apply_drill_down_query_plan,
        merge_ddq_apply_evidence,
    )
    from actone.designer_executor import (
        apply_remove_work_item_plan,
        apply_work_item_plan,
    )
    from actone.designer_hierarchy import (
        HierarchyPlanError,
        apply_business_unit_hierarchy_plan,
    )
    from actone.designer_planner import (
        collect_remove_work_item_observation,
        collect_work_item_observation,
    )
    from actone.designer_presentation import (
        apply_work_item_presentation_plan,
        collect_work_item_presentation_observation,
    )
    from actone.invoke import InvokeError
    from actone.platform_list_capability import (
        apply_platform_list_plan,
        collect_platform_list_observation,
    )

    capability_id = plan.get("capability") if isinstance(plan, dict) else None
    if capability_id not in PLANNABLE_CAPABILITY_IDS:
        return {
            "ok": False,
            "error": "unsupported_capability",
            "capabilityId": capability_id,
        }
    expected_fingerprint = fingerprint_capability_plan(plan)
    if (
        expected_fingerprint != plan.get("fingerprint")
        or plan.get("planId") != expected_fingerprint[:16]
    ):
        return {
            "ok": False,
            "error": "plan_tampered",
            "planId": plan.get("planId"),
        }
    target_environment = env or "default"
    if plan.get("environment") != target_environment:
        return {
            "ok": False,
            "error": "target_environment_changed",
            "plannedEnvironment": plan.get("environment"),
            "actualEnvironment": target_environment,
        }
    client = _get_client(env)
    current_build = getattr(client, "version", None) or "unknown"
    if current_build != plan.get("targetBuild"):
        return {
            "ok": False,
            "error": "target_build_changed",
            "plannedBuild": plan.get("targetBuild"),
            "actualBuild": current_build,
        }
    registry = load_capabilities()
    build_info = registry.inspect(capability_id, current_build)
    if not build_info or build_info["liveCertificationStatus"] != "certified":
        return {
            "ok": False,
            "error": "unsupported_build",
            "capabilityId": capability_id,
            "targetBuild": current_build,
            "verifiedBuilds": (
                build_info.get("verifiedBuilds", []) if build_info else []
            ),
            "offlineContractBuilds": (
                build_info.get("offlineContractBuilds", []) if build_info else []
            ),
            "contractStatus": (
                build_info.get("contractStatus") if build_info else "unverified"
            ),
            "capabilityMaturity": (
                build_info.get("maturity") if build_info else None
            ),
            "liveCertificationStatus": (
                build_info.get("liveCertificationStatus")
                if build_info else "not_live_certified"
            ),
        }
    effective_ddq_evidence = ddq_reference_evidence
    if capability_id == "manage_drill_down_query":
        try:
            effective_ddq_evidence = merge_ddq_apply_evidence(
                plan, ddq_reference_evidence
            )
        except DrillDownQueryPlanError as exc:
            return {
                "ok": False,
                "error": "apply_input_invalid",
                "planId": plan.get("planId"),
                "message": str(exc),
            }
    try:
        designer = _get_designer(env)
        specification = plan.get("specification")
        if capability_id == "manage_platform_list":
            observed = collect_platform_list_observation(
                designer, _reg(), client, specification
            )
            return apply_platform_list_plan(
                plan, designer, _reg(), client, observed
            )
        if capability_id == "manage_drill_down_query":
            return apply_drill_down_query_plan(
                plan,
                designer,
                _reg(),
                client,
                target_environment,
                current_build,
                reference_evidence=effective_ddq_evidence,
                runtime_request=ddq_runtime_request,
            )
        if capability_id == "configure_work_item_presentation":
            if renderer_inventory is not None and not isinstance(
                renderer_inventory, list
            ):
                return {
                    "ok": False,
                    "error": "invalid_renderer_inventory",
                    "message": "renderer_inventory must be a JSON array",
                }
            observed = collect_work_item_presentation_observation(
                _reg(),
                client,
                specification,
                renderer_inventory=renderer_inventory,
            )
            return apply_work_item_presentation_plan(
                plan, _reg(), client, observed
            )
        if capability_id == "manage_business_unit_hierarchy":
            return apply_business_unit_hierarchy_plan(
                plan,
                designer,
                target_environment,
                current_build,
            )
        if capability_id == "create_work_item_type":
            identifier = (
                specification.get("identifier")
                if isinstance(specification, dict) else None
            )
            usage = _collect_alert_type_usage(
                client, identifier, alert_type_usage_data_source, alert_type_usage_ddq
            )
            observed = collect_work_item_observation(
                designer, specification, alert_type_usage=usage
            )
            return apply_work_item_plan(plan, designer, observed)
        observed = collect_remove_work_item_observation(
            designer, specification
        )
        return apply_remove_work_item_plan(plan, designer, observed)
    except (
        DesignerError,
        DrillDownQueryPlanError,
        HierarchyPlanError,
        InvokeError,
    ) as exc:
        return {
            "ok": False,
            "error": "inspection_failed",
            "capabilityId": capability_id,
            "environment": target_environment,
            "message": str(exc),
        }


@mcp.tool()
def designer_verify(plan: dict, env: Optional[str] = None,
                    ddq_runtime_request: Optional[dict] = None,
                    renderer_inventory: Optional[list[str]] = None) -> dict:
    """Read back and verify a Designer capability plan without writing.

    Use this after an interrupted apply or whenever an environment must be checked
    against a saved supported capability plan. Presentation formatter references
    require the same renderer inventory supplied during planning.
    """
    from actone.designer import DesignerError
    from actone.designer_capabilities import (
        PLANNABLE_CAPABILITY_IDS,
        fingerprint_capability_plan,
    )
    from actone.designer_ddq import (
        DrillDownQueryPlanError,
        verify_drill_down_query_plan,
    )
    from actone.designer_executor import (
        verify_remove_work_item_type,
        verify_work_item_type,
    )
    from actone.designer_hierarchy import (
        HierarchyPlanError,
        collect_business_unit_hierarchy_observation,
        verify_business_unit_hierarchy,
    )
    from actone.designer_presentation import (
        collect_work_item_presentation_observation,
        verify_work_item_presentation,
    )
    from actone.invoke import InvokeError
    from actone.platform_list_capability import verify_platform_list

    capability_id = plan.get("capability") if isinstance(plan, dict) else None
    if capability_id not in PLANNABLE_CAPABILITY_IDS:
        return {
            "ok": False,
            "error": "unsupported_capability",
            "capabilityId": capability_id,
        }
    expected_fingerprint = fingerprint_capability_plan(plan)
    if (
        expected_fingerprint != plan.get("fingerprint")
        or plan.get("planId") != expected_fingerprint[:16]
    ):
        return {
            "ok": False,
            "error": "plan_tampered",
            "planId": plan.get("planId"),
        }
    target_environment = env or "default"
    if plan.get("environment") != target_environment:
        return {
            "ok": False,
            "error": "target_environment_changed",
            "plannedEnvironment": plan.get("environment"),
            "actualEnvironment": target_environment,
        }
    client = _get_client(env)
    current_build = getattr(client, "version", None) or "unknown"
    if current_build != plan.get("targetBuild"):
        return {
            "ok": False,
            "error": "target_build_changed",
            "plannedBuild": plan.get("targetBuild"),
            "actualBuild": current_build,
        }
    try:
        designer = _get_designer(env)
        if capability_id == "manage_platform_list":
            result = verify_platform_list(plan, designer, _reg(), client)
        elif capability_id == "manage_drill_down_query":
            result = verify_drill_down_query_plan(
                plan,
                designer,
                _reg(),
                client,
                target_environment,
                current_build,
                runtime_request=ddq_runtime_request,
            )
        elif capability_id == "configure_work_item_presentation":
            if renderer_inventory is not None and not isinstance(
                renderer_inventory, list
            ):
                return {
                    "ok": False,
                    "error": "invalid_renderer_inventory",
                    "message": "renderer_inventory must be a JSON array",
                }
            observed = collect_work_item_presentation_observation(
                _reg(),
                client,
                plan.get("specification"),
                renderer_inventory=renderer_inventory,
            )
            result = verify_work_item_presentation(plan, observed)
        elif capability_id == "manage_business_unit_hierarchy":
            observed = collect_business_unit_hierarchy_observation(
                designer, plan.get("specification")
            )
            result = verify_business_unit_hierarchy(plan, observed)
        elif capability_id == "create_work_item_type":
            result = verify_work_item_type(plan, designer)
        else:
            result = verify_remove_work_item_type(plan, designer)
        result["planId"] = plan.get("planId")
        result["capability"] = capability_id
        result["environment"] = target_environment
        result["targetBuild"] = current_build
        return result
    except (
        DesignerError,
        DrillDownQueryPlanError,
        HierarchyPlanError,
        InvokeError,
    ) as exc:
        return {
            "ok": False,
            "error": "verification_failed",
            "planId": plan.get("planId"),
            "message": str(exc),
        }


@mcp.tool()
def designer_search_types(query: str = "", creatable_only: bool = False,
                          limit: int = 50) -> dict:
    """Discover ActOne **Designer object types** (the catalog of configurable
    artifacts: alert types, case types, queries incl. DrillDownQuery, workflows,
    policies, lists, views, ...).

    `creatable` means only that the SOAP catalog exposes a construction path.
    Check `supportState`, `maturity`, and `capabilityIds`: `catalog_candidate`
    explicitly means the type is not yet a supported procedural capability.

    CONVENTION — REST-first: the Designer/SOAP tools are for the **design-time
    config surface the Extend REST API does not cover**. If an equivalent runtime
    operation exists in REST (search_ops / describe_op / invoke_op), prefer REST;
    use these designer_* tools only when REST has no equivalent.

    Each result has `typeValue` (the wire name used everywhere else), `enumName`,
    `creatable`, capability IDs, and maturity. `creatable` only means a catalog
    create path and bean exist; it is not a certification claim. Prefer
    designer_search_capabilities for authoring intents.

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

    Check `supportState` before authoring. A `catalog_candidate` is discoverable
    from SOAP metadata but is not a supported or certified recipe.

    Use the returned `createBean.fields` (name/type, plus `declaredIn`) to assemble
    the `fields` argument for designer_create_object. `identifier`/`name`/
    `description` populate the object's identity (objectInfo). Scalar fields map to
    JSON scalars; nested-bean fields take a JSON object/array.

    GROUNDING — the response includes a `grounding.sequence` block. The catalog gives
    field *shape*, but not the product *procedure*: read and follow the returned
    ordered steps, prerequisites, and gotchas before authoring. Then follow
    `grounding.suggestedQueries` into the ActWise docs MCP (docenter search_docs /
    get_page) when deeper product detail is needed, and create referenced objects
    first. For custom fields this distinction is critical: REST addCustomFields only
    requests automatic allocation, while the Designer flow discovers a physical
    Source and explicitly maps it through AlertCustomizedField.fieldId.

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

    GROUNDING — call designer_describe_type first and execute its
    `grounding.sequence.steps` in order. Consult the ActWise docs MCP (docenter) for
    deeper details, supply server-mandatory fields, and create referenced objects
    first. For AlertCustomizedField, `fieldId` is the explicit physical Source
    mapping; do not substitute REST type/size allocation for that mapping.

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
                      env: Optional[str] = None,
                      specification: Optional[dict] = None,
                      alert_type_usage_data_source: Optional[str] = None,
                      alert_type_usage_ddq: Optional[str] = None) -> dict:
    """Deprecated compatibility adapter for `create_work_item_type` (WRITE, gated).

    This tool no longer creates an AlertType directly. Supply a complete
    `create_work_item_type` specification containing explicit `customFields`,
    `workflow` (identifier, statuses, transitions), and `view` (identifier, fields).
    The adapter invokes `designer_plan` and then `designer_apply`, so build
    certification, environment binding, write gating, plan integrity, stale-state
    detection, Source allocation, and post-write verification are identical to the
    certified capability. Legacy AlertType-only inputs fail with `migration_required`
    rather than inventing workflow/status/view defaults.

    For clients pinned to the old schema, the same specification may be passed as
    `extra_fields.workItemTypeSpecification`. All other `extra_fields` are refused.

    Args:
        identifier: Must match the work-item specification identifier.
        name: Optional compatibility value; must match or populate specification name.
        description: Optional compatibility value; must match or populate description.
        alert_status_workflow_definition_identifier: Optional compatibility check
            against specification.workflow.identifier.
        using_alert_status_workflow: Deprecated compatibility input. The certified
            recipe always requires an explicit workflow.
        assigned_status_identifiers: Optional compatibility check against the explicit
            workflow status identifiers.
        method_id: Only the certified default (4) is accepted.
        support_manual_alerts: Unsupported when true; migrate to a future recipe.
        enabled_for_global_search: Unsupported when true; migrate to a future recipe.
        extra_fields: Old-schema carrier for `workItemTypeSpecification` only.
        env: Named ActOne environment (see list_environments).
        specification: Complete `create_work_item_type` specification.
        alert_type_usage_data_source: Optional DART source for the same fail-closed
            runtime-use preflight used by designer_plan/designer_apply.
        alert_type_usage_ddq: Preferred parameterized DDQ for that preflight.
    """
    from actone.designer_compat import (
        LegacyAlertTypeMigrationError,
        adapt_legacy_alert_type_specification,
        legacy_alert_type_migration_result,
        mark_legacy_alert_type_result,
    )

    try:
        desired = adapt_legacy_alert_type_specification(
            identifier,
            name=name,
            description=description,
            alert_status_workflow_definition_identifier=(
                alert_status_workflow_definition_identifier
            ),
            assigned_status_identifiers=assigned_status_identifiers,
            method_id=method_id,
            support_manual_alerts=support_manual_alerts,
            enabled_for_global_search=enabled_for_global_search,
            extra_fields=extra_fields,
            specification=specification,
        )
    except LegacyAlertTypeMigrationError as exc:
        return legacy_alert_type_migration_result(str(exc))

    gate = _designer_write_guard(env, "create_alert_type -> create_work_item_type")
    if gate:
        return mark_legacy_alert_type_result(gate)

    plan = designer_plan(
        "create_work_item_type",
        desired,
        env=env,
        alert_type_usage_data_source=alert_type_usage_data_source,
        alert_type_usage_ddq=alert_type_usage_ddq,
    )
    if plan.get("error"):
        return mark_legacy_alert_type_result(plan)
    if not plan.get("applicable"):
        return mark_legacy_alert_type_result({
            "ok": False,
            "error": "plan_not_applicable",
            "planId": plan.get("planId"),
            "plan": plan,
        })
    return mark_legacy_alert_type_result(designer_apply(
        plan,
        env=env,
        alert_type_usage_data_source=alert_type_usage_data_source,
        alert_type_usage_ddq=alert_type_usage_ddq,
    ))


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
