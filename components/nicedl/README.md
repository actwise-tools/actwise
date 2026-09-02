# NICE Download Center (components/nicedl)

Search and download official NICE Actimize product installation packages (installers, service packs, patches) from the NICE Download Center. Packages: `nicedl`. CLIs: `ndc`. MCP: none. Skill(s): `skills/actimize-nicedl`.

## Overview

nicedl is component **C-P (Install Packages)** in the
[ecosystem blueprint](../../docs/2026-06-25-actwise-ecosystem-blueprint.md). The `ndc` CLI
wraps the NICE Software Download Center (`nice.subscribenet.com`, a Flexera SubscribeNet
portal): it lists product lines, searches releases, drills into a release's files, and
downloads them with **MD5 verification** (using the OS trust store via `truststore` for
corporate TLS interception). It is the install-package counterpart to `docenter`
(documentation) and feeds the artifacts consumed by the **Actimize Installer** and
`actone-local`. Friendly product keys resolve the portal's opaque `plne` ids.

## Quick start

```powershell
uv tool install "git+ssh://git@github.com/vinayguda/actwise.git"   # puts ndc on PATH
ndc auth login                                 # uses NDC_EMAIL / NDC_PASSWORD from .env
ndc find actone 10.2 --variant Full            # locate a package (offline catalog cache)
ndc download <element> --plne <plne> --dest packages   # MD5-verified download
```

## CLI reference

Run `ndc <command> --help` for flags.

| Command | Purpose |
|---------|---------|
| `products` | List curated product keys (friendly aliases for `plne` ids + components). |
| `find` | Locate a package by product + version — e.g. `ndc find actone 10.2`. |
| `product-lines` | List product lines (manufacturers) on the portal. |
| `search` | Search product releases; returns `element`/`plne` ids for `list-files`/`download`. |
| `recent` | List recently posted releases. |
| `list-files` | List a release's downloadable files (filename, size, MD5). |
| `download` | Download a release's files, MD5-verified. |
| `auth` | Authenticate to the NICE Download Center. |
| `catalog` | Build/inspect the offline package catalog cache. |

## MCP server

No MCP server in this bucket. (A `nicedl_mcp` layer — `search_packages` / `list_package_files`
/ `recent_releases` + gated `download_package` — is proposed in the blueprint.)

## Skill

[`skills/actimize-nicedl/SKILL.md`](../../skills/actimize-nicedl/SKILL.md) drives the `ndc`
CLI: the `auth → find/search → list-files → download` flow with curated product keys.
Teammates install via `uv tool install "git+ssh://git@github.com/vinayguda/actwise.git"`. An
agent triggers it when the user wants an **installer / service pack / patch** for an Actimize
product/version, or to see available package versions — pairing naturally with
`actimize-docenter` (the matching install guide). For docs, use `actimize-docenter`.

## Configuration

Config search order: `$ACTWISE_CONFIG_DIR` → cwd → `~/.actwise` → dev repo root.

| File / env var | Purpose | Location |
|----------------|---------|----------|
| `.env` (`NDC_PORTAL_URL`, `NDC_EMAIL`, `NDC_PASSWORD`) | Portal URL + SubscribeNet credentials | repo root (see `.env.example`) |
| offline catalog cache | Product → releases metadata (no signed URLs) | built by `ndc catalog refresh` |
| `--dest` (default `packages/`) | Download destination | cwd (gitignored) |

## Auth

`ndc auth login` performs a form-POST login using `NDC_EMAIL` / `NDC_PASSWORD` from `.env`
(or `--email`/`--password`), storing a session for subsequent commands. Corporate TLS
interception is handled via the OS trust store (`truststore`). **Never commit** `.env` or the
`packages/` downloads; rotate the SubscribeNet password in the portal and re-run `ndc auth
login`.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `Session expired. Run: ndc auth login` | Run `ndc auth login`. |
| `Login failed` | Check `NDC_EMAIL` / `NDC_PASSWORD` in `.env`. |
| TLS / certificate error | Ensure `truststore` is installed (uses the OS trust store for TLS interception). |
| No files found for a release | Verify `element`/`plne` from `search`; download limit reached or missing entitlement. |
| Stale / missing results from `find` | Run `ndc catalog refresh` (or add `--online` to hit the live portal). |
| `ndc: command not found` | `uv tool install "git+ssh://git@github.com/vinayguda/actwise.git"`. |

## Design docs & further reading

- [`../../docs/components/nicedl/nice-download-center.md`](../../docs/components/nicedl/nice-download-center.md) — portal reference
- [`../../docs/components/nicedl/2026-07-02-nice-download-center-blueprint.md`](../../docs/components/nicedl/2026-07-02-nice-download-center-blueprint.md) — AI-wrap blueprint (incl. proposed MCP)
- [`skills/actimize-nicedl/SKILL.md`](../../skills/actimize-nicedl/SKILL.md)
