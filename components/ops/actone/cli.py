"""ActOne API → Postman automation suite — console entry point.

Thin wrapper that dispatches to the package's pipeline modules. Each module is a
self-contained CLI (own argparse), so we invoke it via `python -m actone.<module>`
and forward all flags untouched. Run `actone <command> --help` to see a command's
own options. Artifacts (specs/, generated/, reports/, .env) are read/written under
the current directory, or ACTONE_WORKDIR when set.
"""
import json
import subprocess
import sys
from pathlib import Path

import typer

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="ActOne API -> Postman automation suite (spec download, collection generation, review).",
)

ops_app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Spec-driven runtime ops over the ActOne Extend REST API (discovery: search/describe/call), plus SOAP admin + Designer config. Reads open; writes gated (opt-in).",
)
app.add_typer(ops_app, name="ops")

# Disable click's own --help so it passes through to the underlying module's argparse.
PASSTHROUGH = {"allow_extra_args": True, "ignore_unknown_options": True, "help_option_names": []}


def _run(module: str, args) -> None:
    rc = subprocess.call([sys.executable, "-m", f"actone.{module}", *args])
    raise typer.Exit(rc)


@app.command(name="fetch-spec", context_settings=PASSTHROUGH,
             help="Download the live OpenAPI spec from an ActOne URL (auto-converts Swagger 2.0 -> OAS3).")
def fetch_spec(ctx: typer.Context):
    _run("fetch_spec", ctx.args)


@app.command(name="generate", context_settings=PASSTHROUGH,
             help="Generate a logically-organized Postman collection from an OpenAPI spec.")
def generate(ctx: typer.Context):
    _run("generate_collection", ctx.args)


@app.command(name="provision", context_settings=PASSTHROUGH,
             help="One-shot: fetch spec -> generate collection -> optionally push to a Postman workspace.")
def provision(ctx: typer.Context):
    _run("provision_from_url", ctx.args)


@app.command(name="sanitize", context_settings=PASSTHROUGH,
             help="Flatten self-referential enums and break $ref cycles to produce a portman-safe spec.")
def sanitize(ctx: typer.Context):
    _run("sanitize_spec", ctx.args)


@app.command(name="review", context_settings=PASSTHROUGH,
             help="Read-only review of key ActOne configuration via its REST API.")
def review(ctx: typer.Context):
    _run("review_config", ctx.args)


# --------------------------------------------------------------------------- #
# ops: spec-driven discovery runtime (search / describe / call)
# --------------------------------------------------------------------------- #
def _echo(obj):
    typer.echo(json.dumps(obj, indent=2, default=str))


def _optional_json(value: str | None, label: str):
    if value is None:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError("invalid %s JSON: %s" % (label, exc)) from exc


@ops_app.command("search", help="Find operations by keyword over operationId/summary/tags/path.")
def ops_search(
    query: str = typer.Argument("", help="Search terms (empty lists everything)."),
    limit: int = typer.Option(25, "--limit", "-n"),
    reads_only: bool = typer.Option(False, "--reads-only", help="Only show read (GET) operations."),
    spec: str = typer.Option(None, "--spec", help="Spec path override (else cached/bundled)."),
):
    from actone.registry import load_registry
    reg = load_registry(spec)
    _echo({"source": reg.source, "specVersion": reg.info_version,
           "count": len(reg.ops), "results": reg.search(query, limit, reads_only)})


@ops_app.command("describe", help="Show full detail (params, body example, access) for one operationId.")
def ops_describe(
    op_id: str = typer.Argument(..., help="operationId (from `ops search`)."),
    spec: str = typer.Option(None, "--spec"),
):
    from actone.registry import load_registry
    reg = load_registry(spec)
    info = reg.describe(op_id)
    if not info:
        suggest = [o["operationId"] for o in reg.search(op_id, limit=5)]
        typer.echo("unknown operationId %r. Closest: %s" % (op_id, ", ".join(suggest) or "none"))
        raise typer.Exit(1)
    _echo(info)


@ops_app.command("tags", help="List operation tags (domains) and counts.")
def ops_tags(spec: str = typer.Option(None, "--spec")):
    from actone.registry import load_registry
    _echo(load_registry(spec).tags())


@ops_app.command("list", help="List ALL operations (no cap), optionally by tag or grouped.")
def ops_list(
    reads_only: bool = typer.Option(False, "--reads-only", help="Only read (GET) operations."),
    tag: str = typer.Option(None, "--tag", help="Filter to one domain/tag."),
    group: bool = typer.Option(False, "--group", help="Group results by tag."),
    spec: str = typer.Option(None, "--spec"),
):
    from actone.registry import load_registry
    reg = load_registry(spec)
    if group:
        groups = reg.grouped(reads_only=reads_only)
        _echo({"source": reg.source, "specVersion": reg.info_version,
               "count": len(reg.ops), "groups": groups})
    else:
        results = reg.list_ops(reads_only=reads_only, tag=tag)
        _echo({"source": reg.source, "specVersion": reg.info_version,
               "count": len(reg.ops), "returned": len(results), "operations": results})


@ops_app.command("call", help="Invoke an operation live. Reads always run; writes need --allow-write (or ACTONE_ALLOW_WRITES).")
def ops_call(
    op_id: str = typer.Argument(..., help="operationId to invoke."),
    p: list[str] = typer.Option(None, "--p", help="Param as key=value (repeatable)."),
    params: str = typer.Option(None, "--params", help="All params as one JSON object."),
    body: str = typer.Option(None, "--body", help="Request body as JSON."),
    spec: str = typer.Option(None, "--spec"),
    env: str = typer.Option(None, "--env", help="Named ActOne environment (see `actone ops env`)."),
    url: str = typer.Option(None, "--url", help="ActOne base URL (else .env)."),
    user: str = typer.Option(None, "--user"),
    password: str = typer.Option(None, "--password"),
    allow_write: bool = typer.Option(
        False, "--allow-write",
        help="Permit write ops (POST/PUT/DELETE/PATCH). Also honored via "
             "ACTONE_ALLOW_WRITES=true. Off by default (read-only gate)."),
):
    from actone.registry import load_registry
    from actone.invoke import precheck, make_client, invoke, InvokeError, writes_enabled
    aw = allow_write or writes_enabled(env)
    merged = {}
    if params:
        merged.update(json.loads(params))
    for kv in (p or []):
        if "=" not in kv:
            typer.echo("bad --p %r (expected key=value)" % kv)
            raise typer.Exit(2)
        k, v = kv.split("=", 1)
        merged[k] = v
    if body:
        merged["body"] = json.loads(body)
    try:
        reg = load_registry(spec)
        precheck(reg, op_id, allow_write=aw)  # gate fires offline, before any login
        client = make_client(url, user, password, env=env)
        client.login()
        _echo(invoke(reg, client, op_id, merged, allow_write=aw))
    except InvokeError as e:
        typer.echo("error: %s" % e)
        raise typer.Exit(1)


@ops_app.command("env", help="List configured ActOne environments (never shows passwords).")
def ops_env():
    from actone.ops_config import list_environments
    _echo({"environments": list_environments()})


@ops_app.command("version", help="Login and report the detected ActOne version.")
def ops_version(
    env: str = typer.Option(None, "--env", help="Named ActOne environment (see `actone ops env`)."),
    url: str = typer.Option(None, "--url"),
    user: str = typer.Option(None, "--user"),
    password: str = typer.Option(None, "--password"),
):
    from actone.invoke import make_client, InvokeError
    try:
        client = make_client(url, user, password, env=env)
        client.login()
        _echo({"version": client.detect_version(), "base": client.base})
    except InvokeError as e:
        typer.echo("error: %s" % e)
        raise typer.Exit(1)


@ops_app.command("smoke",
                 help="Smoke-test the MCP surface: invoke every reachable read op "
                      "(REST + SOAP + catalog) and report pass/fail/skip. Use --write "
                      "to also exercise the Designer create->exercise->remove lifecycle.")
