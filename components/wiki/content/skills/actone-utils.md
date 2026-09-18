# ActOne Utilities

> Run ActOne's server-side Java maintenance utilities (the full 10.2 `Utilities/bin` set — 33 tools) as typed, discoverable, gated commands via the `actone-utils` CLI and MCP server.

## Goal
ActOne ships dozens of server-side Java utilities — blotter maintenance, the DART runner, import/export, archive/delete/render, policy-type deployment, dbupgrade and more — each driven by hand-assembled `.bat/.sh` lines and `utilities.env`. This skill turns that into a discoverable `list → describe → run` loop where each tool's parameters are modelled and verified, `run` dry-runs by default, and state-changing runs are gated behind explicit opt-in.

## How it fits
This skill drives the `actone-utils` CLI and the `actone-utils` MCP server in the **utils** bucket. It runs the same utility against a `local`, `ssh`, `winrm`, or `container` backend. It is the server-side maintenance counterpart to **actone-ops** (Extend REST API) and **actone-data** (read-only SQL); for documentation use **actimize-docenter** and for packages use **actimize-nicedl**.

## When to use it
Activate when the user wants to operate an ActOne server-side utility:
- "Rematerialize / maintain the blotters" → `blotter-maintenance`.
- "Run / stop / abort the DART query for EDS `<id>`" → `dart-runner`.
- "Import/export alerts or cases" → `import-data` / `export-data`.
- "Archive / delete / render alerts or cases" → `archive-*` / `delete-*` / `render-alerts`.
- "Deploy a policy type" / "activate policy" → `policy-type-deployment`.
- "Generate the DB upgrade / users-and-roles script" → `dbupgrade` / `rcm-users-and-roles`.
- "Show me the command that would run" (preview only) → `run … --dry-run`.
- "What utilities can I run and what params do they take?" → `list` / `describe`.

## What it does
- Follows the loop: **find** (`actone-utils list`, `search`) → **inspect** (`describe <util>` for params, access, source doc) → **preview/run** (`run <util> -s key=value … --dry-run`, then `--execute --yes` to actually run).
- Selects and inspects execution backends: `actone-utils backends`, `actone-utils doctor --backend <b>`, `--backend local|ssh|winrm|container`.
- Exposes the same engine to AI agents via MCP tools: `search_utils`, `list_utils`, `describe_util`, `run_util`.
- Covers the full ActOne 10.2 Utilities catalog (33 tools), each verified against its shipped `<tool>_readme.txt` (and the Implementer Guide for async/forms tools).

## Install / enable
Skills follow the open Agent Skills spec and install via the `skills` CLI:
```powershell
npx skills add https://github.com/vinayguda/actwise.git --skill actone-utils -a claude-code -g
```
Skills are instructions only — they drive the ActWise CLIs, so install the `actwise` distribution too. This skill requires the **`actone-utils`** console script and the **`actone-utils-mcp`** server. A real run also needs the Utilities package staged on the execution host (`ACTONE_UTILS_DIR`) and a healthy, licensed ActOne reachable at the `-acm=` URL.

## Walkthrough
- *"What utilities can I run?"* → `actone-utils list`; then `actone-utils describe blotter-maintenance`.
- *"Show me the command to run the DART query for EDS_ALERTS."* → `actone-utils run dart-runner -s action=execute -s eds_identifier=EDS_ALERTS … --dry-run`.
- *"Actually run it."* → after review, append `--execute --yes` (write utilities require this).

## Limits & safety
- `run` **dry-runs by default** — it assembles and prints the exact command without executing. State-changing utilities require `--yes` (CLI) or `ACTONE_UTILS_ALLOW_RUN=1` (MCP).
- Read vs write is classified: exports, renders, script generators, and local helpers are read (safe); imports, deletes, archives, migrations, and deployments are write (gated). `delete-alerts -physicalDelete=true` and `case-migration` are irreversible.
- The dry-run command is the review point — never `--execute` a command you haven't reviewed against your environment's `utilities.env`.

## See also
- CLI: [../cli/actone-utils.md](../cli/actone-utils.md)
- MCP: [../mcp/actone-utils-mcp.md](../mcp/actone-utils-mcp.md)
- Bucket: [../buckets/utils.md](../buckets/utils.md)
- Related skills: [actone-ops](actone-ops.md), [actone-data](actone-data.md)
