"""actimize-installer — gated runner that installs a downloaded NDC package.

Closes the last mile of the ActWise chain:
    docs (docenter) -> package (ndc) -> **install (actimize-installer)**

It detects which Actimize installer a package carries (ActOne rcm-installer,
the generic/patch Actimize-installer, or the AIS setup.exe), builds the exact
command line, and runs it **only** behind a confirmation gate with captured
logs. Dry-run is the default.
"""
from __future__ import annotations

import json as _json
import sys
from pathlib import Path
from typing import Optional

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

import typer
from rich.console import Console
from rich.table import Table
from rich import print as rprint

from . import detect as D
from . import runner as R

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Actimize Installer runner — install a package fetched by `ndc`. "
         "Dry-run by default; execution is gated. Complements docenter (docs) "
         "and ndc (packages).",
)
console = Console()


def _emit_json(obj) -> None:
    print(_json.dumps(obj, indent=2))


def _resolve_package(package: Path, extract: bool) -> Path:
    if extract or package.suffix.lower() == ".zip":
        return D.maybe_extract(package)
    return package


# ── detect ────────────────────────────────────────────────────────────────────
@app.command("detect")
def detect_cmd(
    package: Path = typer.Option(..., "--package", "-P", help="Extracted package dir (or .zip)"),
    extract: bool = typer.Option(False, "--extract", help="Extract if a .zip is given"),
    json_out: bool = typer.Option(False, "--json", help="Machine-readable output"),
):
    """Inspect a package and report its installer flavor, bin, and CONF files."""
    root = _resolve_package(package, extract)
    det = D.detect(root)
    if json_out:
        _emit_json(det.to_dict())
        raise typer.Exit(0 if det.found else 1)

    if not det.found:
        rprint(f"[red]No Actimize installer found[/red] under {root}")
        for n in det.notes:
            rprint(f"  [dim]-[/dim] {n}")
        raise typer.Exit(1)

    t = Table(title=f"Detected installer: {det.kind.value}", show_header=False)
    t.add_row("Kind", det.kind.value)
    t.add_row("Executable", str(det.bin))
    if det.installer_dir:
        t.add_row("Installer dir", str(det.installer_dir))
    if det.conf_dir:
        t.add_row("CONF dir", str(det.conf_dir))
    if det.logs_dir:
        t.add_row("Logs dir", str(det.logs_dir))
    console.print(t)
    if det.conf_files:
        rprint(f"[dim]CONF files ({len(det.conf_files)}):[/dim]")
        for p in det.conf_files:
            rprint(f"  [cyan]{p.relative_to(det.package_root)}[/cyan]")
    for n in det.notes:
        rprint(f"[yellow]note:[/yellow] {n}")
    rprint("\n[dim]Next:[/dim] [bold]actimize-installer run --package "
           f"{package} --command install[/bold]  [dim](dry-run by default)[/dim]")


# ── show (read-only passthrough to the installer's own `show`) ─────────────────
@app.command("show")
def show_cmd(
    package: Path = typer.Option(..., "--package", "-P", help="Extracted package dir (or .zip)"),
    what: str = typer.Argument("install", help="install | upgrade | properties"),
    verbose: bool = typer.Option(False, "--verbose", "-V", help="Show step detail"),
    extract: bool = typer.Option(False, "--extract", help="Extract if a .zip is given"),
):
    """Run the installer's own read-only `show` command (safe to execute)."""
    root = _resolve_package(package, extract)
    det = D.detect(root)
    if not det.found or det.kind is D.InstallerKind.AIS_MODELER:
        rprint("[red]`show` is only supported for the rcm/generic installers.[/red]")
        raise typer.Exit(1)
    argv = [str(det.bin), "show", what]
    if verbose:
        argv.append("-V")
    plan = R.InstallPlan(det.kind, argv, det.bin.parent, det.logs_dir)
    rprint(f"[dim]cwd:[/dim] {plan.cwd}")
    rprint(f"[bold]{plan.command_str}[/bold]\n")
    code, log_path = R.execute(plan)
    rprint(f"\n[dim]exit {code}; log: {log_path}[/dim]")
    raise typer.Exit(code)