def ops_smoke(
    env: str = typer.Option(None, "--env", help="Named ActOne environment (see `actone ops env`)."),
    rest: bool = typer.Option(True, "--rest/--no-rest", help="Include REST read ops."),
    soap: bool = typer.Option(True, "--soap/--no-soap", help="Include curated SOAP read ops."),
    catalog: bool = typer.Option(True, "--catalog/--no-catalog", help="Include full SOAP catalog read ops."),
    write: bool = typer.Option(False, "--write", help="Also run the Designer write lifecycle (auto-cleanup)."),
    workflow: str = typer.Option(
        "workflow1", "--workflow",
        help="Deprecated smoke compatibility option; the recipe creates its own workflow.",
    ),
    fixtures: str = typer.Option(None, "--fixtures", help="JSON map of param name -> value for reads that need an id."),
    autofixtures: bool = typer.Option(True, "--autofixtures/--no-autofixtures",
                                      help="Discover ids from safe reads to run id-dependent reads."),
    gating: bool = typer.Option(False, "--gating", help="Assert every write op is refused (needs --ro-env)."),
    ro_env: str = typer.Option(None, "--ro-env", help="Read-only env profile (allow_writes: false) for the gating sweep."),
    limit: int = typer.Option(None, "--limit", help="Cap invocations per surface (quick smoke)."),
    full: bool = typer.Option(False, "--full", help="Print every result, not just failures."),
):
    from actone.smoke import run_smoke
    fx = json.loads(fixtures) if fixtures else None
    report = run_smoke(env=env, rest=rest, soap=soap, catalog=catalog,
                       fixtures=fx, write=write, workflow=workflow, limit=limit,
                       autofixtures=autofixtures, gating=gating, ro_env=ro_env)
    if full:
        _echo(report)
    else:
        _echo({"env": report["env"], "fixtures": report.get("fixtures", []),
               "totals": report["totals"],
               "by_surface": {k: {kk: v[kk] for kk in ("pass", "fail", "error", "skip")}
                              for k, v in report["surfaces"].items()},
               "failures": report["failures"]})
    if report["totals"]["fail"] or report["totals"]["error"]:
        raise typer.Exit(1)


# --------------------------------------------------------------------------- #
# ops soap: curated legacy Axis SOAP ops (admin surface the REST API lacks)
# --------------------------------------------------------------------------- #
soap_app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Curated ActOne SOAP ops (admin surface the REST API lacks, e.g. create a "
         "Business Unit). Reads always run; writes need --allow-write.",
)
ops_app.add_typer(soap_app, name="soap")


@soap_app.command("list", help="List the curated SOAP operations (offline).")
def ops_soap_list():
    from actone.soap import list_operations
    _echo({"count": len(list_operations()), "operations": list_operations()})


@soap_app.command("describe", help="Show one SOAP op's service/operation/access/params.")
def ops_soap_describe(op_id: str = typer.Argument(..., help="SOAP opId (from `ops soap list`).")):
    from actone.soap import describe_operation
    info = describe_operation(op_id)
    if not info:
        typer.echo("unknown SOAP op %r (see `actone ops soap list`)" % op_id)
        raise typer.Exit(1)
    _echo(info)


@soap_app.command("call", help="Invoke a curated SOAP op. Reads always run; writes need --allow-write.")
def ops_soap_call(
    op_id: str = typer.Argument(..., help="SOAP opId (from `ops soap list`)."),
    p: list[str] = typer.Option(None, "--p", help="Arg as key=value (repeatable)."),
    params: str = typer.Option(None, "--params", help="All args as one JSON object."),
    env: str = typer.Option(None, "--env", help="Named ActOne environment (see `actone ops env`)."),
    url: str = typer.Option(None, "--url", help="ActOne base URL (else .env)."),
    user: str = typer.Option(None, "--user"),
    password: str = typer.Option(None, "--password"),
    allow_write: bool = typer.Option(
        False, "--allow-write",
        help="Permit write SOAP ops (create/remove). Also honored via "
             "ACTONE_ALLOW_WRITES=true. Off by default (read-only gate)."),
):
    from actone.invoke import make_client, InvokeError, writes_enabled
    from actone.soap import SOAP_OPS, SoapClient, SoapError
    aw = allow_write or writes_enabled(env)
    spec = SOAP_OPS.get(op_id)
    if not spec:
        typer.echo("unknown SOAP op %r (see `actone ops soap list`)" % op_id)
        raise typer.Exit(1)
    if spec["access"] == "write" and not aw:
        typer.echo(
            "error: SOAP op %r is a WRITE (%s.%s) and is gated (read-only). "
            "Re-run with --allow-write (or set ACTONE_ALLOW_WRITES=true)."
            % (op_id, spec["service"], spec["operation"]))
        raise typer.Exit(1)
    args = {}
    if params:
        args.update(json.loads(params))
    for kv in (p or []):
        if "=" not in kv:
            typer.echo("bad --p %r (expected key=value)" % kv)
            raise typer.Exit(2)
        k, v = kv.split("=", 1)
        args[k] = v
    try:
        client = make_client(url, user, password, env=env)
        client.login()
        _echo(SoapClient(client).call(op_id, args))
    except (InvokeError, SoapError) as e:
        typer.echo("error: %s" % e)
        raise typer.Exit(1)


# --------------------------------------------------------------------------- #
# ops designer: catalog-driven generic SOAP (ActOne Designer config surface)
# --------------------------------------------------------------------------- #
designer_app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="ActOne Designer capability discovery plus catalog-driven expert ops. "
         "Reads always run; writes need --allow-write.",
)
ops_app.add_typer(designer_app, name="designer")


@designer_app.command("capabilities",
                      help="Find Designer authoring capabilities and maturity (offline).")
def designer_capabilities(
    query: str = typer.Argument("", help="Intent terms (empty lists all)."),
    maturity: str = typer.Option(
        None, "--maturity",
        help="Filter: certified, verified_read_only, experimental, or catalog_only.",
    ),
    limit: int = typer.Option(25, "--limit", "-n"),
):
    from actone.designer_capabilities import load_capabilities

    registry = load_capabilities()
    try:
        capabilities = registry.search(query, maturity=maturity, limit=limit)
    except ValueError as exc:
        typer.echo("error: %s" % exc)
        raise typer.Exit(1)
    _echo({
        "source": registry.source,
        "registryVersion": registry.version,
        "count": len(capabilities),
        "capabilities": capabilities,
    })


@designer_app.command("search-types",
                      help="Find catalog object types and their explicit support state (offline).")
def designer_search_types(
    query: str = typer.Argument("", help="Search terms (empty lists all)."),
    creatable: bool = typer.Option(
        False,
        "--creatable",
        help="Only catalog-creatable types; this does not imply supported authoring.",
    ),
    limit: int = typer.Option(50, "--limit", "-n"),
):
    from actone.soap_catalog import load_catalog
    cat = load_catalog()
    _echo({"source": cat.source,
           "types": cat.search_object_types(query, creatable_only=creatable, limit=limit)})


@designer_app.command("describe-type",
                      help="Show a type's create path + payload-bean field schema (offline).")
def designer_describe_type(type_value: str = typer.Argument(..., help="typeValue, e.g. DrillDownQuery.")):
    from actone.soap_catalog import load_catalog
    info = load_catalog().describe_type(type_value)
    if not info:
        typer.echo("unknown type %r (see `actone ops designer search-types`)" % type_value)
        raise typer.Exit(1)
    _echo(info)


@designer_app.command("search-ops",
                      help="Find raw SOAP operations across the 22 Axis services (offline).")
def designer_search_ops(
    query: str = typer.Argument("", help="Search terms."),
    limit: int = typer.Option(25, "--limit", "-n"),
):
    from actone.soap_catalog import load_catalog
    cat = load_catalog()
    _echo({"source": cat.source, "operations": cat.search_services(query, limit)})


@designer_app.command("flows",
                      help="Report documented-flow coverage over creatable Designer "
                           "types (data/designer-flows.yaml).")
def designer_flows(
    check: bool = typer.Option(False, "--check",
                               help="Exit non-zero if a flow key is not a creatable "
                                    "typeValue (typo/stale). For CI."),
):
    from actone.soap_catalog import load_catalog
    cat = load_catalog()
    cov = cat.flow_coverage()
    _echo({"source": cat.source, "coverage": cov})
    if check and cov["unknown_flow_keys"]:
        typer.echo("designer-flows.yaml has keys that are not creatable typeValues: %s"
                   % ", ".join(cov["unknown_flow_keys"]))
        raise typer.Exit(1)


def _designer_client(url, user, password, env):
    from actone.invoke import make_client
    from actone.designer import DesignerClient
    client = make_client(url, user, password, env=env)
    client.login()
    return DesignerClient(client)


_DESIGNER_CONN = dict(
    env=typer.Option(None, "--env", help="Named ActOne environment (see `actone ops env`)."),
    url=typer.Option(None, "--url", help="ActOne base URL (else .env)."),
    user=typer.Option(None, "--user"),
    password=typer.Option(None, "--password"),
)

_DESIGNER_STATE_CAPABILITY = "create_work_item_type"


def _designer_state_document(exported: dict, label: str) -> tuple[dict, str]:
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


