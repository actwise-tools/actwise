# Actimize Installer (components/installer)

Install/upgrade Actimize packages behind a confirmation gate, and stand up ActOne core locally on Docker + PostgreSQL. Packages: `actinstaller`, `actone_local`. CLIs: `actimize-installer`, `actone-local`. MCP: none. Skill(s): `skills/actimize-installer`, `skills/actone-local`.

## Overview

This bucket is the **install-execution** end of the ActWise chain, complementing `ndc`
(downloads the package) and `docenter` (documentation). `actimize-installer` detects which
Actimize installer a downloaded package carries (`rcm-installer`, `Actimize-installer`, AIS
`setup.exe`), builds the exact command, and runs it **only behind a confirmation gate** with
captured logs — dry-run by default. `actone-local` automates the ActOne 10.2 local Docker
install (see [`../../docs/components/installer/2026-07-02-actone-10.2-local-docker-install-plan.md`](../../docs/components/installer/2026-07-02-actone-10.2-local-docker-install-plan.md)):
idempotent, disk-aware, laptop-friendly phases that build the image and stand up a lightweight
Postgres.

## Quick start

```powershell
uv tool install "git+ssh://git@github.com/vinayguda/actwise.git"   # puts both CLIs on PATH
actimize-installer detect --package packages/ActOne_10.2.0         # classify a package
actimize-installer run --package packages/ActOne_10.2.0 --command install   # dry-run first
actone-local doctor                            # preflight docker/disk/package/license
```

## CLI reference

Run `<cli> <command> --help` for flags.

| Command | Purpose |
|---------|---------|
| `actimize-installer detect` | Inspect a package: installer flavor, bin, and CONF files. |
| `actimize-installer show` | Run the installer's own read-only `show` command. |
| `actimize-installer run` | Build the install command (dry-run); `--execute` runs it behind a gate. |
| `actone-local doctor` / `config` | Preflight (docker/disk/package/WAR/license/image); show/scaffold config. |
| `actone-local extract` / `db-up` / `db-init` / `db-schema` | Extract WAR, start Postgres, create schema, populate DDL. |
| `actone-local render-config` / `encrypt-config` | Write `acm.ini`; AES-encrypt the DB password + IV. |
| `actone-local build` / `run` / `up` | Build the image (disk-guarded), run the container, or orchestrate all phases. |
| `actone-local status` / `verify` / `down` | Container status; wait for RCM to serve; stop/remove (`--purge` drops the DB volume). |

## MCP server

No MCP server in this bucket.

## Skill

Two skills. [`skills/actimize-installer/SKILL.md`](../../skills/actimize-installer/SKILL.md)
drives the gated installer runner (`detect → run --dry-run → run --execute`).
[`skills/actone-local/SKILL.md`](../../skills/actone-local/SKILL.md) drives the local Docker
stand-up (`doctor → extract/db-*/render/encrypt → build → run`). Teammates install via
`uv tool install "git+ssh://git@github.com/vinayguda/actwise.git"`. Trigger `actimize-installer`
to install/upgrade a downloaded package; trigger `actone-local` to run ActOne on a laptop for
dev/demo. Use `actimize-nicedl` to obtain the package and `actimize-docenter` for guides.

## Configuration

Config search order: `$ACTWISE_CONFIG_DIR` → cwd → `~/.actwise` → dev repo root.

| File / env var | Purpose | Location |
|----------------|---------|----------|
| `--package <dir\|zip>` | Package to detect/install (`--extract` for a zip) | cwd / `packages/` |
| `installer-runs/` | Timestamped install run logs | cwd (created on `--execute`) |
| `actone-local.yaml` (`actone-local config --init`) | Local build knobs (image, heap, ports, Postgres, SSL) | repo root |
| `packages/ActOne-10.2.0-inner.zip`, `packages/actone-local/license.lic` | ActOne payload + license | `packages/` (gitignored) |
| defaults in `actone_local/config.py` | `postgres:16-alpine`, `-Xmx2048m`, http port 8082, image `actone:10.2` | code |

## Auth

The installer runner needs no portal credentials — it operates on a **local package on disk**
(obtained via `ndc`). `actone-local` needs a valid NICE **`license.lic`** dropped at
`packages/actone-local/license.lic` for the `run` phase (DB/build phases work without it), and
encrypts the ActOne DB password into `acm.ini` via the bundled RCM Encryption Tool. **Never
commit** license files, `packages/`, or `installer-runs/` logs; installs are dry-run by default
and production CONF targets require explicit `--allow-prod`.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `No Actimize installer found` | Package not extracted, or it's docs — extract the archive / re-download. |
| `BLOCKED: ActOne … does NOT support upgrade` | Use `--command install` (or the Patch Installer for patches). |
| `BLOCKED: CONF references a production environment` | Confirm intent; re-run with `--allow-prod` only if truly prod. |
| `disk … below … build needs >= 6.0 GB` | Free space or run only the light `actone-local` phases (avoid `build`). |
| `RCM.war — not yet` / `package … not found` | Run `actone-local extract`; download/extract the payload via `ndc`. |
| RCM won't start (`acm_md_config_params`) / license gate | Run `db-schema` then `encrypt-config`; drop a valid `license.lic`. |

## Design docs & further reading

- [`../../docs/components/installer/2026-07-02-actone-10.2-local-docker-install-plan.md`](../../docs/components/installer/2026-07-02-actone-10.2-local-docker-install-plan.md)
- [`skills/actimize-installer/SKILL.md`](../../skills/actimize-installer/SKILL.md) · [`skills/actone-local/SKILL.md`](../../skills/actone-local/SKILL.md)
- [`../../docs/runbooks/2026-07-07-actwise-prod-promotion-plan.md`](../../docs/runbooks/2026-07-07-actwise-prod-promotion-plan.md)