# ── run ────────────────────────────────────────────────────────────────────────
@app.command("run")
def run_cmd(
    package: Path = typer.Option(..., "--package", "-P", help="Extracted package dir (or .zip)"),
    command: str = typer.Option("install", "--command", help="install | upgrade | show"),
    mode: Optional[str] = typer.Option(None, "--mode", help="full | sp | patch (alias for --command)"),
    include: list[str] = typer.Option([], "--include", "-i", help="Only this task/step (repeatable)"),
    exclude: list[str] = typer.Option([], "--exclude", "-x", help="Exclude this task/step (repeatable)"),
    force: bool = typer.Option(False, "--force", "-f", help="Force steps even if already installed"),
    from_version: Optional[str] = typer.Option(None, "--from", help="Patch upgrade: from version (-F)"),
    to_version: Optional[str] = typer.Option(None, "--to", help="Patch upgrade: to version (-T)"),
    conf: Optional[Path] = typer.Option(None, "--conf", "-c", help="Override CONF folder"),
    work: Optional[Path] = typer.Option(None, "--work", "-w", help="Override work folder"),
    log: Optional[Path] = typer.Option(None, "--log", "-l", help="Override installer log folder"),
    # AIS setup.exe knobs
    features: Optional[str] = typer.Option(None, "--features", help="setup.exe -f (modeler|monitor|all)"),
    target_path: Optional[str] = typer.Option(None, "--target-path", help="setup.exe -p install path"),
    upgrade_from: Optional[str] = typer.Option(None, "--upgrade-from", help="setup.exe -v old version"),
    # guardrails
    execute: bool = typer.Option(False, "--execute", help="Actually run (default: dry-run)"),
    yes: bool = typer.Option(False, "--yes", help="Skip the confirmation prompt (with --execute)"),
    allow_prod: bool = typer.Option(False, "--allow-prod", help="Permit a prod-looking CONF"),
    extract: bool = typer.Option(False, "--extract", help="Extract if a .zip is given"),
    json_out: bool = typer.Option(False, "--json", help="Machine-readable plan output"),
):
    """Build the install command (dry-run) and, with --execute, run it behind a gate."""
    root = _resolve_package(package, extract)
    det = D.detect(root)
    if not det.found:
        rprint(f"[red]No Actimize installer found[/red] under {root}")
        raise typer.Exit(1)

    plan = R.build_plan(
        det, command=command, mode=mode,
        include=list(include), exclude=list(exclude), force=force,
        from_version=from_version, to_version=to_version,
        conf=conf, work=work, log=log,
        features=features, target_path=target_path, upgrade_from=upgrade_from,
        allow_prod=allow_prod,
    )

    if json_out:
        _emit_json({**plan.to_dict(), "execute": execute})
        raise typer.Exit(1 if plan.blockers else 0)

    rprint(f"[bold]Installer:[/bold] {plan.kind.value}")
    rprint(f"[dim]cwd:[/dim] {plan.cwd}")
    rprint(f"\n  [bold cyan]{plan.command_str}[/bold cyan]\n")
    for w in plan.warnings:
        rprint(f"[yellow]warn:[/yellow] {w}")
    for b in plan.blockers:
        rprint(f"[red]BLOCKED:[/red] {b}")

    if plan.blockers:
        rprint("\n[red]Not runnable until blockers are resolved.[/red]")
        raise typer.Exit(1)

    if not execute:
        rprint("[dim]Dry-run only. Re-run with[/dim] [bold]--execute[/bold] "
               "[dim]to install (you'll be asked to confirm).[/dim]")
        raise typer.Exit(0)

    if not yes:
        rprint("[bold red]This will install/modify software on this machine.[/bold red]")
        if not typer.confirm(f"Run: {plan.command_str} ?", default=False):
            rprint("[dim]Aborted.[/dim]")
            raise typer.Exit(1)

    rprint("[green]Running…[/green]\n")
    code, log_path = R.execute(plan)
    rprint(f"\n[dim]exit {code}; run log:[/dim] {log_path}")
    if det.logs_dir:
        rprint(f"[dim]installer log:[/dim] {det.logs_dir / 'installation.log'}")
    raise typer.Exit(code)


if __name__ == "__main__":
    app()