def _collect_designer_state(specification: dict, env=None, url=None, user=None,
                            password=None) -> dict:
    from actone.designer import DesignerClient
    from actone.designer_capabilities import load_capabilities
    from actone.designer_planner import collect_work_item_observation
    from actone.designer_state import export_capability_state
    from actone.invoke import make_client

    environment = env or "default"
    client = make_client(url, user, password, env=env)
    client.login()
    target_build = client.detect_version()
    build_info = load_capabilities().inspect(
        _DESIGNER_STATE_CAPABILITY, target_build
    )
    if not build_info or build_info["buildStatus"] != "verified":
        verified = build_info.get("verifiedBuilds", []) if build_info else []
        raise ValueError(
            "unsupported build %r for %s; verified builds: %s"
            % (
                target_build,
                _DESIGNER_STATE_CAPABILITY,
                ", ".join(verified) or "none",
            )
        )
    observed = collect_work_item_observation(
        DesignerClient(client), specification
    )
    exported = export_capability_state(
        _DESIGNER_STATE_CAPABILITY, specification, observed
    )
    return {
        "sourceEnvironment": environment,
        "sourceBuild": target_build,
        **exported,
    }


_ALERT_TYPE_USAGE_OPTION = typer.Option(
    None, "--alert-type-usage-data-source",
    help=(
        "DART data source identifier used to REST-preflight whether runtime "
        "alerts already exist for the work-item type (getDartResultsGet, "
        "filtered by alertTypeIdentifier). When set and alerts are found, any "
        "proposed AlertType update becomes an explicit conflict instead of a "
        "step. Existing AlertType updates are also blocked when this option is "
        "omitted or the query cannot establish zero runtime references."
    ),
)

_ALERT_TYPE_USAGE_DDQ_OPTION = typer.Option(
    None, "--alert-type-usage-ddq",
    help=(
        "Preferred parameterized DDQ used to establish AlertType runtime usage. "
        "Its sole parameter must be the alertTypeIdentifier and it must return "
        "alert_id rows."
    ),
)


def _dart_rows(body):
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


def _collect_alert_type_usage(client, identifier, data_source_identifier,
                              ddq_identifier=None):
    """REST-first runtime-use preflight for the `create_work_item_type`
    conservative-update slice: execute the bundled Extend REST operation
    `getDartResultsGet` (`GET /RCM/api/v1/dart/{dataSourceIdentifier}`, filtered
    with `filter=alertTypeIdentifier=<identifier>`) against a pre-provisioned
    DART data source, and normalize the rows into the alertTypeInUse /
    alertTypeUseCount / alertTypeUseEvidence fact consumed by plan_work_item_type.

    Returns {} (unknown) when no data source is configured, no work-item
    identifier is known yet, or the REST call fails. Unknown usage blocks only
    an existing AlertType mutation; create and exact reuse remain available."""
    if not identifier or not (data_source_identifier or ddq_identifier):
        return {}
    from actone.designer_planner import alert_type_usage_from_dart_rows
    from actone.invoke import InvokeError, invoke
    from actone.registry import load_registry
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
        result = invoke(load_registry(), client, operation_id, params=params)
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


def _build_create_work_item_type_plan(client, designer, specification,
                                      environment, usage_data_source,
                                      usage_ddq=None,
                                      target_build=None):
    from actone.designer_capabilities import load_capabilities
    from actone.designer_planner import (
        collect_work_item_observation,
        plan_work_item_type,
    )

    target_build = target_build or client.detect_version()
    usage = _collect_alert_type_usage(
        client,
        specification.get("identifier")
        if isinstance(specification, dict) else None,
        usage_data_source,
        usage_ddq,
    )
    observed = collect_work_item_observation(
        designer, specification, alert_type_usage=usage
    )
    plan = plan_work_item_type(
        specification,
        observed,
        environment=environment,
        target_build=target_build,
    )
    registry = load_capabilities()
    capability = registry.describe("create_work_item_type")
    build_info = registry.inspect("create_work_item_type", target_build)
    plan["capabilityMaturity"] = capability["maturity"]
    plan["buildStatus"] = build_info["buildStatus"]
    plan["contractStatus"] = build_info["contractStatus"]
    plan["liveCertificationStatus"] = build_info["liveCertificationStatus"]
    return plan


def _apply_create_work_item_type_plan(client, designer, plan, environment,
                                      usage_data_source, usage_ddq=None,
                                      current_build=None):
    from actone.designer_capabilities import load_capabilities
    from actone.designer_executor import apply_work_item_plan
    from actone.designer_planner import collect_work_item_observation

    if plan.get("environment") != environment:
        return {
            "ok": False,
            "error": "target_environment_changed",
            "plannedEnvironment": plan.get("environment"),
            "actualEnvironment": environment,
        }
    current_build = current_build or client.detect_version()
    if current_build != plan.get("targetBuild"):
        return {
            "ok": False,
            "error": "target_build_changed",
            "plannedBuild": plan.get("targetBuild"),
            "actualBuild": current_build,
        }
    build_info = load_capabilities().inspect(
        "create_work_item_type", current_build
    )
    if not build_info or build_info["liveCertificationStatus"] != "certified":
        return {
            "ok": False,
            "error": "unsupported_build",
            "capabilityId": "create_work_item_type",
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
        }
    specification = plan.get("specification")
    usage = _collect_alert_type_usage(
        client,
        specification.get("identifier")
        if isinstance(specification, dict) else None,
        usage_data_source,
        usage_ddq,
    )
    observed = collect_work_item_observation(
        designer, specification, alert_type_usage=usage
    )
    return apply_work_item_plan(plan, designer, observed)


@designer_app.command(
    "export-state",
    help="Export normalized create_work_item_type state from a verified environment (READ).",
)
def designer_export_state(
    specification: str = typer.Option(
        ..., "--specification", "--spec-json",
        help="Work-item specification identifying the exact owned objects.",
    ),
    env: str = _DESIGNER_CONN["env"], url: str = _DESIGNER_CONN["url"],
    user: str = _DESIGNER_CONN["user"], password: str = _DESIGNER_CONN["password"],
):
    from actone.designer import DesignerError
    from actone.invoke import InvokeError

    try:
        desired = json.loads(specification)
        _echo(_collect_designer_state(desired, env, url, user, password))
    except json.JSONDecodeError as exc:
        typer.echo("error: invalid --specification JSON: %s" % exc)
        raise typer.Exit(1)
    except (InvokeError, DesignerError, ValueError) as exc:
        typer.echo("error: %s" % exc)
        raise typer.Exit(1)


@designer_app.command(
    "compare-state",
    help="Compare verified environment state with a desired specification (READ).",
)
def designer_compare_state(
    specification: str = typer.Option(
        ..., "--specification", "--spec-json",
        help="Complete desired create_work_item_type specification.",
    ),
    env: str = _DESIGNER_CONN["env"], url: str = _DESIGNER_CONN["url"],
    user: str = _DESIGNER_CONN["user"], password: str = _DESIGNER_CONN["password"],
):
    from actone.designer import DesignerError
    from actone.designer_state import diff_documents
    from actone.invoke import InvokeError

    try:
        desired_specification = json.loads(specification)
        desired, desired_fingerprint = _desired_designer_state(
            desired_specification
        )
        exported = _collect_designer_state(
            desired_specification, env, url, user, password
        )
        actual, actual_fingerprint = _designer_state_document(
            exported, "environment export"
        )
        _echo({
            "sourceEnvironment": exported["sourceEnvironment"],
            "sourceBuild": exported["sourceBuild"],
            "sourceFingerprint": actual_fingerprint,
            "desiredFingerprint": desired_fingerprint,
            "diff": diff_documents(actual, desired),
        })
    except json.JSONDecodeError as exc:
        typer.echo("error: invalid --specification JSON: %s" % exc)
        raise typer.Exit(1)
    except (InvokeError, DesignerError, ValueError) as exc:
        typer.echo("error: %s" % exc)
        raise typer.Exit(1)


@designer_app.command(
    "diff-exports",
    help="Diff two exported state JSON documents without logging in.",
)
def designer_diff_exports(
    source_export: str = typer.Option(
        ..., "--source-export",
        help="JSON output from designer export-state.",
    ),
    target_export: str = typer.Option(
        ..., "--target-export",
        help="JSON output from designer export-state.",
    ),
):
    from actone.designer_state import diff_documents

    try:
        source, source_fingerprint = _designer_state_document(
            json.loads(source_export), "source export"
        )
        target, target_fingerprint = _designer_state_document(
            json.loads(target_export), "target export"
        )
        _echo({
            "sourceFingerprint": source_fingerprint,
            "targetFingerprint": target_fingerprint,
            "diff": diff_documents(source, target),
        })
    except json.JSONDecodeError as exc:
        typer.echo("error: invalid export JSON: %s" % exc)
        raise typer.Exit(1)
    except ValueError as exc:
        typer.echo("error: %s" % exc)
        raise typer.Exit(1)


