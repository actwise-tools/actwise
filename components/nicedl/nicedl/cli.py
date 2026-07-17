"""nicedl CLI — search & download NICE Actimize installation packages.

Modeled on the `docenter` CLI (Typer + Rich). Where docenter covers *documentation*,
`ndc` covers the *installation packages* consumed by the Actimize Installer.
"""
from __future__ import annotations

import hashlib
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

from . import portal as P
from . import keys as K
from . import catalog as C

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="NICE Download Center CLI — search & download Actimize installation packages "
         "(Flexera SubscribeNet). Complements `docenter` (documentation).",
)
auth_app = typer.Typer(help="Authenticate to the NICE Download Center.")
app.add_typer(auth_app, name="auth")
catalog_app = typer.Typer(help="Build/inspect the offline package catalog cache.")
app.add_typer(catalog_app, name="catalog")
console = Console()


def _portal() -> P.Portal:
    return P.Portal()


def _emit_json(obj) -> None:
    # Use builtin print (not rich) so wide JSON isn't reflowed/wrapped when piped.
    print(_json.dumps(obj, indent=2))


# ── auth ─────────────────────────────────────────────────────────────────────────
@auth_app.command("login")
def auth_login(
    email: str = typer.Option("", "--email", help="Override NDC_EMAIL from .env"),
    password: str = typer.Option("", "--password", help="Override NDC_PASSWORD from .env"),
):
    """Log in using credentials from .env (NDC_EMAIL / NDC_PASSWORD) or --email/--password."""
    portal = _portal()
    try:
        ok = portal.login(email, password)
    except P.AuthError as e:
        rprint(f"[red]{e}[/red]")
        raise typer.Exit(1)
    if ok:
        rprint(f"[green]Authenticated![/green] Session saved to [dim]{P.COOKIES_FILE}[/dim]")
    else:
        rprint("[red]Login failed.[/red] Check NDC_EMAIL / NDC_PASSWORD in .env.")
        raise typer.Exit(1)


@auth_app.command("status")
def auth_status():
    """Show whether the stored session is still valid."""
    portal = _portal()
    if not P.COOKIES_FILE.exists():
        rprint("[yellow]Not authenticated.[/yellow] Run: [bold]ndc auth login[/bold]")
        raise typer.Exit(1)
    if portal.is_authed():
        rprint(f"[green]Authenticated.[/green] [dim]{P.COOKIES_FILE}[/dim]")
    else:
        rprint("[yellow]Session expired.[/yellow] Run: [bold]ndc auth login[/bold]")
        raise typer.Exit(1)


@auth_app.command("logout")
def auth_logout():
    """Clear the stored session."""
    _portal().logout()
    rprint("[green]Logged out.[/green]")


# ── discovery ────────────────────────────────────────────────────────────────────
@app.command("products")
def products(json: bool = typer.Option(False, "--json")):
    """List curated product keys (friendly aliases for plne ids + components)."""
    prods = K.load_products()
    if json:
        _emit_json([K.product_dict(p) for p in prods]); return
    if not prods:
        rprint("[yellow]No product keys found[/yellow] (missing data/product-keys.yaml).")
        return
    t = Table(title="NDC — curated product keys")
    t.add_column("Key", style="cyan")
    t.add_column("Product", style="white", overflow="fold")
    t.add_column("plne", style="dim")
    t.add_column("Aliases", style="dim", overflow="fold")
    for p in prods:
        t.add_row(p.key, p.name, p.plne, ", ".join(p.aliases))
    console.print(t)
    rprint("[dim]Use: ndc search --product <key>   (e.g. ndc search --product actone --version 10.2)[/dim]")


