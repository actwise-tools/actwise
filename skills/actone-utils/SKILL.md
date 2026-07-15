---
name: actone-utils
description: "Run NICE Actimize ActOne installer Utilities-package tools (the full ActOne 10.2 `Utilities/bin` set — 33 CLIs: Blotter Maintenance, DART runner, import/export data, archive/delete/render alerts & cases, resource-strings, platform-lists, policy-type deployment, forms, VLA graphs, dbupgrade, and more) as typed commands via the `actone-utils` CLI and the `actone-utils` MCP server, over a local, ssh, winrm, or container execution backend. Use when the user wants to run, preview, or inspect an ActOne server-side Java utility — e.g. rematerialize blotters, execute/stop/abort a DART query, import/export alerts, archive or delete cases, deploy a policy type, or see what a utility invocation would look like without running it. Dry-run by default; state-changing runs are gated behind explicit opt-in. Not for the Extend REST API (use actone-ops) and not for product documentation (use actimize-docenter)."
---

# ActOne Utilities

Run ActOne's server-side Java maintenance utilities — the `.bat/.sh` tools driven
by `utilities.env` (JDK/classpath) — as **typed, discoverable, gated** commands
instead of hand-assembled shell lines. Backed by the `actone-utils` CLI and the
`actone-utils` MCP server (tools: `search_utils`, `list_utils`, `describe_util`,
`run_util`).

```
list / search  →  describe  →  run   (--dry-run by default)
   (find)          (inspect)    (assemble, then execute only if opted in)
```

> **Safety.** `run` **dry-runs by default** — it assembles and prints the exact
> command without executing it. Utilities that change state require `--yes` (CLI)
> or `ACTONE_UTILS_ALLOW_RUN=1` (MCP server) for a real run. **Always review the
> dry-run command first.**

## When to use

Activate when the user wants to **operate an ActOne server-side utility**:
- "Rematerialize / maintain the blotters" → `blotter-maintenance`
- "Run / stop / abort the DART query for EDS `<id>`" → `dart-runner`
- "Import/export alerts or cases" → `import-data` / `export-data`
- "Archive / delete / render alerts or cases" → `archive-*` / `delete-*` / `render-alerts`
- "Deploy a policy type", "activate policy" → `policy-type-deployment`
- "Generate the DB upgrade / users-and-roles script" → `dbupgrade` / `rcm-users-and-roles`
- "Show me the command that would run" (preview only) → `run ... --dry-run`
- "What utilities can I run and what params do they take?" → `list` / `describe`

For the **Extend REST API** (work items, alerts, policies), use **actone-ops**.
For **documentation** questions, use **actimize-docenter**. To fetch install
**packages**, use **actimize-nicedl**.

## The discovery loop (always follow this order)

1. **Find** the utility — never guess a name:
   ```
   actone-utils list
   actone-utils search "blotter"
   ```
2. **Inspect** its parameters, access (read/write), and source doc:
   ```
   actone-utils describe dart-runner
   ```
3. **Preview**, then run. Dry-run first — inspect the assembled command — then
   opt in for a real run:
   ```
   actone-utils run dart-runner -s action=execute -s eds_identifier=EDS_ALERTS \
     -s reference_date=2026-07-08 -s acm_nodes=http://acm:8080/actimize -s user=dan -s password=pw --dry-run
   actone-utils run dart-runner -s action=execute -s eds_identifier=EDS_ALERTS \
     -s reference_date=2026-07-08 -s acm_nodes=http://acm:8080/actimize -s user=dan -s password=pw --execute --yes
   ```

## Execution backends

The same utility runs against whichever backend is configured — abstracted so the
agent never hand-writes SSH/WinRM plumbing:

| backend | where it runs | how |
|---------|---------------|-----|
| `local` | this host (dev / actone_local container host) | subprocess |
| `ssh`   | a remote (usually Linux) ActOne host | system OpenSSH client |
| `winrm` | a remote Windows ActOne host | pywinrm (optional; dry-run needs nothing) |
| `container` | inside a running container (e.g. the `actone_local` `actone` container) | `docker exec` (or podman) |

Select and inspect:
```
actone-utils backends                 # list backends + their config
actone-utils doctor --backend ssh     # effective config (paths, JDK, utilities.env)
actone-utils run <util> --backend ssh --dry-run
```

Configure via env (`ACTONE_UTILS_*`) or `actone-utils.yaml` at the repo root —
see REFERENCE.md.

**Two prerequisites for a *real* (non-dry-run) execution** — the ActOne connection URL is always a
per-utility parameter (`-s acm=<url>` → `-acm=`), independent of the backend, but the run needs:

1. **The Utilities package staged on the execution host** at `ACTONE_UTILS_DIR`. A stock ActOne app
   container is often **app-server-only** (Tomcat + JDK, *no* Utilities scripts); the standalone
   Utilities package (`packages/ActOne-10.2.0-Utilities/Utilities/`) must be present there.
2. **A healthy, licensed ActOne** reachable at the `-acm=` URL. If the app context failed to start
   (e.g. missing license) it will 404 and no utility can authenticate. Confirm the app responds
   before a real run.

Until both hold, use `--dry-run` — it assembles and prints the exact command without executing.

## MCP

Local (stdio) client config runs `actone-utils-mcp`; remote/Copilot
Studio uses the Streamable-HTTP app (`uvicorn actone_utils.server:app`, endpoint
`/mcp`, optional `X-API-Key` via `ACTONE_UTILS_API_KEY`). `run_util` defaults to
`dry_run=true`; real state-changing runs need `ACTONE_UTILS_ALLOW_RUN=1`.

## Verify before real runs

The catalog covers the **full ActOne 10.2 installer Utilities package** (33 tools
under `Utilities/bin`). Every entry and its parameters are **verified against the
shipped `<tool>_readme.txt`** (and, for the six async/forms tools, the ActOne 10.2
Implementer Guide — see each entry's `doc_url`). ActOne utilities use the
`-name=value` convention; ACM-connected utilities share the documented
**Authentication** (`user`/`password`/`auth_mode`/`ntlm_domain`/`encrypted`) and
**SSL** (`ts`/`ks`/…) parameters, while the DB-script tools (`dbupgrade`,
`rcm-users-and-roles`) and local helpers (`merge-aho-files`, `run-encryptor`) take
their own. Use `run ... --arg <raw>` (repeatable) for anything not modelled. The
dry-run command is the review point — never `--execute` a command you haven't
reviewed, and confirm values against your environment's `utilities.env` / config
parameters first.

> Read vs. write: exports, renders, script generators and local helpers are
> classified **read** (safe to run); imports, deletes, archives, migrations and
> deployments are **write** (gated). Note `import-virtualfs` uses `-rcm` (not
> `-acm`), and `dbupgrade`/`rcm-users-and-roles` connect to the **database**, not
> the ACM URL. `delete-alerts -physicalDelete=true` and `case-migration` are
> irreversible.

> Intentionally **not** runnable entries: **APF Comparer** (a Designer GUI feature,
> not a CLI script) and `dart_detection_and_research_tool` (the DART product concept,
> not a batch tool — the DART *scheduling* batch tool is `dart-runner`).

See **REFERENCE.md** for the full config, catalog schema, and how to add a utility.