@designer_app.command(
    "compare-environments",
    help="Compare independently collected exports from two verified environments (READ).",
)
def designer_compare_environments(
    specification: str = typer.Option(
        ..., "--specification", "--spec-json",
        help="Work-item specification identifying the exact owned objects.",
    ),
    source_env: str = typer.Option(
        ..., "--source-env", help="Named source ActOne environment."
    ),
    target_env: str = typer.Option(
        ..., "--target-env", help="Named target ActOne environment."
    ),
):
    from actone.designer import DesignerError
    from actone.designer_state import diff_documents
    from actone.invoke import InvokeError

    try:
        selector = json.loads(specification)
        source_export = _collect_designer_state(selector, env=source_env)
        target_export = _collect_designer_state(selector, env=target_env)
        source, source_fingerprint = _designer_state_document(
            source_export, "source environment export"
        )
        target, target_fingerprint = _designer_state_document(
            target_export, "target environment export"
        )
        _echo({
            "sourceEnvironment": source_export["sourceEnvironment"],
            "sourceBuild": source_export["sourceBuild"],
            "sourceFingerprint": source_fingerprint,
            "targetEnvironment": target_export["sourceEnvironment"],
            "targetBuild": target_export["sourceBuild"],
            "targetFingerprint": target_fingerprint,
            "diff": diff_documents(source, target),
        })
    except json.JSONDecodeError as exc:
        typer.echo("error: invalid --specification JSON: %s" % exc)
        raise typer.Exit(1)
    except (InvokeError, DesignerError, ValueError) as exc:
        typer.echo("error: %s" % exc)
        raise typer.Exit(1)


@designer_app.command("inspect",
                      help="Inspect capability maturity against a live ActOne build (READ).")
def designer_inspect(
    capability_id: str = typer.Argument(
        ..., help="Capability ID (see `designer capabilities`)."
    ),
    env: str = _DESIGNER_CONN["env"], url: str = _DESIGNER_CONN["url"],
    user: str = _DESIGNER_CONN["user"], password: str = _DESIGNER_CONN["password"],
):
    from actone.designer_capabilities import load_capabilities
    from actone.invoke import InvokeError, make_client

    registry = load_capabilities()
    if not registry.describe(capability_id):
        typer.echo("unknown capability %r (see `actone ops designer capabilities`)"
                   % capability_id)
        raise typer.Exit(1)
    try:
        client = make_client(url, user, password, env=env)
        client.login()
        target_build = client.detect_version()
        result = registry.inspect(capability_id, target_build)
        result["environment"] = env or "default"
        _echo(result)
    except InvokeError as exc:
        typer.echo("error: %s" % exc)
        raise typer.Exit(1)


@designer_app.command("plan",
                      help="Build a read-only capability plan from JSON against an environment.")