# ── catalog cache ─────────────────────────────────────────────────────────────────
@catalog_app.command("refresh")
def catalog_refresh(
    product: str = typer.Option("", "--product", "-p", help="Refresh only this product key (default: all)"),
):
    """Sweep the portal and (re)build the offline catalog cache."""
    portal = _portal()
    keys = None
    if product:
        prod = K.resolve(product)
        if prod is None:
            rprint(f"[red]Unknown product key '{product}'.[/red] Run: [bold]ndc products[/bold]")
            raise typer.Exit(1)
        keys = [prod.key]
    rprint("[cyan]Refreshing catalog[/cyan] (live portal sweep)...")
    try:
        data = C.build(portal, keys, log=lambda m: console.print(m, style="dim"))
    except P.AuthError as e:
        rprint(f"[red]{e}[/red]"); raise typer.Exit(1)
    if keys:  # merge into any existing cache so we don't drop other products
        existing = C.load() or {"products": {}}
        existing.setdefault("products", {}).update(data["products"])
        existing["refreshed_at"] = data["refreshed_at"]
        existing["source"] = data["source"]
        existing["product_count"] = len(existing["products"])
        existing["release_count"] = sum(len(v.get("releases", [])) for v in existing["products"].values())
        data = existing
    path = C.save(data)
    rprint(f"[green]Catalog saved[/green] → [dim]{path}[/dim]  "
           f"({data['product_count']} products, {data['release_count']} releases)")


@catalog_app.command("status")
def catalog_status(json: bool = typer.Option(False, "--json")):
    """Show catalog freshness and per-product release counts."""
    data = C.load()
    if not data:
        rprint("[yellow]No catalog cache.[/yellow] Run: [bold]ndc catalog refresh[/bold]")
        raise typer.Exit(1)
    if json:
        _emit_json({k: len(v.get("releases", [])) for k, v in data.get("products", {}).items()}); return
    rprint(f"[green]Catalog[/green] [dim]{C.CATALOG_FILE}[/dim]")
    rprint(f"refreshed_at: [cyan]{data.get('refreshed_at')}[/cyan]   "
           f"products: {data.get('product_count')}   releases: {data.get('release_count')}")
    t = Table(title="Catalog — releases per product")
    t.add_column("Key", style="cyan"); t.add_column("Product", overflow="fold")
    t.add_column("plne", style="dim"); t.add_column("Releases", justify="right", style="green")
    for key, v in data.get("products", {}).items():
        t.add_row(key, v.get("name", ""), v.get("plne", ""), str(len(v.get("releases", []))))
    console.print(t)


@app.command("find")
def find(
    product: str = typer.Argument(..., help="Product key or alias (see `ndc products`), e.g. actone"),
    version: str = typer.Argument("", help="Version substring, e.g. 10.2"),
    variant: str = typer.Option("", "--variant", help="Full | SP | Patch"),
    online: bool = typer.Option(False, "--online", help="Query the live portal instead of the cache"),
    json: bool = typer.Option(False, "--json"),
):
    """Locate a package by product + version — e.g. `ndc find actone 10.2`.

    Answers from the offline catalog cache (fast/offline); use --online to hit
    the live portal, or run `ndc catalog refresh` to (re)build the cache.
    """
    prod = K.resolve(product)
    if prod is None:
        rprint(f"[red]Unknown product '{product}'.[/red] Run: [bold]ndc products[/bold]")
        raise typer.Exit(1)

    rows: list[dict] = []
    source = "cache"
    data = None if online else C.load()
    if data is not None and prod.key in data.get("products", {}):
        rows = C.find(data, prod.key, version, variant)
    else:
        # Fall back to a live search (no cache, or --online, or product not cached yet).
        source = "live"
        portal = _portal()
        try:
            rels = portal.search(f"{prod.search} {version}".strip() if version else prod.search)
        except P.AuthError as e:
            rprint(f"[red]{e}[/red]"); raise typer.Exit(1)
        rels = [r for r in rels if (not prod.plne or r.plne == prod.plne) and prod.title_matches(r.title)]
        if version:
            rels = [r for r in rels if version in r.version]
        if variant:
            rels = [r for r in rels if r.variant.lower() == variant.lower()]
        rows = [P.release_dict(r) for r in sorted(rels, key=lambda r: C.version_key(r.version), reverse=True)]

    if json:
        _emit_json(rows); return
    if not rows:
        hint = "" if online else " (try `ndc catalog refresh`, or add --online)"
        rprint(f"[yellow]No match for {prod.key} {version}[/yellow]{hint}.")
        raise typer.Exit(1)

    t = Table(title=f"ndc find: {prod.name}  [{source}]")
    t.add_column("Release", style="cyan", overflow="fold")
    t.add_column("Ver", style="green"); t.add_column("Type", style="magenta")
    t.add_column("element", style="yellow"); t.add_column("plne", style="dim")
    for r in rows:
        t.add_row(r.get("title", ""), r.get("version", ""), r.get("variant", ""),
                  r.get("element", ""), r.get("plne", ""))
    console.print(t)
    top = rows[0]
    rprint(f"[dim]Download the top match:[/dim] "
           f"[bold]ndc download {top.get('element')} --plne {top.get('plne')} --dest packages[/bold]")


