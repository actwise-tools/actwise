"""ActWise Data — read-only NL-to-SQL engine over ActOne ``v_acm_*`` views (CLI).

Milestone 1 surface: ``actone-data ping``. The engine generates no SQL itself —
the host LLM (skill / Copilot Studio) writes SELECTs; later milestones add
schema/validate/execute commands.
"""
import sys

# UTF-8 guard so Rich box-drawing / non-ASCII output is safe on Windows consoles.
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Load .env before anything reads env vars: current working directory first,
# then the source-checkout root (one level above this package). (docenter/cli.py)
from pathlib import Path as _Path

from actwise.paths import repo_root

for _env_file in (_Path.cwd() / ".env", (repo_root() or _Path(__file__).resolve().parent.parent) / ".env"):
    if _env_file.exists():
        try:
            from dotenv import load_dotenv as _load_dotenv

            _load_dotenv(_env_file, override=False)  # .env sets defaults; real env vars win
        except ImportError:
            pass  # dotenv not installed — env vars must be set manually
        break

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="ActWise Data -> read-only query engine over ActOne v_acm_* views.",
)
console = Console()


@app.callback()
def _main():
    """ActWise Data: read-only query engine over ActOne v_acm_* views."""


def _resolve_or_exit(profile: str, dsn: str = None, **overrides):
    """Resolve a ConnConfig from profile/env/flags, exiting 2 on bad profile."""
    from actone_data import config as _config

    try:
        return _config.resolve(profile=profile, dsn=dsn, **overrides)
    except KeyError as e:
        console.print(f"[red]config error:[/red] {e}")
        raise typer.Exit(2)


@app.command(help="Test the DB connection: prints server version, schema, and the ActOne sentinel check.")
def ping(
    profile: str = typer.Option("local", "--profile", "-p", help="Named profile from actone-data.yaml (default: built-in local)."),
    host: str = typer.Option(None, "--host", help="DB host (overrides profile/env)."),
    port: int = typer.Option(None, "--port", help="DB port."),
    name: str = typer.Option(None, "--name", help="Database name."),
    user: str = typer.Option(None, "--user", help="DB user."),
    password: str = typer.Option(None, "--password", help="DB password (prefer env ACTONE_DB_PASSWORD)."),
    schema: str = typer.Option(None, "--schema", help="Schema (default: actone)."),
    dsn: str = typer.Option(None, "--dsn", help="Full libpq DSN (wins over discrete fields)."),
):
    from actone_data import config as _config
    from actone_data import db

    try:
        cfg = _config.resolve(
            profile=profile, host=host, port=port, name=name,
            user=user, password=password, schema=schema, dsn=dsn,
        )
    except KeyError as e:
        console.print(f"[red]config error:[/red] {e}")
        raise typer.Exit(2)

    try:
        info = db.ping(cfg)
    except Exception as e:  # psycopg.OperationalError and friends
        console.print(f"[red]connection failed[/red] ({cfg.target}): {e}")
        raise typer.Exit(1)

    table = Table(show_header=False, box=None, pad_edge=False)
    table.add_column(style="cyan", no_wrap=True)
    table.add_column()
    table.add_row("target", info["target"])
    table.add_row("server", info["server_version"].split(" on ", 1)[0])
    table.add_row("schema", f'{info["schema"]} (current: {info["current_schema"]})')
    sentinel_ok = info["sentinel"]
    table.add_row(
        "sentinel",
        "[green]found[/green] (acm_md_config_params)" if sentinel_ok
        else "[yellow]not found[/yellow] (run: actone-local db-schema)",
    )
    table.add_row("v_acm_ views", str(info["v_acm_view_count"]))
    console.print(table)
    if not sentinel_ok:
        raise typer.Exit(1)


schema_app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Introspect the live ActOne schema (v_acm_* views).",
)
app.add_typer(schema_app, name="schema")


