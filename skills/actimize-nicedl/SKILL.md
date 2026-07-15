---
name: actimize-nicedl
description: Search and download NICE Actimize product installation packages (installers, service packs, patches) via the `ndc` CLI over the NICE Download Center (nice.subscribenet.com, Flexera SubscribeNet). Use when the user wants to find or download an install package / installer / patch / service pack for an Actimize product or solution version (ActOne, AIS, SAM, CDD, IFM, connectors) — i.e. the artifacts consumed by the Actimize Installer. For product *documentation* use actimize-docenter instead.
---

# Actimize NICE Download Center Skill

This skill finds and downloads official NICE Actimize **installation packages** using the `ndc`
CLI, which drives the NICE Software Download Center (`nice.subscribenet.com`, a Flexera
SubscribeNet portal). These are the installers / service packs / patches that the **Actimize
Installer** uses to install and upgrade products and solutions.

It is the **install-package counterpart** to the `actimize-docenter` skill (which covers
*documentation*). Rule of thumb:
- "How do I install/configure X?" → **actimize-docenter** (docs).
- "Get me the installer / patch / package for X version Y" → **this skill** (packages).

## When to use

Activate when the user wants to:
- Find or download an **installer, service pack, or patch** for an Actimize product/version.
- Know **which package versions** are available for a product (ActOne, AIS, SAM, CDD, IFM, WL-X,
  Productivity Studio, connectors, etc.).
- Fetch the exact artifact to feed the **Actimize Installer** for an install/upgrade.
- See **recently posted** releases or files on the download center.

## CLI commands

```
# Authentication (form-POST login using NDC_EMAIL / NDC_PASSWORD from .env)
ndc auth login | status | logout

# Discover
ndc products [--json]
ndc product-lines [--json]
ndc search "<query>" [--product <key>] [--variant Full|SP|Patch] [--version <v>] [--max N] [--json]
ndc recent [--json]

# Locate a package by product + version (preferred entry point)
ndc find <product> [version] [--variant Full|SP|Patch] [--online] [--json]

# Offline catalog cache (metadata: product -> releases; no signed URLs)
ndc catalog refresh [--product <key>]      # sweep the portal, (re)build the cache
ndc catalog status [--json]                # freshness + per-product release counts

# Drill into a release and download
ndc list-files <element> --plne <plne> [--json]
ndc download <element> --plne <plne> [--dest DIR] [--match SUBSTR] [--dry-run] [--no-verify]
```

Add `--json` to `products`, `find`, `search`, `recent`, `product-lines`, `list-files`, and `catalog status` for machine-readable output.

**Preferred flow — `ndc find`.** When the user says *"I want ActOne 10.2"* (or SAM/CDD/AIS/IFM/STAR
etc.), run `ndc find <product> <version>`. It answers from the **offline catalog cache** (fast, no
login) and prints the matching releases plus the exact `ndc download …` command. If the cache is
missing/stale, run `ndc catalog refresh` first (or add `--online` to hit the live portal). Example:
`ndc find actone 10.2 --variant Full`.

**Friendly product keys.** The portal groups many components under one opaque `plne` id (e.g. ActOne,
Risk Insights, QAS, Visual Analytics all share `plne=792217`). Use `ndc products` to list curated
keys, then `ndc find <key> <version>` or `ndc search --product <key>` to auto-scope. Keys span the
platform (`actone`, `actone-ws`, `actone-df`, `risk-insights`, `productivity-studio`, `va-server`,
`va-designer`, `qas`, `jreport`, `ais`, `udm`, `rcm`, `cs-actone-connector`), AML (`sam`, `sam-sim`,
`cdd`, `wlf`, `wlx`, `star`), fraud (`ifm`) and markets (`svx`) — plus aliases (`actone-mr`, `vas`…).

## Instructions

### 1. Check auth first
```
ndc auth status
```
If it reports "expired" or "not authenticated", run `ndc auth login` (uses `NDC_EMAIL` /
`NDC_PASSWORD` from `.env`) before continuing.

### 2. Search for the release
```
ndc search --product actone --version 10.2      # curated key auto-scopes plne + component
ndc search --product risk-insights              # same plne (792217), isolated by title match
ndc search "ActOne Risk Insights" --version 6.0 # free-text still works
ndc search "AIS" --variant Full
ndc search "SAM 10.2"
```
Prefer `--product <key>` (see `ndc products`) when the user names a known product — it resolves the
`plne` and filters to that one component. Search returns each release with its **`element`** id,
**`plne`** (product-line) id, version, and **variant** (Full / SP / Patch). Note the `element` and
`plne` — you need both for the next steps.
Tips: search by product name; narrow with `--version` and `--variant` rather than long queries.

### 3. List the files in the release
```
ndc list-files <element> --plne <plne>
```
Shows each file's **name, size, and MD5**. Use this to confirm you have the right artifact
(e.g. the OS/DB-specific package) before downloading.

### 4. Download (with MD5 verification)
```
ndc download <element> --plne <plne> --dest packages            # all files
ndc download <element> --plne <plne> --match linux --dest packages   # only matching files
ndc download <element> --plne <plne> --dry-run                  # preview, download nothing
```
Files download to `--dest` (default `packages/`, gitignored) and are **MD5-verified** against the
portal's signature. Report the saved path(s) and hand the package to the Actimize Installer.

### 5. Answer format
1. **Direct answer** — the package(s) found and their versions/variants.
2. **Details** — filenames, sizes, MD5, and the `element`/`plne` used.
3. **Next step** — the exact `ndc download …` command, or confirmation the file was saved.

## Pairing with docs

For install *instructions* to go with a package, use `actimize-docenter` (e.g.
`docenter search "ActOne installation guide"`). A complete answer often pairs the **package**
(this skill) with the matching **installation guide** (docenter).

## Installation & invocation

This skill drives the `ndc` CLI (from the private `actwise` repo). Prefer `ndc <command>`
when on PATH. If not installed, run via uv:

```bash
uv tool install "git+ssh://git@github.com/vinayguda/actwise.git"   # puts `ndc` on PATH
# or ad-hoc:
uvx --from "git+ssh://git@github.com/vinayguda/actwise.git" ndc <command> [args]
```

Requires `NDC_EMAIL` / `NDC_PASSWORD` in `.env` (or `--email`/`--password` on `ndc auth login`).

## Error handling

| Symptom | Action |
|---------|--------|
| `Session expired. Run: ndc auth login` | Run `ndc auth login` |
| `Login failed` | Check `NDC_EMAIL` / `NDC_PASSWORD` in `.env` |
| TLS / certificate error | The CLI uses `truststore` (OS trust store) for corporate TLS interception; ensure `truststore` is installed |
| No files found for a release | Verify `element`/`plne` from `search`; the file's download limit may be reached, or you may lack entitlement |
| `ndc: command not found` | Install via uv (see above) |
