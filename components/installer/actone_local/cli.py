"""actone-local — stand up ActOne core locally (Docker + PostgreSQL).

The repeatable, idempotent runner behind the ActOne local-setup plan
(``docs/components/installer/2026-07-02-actone-10.2-local-docker-install-plan.md``). Every phase is a
subcommand and safe to re-run; ``up`` chains them. Defaults target a
low-resource laptop (alpine Postgres, trimmed JVM heap, no SSL). The heavy
``build`` phase is disk-guarded.

Chain:  ndc (package) -> actone-local extract -> db-up -> db-init ->
        db-schema -> render-config -> encrypt-config -> build -> run
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

import typer
from rich import print as rprint
from rich.console import Console

from .config import Config, DEFAULT_CONFIG_PATH
from . import steps as S

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Stand up ActOne core locally (Docker + PostgreSQL). Idempotent, "
         "disk-aware, laptop-friendly. Complements ndc (packages) and "
         "actimize-installer (DB tasks).",
)
console = Console()


def _cfg(config: Optional[Path]) -> Config:
    return Config.load(config)


def _report(steps: list[S.Step]) -> None:
    for st in steps:
        rprint(st.line())
    if any(not s.ok for s in steps):
        raise typer.Exit(1)


CONFIG_OPT = typer.Option(None, "--config", "-c", help="Path to actone-local.yaml (else defaults)")


@app.command("doctor")
def doctor_cmd(config: Optional[Path] = CONFIG_OPT):
    """Preflight: docker, disk headroom, package, WAR, license, image."""
    rprint("[bold]ActOne local — preflight[/bold]")
    _report(S.doctor(_cfg(config)))


@app.command("config")
def config_cmd(config: Optional[Path] = CONFIG_OPT,
               init: bool = typer.Option(False, "--init", help="Write a default actone-local.yaml")):
    """Show the effective config (or --init to scaffold one)."""
    cfg = _cfg(config)
    if init:
        DEFAULT_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        DEFAULT_CONFIG_PATH.write_text(cfg.dump(), encoding="utf-8")
        rprint(f"[green]wrote[/green] {DEFAULT_CONFIG_PATH}")
        return
    console.print(cfg.dump())


@app.command("extract")
def extract_cmd(config: Optional[Path] = CONFIG_OPT):
    """Extract only the lean build inputs (RCM.war + Docker/) from the payload."""
    _report([S.extract(_cfg(config))])


@app.command("db-up")
def db_up_cmd(config: Optional[Path] = CONFIG_OPT):
    """Start the lightweight PostgreSQL container (postgres:16-alpine)."""
    _report([S.db_up(_cfg(config))])


@app.command("db-init")
def db_init_cmd(config: Optional[Path] = CONFIG_OPT):
    """Create the ActOne schema (lower-case) + search_path."""
    _report([S.db_init(_cfg(config))])


@app.command("db-schema")
def db_schema_cmd(config: Optional[Path] = CONFIG_OPT):
    """Populate the ActOne DDL + seed data (dbupgrade -exec -new). Takes a few minutes."""
    _report([S.db_schema(_cfg(config))])


@app.command("render-config")
def render_cmd(config: Optional[Path] = CONFIG_OPT):
    """Write acm.ini (PostgreSQL, plaintext password) into the work dir."""
    _report([S.render_config(_cfg(config))])


@app.command("encrypt-config")
def encrypt_cmd(config: Optional[Path] = CONFIG_OPT):
    """Encrypt the DB password (bundled tool) and rewrite acm.ini with the IV."""
    _report([S.encrypt_config(_cfg(config))])


@app.command("build")
def build_cmd(config: Optional[Path] = CONFIG_OPT,
              force: bool = typer.Option(False, "--force", help="Build even if disk is below the safety line")):
    """Build the ActOne Docker image (disk-guarded)."""
    _report([S.build(_cfg(config), force=force)])


@app.command("run")
def run_cmd(config: Optional[Path] = CONFIG_OPT):
    """Run the ActOne container (needs a license.lic)."""
    _report([S.run_container(_cfg(config))])


@app.command("status")
def status_cmd(config: Optional[Path] = CONFIG_OPT):
    """Show ActOne + DB container status."""
    console.print(S.status(_cfg(config)))


@app.command("verify")
def verify_cmd(config: Optional[Path] = CONFIG_OPT,
               timeout: int = typer.Option(180, "--timeout", help="Seconds to wait for RCM to serve")):
    """Wait until the RCM webapp actually serves (login redirect) — not just 'container started'."""
    _report([S.verify(_cfg(config), timeout=timeout)])


@app.command("down")
def down_cmd(config: Optional[Path] = CONFIG_OPT,
             purge: bool = typer.Option(False, "--purge", help="Also delete the Postgres data volume")):
    """Stop & remove the containers (keep the DB volume unless --purge)."""
    _report(S.down(_cfg(config), purge=purge))


@app.command("up")
def up_cmd(config: Optional[Path] = CONFIG_OPT,
           force: bool = typer.Option(False, "--force", help="Override the build disk guard"),
           skip_build: bool = typer.Option(False, "--skip-build", help="Stop before build/run (safe phases only)")):
    """Orchestrate all phases end-to-end (each idempotent)."""
    cfg = _cfg(config)
    rprint("[bold]== ActOne local — up ==[/bold]")
    doc = S.doctor(cfg)
    for st in doc:
        rprint(st.line())
    results = [S.extract(cfg), S.db_up(cfg), S.db_init(cfg), S.db_schema(cfg),
               S.render_config(cfg), S.encrypt_config(cfg)]
    for st in results:
        rprint(st.line())
    if skip_build:
        rprint("[yellow]-- stopping before build (--skip-build) --[/yellow]")
        raise typer.Exit(0 if all(s.ok for s in results) else 1)
    b = S.build(cfg, force=force)
    rprint(b.line())
    if not b.ok:
        raise typer.Exit(1)
    r = S.run_container(cfg)
    rprint(r.line())
    if not r.ok:
        raise typer.Exit(1)
    v = S.verify(cfg)
    rprint(v.line())
    raise typer.Exit(0 if v.ok else 1)
