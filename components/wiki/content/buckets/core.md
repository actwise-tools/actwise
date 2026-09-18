# core bucket

> The shared path/config resolution layer used by every other ActWise bucket.

## Goal

`core` is the one dependency every other bucket relies on. It ships a single
package, `actwise`, whose job is to answer two questions consistently across all
CLIs, MCP servers, and skills: *where is the dev repo root?* and *where does this
config file live?* Centralizing this means no bucket hardcodes `parent.parent`
repo-relative paths, and one `ACTWISE_CONFIG_DIR` can point the whole toolkit at
a single config directory.

## Packages

| Package | Role |
|---------|------|
| `actwise` | Shared path/config resolution (`actwise/paths.py`): `repo_root()` and `find_config()`. Imported by every other bucket. |

## CLI / MCP / Skills / Agent

This bucket ships **only the `actwise` shared package** — no CLI console script,
no MCP server, no skill, and no Copilot Studio agent (its row in the
[project map](index.md) is all dashes). It is pure library code consumed by the
other buckets.

## Key concepts

- **`find_config(filename)` resolution order.** Returns the first existing of:
  1. `$ACTWISE_CONFIG_DIR/<filename>` (when the env var is set),
  2. `./<filename>` (current working directory),
  3. `~/.actwise/<filename>` (per-user config home),
  4. `<dev repo root>/<filename>` (only in a dev checkout).

  If none exist it returns the `~/.actwise/<filename>` path (which does not yet
  exist) so callers' `.exists()` checks fall through to their built-in defaults,
  and `config init`-style writers have a sane target.
- **`repo_root()`.** Walks up from the module (or a given anchor) to the first
  directory containing **both** `pyproject.toml` and `components/`. Returns
  `None` when the distribution is wheel-installed (no dev checkout), which is why
  the repo-root candidate is skipped in that case.
- **One switch for the whole toolkit.** Setting `ACTWISE_CONFIG_DIR` points every
  component — docenter, ops, data, utils, nicedl, installer — at the same config
  directory, without per-bucket flags.
- **Profiles hold no secrets.** Config resolution finds profile YAMLs
  (`actone-ops.yaml`, `actone-data.yaml`, …); passwords come from the matching
  `*.secrets.yaml` or environment variables, never the profile.

## See also

- [Buckets hub](index.md) — the full project map.
- Consumers: [docenter](docenter.md) · [ops](ops.md) · [data](data.md) ·
  [utils](utils.md) · [nicedl](nicedl.md) · [installer](installer.md)
