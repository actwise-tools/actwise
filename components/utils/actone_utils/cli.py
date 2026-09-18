"""actone-utils — typed runner for ActOne maintenance utilities (C-U).

Wrap ActOne's Java ``.bat/.sh`` utilities behind a discovery-loop CLI:

    list / search  ->  describe  ->  run  (--dry-run by default)

Runs against a **local**, **ssh**, or **winrm** backend (see ``doctor`` / config).
State-changing utilities require ``--yes`` for a real run; ``--dry-run`` assembles
and prints the exact command without executing.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import List, Optional

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

import typer
from rich.console import Console
from rich.table import Table

from . import catalog
from .backends import make_backend
from .config import UtilsConfig
from .runner import run_utility, build_argv, UtilityError, RunGate

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Typed runner for ActOne maintenance utilities (Blotter Maintenance, DART "
         "runner) over local / ssh / winrm backends. Discovery loop: list -> "
         "describe -> run. Dry-run by default; state-changing runs need --yes.",
)
console = Console()


def _cfg(config: Optional[Path], backend: Optional[str]) -> UtilsConfig:
    cfg = UtilsConfig.load(config)
    if backend:
        cfg.backend = backend
    return cfg


def _parse_params(pairs: List[str]) -> dict:
    out: dict = {}
    for item in pairs or []:
        if "=" not in item:
            raise typer.BadParameter(f"expected KEY=VALUE, got {item!r}")
        k, v = item.split("=", 1)
        out[k.strip()] = v.strip()
    return out


@app.command("list", help="List all utilities in the catalog.")
def list_cmd(as_json: bool = typer.Option(False, "--json", help="Emit JSON.")):
    briefs = catalog.list_briefs()
    if as_json:
        console.print_json(data=briefs)
        return
    table = Table(title="ActOne utilities", show_lines=False)
    table.add_column("name", style="cyan")
    table.add_column("access")
    table.add_column("tags", style="dim")
    table.add_column("title")
    for b in briefs:
        access = "[red]write[/red]" if b["access"] == "write" else "[green]read[/green]"
        table.add_row(b["name"], access, ",".join(b["tags"]), b["title"])
    console.print(table)


@app.command("search", help="Search utilities by keyword (name/title/tool/tags/summary).")
def search_cmd(query: str, limit: int = 25,
               as_json: bool = typer.Option(False, "--json")):
    res = catalog.search(query, limit)
    if as_json:
        console.print_json(data=res)
        return
    for b in res:
        console.print(f"[cyan]{b['name']}[/cyan] ({b['access']}) — {b['title']}")


@app.command("describe", help="Show a utility's parameters, access, and source doc.")
def describe_cmd(name: str, as_json: bool = typer.Option(False, "--json")):
    util = catalog.get(name)
    if not util:
        sugg = ", ".join(b["name"] for b in catalog.search(name, 5))
        console.print(f"[red]unknown utility[/red] '{name}'. Did you mean: {sugg}")
        raise typer.Exit(1)
    info = util.describe()
    if as_json:
        console.print_json(data=info)
        return
    console.print(f"[bold cyan]{info['name']}[/bold cyan] — {info['title']}")
    console.print(f"tool: [yellow]{info['tool']}[/yellow]   access: "
                  f"{'[red]write[/red]' if info['access'] == 'write' else '[green]read[/green]'}")
    console.print(info["summary"])
    if info["notes"]:
        console.print(f"[dim]{info['notes']}[/dim]")
    table = Table(title="parameters")
    for col in ("name", "type", "required", "default", "flag", "description"):
        table.add_column(col)
    for p in info["parameters"]:
        table.add_row(p["name"], p["type"], "yes" if p["required"] else "",
                      str(p["default"] or ""),
                      "(positional)" if p["positional"] else str(p["flag"]),
                      p["description"])
    console.print(table)
    if info["doc_url"]:
        console.print(f"[dim]doc:[/dim] {info['doc_url']}")


@app.command("run", help="Assemble and run a utility. Dry-run by default; --yes for a real state-changing run.")
def run_cmd(
    name: str = typer.Argument(..., help="Utility name (see `list`)."),
    param: List[str] = typer.Option([], "--set", "-s", help="Parameter as KEY=VALUE (repeatable)."),
    arg: List[str] = typer.Option([], "--arg", "-a", help="Raw arg appended verbatim (repeatable; for options not in the catalog)."),
    dry_run: bool = typer.Option(True, "--dry-run/--execute",
                                 help="Assemble only (default), or actually run."),
    yes: bool = typer.Option(False, "--yes", help="Confirm a state-changing real run."),
    backend: Optional[str] = typer.Option(None, "--backend", help="Override backend: local|ssh|winrm|container."),
    config: Optional[Path] = typer.Option(None, "--config", help="Path to actone-utils.yaml."),
    as_json: bool = typer.Option(False, "--json"),
):
    cfg = _cfg(config, backend)
    values = _parse_params(param)
    try:
        result = run_utility(cfg, name, values, dry_run=dry_run, assume_yes=yes,
                             raw_args=list(arg))
    except RunGate as e:
        console.print(f"[yellow]gated:[/yellow] {e}")
        raise typer.Exit(2)
    except UtilityError as e:
        console.print(f"[red]error:[/red] {e}")
        raise typer.Exit(1)
    except RuntimeError as e:
        console.print(f"[red]backend error:[/red] {e}")
        raise typer.Exit(1)

    if as_json:
        console.print_json(data=result)
        return
    tag = "[blue]DRY-RUN[/blue]" if result["dry_run"] else (
        "[green]OK[/green]" if result["ok"] else "[red]FAILED[/red]")
    console.print(f"{tag}  {result['utility']} via [magenta]{result['backend']}[/magenta] "
                  f"-> {result['target']}")
    console.print(f"[dim]command:[/dim] {result['command']}")
    if result.get("remote_command"):
        console.print(f"[dim]remote:[/dim]  {result['remote_command']}")
    if not result["dry_run"]:
        console.print(f"[dim]exit:[/dim] {result['returncode']}")
        if result["stdout"]:
            console.print(result["stdout"])
        if result["stderr"]:
            console.print(f"[red]{result['stderr']}[/red]")


@app.command("backends", help="Show the available execution backends.")
def backends_cmd(config: Optional[Path] = typer.Option(None, "--config")):
    cfg = UtilsConfig.load(config)
    for name in ("local", "ssh", "winrm", "container"):
        cfg.backend = name
        b = make_backend(cfg)
        active = " [green](active)[/green]" if UtilsConfig.load(config).backend == name else ""
        console.print(f"[cyan]{name}[/cyan]{active}: {b.describe()}")


@app.command("doctor", help="Show the effective config: backend, paths, JDK, utilities.env.")
def doctor_cmd(config: Optional[Path] = typer.Option(None, "--config"),
               backend: Optional[str] = typer.Option(None, "--backend")):
    cfg = _cfg(config, backend)
    console.print_json(data=cfg.summary())


def main() -> None:
    app()


if __name__ == "__main__":
    main()
