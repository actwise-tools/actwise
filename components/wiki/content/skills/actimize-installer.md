# Actimize Installer

> Install NICE Actimize product packages from disk by driving the gated `actimize-installer` CLI — dry-run by default, execution behind a confirmation gate.

## Goal
Once an install package is on disk, someone still has to run the right Actimize installer with the right command and options — and doing that by hand is error-prone and risky against a real environment. This skill teaches an AI agent to detect which installer a package carries, build the exact command, show it as a dry-run, and only execute behind an explicit confirmation gate with captured logs.

## How it fits
This skill drives the `actimize-installer` CLI in the **installer** bucket — the install-execution step of the ActWise chain. It sits downstream of **actimize-nicedl** (which downloads the package) and pairs with **actimize-docenter** (which supplies the matching installation guide). For running ActOne locally in Docker instead, use **actone-local**.

## When to use it
Activate when the user wants to:
- **Install or upgrade** an Actimize product/solution from a package already downloaded with `ndc`.
- **Inspect** what installer a package uses, its CONF files, or the tasks/steps it will run.
- **Dry-run** an install to see the exact command before executing.

Do not use it to download packages (use **actimize-nicedl**) or answer documentation questions (use **actimize-docenter**).

## What it does
- Classifies a package (safe, read-only) with `actimize-installer detect --package <dir|zip>`, auto-detecting the installer kind: `actone` (`rcm-installer`), `generic` (`Actimize-installer`), or `ais-modeler` (`setup.exe`).
- Runs the installer's own read-only `show` (e.g. effective CONF properties).
- Builds the install command as a **dry-run** (`actimize-installer run --package … --command install`), surfacing blockers.
- Executes only with `--execute` behind a confirmation prompt (`--yes` for automation), teeing all output to a timestamped log under `installer-runs/`.
- Supports patch/service-pack ranges (`--command upgrade --from … --to …`) and AIS Visual Modeler (`--mode full --features … --target-path …`).

## Install / enable
Skills follow the open Agent Skills spec and install via the `skills` CLI:
```powershell
npx skills add https://github.com/vinayguda/actwise.git --skill actimize-installer -a claude-code -g
```
Skills are instructions only — they drive the ActWise CLIs, so install the `actwise` distribution too. This skill requires the **`actimize-installer`** console script and an extracted package on disk.

## Walkthrough
- *"What installer does this ActOne package use?"* → `actimize-installer detect --package packages/ActOne_10.2.0`.
- *"Show me the install command before running it."* → `actimize-installer run --package packages/ActOne_10.2.0 --command install` (dry-run output).
- *"OK, install it."* → after confirmation, append `--execute`; output is teed to `installer-runs/`.

## Limits & safety
- `run` is **dry-run by default** — nothing touches the system without `--execute`.
- ActOne does **not** support `upgrade` — use `--command install` (or the Patch Installer for patches).
- A **production CONF guard** blocks installs targeting a prod host unless `--allow-prod` is explicitly passed; the skill must never bypass this without the user's confirmation.
- Missing/unpopulated CONF files block an install. After a run, point the user at both the run log and `Installer/logs/installation.log`.

## See also
- CLI: [../cli/actimize-installer.md](../cli/actimize-installer.md)
- Bucket: [../buckets/installer.md](../buckets/installer.md)
- Related skills: [actimize-nicedl](actimize-nicedl.md), [actone-local](actone-local.md), [actimize-docenter](actimize-docenter.md)