@app.command("product-lines")
def product_lines(json: bool = typer.Option(False, "--json")):
    """List product lines (manufacturers) available on the portal."""
    portal = _portal()
    try:
        lines = portal.product_lines()
    except P.AuthError as e:
        rprint(f"[red]{e}[/red]"); raise typer.Exit(1)
    if json:
        _emit_json(lines); return
    t = Table(title="NICE Download Center — product lines")
    t.add_column("Name", style="cyan"); t.add_column("manu", style="dim")
    for l in lines:
        t.add_row(l["name"], l["manu"])
    console.print(t)


@app.command("search")
def search(
    query: str = typer.Argument("", help="e.g. 'ActOne', 'AIS', 'SAM 10.2' (optional if --product given)"),
    product: str = typer.Option("", "--product", "-p", help="Curated product key (see `ndc products`), e.g. actone"),
    variant: str = typer.Option("", "--variant", help="Filter: Full | SP | Patch"),
    version: str = typer.Option("", "--version", help="Filter by version substring, e.g. 6.0"),
    max: int = typer.Option(40, "--max", help="Max rows"),
    json: bool = typer.Option(False, "--json"),
):
    """Search product releases. Returns element/plne ids for `list-files` / `download`.

    Pass a curated key with --product (see `ndc products`) to auto-scope the
    search to one component's plne and title pattern.
    """
    prod: Optional[K.Product] = None
    if product:
        prod = K.resolve(product)
        if prod is None:
            rprint(f"[red]Unknown product key '{product}'.[/red] Run: [bold]ndc products[/bold]")
            raise typer.Exit(1)
    if not query:
        if prod is None:
            rprint("[red]Provide a search query or --product <key>.[/red]"); raise typer.Exit(1)
        # Fold the version into the portal query so specific releases surface
        # (the portal ranks/caps results, so a bare product term can miss them).
        query = f"{prod.search} {version}".strip() if version else prod.search
    portal = _portal()
    try:
        rels = portal.search(query)
    except P.AuthError as e:
        rprint(f"[red]{e}[/red]"); raise typer.Exit(1)
    if prod is not None:
        rels = [r for r in rels if (not prod.plne or r.plne == prod.plne) and prod.title_matches(r.title)]
    if variant:
        rels = [r for r in rels if r.variant.lower() == variant.lower()]
    if version:
        rels = [r for r in rels if version in r.version]
    rels = rels[:max]
    if json:
        _emit_json([P.release_dict(r) for r in rels]); return
    if not rels:
        rprint("[yellow]No releases found.[/yellow] Try a broader query."); return
    title = f"NDC search: {prod.name}" if prod else f"NDC search: {query}"
    t = Table(title=title)
    t.add_column("Release", style="cyan", overflow="fold")
    t.add_column("Ver", style="green"); t.add_column("Type", style="magenta")
    t.add_column("element", style="yellow"); t.add_column("plne", style="dim")
    for r in rels:
        t.add_row(r.title, r.version, r.variant, r.element, r.plne)
    console.print(t)
    rprint("[dim]Next: ndc list-files <element> --plne <plne>[/dim]")