@schema_app.command("list", help="List the live v_acm_* views and their column counts.")
def schema_list(
    profile: str = typer.Option("local", "--profile", "-p", help="Named profile (default: built-in local)."),
    dsn: str = typer.Option(None, "--dsn", help="Full libpq DSN (wins over profile/env)."),
    names_only: bool = typer.Option(False, "--names-only", help="Print bare view names (no table), one per line."),
):
    from actone_data import db

    cfg = _resolve_or_exit(profile, dsn=dsn)
    try:
        views = db.introspect_views(cfg)
    except Exception as e:
        console.print(f"[red]introspection failed[/red] ({cfg.target}): {e}")
        raise typer.Exit(1)

    if names_only:
        for v in views:
            print(v["name"])
        return

    table = Table(box=None, pad_edge=False)
    table.add_column("view", style="cyan", no_wrap=True)
    table.add_column("cols", justify="right")
    for v in views:
        table.add_row(v["name"], str(v["column_count"]))
    console.print(table)
    console.print(f"[bold]{len(views)}[/bold] v_acm_ views (schema {cfg.schema})")


@schema_app.command("build", help="Build the schema pack (introspection + doc enrichment) and write JSON.")
def schema_build(
    profile: str = typer.Option("local", "--profile", "-p", help="Named profile (default: built-in local)."),
    dsn: str = typer.Option(None, "--dsn", help="Full libpq DSN (wins over profile/env)."),
    bundle: str = typer.Option(None, "--bundle", help="Doc bundle dir (default: ActOne 10.2 Implementer Guide)."),
    doc_version: str = typer.Option(None, "--doc-version", help="Override the doc/pack version when the DB carries no stamp."),
    out: str = typer.Option(None, "--out", help="Output path (default: bundled data/schema-pack-actone-<ver>.json)."),
):
    from pathlib import Path as _P

    from actone_data import schema_pack

    cfg = _resolve_or_exit(profile, dsn=dsn)
    bundle_dir = _P(bundle) if bundle else None
    try:
        pack = schema_pack.build(cfg, bundle_dir=bundle_dir, doc_version=doc_version)
    except Exception as e:
        console.print(f"[red]build failed[/red] ({cfg.target}): {e}")
        raise typer.Exit(1)
    path = schema_pack.save(pack, _P(out) if out else None)

    views = pack["views"]
    allow = [v for v in views.values() if v["provenance"] != "doc_only"]
    doc_only = [v for v in views.values() if v["provenance"] == "doc_only"]
    introspected_only = [v for v in allow if v["provenance"] == "introspected"]
    total_cols = sum(len(v["columns"]) for v in views.values())
    documented_cols = sum(1 for v in views.values() for c in v["columns"] if c["description"])
    preferred = sum(1 for v in allow if v["preferred"])
    legacy = sum(1 for v in allow if v["family"] == "alert")

    table = Table(show_header=False, box=None, pad_edge=False)
    table.add_column(style="cyan", no_wrap=True)
    table.add_column()
    table.add_row("pack", str(path))
    table.add_row("version", f'{pack["source"]["db_product_version"]} (source: {pack["source"]["db_version_source"]})')
    table.add_row("views", f'{len(allow)} allowlisted (+{len(doc_only)} doc-only)')
    table.add_row("provenance", f'{len(allow) - len(introspected_only)} both, {len(introspected_only)} introspected-only, {len(doc_only)} doc-only')
    table.add_row("columns", f'{total_cols} ({documented_cols} with descriptions, {100*documented_cols//max(total_cols,1)}% coverage)')
    table.add_row("preference", f'{preferred} preferred, {legacy} legacy alert')
    console.print(table)


