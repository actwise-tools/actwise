# Configuration

Every ActWise component resolves its config files through one shared function,
`actwise.paths.find_config()`. Understanding its search order is the key to a clean
setup.

## Resolution order

`find_config(<file>)` checks these locations **in order** and returns the first hit:

1. **`$ACTWISE_CONFIG_DIR/<file>`** — explicit override. Set this env var to point
   every component at one directory.
2. **`./<file>`** — the current working directory.
3. **`~/.actwise/<file>`** — the recommended home for an installed (non-dev) user.
4. **`<dev repo root>/<file>`** — convenient when working inside a source checkout.

```powershell
# Point all components at one directory, regardless of where you run them:
$env:ACTWISE_CONFIG_DIR = "$HOME\.actwise"
```

!!! tip
    New code should always resolve config via `actwise.paths.find_config()` rather
    than hardcoding repo-relative paths. This is what makes the same tool behave
    correctly whether it's an editable dev checkout or a global `uv tool` install.

## Config files vs secrets

Profile YAMLs never contain passwords. Each has a paired secrets file:

| Component | Profile (no secrets) | Secrets |
| --- | --- | --- |
| Ops (live REST) | `actone-ops.yaml` | `actone-ops.secrets.yaml` |
| Data (read-only SQL) | `actone-data.yaml` | `actone-data.secrets.yaml` |
| Docs portal | — (session cookie) | `browser-profile/session-cookies.json` |

Passwords may also come from environment variables (see
[Install & onboarding](install.md#env-var-alternatives)).

## What lives where

- **Ops** — `actone-ops.yaml` lists one profile per ActOne instance (URL,
  `context_root`, user, `allow_writes`).
- **Data** — `actone-data.yaml` lists one DB profile per environment (host, port,
  name, read-only user, schema).
- **Docenter** — the catalog resolves to `~/.docenter/catalog.yaml`, fetched on
  first run using your own portal session (no NICE data is bundled).

## Secrets are never committed

`.env`, `*.secrets.yaml`, `browser-profile/`, and license files are gitignored and
must stay uncommitted. See [Security & secrets](security.md).
