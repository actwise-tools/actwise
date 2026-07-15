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

import typer

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="ActOne API -> Postman automation suite (spec download, collection generation, review).",
)

ops_app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Spec-driven runtime ops over the ActOne Extend REST API (discovery: search/describe/call). Read-only in P1.",
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