@schema_app.command("show", help="Show a view's family/preference/FKs and columns from the schema pack.")
def schema_show(
    view: str = typer.Argument(..., help="View name, e.g. v_acm_items."),
    pack: str = typer.Option(None, "--pack", help="Pack path (default: ACTONE_DATA_PACK or bundled)."),
):
    from pathlib import Path as _P

    from actone_data import schema_pack

    try:
        data = schema_pack.load(_P(pack) if pack else None)
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    key = view.strip().lower()
    v = data["views"].get(key)
    if v is None:
        console.print(f"[red]view not in pack:[/red] {key}")
        raise typer.Exit(1)

    pref = "[green]preferred[/green]" if v["preferred"] else "[yellow]legacy[/yellow]" if v["family"] == "alert" else v["family"]
    allow = "excluded from allowlist" if v["provenance"] == "doc_only" else "allowlisted"
    console.print(f"[bold]{key}[/bold]  family={v['family']}  {pref}  ({allow}, provenance={v['provenance']})")
    if v.get("description"):
        console.print(f"  {v['description']}")
    if v.get("related_views"):
        console.print(f"  related (preferred equivalents): {', '.join(v['related_views'])}")
    tbl = Table(box=None, pad_edge=False)
    tbl.add_column("column", style="cyan", no_wrap=True)
    tbl.add_column("type")
    tbl.add_column("fk -> view")
    tbl.add_column("prov")
    tbl.add_column("description", overflow="fold")
    for c in v["columns"]:
        tbl.add_row(c["name"], c["type"] or "-", c["fk"] or "", c["provenance"], (c["description"] or "")[:70])
    console.print(tbl)


@schema_app.command("summary", help="Summarize the schema pack (view/column/coverage/preference counts).")
def schema_summary(
    pack: str = typer.Option(None, "--pack", help="Pack path (default: ACTONE_DATA_PACK or bundled)."),
):
    from pathlib import Path as _P

    from actone_data import schema_pack

    try:
        data = schema_pack.load(_P(pack) if pack else None)
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    views = data["views"]
    allow = [v for v in views.values() if v["provenance"] != "doc_only"]
    doc_only = [v for v in views.values() if v["provenance"] == "doc_only"]
    fams: dict[str, int] = {}
    for v in allow:
        fams[v["family"]] = fams.get(v["family"], 0) + 1
    total_cols = sum(len(v["columns"]) for v in views.values())
    fk_cols = sum(1 for v in views.values() for c in v["columns"] if c["fk"])

    table = Table(show_header=False, box=None, pad_edge=False)
    table.add_column(style="cyan", no_wrap=True)
    table.add_column()
    table.add_row("built_at", data.get("built_at", "-"))
    table.add_row("version", f'{data["source"]["db_product_version"]} ({data["source"]["db_version_source"]})')
    table.add_row("bundle", data["source"]["doc_bundle"])
    table.add_row("views", f'{len(allow)} allowlisted (+{len(doc_only)} doc-only)')
    table.add_row("families", ", ".join(f"{k}={v}" for k, v in sorted(fams.items())))
    table.add_row("preferred", str(sum(1 for v in allow if v["preferred"])))
    table.add_row("columns", f"{total_cols} ({fk_cols} with FK)")
    console.print(table)


query_app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Validate or run a read-only SELECT over the v_acm_* views.",
)
app.add_typer(query_app, name="query")


@query_app.command("validate", help="Dry-run the guardrail pipeline on a SQL string (no execution).")
def query_validate(
    sql: str = typer.Argument(..., help="SQL to validate."),
    profile: str = typer.Option("local", "--profile", "-p", help="Profile used to fetch the live allowlist."),
    dsn: str = typer.Option(None, "--dsn", help="Full libpq DSN (wins over profile/env)."),
    max_rows: int = typer.Option(100, "--max-rows", help="Row limit to inject/clamp to (cap 1000)."),
):
    from actone_data import audit, db, guardrails

    cfg = _resolve_or_exit(profile, dsn=dsn)
    try:
        with db.connect(cfg) as conn, conn.cursor() as cur:
            allowed = db._live_view_names(cur, cfg.schema)
    except Exception as e:
        console.print(f"[red]connection failed[/red] ({cfg.target}): {e}")
        raise typer.Exit(1)

    res = guardrails.validate(sql, allowed, cfg.schema, max_rows=max_rows)
    audit.record(transport="cli", question="", sql=sql, ok=res["ok"],
                 sql_used=res["sql_used"],
                 rejected_reason=None if res["ok"] else "; ".join(res["errors"]),
                 db=cfg.target, env=profile)
    if res["ok"]:
        console.print("[green]OK[/green]")
        console.print(f"  views: {', '.join(res['views_used'])}")
        console.print(f"  limit_injected: {res['limit_injected']}")
        console.print(f"  sql_used: {res['sql_used']}")
    else:
        console.print("[red]REJECTED[/red]")
        for e in res["errors"]:
            console.print(f"  - {e}")
        raise typer.Exit(1)