def designer_plan(
    capability_id: str = typer.Argument(
        ...,
        help=(
            "Capability ID (see `designer capabilities`)."
        ),
    ),
    specification: str = typer.Option(
        ..., "--specification", "--spec-json",
        help="Domain-level desired configuration as a JSON object.",
    ),
    env: str = _DESIGNER_CONN["env"], url: str = _DESIGNER_CONN["url"],
    user: str = _DESIGNER_CONN["user"], password: str = _DESIGNER_CONN["password"],
    alert_type_usage_data_source: str = _ALERT_TYPE_USAGE_OPTION,
    alert_type_usage_ddq: str = _ALERT_TYPE_USAGE_DDQ_OPTION,
    ddq_reference_evidence: str = typer.Option(
        None,
        "--ddq-reference-evidence",
        help="Trusted DDQ connection/reference evidence as a JSON object.",
    ),
    internal_connection_evidence: bool = typer.Option(
        False,
        "--internal-connection-evidence",
        help="Explicitly evidence documented DDQ connectionId=-1.",
    ),
    internal_connection_evidence_source: str = typer.Option(
        None,
        "--internal-connection-evidence-source",
        help="Internal evidence source: documented or live-evidenced.",
    ),
    renderer_inventory: str = typer.Option(
        None,
        "--renderer-inventory",
        help="Presentation formatter identifiers as a JSON array.",
    ),
):
    from actone.designer import DesignerClient, DesignerError
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
        plan_remove_work_item_type,
    )
    from actone.designer_presentation import (
        collect_work_item_presentation_observation,
        plan_work_item_presentation,
    )
    from actone.invoke import InvokeError, make_client
    from actone.platform_list_capability import (
        collect_platform_list_observation,
        plan_platform_list,
    )

    registry = load_capabilities()
    capability = registry.describe(capability_id)
    if not capability:
        typer.echo("unknown capability %r (see `actone ops designer capabilities`)"
                   % capability_id)
        raise typer.Exit(1)
    if capability_id not in PLANNABLE_CAPABILITY_IDS:
        typer.echo("planning is not implemented for capability %r" % capability_id)
        raise typer.Exit(1)
    try:
        desired = json.loads(specification)
        parsed_evidence = _optional_json(
            ddq_reference_evidence, "--ddq-reference-evidence"
        )
        parsed_renderers = _optional_json(
            renderer_inventory, "--renderer-inventory"
        )
        if parsed_renderers is not None and not isinstance(parsed_renderers, list):
            raise ValueError("--renderer-inventory must be a JSON array")
        if capability_id == "manage_drill_down_query":
            parsed_evidence = build_ddq_reference_evidence(
                desired,
                parsed_evidence,
                internal_connection_evidence=internal_connection_evidence,
                internal_connection_evidence_source=(
                    internal_connection_evidence_source
                ),
            )
        client = make_client(url, user, password, env=env)
        client.login()
        target_build = client.detect_version()
        designer = DesignerClient(client)
        if capability_id == "manage_platform_list":
            from actone.registry import load_registry

            observed = collect_platform_list_observation(
                designer, load_registry(), client, desired
            )
            plan = plan_platform_list(
                desired,
                observed,
                environment=env or "default",
                target_build=target_build,
            )
        elif capability_id == "manage_drill_down_query":
            from actone.registry import load_registry

            observed = collect_drill_down_query_observation(
                designer,
                load_registry(),
                client,
                desired,
                reference_evidence=parsed_evidence,
            )
            plan = manage_drill_down_query(
                desired,
                observed,
                environment=env or "default",
                target_build=target_build,
            )
        elif capability_id == "configure_work_item_presentation":
            from actone.registry import load_registry

            observed = collect_work_item_presentation_observation(
                load_registry(),
                client,
                desired,
                renderer_inventory=parsed_renderers,
            )
            plan = plan_work_item_presentation(
                desired,
                observed,
                environment=env or "default",
                target_build=target_build,
            )
        elif capability_id == "manage_business_unit_hierarchy":
            observed = collect_business_unit_hierarchy_observation(
                designer, desired
            )
            plan = plan_business_unit_hierarchy(
                desired,
                observed,
                environment=env or "default",
                target_build=target_build,
            )
        elif capability_id == "create_work_item_type":
            plan = _build_create_work_item_type_plan(
                client,
                designer,
                desired,
                env or "default",
                alert_type_usage_data_source,
                alert_type_usage_ddq,
                target_build=target_build,
            )
        else:
            observed = collect_remove_work_item_observation(designer, desired)
            plan = plan_remove_work_item_type(
                desired,
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
        _echo(plan)
    except json.JSONDecodeError as exc:
        typer.echo("error: invalid --specification JSON: %s" % exc)
        raise typer.Exit(1)
    except (
        InvokeError,
        DesignerError,
        DesignerPlanError,
        DrillDownQueryPlanError,
        HierarchyPlanError,
        ValueError,
    ) as exc:
        typer.echo("error: %s" % exc)
        raise typer.Exit(1)


@designer_app.command("apply",
                      help="Apply and verify a saved Designer plan (WRITE, gated).")
def designer_apply(
    plan_file: Path = typer.Argument(
        ..., exists=True, dir_okay=False, readable=True,
        help="JSON file containing the complete output of `designer plan`.",
    ),
    env: str = _DESIGNER_CONN["env"], url: str = _DESIGNER_CONN["url"],
    user: str = _DESIGNER_CONN["user"], password: str = _DESIGNER_CONN["password"],
    allow_write: bool = typer.Option(
        False, "--allow-write",
        help="Permit the write. Also honored via ACTONE_ALLOW_WRITES=true.",
    ),
    alert_type_usage_data_source: str = _ALERT_TYPE_USAGE_OPTION,
    alert_type_usage_ddq: str = _ALERT_TYPE_USAGE_DDQ_OPTION,
    ddq_reference_evidence: str = typer.Option(
        None,
        "--ddq-reference-evidence",
        help="Same DDQ reference evidence used during planning.",
    ),
    ddq_runtime_request: str = typer.Option(
        None,
        "--ddq-runtime-request",
        help="Optional runDDQ verification parameters as a JSON object.",
    ),
    renderer_inventory: str = typer.Option(
        None,
        "--renderer-inventory",
        help="Same presentation formatter inventory as a JSON array.",
    ),
):
    from actone.designer import DesignerClient, DesignerError
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
    )
    from actone.designer_hierarchy import (
        HierarchyPlanError,
        apply_business_unit_hierarchy_plan,
    )
    from actone.designer_planner import (
        collect_remove_work_item_observation,
    )
    from actone.designer_presentation import (
        apply_work_item_presentation_plan,
        collect_work_item_presentation_observation,
    )
    from actone.invoke import InvokeError, make_client, writes_enabled
    from actone.platform_list_capability import (
        apply_platform_list_plan,
        collect_platform_list_observation,
    )

    if not (allow_write or writes_enabled(env)):
        typer.echo("error: designer apply is a WRITE and is gated. Re-run with "
                   "--allow-write (or enable writes for the environment).")
        raise typer.Exit(1)
    try:
        plan = json.loads(plan_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        typer.echo("error: cannot read plan JSON: %s" % exc)
        raise typer.Exit(1)
    capability_id = plan.get("capability") if isinstance(plan, dict) else None
    if capability_id not in PLANNABLE_CAPABILITY_IDS:
        typer.echo("error: unsupported capability %r" % capability_id)
        raise typer.Exit(1)
    expected_fingerprint = fingerprint_capability_plan(plan)
    if (
        expected_fingerprint != plan.get("fingerprint")
        or plan.get("planId") != expected_fingerprint[:16]
    ):
        typer.echo("error: plan fingerprint does not match its contents")
        raise typer.Exit(1)
    target_environment = env or "default"
    if plan.get("environment") != target_environment:
        typer.echo(
            "error: plan targets environment %r, not %r"
            % (plan.get("environment"), target_environment)
        )
        raise typer.Exit(1)
    try:
        parsed_evidence = _optional_json(
            ddq_reference_evidence, "--ddq-reference-evidence"
        )
        parsed_runtime = _optional_json(
            ddq_runtime_request, "--ddq-runtime-request"
        )
        parsed_renderers = _optional_json(
            renderer_inventory, "--renderer-inventory"
        )
        if parsed_renderers is not None and not isinstance(parsed_renderers, list):
            raise ValueError("--renderer-inventory must be a JSON array")
        if capability_id == "manage_drill_down_query":
            parsed_evidence = merge_ddq_apply_evidence(
                plan, parsed_evidence
            )
        client = make_client(url, user, password, env=env)
        client.login()
        current_build = client.detect_version()
        if current_build != plan.get("targetBuild"):
            typer.echo(
                "error: target build changed (planned %r, actual %r)"
                % (plan.get("targetBuild"), current_build)
            )
            raise typer.Exit(1)
        build_info = load_capabilities().inspect(capability_id, current_build)
        if not build_info or build_info["liveCertificationStatus"] != "certified":
            contract_note = (
                " (offline contract verified, but not live-certified)"
                if build_info
                and build_info.get("contractStatus") == "offline_verified"
                else ""
            )
            typer.echo(
                "error: capability %r is not certified for writes on build %r%s"
                % (capability_id, current_build, contract_note)
            )
            raise typer.Exit(1)
        designer = DesignerClient(client)
        specification = plan.get("specification")
        if capability_id == "manage_platform_list":
            from actone.registry import load_registry

            rest_registry = load_registry()
            observed = collect_platform_list_observation(
                designer, rest_registry, client, specification
            )
            result = apply_platform_list_plan(
                plan, designer, rest_registry, client, observed
            )
        elif capability_id == "manage_drill_down_query":
            from actone.registry import load_registry

            result = apply_drill_down_query_plan(
                plan,
                designer,
                load_registry(),
                client,
                target_environment,
                current_build,
                reference_evidence=parsed_evidence,
                runtime_request=parsed_runtime,
            )
        elif capability_id == "configure_work_item_presentation":
            from actone.registry import load_registry

            rest_registry = load_registry()
            observed = collect_work_item_presentation_observation(
                rest_registry,
                client,
                specification,
                renderer_inventory=parsed_renderers,
            )
            result = apply_work_item_presentation_plan(
                plan, rest_registry, client, observed
            )
        elif capability_id == "manage_business_unit_hierarchy":
            result = apply_business_unit_hierarchy_plan(
                plan,
                designer,
                target_environment,
                current_build,
            )
        elif capability_id == "create_work_item_type":
            result = _apply_create_work_item_type_plan(
                client,
                designer,
                plan,
                target_environment,
                alert_type_usage_data_source,
                alert_type_usage_ddq,
                current_build=current_build,
            )
        else:
            observed = collect_remove_work_item_observation(
                designer, specification
            )
            result = apply_remove_work_item_plan(plan, designer, observed)
        _echo(result)
        if not result.get("ok"):
            raise typer.Exit(1)
    except (
        InvokeError,
        DesignerError,
        DrillDownQueryPlanError,
        HierarchyPlanError,
        ValueError,
    ) as exc:
        typer.echo("error: %s" % exc)
        raise typer.Exit(1)


@designer_app.command("verify",
                      help="Read back and verify a saved Designer plan (READ).")
def designer_verify(
    plan_file: Path = typer.Argument(
        ..., exists=True, dir_okay=False, readable=True,
        help="JSON file containing the complete output of `designer plan`.",
    ),
    env: str = _DESIGNER_CONN["env"], url: str = _DESIGNER_CONN["url"],
    user: str = _DESIGNER_CONN["user"], password: str = _DESIGNER_CONN["password"],
    ddq_runtime_request: str = typer.Option(
        None,
        "--ddq-runtime-request",
        help="Optional runDDQ verification parameters as a JSON object.",
    ),
    renderer_inventory: str = typer.Option(
        None,
        "--renderer-inventory",
        help="Presentation formatter identifiers as a JSON array.",
    ),
):
    from actone.designer import DesignerClient, DesignerError
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
    from actone.invoke import InvokeError, make_client
    from actone.platform_list_capability import verify_platform_list

    try:
        plan = json.loads(plan_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        typer.echo("error: cannot read plan JSON: %s" % exc)
        raise typer.Exit(1)
    if plan.get("capability") not in PLANNABLE_CAPABILITY_IDS:
        typer.echo("error: unsupported capability %r" % plan.get("capability"))
        raise typer.Exit(1)
    expected_fingerprint = fingerprint_capability_plan(plan)
    if (
        expected_fingerprint != plan.get("fingerprint")
        or plan.get("planId") != expected_fingerprint[:16]
    ):
        typer.echo("error: plan fingerprint does not match its contents")
        raise typer.Exit(1)
    target_environment = env or "default"
    if plan.get("environment") != target_environment:
        typer.echo(
            "error: plan targets environment %r, not %r"
            % (plan.get("environment"), target_environment)
        )
        raise typer.Exit(1)
    try:
        parsed_runtime = _optional_json(
            ddq_runtime_request, "--ddq-runtime-request"
        )
        parsed_renderers = _optional_json(
            renderer_inventory, "--renderer-inventory"
        )
        if parsed_renderers is not None and not isinstance(parsed_renderers, list):
            raise ValueError("--renderer-inventory must be a JSON array")
        client = make_client(url, user, password, env=env)
        client.login()
        current_build = client.detect_version()
        if current_build != plan.get("targetBuild"):
            typer.echo(
                "error: target build changed (planned %r, actual %r)"
                % (plan.get("targetBuild"), current_build)
            )
            raise typer.Exit(1)
        designer = DesignerClient(client)
        if plan.get("capability") == "manage_platform_list":
            from actone.registry import load_registry

            result = verify_platform_list(
                plan, designer, load_registry(), client
            )
        elif plan.get("capability") == "manage_drill_down_query":
            from actone.registry import load_registry

            result = verify_drill_down_query_plan(
                plan,
                designer,
                load_registry(),
                client,
                target_environment,
                current_build,
                runtime_request=parsed_runtime,
            )
        elif plan.get("capability") == "configure_work_item_presentation":
            from actone.registry import load_registry

            observed = collect_work_item_presentation_observation(
                load_registry(),
                client,
                plan.get("specification"),
                renderer_inventory=parsed_renderers,
            )
            result = verify_work_item_presentation(plan, observed)
        elif plan.get("capability") == "manage_business_unit_hierarchy":
            observed = collect_business_unit_hierarchy_observation(
                designer, plan.get("specification")
            )
            result = verify_business_unit_hierarchy(plan, observed)
        elif plan.get("capability") == "create_work_item_type":
            result = verify_work_item_type(plan, designer)
        else:
            result = verify_remove_work_item_type(plan, designer)
        result.update({
            "planId": plan.get("planId"),
            "capability": plan.get("capability"),
            "environment": target_environment,
            "targetBuild": current_build,
        })
        _echo(result)
        if not result.get("ok"):
            raise typer.Exit(1)
    except (
        InvokeError,
        DesignerError,
        DrillDownQueryPlanError,
        HierarchyPlanError,
        ValueError,
    ) as exc:
        typer.echo("error: %s" % exc)
        raise typer.Exit(1)


@designer_app.command("list", help="List existing objects of a type (READ).")
def designer_list(
    type_value: str = typer.Argument(..., help="typeValue (see search-types)."),
    full: bool = typer.Option(False, "--full", help="Full objects instead of the info list."),
    env: str = _DESIGNER_CONN["env"], url: str = _DESIGNER_CONN["url"],
    user: str = _DESIGNER_CONN["user"], password: str = _DESIGNER_CONN["password"],
):
    from actone.invoke import InvokeError
    from actone.designer import DesignerError
    try:
        d = _designer_client(url, user, password, env)
        _echo(d.get_object_list(type_value) if full else d.get_object_info_list(type_value))
    except (InvokeError, DesignerError) as e:
        typer.echo("error: %s" % e)
        raise typer.Exit(1)


@designer_app.command("get", help="Fetch one object by type + identifier (READ).")
def designer_get(
    type_value: str = typer.Argument(..., help="typeValue."),
    identifier: str = typer.Argument(..., help="Object identifier."),
    env: str = _DESIGNER_CONN["env"], url: str = _DESIGNER_CONN["url"],
    user: str = _DESIGNER_CONN["user"], password: str = _DESIGNER_CONN["password"],
):
    from actone.invoke import InvokeError
    from actone.designer import DesignerError
    try:
        _echo(_designer_client(url, user, password, env).get_object(type_value, identifier))
    except (InvokeError, DesignerError) as e:
        typer.echo("error: %s" % e)
        raise typer.Exit(1)


@designer_app.command("constraints", help="List delete constraints for an object (READ).")
def designer_constraints(
    type_value: str = typer.Argument(..., help="typeValue."),
    identifier: str = typer.Argument(..., help="Object identifier."),
    env: str = _DESIGNER_CONN["env"], url: str = _DESIGNER_CONN["url"],
    user: str = _DESIGNER_CONN["user"], password: str = _DESIGNER_CONN["password"],
):
    from actone.invoke import InvokeError
    from actone.designer import DesignerError
    try:
        _echo(_designer_client(url, user, password, env).get_remove_constraints(type_value, identifier))
    except (InvokeError, DesignerError) as e:
        typer.echo("error: %s" % e)
        raise typer.Exit(1)


@designer_app.command("create",
                      help="Create any Designer object type from --fields JSON (WRITE).")
def designer_create(
    type_value: str = typer.Argument(..., help="Creatable typeValue (see search-types --creatable)."),
    fields: str = typer.Option(..., "--fields", help="Bean fields + identifier/name as a JSON object."),
    validate_only: bool = typer.Option(
        False, "--validate-only",
        help="Validate the object server-side WITHOUT saving; prints validation messages."),
    env: str = _DESIGNER_CONN["env"], url: str = _DESIGNER_CONN["url"],
    user: str = _DESIGNER_CONN["user"], password: str = _DESIGNER_CONN["password"],
    allow_write: bool = typer.Option(False, "--allow-write",
                                     help="Permit the write. Also honored via ACTONE_ALLOW_WRITES=true."),
):
    from actone.invoke import InvokeError, writes_enabled
    from actone.designer import DesignerError
    if not validate_only and not (allow_write or writes_enabled(env)):
        typer.echo("error: create is a WRITE and is gated. Re-run with --allow-write "
                   "(or set ACTONE_ALLOW_WRITES=true). Tip: use --validate-only to dry-run.")
        raise typer.Exit(1)
    try:
        payload = json.loads(fields)
        client = _designer_client(url, user, password, env)
        if validate_only:
            _echo(client.validate_fields(type_value, payload))
        else:
            _echo(client.create_object(type_value, payload))
    except (InvokeError, DesignerError) as e:
        typer.echo("error: %s" % e)
        raise typer.Exit(1)


@designer_app.command("create-ddq",
                      help="Create a Drill Down Query (WRITE). Convenience over `create DrillDownQuery`.")
def designer_create_ddq(
    identifier: str = typer.Argument(..., help="Unique DDQ identifier."),
    sql: str = typer.Option(..., "--sql", help="The SQL the drill-down runs."),
    name: str = typer.Option(None, "--name", help="Display name (defaults to identifier)."),
    description: str = typer.Option("", "--description"),
    page_title: str = typer.Option("", "--page-title"),
    connection_id: int = typer.Option(None, "--connection-id", help="JDBC connection id."),
    column_names: str = typer.Option("", "--column-names", help="Comma-separated display columns."),
    column_widths: str = typer.Option(
        "", "--column-widths",
        help="Comma-separated pixel widths; must match --column-names count. "
             "Defaults to 100 per column when omitted."),
    row_format: int = typer.Option(
        0, "--row-format",
        help="Row format (server-required, non-null; runDDQ NPEs if unset). 0 = default grid."),
    parameters: str = typer.Option("", "--parameters"),
    parameter_types: str = typer.Option("", "--parameter-types"),
    page_size: int = typer.Option(None, "--page-size"),
    web_accessible: bool = typer.Option(True, "--web-accessible/--no-web-accessible"),
    secured: bool = typer.Option(False, "--secured/--no-secured"),
    sortable: bool = typer.Option(
        False, "--sortable/--no-sortable",
        help="Whether result columns are sortable (server-required, non-null; runDDQ NPEs if unset)."),
    extra: str = typer.Option(None, "--extra", help="Additional DrillDownQuery fields as JSON."),
    validate_only: bool = typer.Option(
        False, "--validate-only",
        help="Validate the DDQ server-side WITHOUT saving; prints validation messages."),
    env: str = _DESIGNER_CONN["env"], url: str = _DESIGNER_CONN["url"],
    user: str = _DESIGNER_CONN["user"], password: str = _DESIGNER_CONN["password"],
    allow_write: bool = typer.Option(False, "--allow-write",
                                     help="Permit the write. Also honored via ACTONE_ALLOW_WRITES=true."),
):
    from actone.invoke import InvokeError, writes_enabled
    from actone.designer import DesignerError
    if not validate_only and not (allow_write or writes_enabled(env)):
        typer.echo("error: create-ddq is a WRITE and is gated. Re-run with --allow-write "
                   "(or set ACTONE_ALLOW_WRITES=true). Tip: use --validate-only to dry-run.")
        raise typer.Exit(1)
    fields = {
        "identifier": identifier, "name": name or identifier, "description": description,
        "pageTitle": page_title, "sqlQuery": sql, "columnNames": column_names,
        "parameters": parameters, "parameterTypes": parameter_types,
        "webAccessible": web_accessible, "secured": secured, "rowFormat": row_format,
        "sortable": sortable,
    }
    # columnWidths must have the same element count as columnNames or Designer
    # rejects the object ("Display columns width is not specified").
    cols = [c for c in column_names.split(",") if c.strip()]
    if column_widths.strip():
        fields["columnWidths"] = column_widths
    elif cols:
        fields["columnWidths"] = ",".join(["100"] * len(cols))
    if connection_id is not None:
        fields["connectionId"] = connection_id
    if page_size is not None:
        fields["pageSize"] = page_size
    if extra:
        fields.update(json.loads(extra))
    try:
        client = _designer_client(url, user, password, env)
        if validate_only:
            _echo(client.validate_fields("DrillDownQuery", fields))
        else:
            _echo(client.create_object("DrillDownQuery", fields))
    except (InvokeError, DesignerError) as e:
        typer.echo("error: %s" % e)
        raise typer.Exit(1)


@designer_app.command("create-alert-type",
                      help="DEPRECATED: compatibility adapter for create_work_item_type.")
def designer_create_alert_type(
    identifier: str = typer.Argument(..., help="Unique alert-type identifier."),
    name: str = typer.Option(None, "--name", help="Display name (defaults to identifier)."),
    description: str = typer.Option("", "--description"),
    workflow_definition: str = typer.Option(
        None, "--workflow-definition",
        help="FK to an existing AlertStatusWorkflowDefinition identifier."),
    using_workflow: bool = typer.Option(
        False, "--using-workflow/--no-using-workflow",
        help="Whether the type uses a status workflow."),
    statuses: str = typer.Option("", "--statuses", help="Comma-separated AlertStatus identifiers."),
    method_id: int = typer.Option(
        4, "--method-id",
        help="Alert display/render method (server-mandatory). 4 = XML-from-DB, the modern default."),
    support_manual_alerts: bool = typer.Option(False, "--support-manual-alerts/--no-support-manual-alerts"),
    global_search: bool = typer.Option(False, "--global-search/--no-global-search"),
    extra: str = typer.Option(
        None, "--extra",
        help="Deprecated old-schema carrier for workItemTypeSpecification only.",
    ),
    specification: str = typer.Option(
        None, "--specification", "--spec-json",
        help="Complete create_work_item_type specification as JSON (required).",
    ),
    validate_only: bool = typer.Option(
        False, "--validate-only",
        help="Build and print the guarded recipe plan without applying it.",
    ),
    env: str = _DESIGNER_CONN["env"], url: str = _DESIGNER_CONN["url"],
    user: str = _DESIGNER_CONN["user"], password: str = _DESIGNER_CONN["password"],
    allow_write: bool = typer.Option(False, "--allow-write",
                                     help="Permit the write. Also honored via ACTONE_ALLOW_WRITES=true."),
    alert_type_usage_data_source: str = _ALERT_TYPE_USAGE_OPTION,
    alert_type_usage_ddq: str = _ALERT_TYPE_USAGE_DDQ_OPTION,
):
    from actone.designer import DesignerClient, DesignerError
    from actone.designer_compat import (
        LegacyAlertTypeMigrationError,
        adapt_legacy_alert_type_specification,
        legacy_alert_type_migration_result,
        mark_legacy_alert_type_result,
    )
    from actone.designer_planner import DesignerPlanError
    from actone.invoke import InvokeError, make_client, writes_enabled

    try:
        extra_fields = json.loads(extra) if extra else None
        specification_value = json.loads(specification) if specification else None
        desired = adapt_legacy_alert_type_specification(
            identifier,
            name=name,
            description=description,
            alert_status_workflow_definition_identifier=workflow_definition,
            assigned_status_identifiers=statuses,
            method_id=method_id,
            support_manual_alerts=support_manual_alerts,
            enabled_for_global_search=global_search,
            extra_fields=extra_fields,
            specification=specification_value,
        )
    except json.JSONDecodeError as exc:
        typer.echo("error: invalid compatibility JSON: %s" % exc)
        raise typer.Exit(1)
    except LegacyAlertTypeMigrationError as exc:
        _echo(legacy_alert_type_migration_result(str(exc)))
        raise typer.Exit(1)

    if not validate_only and not (allow_write or writes_enabled(env)):
        _echo(mark_legacy_alert_type_result({
            "ok": False,
            "error": "write_disabled",
            "message": (
                "create-alert-type redirects to create_work_item_type and is a "
                "WRITE. Re-run with --allow-write or enable writes for the "
                "environment."
            ),
            "environment": env or "default",
        }))
        raise typer.Exit(1)

    try:
        client = make_client(url, user, password, env=env)
        client.login()
        target_build = client.detect_version()
        designer = DesignerClient(client)
        plan = _build_create_work_item_type_plan(
            client,
            designer,
            desired,
            env or "default",
            alert_type_usage_data_source,
            alert_type_usage_ddq,
            target_build=target_build,
        )
        if validate_only:
            _echo(mark_legacy_alert_type_result(plan))
            return
        if not plan.get("applicable"):
            _echo(mark_legacy_alert_type_result({
                "ok": False,
                "error": "plan_not_applicable",
                "planId": plan.get("planId"),
                "plan": plan,
            }))
            raise typer.Exit(1)
        result = _apply_create_work_item_type_plan(
            client,
            designer,
            plan,
            env or "default",
            alert_type_usage_data_source,
            alert_type_usage_ddq,
        )
        _echo(mark_legacy_alert_type_result(result))
        if not result.get("ok"):
            raise typer.Exit(1)
    except (InvokeError, DesignerError, DesignerPlanError) as e:
        typer.echo("error: %s" % e)
        raise typer.Exit(1)


@designer_app.command("create-case-type",
                      help="Create a Case Type (WRITE). Convenience over `create CaseType`.")
def designer_create_case_type(
    identifier: str = typer.Argument(..., help="Unique case-type identifier."),
    name: str = typer.Option(None, "--name", help="Display name (defaults to identifier)."),
    description: str = typer.Option("", "--description"),
    workflow_definition: str = typer.Option(
        None, "--workflow-definition",
        help="FK to an existing CaseStatusWorkflowDefinition identifier."),
    using_workflow: bool = typer.Option(
        False, "--using-workflow/--no-using-workflow",
        help="Whether the type uses a status workflow."),
    statuses: str = typer.Option("", "--statuses", help="Comma-separated CaseStatus identifiers."),
    notes: str = typer.Option("", "--notes", help="Comma-separated predefined-note identifiers."),
    extra: str = typer.Option(None, "--extra", help="Additional CaseType fields as JSON."),
    validate_only: bool = typer.Option(
        False, "--validate-only",
        help="Validate the case type server-side WITHOUT saving; prints validation messages."),
    env: str = _DESIGNER_CONN["env"], url: str = _DESIGNER_CONN["url"],
    user: str = _DESIGNER_CONN["user"], password: str = _DESIGNER_CONN["password"],
    allow_write: bool = typer.Option(False, "--allow-write",
                                     help="Permit the write. Also honored via ACTONE_ALLOW_WRITES=true."),
):
    from actone.invoke import InvokeError, writes_enabled
    from actone.designer import DesignerError
    if not validate_only and not (allow_write or writes_enabled(env)):
        typer.echo("error: create-case-type is a WRITE and is gated. Re-run with --allow-write "
                   "(or set ACTONE_ALLOW_WRITES=true). Tip: use --validate-only to dry-run.")
        raise typer.Exit(1)
    fields = {
        "identifier": identifier, "name": name or identifier, "description": description,
        "usingCaseStatusWorkflow": using_workflow,
    }
    if workflow_definition:
        fields["caseStatusWorkflowDefinitionIdentifier"] = workflow_definition
    status_list = [s.strip() for s in statuses.split(",") if s.strip()]
    if status_list:
        fields["caseStatuses"] = status_list
    note_list = [s.strip() for s in notes.split(",") if s.strip()]
    if note_list:
        fields["preDefinedNotes"] = note_list
    if extra:
        fields.update(json.loads(extra))
    try:
        client = _designer_client(url, user, password, env)
        if validate_only:
            _echo(client.validate_fields("CaseType", fields))
        else:
            _echo(client.create_object("CaseType", fields))
    except (InvokeError, DesignerError) as e:
        typer.echo("error: %s" % e)
        raise typer.Exit(1)


@designer_app.command("clone",
                      help="Copy an existing object to a new identifier (WRITE).")
def designer_clone(
    type_value: str = typer.Argument(..., help="typeValue."),
    source_identifier: str = typer.Argument(..., help="Identifier of the object to copy."),
    new_identifier: str = typer.Argument(..., help="Identifier for the new object."),
    overrides: str = typer.Option(None, "--overrides", help="Field overrides as JSON."),
    env: str = _DESIGNER_CONN["env"], url: str = _DESIGNER_CONN["url"],
    user: str = _DESIGNER_CONN["user"], password: str = _DESIGNER_CONN["password"],
    allow_write: bool = typer.Option(False, "--allow-write"),
):
    from actone.invoke import InvokeError, writes_enabled
    from actone.designer import DesignerError
    if not (allow_write or writes_enabled(env)):
        typer.echo("error: clone is a WRITE and is gated. Re-run with --allow-write.")
        raise typer.Exit(1)
    try:
        ov = json.loads(overrides) if overrides else None
        _echo(_designer_client(url, user, password, env).clone_object(
            type_value, source_identifier, new_identifier, ov))
    except (InvokeError, DesignerError) as e:
        typer.echo("error: %s" % e)
        raise typer.Exit(1)


@designer_app.command("remove", help="Delete an object by type + identifier (WRITE).")
def designer_remove(
    type_value: str = typer.Argument(..., help="typeValue."),
    identifier: str = typer.Argument(..., help="Object identifier."),
    env: str = _DESIGNER_CONN["env"], url: str = _DESIGNER_CONN["url"],
    user: str = _DESIGNER_CONN["user"], password: str = _DESIGNER_CONN["password"],
    allow_write: bool = typer.Option(False, "--allow-write"),
):
    from actone.invoke import InvokeError, writes_enabled
    from actone.designer import DesignerError
    if not (allow_write or writes_enabled(env)):
        typer.echo("error: remove is a WRITE and is gated. Re-run with --allow-write.")
        raise typer.Exit(1)
    try:
        _echo(_designer_client(url, user, password, env).remove_object(type_value, identifier))
    except (InvokeError, DesignerError) as e:
        typer.echo("error: %s" % e)
        raise typer.Exit(1)


@designer_app.command("update", help="Save a modified object payload XML (WRITE).")
def designer_update(
    type_value: str = typer.Argument(..., help="typeValue."),
    identifier: str = typer.Argument(..., help="Object identifier."),
    object_xml: str = typer.Option(..., "--xml", help="Full object payload XML (root xsi:type preserved)."),
    env: str = _DESIGNER_CONN["env"], url: str = _DESIGNER_CONN["url"],
    user: str = _DESIGNER_CONN["user"], password: str = _DESIGNER_CONN["password"],
    allow_write: bool = typer.Option(False, "--allow-write"),
):
    from actone.invoke import InvokeError, writes_enabled
    from actone.designer import DesignerError
    if not (allow_write or writes_enabled(env)):
        typer.echo("error: update is a WRITE and is gated. Re-run with --allow-write.")
        raise typer.Exit(1)
    try:
        _echo(_designer_client(url, user, password, env).update_object(
            type_value, identifier, object_xml))
    except (InvokeError, DesignerError) as e:
        typer.echo("error: %s" % e)
        raise typer.Exit(1)


@designer_app.command("validate",
                      help="Server-side validate an object payload WITHOUT saving (READ).")
def designer_validate(
    type_value: str = typer.Argument(..., help="typeValue."),
    identifier: str = typer.Argument(..., help="Object identifier."),
    object_xml: str = typer.Option(..., "--xml", help="Object payload XML to validate."),
    env: str = _DESIGNER_CONN["env"], url: str = _DESIGNER_CONN["url"],
    user: str = _DESIGNER_CONN["user"], password: str = _DESIGNER_CONN["password"],
):
    from actone.invoke import InvokeError
    from actone.designer import DesignerError
    try:
        _echo(_designer_client(url, user, password, env).validate_object(
            type_value, identifier, object_xml))
    except (InvokeError, DesignerError) as e:
        typer.echo("error: %s" % e)
        raise typer.Exit(1)


@designer_app.command("call",
                      help="Escape hatch: invoke ANY catalog SOAP operation with raw inner-XML. Reads run freely; writes are gated.")
def designer_call(
    service: str = typer.Argument(..., help="Axis service name, e.g. businessUnitService."),
    operation: str = typer.Argument(..., help="Operation name, e.g. getAllBusinessUnits."),
    inner_xml: str = typer.Option("", "--inner-xml", help="Encoded parameter list (may be empty)."),
    out_param: str = typer.Option(None, "--out-param", help="Response out-parameter to extract, if known."),
    env: str = _DESIGNER_CONN["env"], url: str = _DESIGNER_CONN["url"],
    user: str = _DESIGNER_CONN["user"], password: str = _DESIGNER_CONN["password"],
    allow_write: bool = typer.Option(False, "--allow-write",
                                     help="Required for write/unclassified operations."),
):
    from actone.invoke import InvokeError, writes_enabled
    from actone.designer import DesignerError
    from actone.soap_catalog import operation_access
    if operation_access(operation) == "write" and not (allow_write or writes_enabled(env)):
        typer.echo("error: %r is a WRITE (or unclassified) and is gated. "
                   "Re-run with --allow-write." % operation)
        raise typer.Exit(1)
    try:
        _echo(_designer_client(url, user, password, env).call_operation(
            service, operation, inner_xml or "", out_param))
    except (InvokeError, DesignerError) as e:
        typer.echo("error: %s" % e)
        raise typer.Exit(1)


# --- skill reference sync (mirror of `docenter skill sync-reference`) -------- #
DOMAINS_BEGIN = (
    "<!-- BEGIN GENERATED: actone-ops-domains "
    "(run `actone ops sync-skill` to refresh from the spec) -->"
)
DOMAINS_END = "<!-- END GENERATED: actone-ops-domains -->"


def _domain_rows(reg):
    """(domain, total ops, read ops) per tag, sorted by domain."""
    totals, reads = {}, {}
    for op in reg.ops.values():
        for t in (op["tags"] or ["(untagged)"]):
            totals[t] = totals.get(t, 0) + 1
            if op["read"]:
                reads[t] = reads.get(t, 0) + 1
    return [(t, totals[t], reads.get(t, 0)) for t in sorted(totals)]


def _render_domains_table(rows):
    headers = ("Domain (tag)", "Operations", "Read (GET)")
    all_rows = [headers, *[(r[0], str(r[1]), str(r[2])) for r in rows]]
    w = [max(len(str(r[i])) for r in all_rows) for i in range(3)]
    fmt = lambda r: "| " + " | ".join(str(r[i]).ljust(w[i]) for i in range(3)) + " |"
    sep = "|" + "|".join("-" * (w[i] + 2) for i in range(3)) + "|"
    return "\n".join([fmt(headers), sep, *[fmt((r[0], str(r[1]), str(r[2]))) for r in rows]])


@ops_app.command("sync-skill",
                 help="Regenerate the auto-generated domains table in skills/actone-ops/SKILL.md from the spec.")
def ops_sync_skill(
    check: bool = typer.Option(False, "--check", help="Exit non-zero if the table is stale (no write). For CI."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the regenerated table without writing."),
    spec: str = typer.Option(None, "--spec"),
):
    import re
    from actone.registry import load_registry
    from actwise.paths import repo_root
    from actone.paths import PKG

    reg = load_registry(spec)
    rows = _domain_rows(reg)
    caption = ("_%d operations across %d domains - spec %s. Read (GET) operations are callable; "
               "writes are gated (read-only)._" % (len(reg.ops), len(rows), reg.info_version))
    table = _render_domains_table(rows)
    new_block = "%s\n%s\n\n%s\n%s" % (DOMAINS_BEGIN, table, caption, DOMAINS_END)

    skill_file = (repo_root() or PKG.parent.parent.parent) / "skills" / "actone-ops" / "SKILL.md"
    if not skill_file.exists():
        typer.echo("skill file not found: %s (sync-skill only runs in a source checkout)" % skill_file)
        raise typer.Exit(1)

    text = skill_file.read_text(encoding="utf-8")
    block_re = re.compile(re.escape("<!-- BEGIN GENERATED: actone-ops-domains") + r".*?-->.*?"
                          + re.escape(DOMAINS_END), re.DOTALL)
    if not block_re.search(text):
        typer.echo("generated-section markers not found in %s" % skill_file)
        typer.echo("expected a block delimited by:\n  %s\n  %s" % (DOMAINS_BEGIN, DOMAINS_END))
        raise typer.Exit(1)

    new_text = block_re.sub(lambda _m: new_block, text, count=1)
    changed = new_text != text

    # Designer flow-coverage summary (advisory) — how many creatable types have a
    # documented flow in designer-flows.yaml, and any stale/typo flow keys.
    try:
        from actone.soap_catalog import load_catalog
        cov = load_catalog().flow_coverage()
        typer.echo("Designer flow coverage: %d/%d creatable types documented%s"
                   % (cov["documented"], cov["creatable_total"],
                      (" | STALE flow keys: " + ", ".join(cov["unknown_flow_keys"]))
                      if cov["unknown_flow_keys"] else ""))
        if check and cov["unknown_flow_keys"]:
            typer.echo("designer-flows.yaml has non-creatable keys. Run: actone ops designer flows --check")
            raise typer.Exit(1)
    except typer.Exit:
        raise
    except Exception as e:  # coverage is advisory; never block the domains sync on it
        typer.echo("(flow coverage unavailable: %s)" % e)

    if check:
        if changed:
            typer.echo("Domains table is OUT OF DATE. Run: actone ops sync-skill")
            raise typer.Exit(1)
        typer.echo("Domains table is up to date.")
        return
    if dry_run:
        typer.echo(table + "\n\n" + caption)
        return
    if changed:
        skill_file.write_text(new_text, encoding="utf-8")
        typer.echo("Updated %s (%d domains)." % (skill_file, len(rows)))
    else:
        typer.echo("No change.")


if __name__ == "__main__":
    app()
