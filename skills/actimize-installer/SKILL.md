---
name: actimize-installer
description: Install NICE Actimize product packages downloaded from the NICE Download Center, using the gated `actimize-installer` CLI runner. Use when the user wants to install/upgrade an Actimize product or solution from a package on disk (ActOne, AIS, SAM, CDD, IFM, patches/service packs) — i.e. drive the Actimize Installer (rcm-installer / Actimize-installer / AIS setup.exe). It is the install-execution counterpart to actimize-nicedl (which *downloads* the package) and actimize-docenter (which covers *documentation*). Dry-run by default; execution is confirmation-gated.
---

# Actimize Installer Runner Skill

This skill installs NICE Actimize **installation packages** on a target machine using the
`actimize-installer` CLI. It detects which Actimize installer a downloaded package carries, builds
the exact command, and runs it **only behind a confirmation gate** with captured logs.

It is the **install-execution** step of the ActWise chain:

- "How do I install/configure X?" → **actimize-docenter** (docs).
- "Get me the installer / patch / package for X version Y" → **actimize-nicedl** (`ndc`, download).
- "Install this downloaded package" → **this skill** (`actimize-installer`, run).

## When to use

Activate when the user wants to:
- **Install or upgrade** an Actimize product/solution from a package already downloaded with `ndc`.
- **Inspect** what installer a package uses, its CONF files, or the tasks/steps it will run.
- **Dry-run** an install to see the exact command before executing.

Do NOT use this to download packages (use **actimize-nicedl**) or to answer documentation questions
(use **actimize-docenter**).

## Installer interface (background)

Actimize ships two command grammars; the runner auto-detects from the package layout:

| Kind | Executable | Notes |
|------|-----------|-------|
| `actone` | `Installer/bin/rcm-installer.{bat,sh}` | CONF-driven task/step engine. **`upgrade` is not supported** for ActOne — use `install`. |
| `generic` | `Installer/bin/Actimize-installer{,.bat,.sh}` | Same grammar + `upgrade --from/--to` for **patch** ranges; `-x "Execute Db Scripts"` skips DB steps. |
| `ais-modeler` | `setup.exe` | AIS Visual Modeler / Server Monitor: `setup.exe silent -<mode> [-f features] [-p path] [-v version] /hide_progress`. |

CONF engines populate `Installer/conf/*` first and log to `Installer/logs/installation.log`.

## CLI commands

```
# Classify a package (safe, read-only)
actimize-installer detect --package <dir|zip> [--extract] [--json]

# Run the installer's own read-only `show` (e.g. effective CONF properties)
actimize-installer show --package <dir> [install|upgrade|properties] [-V]

# Build the install command (DRY-RUN by default) and, with --execute, run it (gated)
actimize-installer run --package <dir> [--command install|upgrade] [--mode full|sp|patch] \
    [-i/--include TASK ...] [-x/--exclude TASK ...] [-f/--force] \
    [--from VER] [--to VER] [-c/--conf DIR] [-w/--work DIR] [-l/--log DIR] \
    [--features all|modeler|monitor] [--target-path PATH] [--upgrade-from VER] \
    [--execute] [--yes] [--allow-prod] [--extract] [--json]
```

`--package` accepts an **extracted** package directory (or a `.zip` with `--extract`). The runner
finds the installer anywhere under that directory.

## Instructions

### 1. Detect first

Always start by classifying the package so you know the installer kind, executable, and CONF files:

```
actimize-installer detect --package packages/ActOne_10.2.0
```

If nothing is found, the package is probably not extracted, or the download is documentation, not an
installer. Ask the user to extract the archive.

### 2. Dry-run before executing

`run` is **dry-run by default** — it prints the exact command, any warnings, and any blockers
without touching the system. Show this to the user and confirm the command looks right:

```
actimize-installer run --package packages/ActOne_10.2.0 --command install
```

Common blockers you may see:
- **ActOne `upgrade` is unsupported** — use `--command install` (or the Patch Installer for patches).
- **Production CONF guard** — the CONF names a prod host; requires explicit `--allow-prod`.
- **Missing CONF** — CONF files must be populated before an install.

### 3. Execute behind the gate

Only when the user confirms, add `--execute`. The runner prompts for confirmation (bypass with
`--yes` for non-interactive automation) and tees all output to a timestamped log under
`installer-runs/`:

```
actimize-installer run --package packages/ActOne_10.2.0 --command install --execute
```

For a **patch/service pack** (generic installer):

```
actimize-installer run --package packages/Patch_5.8.0.58 --command upgrade \
    --from 5.8.0.56 --to 5.8.0.58 --execute
```

For **AIS Visual Modeler**:

```
actimize-installer run --package packages/AIS_Modeler --mode full \
    --features all --target-path "C:\\Program Files\\Actimize\\Modeler" --execute
```

### 4. Guardrails to respect

- **Never run `--execute` without the user's explicit go-ahead**, and prefer showing the dry-run
  command first.
- **Never bypass `--allow-prod`** unless the user confirms they are targeting production on purpose.
- Prefer running a limited step first (`-i "<task>"`) when validating on a new environment.
- After a run, point the user at both the run log (`installer-runs/…`) and the installer's own
  `Installer/logs/installation.log`.

### 5. Pair with the other skills

- Use **actimize-docenter** to fetch the matching *Installation Guide* (prerequisites, pre-installed
  products, CONF field meanings) before installing.
- Use **actimize-nicedl** (`ndc find` / `ndc download`) to obtain the package this skill installs.

## Error handling

| Symptom | Action |
|---------|--------|
| `No Actimize installer found` | Package not extracted, or it's docs not an installer. Extract the archive / re-download. |
| `BLOCKED: ActOne … does NOT support upgrade` | Use `--command install`, or the Patch Installer for patches. |
| `BLOCKED: CONF references a production environment` | Confirm intent; re-run with `--allow-prod` only if truly targeting prod. |
| `actimize-installer: command not found` | Install the repo package: `pip install -e .` (or via uv, like the other ActWise CLIs). |