@query_app.command("run", help="Validate and execute a read-only SELECT; prints results.")
def query_run(
    sql: str = typer.Argument(..., help="SQL to run."),
    profile: str = typer.Option("local", "--profile", "-p", help="Named profile (default: built-in local)."),
    dsn: str = typer.Option(None, "--dsn", help="Full libpq DSN (wins over profile/env)."),
    max_rows: int = typer.Option(100, "--max-rows", help="Max rows to return (cap 1000)."),
    question: str = typer.Option("", "--question", "-q", help="The user question, recorded for audit."),
    fmt: str = typer.Option("table", "--format", "-f", help="Output format: table | json | csv."),
):
    import json as _json

    from actone_data import audit, db
    from actone_data.guardrails import GuardrailError

    cfg = _resolve_or_exit(profile, dsn=dsn)
    try:
        res = db.run_query(cfg, sql, max_rows=max_rows)
    except GuardrailError as ge:
        audit.record(transport="cli", question=question, sql=sql, ok=False,
                     rejected_reason="; ".join(ge.errors), db=cfg.target, env=profile)
        console.print("[red]REJECTED[/red]")
        for e in ge.errors:
            console.print(f"  - {e}")
        raise typer.Exit(1)
    except Exception as e:
        audit.record(transport="cli", question=question, sql=sql, ok=False,
                     rejected_reason=f"execution error: {e}", db=cfg.target, env=profile)
        console.print(f"[red]execution failed[/red]: {e}")
        raise typer.Exit(1)

    audit.record(transport="cli", question=question, sql=res["sql_used"], ok=True,
                 sql_used=res["sql_used"], rows=res["row_count"],
                 truncated=res["truncated"], duration_ms=res["duration_ms"],
                 db=cfg.target, env=profile)

    if fmt == "json":
        console.print_json(_json.dumps({"columns": res["columns"], "rows": res["rows"]}))
    elif fmt == "csv":
        import csv
        import io
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(res["columns"])
        w.writerows(res["rows"])
        print(buf.getvalue().rstrip("\n"))
    else:
        tbl = Table(box=None, pad_edge=False)
        for c in res["columns"]:
            tbl.add_column(c, overflow="fold")
        for row in res["rows"]:
            tbl.add_row(*["" if v is None else str(v) for v in row])
        console.print(tbl)
    trunc = " [yellow](truncated)[/yellow]" if res["truncated"] else ""
    console.print(
        f"[dim]{res['row_count']} rows{trunc} in {res['duration_ms']} ms; "
        f"limit_injected={res['limit_injected']}; sql: {res['sql_used']}[/dim]"
    )


audit_app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Inspect the query audit log.",
)
app.add_typer(audit_app, name="audit")


@audit_app.command("tail", help="Show the most recent audit records.")
def audit_tail(
    n: int = typer.Option(20, "--n", "-n", help="Number of records to show."),
):
    from actone_data import audit

    records = audit.tail(n)
    if not records:
        console.print("[dim]no audit records[/dim]")
        return
    tbl = Table(box=None, pad_edge=False)
    tbl.add_column("ts", style="cyan", no_wrap=True)
    tbl.add_column("actor")
    tbl.add_column("env")
    tbl.add_column("ok")
    tbl.add_column("rows")
    tbl.add_column("detail", overflow="fold")
    for r in records:
        ok = "[green]ok[/green]" if r.get("ok") else "[red]rej[/red]"
        detail = r.get("sql_used") or r.get("rejected_reason") or r.get("sql") or ""
        tbl.add_row(r.get("ts", ""), str(r.get("actor", "")), str(r.get("env") or ""), ok,
                    str(r.get("rows", "")) if r.get("rows") is not None else "",
                    detail[:80])
    console.print(tbl)


