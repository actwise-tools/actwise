# utils bucket

> Run ActOne's server-side Java maintenance utilities as typed, discoverable,
> gated commands over local/ssh/winrm/container backends.

## Goal

Instead of hand-assembling `.bat/.sh` lines driven by `utilities.env`, utils
exposes ActOne's server-side Java utilities as a declarative catalog through a
`list → describe → run` loop. It covers the full 10.2 `Utilities/bin` set
(Blotter Maintenance, DART runner, import/export, archive/delete/render alerts &
cases, policy-type deployment, forms, dbupgrade, …). Every entry and its
parameters are verified against the shipped `<tool>_readme.txt`. `run` is
**dry-run by default**; state-changing runs are gated. An execution-backend
abstraction runs the same utility on `local`, `ssh`, `winrm`, or a `container`
host.

## Packages

| Package | Role |
|---------|------|
| `actone_utils` | The `actone-utils` CLI, the `actone-utils-mcp` MCP server, the declarative utility catalog, the runner, and the execution-backend abstraction. |

## CLI / MCP / Skills / Agent

- **CLI:** [`actone-utils`](../cli/actone-utils.md) — `list`, `search`,
  `describe`, `run` (dry-run by default; `--yes` for a real run), `backends`,
  `doctor`.
- **MCP:** [`actone-utils-mcp`](../mcp/actone-utils-mcp.md) — the same discovery
  loop as four tools: `search_utils`, `list_utils`, `describe_util`, `run_util`.
- **Skill:** [`actone-utils`](../skills/actone-utils.md) — drives the
  `list/search → describe → run --dry-run` loop and backend selection.
- **Agent:** none. This bucket ships no Copilot Studio agent grounded on its MCP
  (its agent column in the [project map](index.md) is a dash).

## Key concepts

- **Declarative catalog.** Each utility, its parameters, and its read/write
  access are modelled from the shipped `<tool>_readme.txt` — no guessing utility
  names or flags.
- **`list → describe → run`.** Discover a utility, inspect its parameters and
  access, then assemble the command.
- **Dry-run by default, gated writes.** `run` shows the exact command without
  executing; a real state-changing run needs `--yes` (CLI) or
  `ACTONE_UTILS_ALLOW_RUN=1` (MCP).
- **Backend abstraction.** The same utility runs on `local`, `ssh`, `winrm`, or a
  `container` host, selected by `ACTONE_UTILS_BACKEND` / config.
- **Auth per utility.** Utilities authenticate via per-utility parameters (the
  shared Authentication family + the `-acm=` URL); DB-script tools connect to the
  database instead.

## See also

- [Buckets hub](index.md)
- MCP: [`actone-utils-mcp`](../mcp/actone-utils-mcp.md)
- Related buckets: [ops](ops.md) (REST operations) · [installer](installer.md) (local stand-up)
