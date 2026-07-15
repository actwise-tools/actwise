# Security & secrets

ActWise is designed so that **no secret and no NICE Actimize content ever needs to
be committed**. It operates entirely with **your own** authenticated sessions.

## What ActWise never stores or ships

- **No bundled NICE content.** Documentation and data are fetched on demand with
  your credentials; nothing proprietary is packaged.
- **No shared credentials.** There is no ActWise service account — you authenticate
  to the docs portal, ActOne, and the database as yourself.

## Files that must stay uncommitted

These are expected local inputs, covered by `.gitignore`:

| File / dir | What it holds |
| --- | --- |
| `.env` | environment variables (may include passwords/tokens) |
| `*.secrets.yaml` | per-component passwords (e.g. `actone-ops.secrets.yaml`) |
| `browser-profile/session-cookies.json` | your NICE portal doc session cookie |
| `license.lic` / `*.lic` | ActOne product license (installer / local run) |

!!! danger "Never commit secrets"
    If you add a new config path, treat any credential-bearing file as a secret and
    add it to `.gitignore`. Keep passwords in the `*.secrets.yaml` companion or in
    environment variables — never in the profile YAMLs.

## Read-first, gated writes

ActWise is conservative by default:

- **Data** is strictly **read-only** — it only issues `SELECT` over the ActOne
  reporting views, on a row-capped, audited session. It never inserts, updates, or
  deletes.
- **Ops** performs reads directly but runs a **confirm-before-write** step for any
  change (create/update/close/progress/invoke).
- **Utilities** and the **installer** are **dry-run by default**; a state-changing
  run needs an explicit `--yes` / `--execute`.

## Publishing safely

When ActWise is published (wiki or open-source distribution), **hosted endpoint
identifiers** — the MCP server FQDNs, tunnel hostnames, IP addresses, and license
files — are treated as private and excluded. Public pages refer to them generically
as "a self-hosted MCP endpoint". The repository's public-distribution plan
(`docs/2026-07-15-actwise-public-and-wiki-plan.md`) documents the export allow-list
and endpoint-scrubbing approach.