env_app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="List the configured ActOne environments (DB profiles).",
)
app.add_typer(env_app, name="env")


@env_app.command("list", help="List configured environments (metadata only; never passwords).")
def env_list():
    from actone_data import config as _config

    envs = _config.list_profiles()
    tbl = Table(box=None, pad_edge=False)
    tbl.add_column("name", style="cyan", no_wrap=True)
    tbl.add_column("host")
    tbl.add_column("port")
    tbl.add_column("database")
    tbl.add_column("user")
    tbl.add_column("schema")
    tbl.add_column("pwd")
    tbl.add_column("default")
    for e in envs:
        tbl.add_row(
            e["name"],
            "[dim]dsn[/dim]" if e["dsn"] else e["host"],
            "" if e["dsn"] else str(e["port"]),
            "" if e["dsn"] else e["database"],
            "" if e["dsn"] else e["user"],
            "" if e["dsn"] else e["schema"],
            "[green]yes[/green]" if e["password_configured"] else "[red]no[/red]",
            "*" if e["is_default"] else "",
        )
    console.print(tbl)


@app.command(help="Detect the ActOne product version from the DB (falls back to the bundled doc version).")
def version(
    profile: str = typer.Option("local", "--profile", "-p", help="Named profile (default: built-in local)."),
    dsn: str = typer.Option(None, "--dsn", help="Full libpq DSN (wins over profile/env)."),
):
    from actone_data import config as _config
    from actone_data import db

    cfg = _resolve_or_exit(profile, dsn=dsn)
    try:
        info = db.detect_version(cfg)
    except Exception as e:
        console.print(f"[red]version detect failed[/red] ({cfg.target}): {e}")
        raise typer.Exit(1)

    table = Table(show_header=False, box=None, pad_edge=False)
    table.add_column(style="cyan", no_wrap=True)
    table.add_column()
    if info["version"]:
        table.add_row("detected", f'[green]{info["version"]}[/green]')
        table.add_row("source", f'db ({info["detail"]})')
    else:
        table.add_row("detected", "[yellow]not stamped in DB[/yellow]")
        table.add_row("fallback", f'{_config.DEFAULT_DOC_VERSION} (bundled doc version)')
        table.add_row("source", info["detail"])
    console.print(table)


docs_app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Parse the v_acm_* doc pages (descriptions + FK graph).",
)
app.add_typer(docs_app, name="docs")


