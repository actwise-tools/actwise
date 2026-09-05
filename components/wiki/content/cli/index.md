# CLIs

ActWise installs **seven command-line tools** (plus five [MCP servers](../mcp/index.md))
as console scripts. Each is the executable core of a [bucket](../buckets/index.md);
the matching [skill](../skills/index.md) teaches an AI agent how to drive it.

| CLI | Bucket | What it does |
| --- | --- | --- |
| [`docenter`](docenter.md) | docenter | Browse, search, download, and sync NICE Actimize documentation. |
| [`actone`](actone.md) | ops | ActOne REST → Postman automation + spec-driven runtime ops. |
| [`actone-data`](actone-data.md) | data | Read-only NL/SQL query engine over ActOne `v_acm_*` views. |
| [`actone-utils`](actone-utils.md) | utils | Typed runner for ActOne server-side Java maintenance utilities. |
| [`ndc`](ndc.md) | nicedl | Search & download Actimize install media (NICE Download Center). |
| [`actimize-installer`](actimize-installer.md) | installer | Install a package fetched by `ndc` (gated). |
| [`actone-local`](actone-local.md) | installer | Stand up ActOne locally on Docker + PostgreSQL. |

## Conventions shared by every CLI

- **Discovery loops.** Most CLIs follow a *list → describe → act* pattern so you can
  explore before running anything.
- **Dry-run / read-first.** State-changing tools default to a preview; a real run
  needs an explicit `--yes` / `--execute`, and writes to live ActOne are
  confirm-gated.
- **Config resolution.** All of them find config via `actwise.paths.find_config()`
  — see [Configuration](../config.md).
- **`--help` everywhere.** Every command and subcommand prints `--help`; the tables
  on these pages are generated from that output.

!!! note "Install"
    All seven land on your PATH with one install — see
    [Install & onboarding](../install.md).