@app.command("recent")
def recent(json: bool = typer.Option(False, "--json")):
    """List recent product releases posted to the portal."""
    portal = _portal()
    try:
        rels = portal.recent()
    except P.AuthError as e:
        rprint(f"[red]{e}[/red]"); raise typer.Exit(1)
    if json:
        _emit_json([P.release_dict(r) for r in rels]); return
    t = Table(title="NDC — recent product releases")
    t.add_column("Release", style="cyan", overflow="fold")
    t.add_column("Ver", style="green"); t.add_column("Type", style="magenta")
    t.add_column("element", style="yellow")
    for r in rels:
        t.add_row(r.title, r.version, r.variant, r.element)
    console.print(t)


@app.command("list-files")
def list_files(
    element: str = typer.Argument(..., help="Release element id (from `search`)"),
    plne: str = typer.Option("", "--plne", help="Product-line id (from `search`)"),
    cert_num: str = typer.Option("", "--cert-num", help="Optional cert_num from `search`"),
    json: bool = typer.Option(False, "--json"),
):
    """List the downloadable files in a release (filename, size, MD5)."""
    portal = _portal()
    try:
        files = portal.list_files(element, plne, cert_num)
    except P.AuthError as e:
        rprint(f"[red]{e}[/red]"); raise typer.Exit(1)
    if json:
        _emit_json([P.file_dict(f) for f in files]); return
    if not files:
        rprint("[yellow]No files found[/yellow] (check element/plne, or download limit reached).")
        return
    t = Table(title=f"Files in release element={element}")
    t.add_column("Filename", style="cyan", overflow="fold")
    t.add_column("Size", style="green"); t.add_column("MD5", style="dim")
    for f in files:
        t.add_row(f.filename, f.size, f.md5)
    console.print(t)
    rprint("[dim]Next: ndc download <element> --plne <plne> [--match GLOB][/dim]")


@app.command("download")
def download(
    element: str = typer.Argument(..., help="Release element id (from `search`)"),
    plne: str = typer.Option("", "--plne", help="Product-line id (from `search`)"),
    cert_num: str = typer.Option("", "--cert-num", help="Optional cert_num from `search`"),
    dest: Path = typer.Option(Path("packages"), "--dest", help="Destination directory"),
    match: str = typer.Option("", "--match", help="Only files whose name contains this substring"),
    dry_run: bool = typer.Option(False, "--dry-run", help="List what would be downloaded"),
    no_verify: bool = typer.Option(False, "--no-verify", help="Skip MD5 verification"),
):
    """Download the installation package files for a release (with MD5 verification)."""
    portal = _portal()
    try:
        files = portal.list_files(element, plne, cert_num)
    except P.AuthError as e:
        rprint(f"[red]{e}[/red]"); raise typer.Exit(1)
    if match:
        files = [f for f in files if match.lower() in f.filename.lower()]
    if not files:
        rprint("[yellow]Nothing to download[/yellow] (no matching files)."); return

    for f in files:
        if dry_run:
            rprint(f"[dim]would download[/dim] {f.filename} ({f.size or '?'})")
            continue
        rprint(f"[cyan]Downloading[/cyan] {f.filename} ({f.size or '?'})...")
        try:
            path = portal.download_file(f, dest)
        except Exception as e:
            rprint(f"  [red]failed:[/red] {e}"); continue
        if not no_verify and f.md5:
            got = hashlib.md5(path.read_bytes()).hexdigest()
            if got.lower() == f.md5.lower():
                rprint(f"  [green]saved[/green] {path}  [dim]MD5 ok[/dim]")
            else:
                rprint(f"  [red]MD5 MISMATCH[/red] {path} (expected {f.md5}, got {got})")
        else:
            rprint(f"  [green]saved[/green] {path}")
    if dry_run:
        rprint(f"[dim]{len(files)} file(s) — dry run, nothing downloaded.[/dim]")


if __name__ == "__main__":
    app()
