# ActOne Local

> Stand up ActOne core (10.2) on your own laptop with Docker + PostgreSQL using the idempotent, disk-aware `actone-local` CLI.

## Goal
Getting a working ActOne environment for dev or demo normally means a heavyweight, multi-step install. This skill teaches an AI agent to build the ActOne image from a downloaded package and bring up a lightweight local stack — Postgres, schema, config, container — as a set of safe-to-re-run phases tuned for a low-resource laptop, with the expensive image build guarded behind a disk check.

## How it fits
This skill drives the `actone-local` CLI, which lives in the **installer** bucket alongside `actimize-installer`. It is the "run-it-locally" step of the ActWise chain: **actimize-nicedl** downloads the ActOne package, **actimize-installer** drives the product's own installer, **actimize-docenter** covers the docs, and this skill stands the product up in Docker.

## When to use it
Activate when the user wants to:
- **Spin up ActOne core locally** for dev/demo (Docker image + Postgres).
- **Preflight** their machine for an ActOne build (docker, disk headroom, package, license).
- Run **individual phases** (extract WAR, start DB, init schema, render config, build, run).

Do not use it to download packages (**actimize-nicedl**), drive the shipped product installer (**actimize-installer**), or answer documentation questions (**actimize-docenter**).

## What it does
- Preflights the machine with `actone-local doctor` (docker, disk vs the 6 GB build line, package, WAR, license, image).
- Runs the light phases: `extract` (RCM.war + Docker tree), `db-up` (postgres:16-alpine), `db-init` (schema + search_path), `db-schema` (600+ ActOne tables via `dbupgrade`), `render-config` (acm.ini), `encrypt-config` (AES-encrypt the DB password).
- Builds the ActOne image (`build`, disk-guarded; `--force` to override) and runs the container (`run`, needs `license.lic`).
- Orchestrates end-to-end with `up [--skip-build] [--force]`, checks `status`, and tears down with `down [--purge]`.
- Every phase is idempotent; config knobs live in `actone-local.yaml` (`config --init`).

## Install / enable
Skills follow the open Agent Skills spec and install via the `skills` CLI:
```powershell
npx skills add https://github.com/vinayguda/actwise.git --skill actone-local -a claude-code -g
```
Skills are instructions only — they drive the ActWise CLIs, so install the `actwise` distribution too. This skill requires the **`actone-local`** console script, Docker Desktop, the ActOne 10.2 payload on disk, and (for `run`) a valid `license.lic`.

## Walkthrough
- *"Is my machine ready to build ActOne locally?"* → `actone-local doctor` reports each prerequisite as OK/XX.
- *"Bring up ActOne's DB and config but skip the heavy build."* → `actone-local up --skip-build` runs the safe phases (well under 1 GB).
- *"Run the full ActOne container."* → after `build`, `actone-local run` then `actone-local status`; ActOne serves on host port 8082.

## Limits & safety
- The image build **refuses to run below ~6 GB free** unless `--force`; the skill should prefer the light phases on a constrained laptop and ask the user to free space.
- The container `run` phase needs a valid NICE `license.lic` at `packages/actone-local/license.lic`; DB and build phases work without it.
- `render-config` writes a plaintext DB password, so `encrypt-config` must run before `run` (ActOne always decrypts the repository password at startup). `down --purge` deletes the Postgres data volume.

## See also
- CLI: [../cli/actone-local.md](../cli/actone-local.md)
- Bucket: [../buckets/installer.md](../buckets/installer.md)
- Related skills: [actimize-nicedl](actimize-nicedl.md), [actimize-installer](actimize-installer.md), [actone-ops](actone-ops.md)