@docs_app.command("enrich", help="Parse the v_acm_* doc pages and resolve the FK graph.")
def docs_enrich_cmd(
    profile: str = typer.Option("local", "--profile", "-p", help="Profile used to introspect live views for FK reconciliation."),
    dsn: str = typer.Option(None, "--dsn", help="Full libpq DSN (wins over profile/env)."),
    bundle: str = typer.Option(None, "--bundle", help="Doc bundle dir (default: the ActOne 10.2 Implementer Guide)."),
    page: str = typer.Option(None, "--page", help="Dump resolved columns/FKs for a single view (e.g. v_acm_items)."),
    offline: bool = typer.Option(False, "--offline", help="Skip DB introspection; reconcile FKs against the parsed page names only."),
):
    from pathlib import Path as _P

    from actone_data import db, docs_enrich

    known = None
    if not offline:
        cfg = _resolve_or_exit(profile, dsn=dsn)
        try:
            known = {v["name"] for v in db.introspect_views(cfg)}
        except Exception as e:
            console.print(f"[yellow]note:[/yellow] DB unreachable ({e}); reconciling against doc names only.")

    bundle_dir = _P(bundle) if bundle else docs_enrich.DEFAULT_BUNDLE
    if not bundle_dir.exists():
        console.print(f"[red]bundle not found:[/red] {bundle_dir}")
        raise typer.Exit(1)

    views = docs_enrich.enrich(bundle_dir, known_views=known)
    files = sorted(bundle_dir.glob("v_acm_*.md"))

    if page:
        key = page.strip().lower()
        dv = views.get(key)
        if dv is None:
            console.print(f"[red]no doc page for view:[/red] {key}")
            raise typer.Exit(1)
        console.print(f"[bold]{dv.name}[/bold]  ({len(dv.columns)} columns)  {dv.source_url or ''}")
        if dv.description:
            console.print(f"  {dv.description}")
        tbl = Table(box=None, pad_edge=False)
        tbl.add_column("column", style="cyan", no_wrap=True)
        tbl.add_column("fk -> view")
        tbl.add_column("source")
        for col in dv.columns:
            if col.fk or col.fk_raw:
                tbl.add_row(col.name, col.fk or f"[red]{col.fk_raw} (unresolved)[/red]", col.fk_source or "")
        console.print(tbl)
        for w in dv.warnings:
            console.print(f"  [yellow]![/yellow] {w}")
        return

    failures = [v.name for v in views.values() if any("no field table" in w for w in v.warnings)]
    total_cols = sum(len(v.columns) for v in views.values())
    by_source = {"parenthetical": 0, "learned": 0, "naming": 0}
    unresolved = 0
    corrections = 0
    for v in views.values():
        for c in v.columns:
            if c.fk_source in by_source and c.fk:
                by_source[c.fk_source] += 1
            if c.fk_raw and not c.fk:
                unresolved += 1
            elif c.fk and c.fk_raw:
                corrections += 1
    console.print(f"parsed [bold]{len(files)}[/bold] pages ([bold]{len(views)}[/bold] unique views), [bold]{len(failures)}[/bold] failures; {total_cols} columns")
    dupes = len(files) - len(views)
    if dupes:
        console.print(f"[yellow]note:[/yellow] {dupes} duplicate page_title(s) collapsed (e.g. v_acm_items_findings_reasons)")
    console.print(
        f"FK edges: parenthetical={by_source['parenthetical']} "
        f"learned={by_source['learned']} naming={by_source['naming']} "
        f"| corrections={corrections} unresolved={unresolved}"
    )
    if failures:
        console.print(f"[red]failed pages:[/red] {', '.join(failures)}")


@app.command(help="Run the NL->SQL eval set through the guardrail + execute path and print a scoreboard.")
def eval(
    profile: str = typer.Option("local", "--profile", "-p", help="Named profile (default: built-in local)."),
    dsn: str = typer.Option(None, "--dsn", help="Full libpq DSN (wins over profile/env)."),
    set_path: str = typer.Option(None, "--set", help="A single eval-set YAML (default: all under actone_data/data/evals/)."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show per-case detail (views/rows or failure reasons)."),
):
    from pathlib import Path as _P

    from actone_data import evals

    cfg = _resolve_or_exit(profile, dsn=dsn)
    try:
        results = evals.run(cfg, _P(set_path) if set_path else None)
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    tbl = Table(box=None, pad_edge=False)
    tbl.add_column("result", no_wrap=True)
    tbl.add_column("id", style="cyan", no_wrap=True)
    tbl.add_column("expect", no_wrap=True)
    tbl.add_column("detail", overflow="fold")
    for r in results:
        mark = "[green]PASS[/green]" if r.passed else "[red]FAIL[/red]"
        detail = r.detail if r.passed else "; ".join(r.fails)
        if r.passed and not verbose:
            detail = ""
        tbl.add_row(mark, r.id, r.expect, detail)
    console.print(tbl)

    passed = sum(1 for r in results if r.passed)
    total = len(results)
    color = "green" if passed == total else "red"
    console.print(f"[{color}]{passed}/{total} passed[/{color}]")
    if passed != total:
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
