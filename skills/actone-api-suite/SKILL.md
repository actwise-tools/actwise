---
name: actone-api-suite
description: Generate, test, and push Postman collections for NICE Actimize ActOne (and other Actimize REST APIs) from an OpenAPI spec or a live instance URL. Use when the user wants to build a Postman collection for ActOne, test ActOne REST APIs (login, save-step, work items, alerts, cases), download/detect an ActOne spec, review an ActOne instance configuration, or generalize an OpenAPI spec into an Actimize API testing suite.
---

# ActOne API Suite

Turn an **ActOne URL + creds** (or a bundled OpenAPI spec) into a categorized,
quirk-aware Postman collection, contract tests, and a configuration review.

Pipeline is an installable CLI: the `actone` console command (Typer), packaged in the
repo's root `pyproject.toml` (`[project.scripts] actone = "actone:app"`, package `actone/`).
Install with `pip install -e .` / `uv tool install .` / `pipx install .`, or run a
subcommand as a module: `python -m actone.<module>`. Python 3, stdlib + PyYAML.

## Quick start

```powershell
# Install once from the repo root (pick one): pip install -e .  |  uv tool install .  |  pipx install .
cd postman   # run here so specs/generated/reports/.env stay in postman/ (or set ACTONE_WORKDIR)

# 1. URL -> detect version -> fetch/fallback spec -> generate -> (optional) push
actone provision --url http://HOST:8080/RCM --user admin --password password --push

# 2. Spec only -> categorized full collection from the bundled spec
actone generate                          # uses the packaged bundled spec
actone sanitize; npm run gen:contract    # portman schema/status contract tests

# 3. Read-only configuration review of a live instance
actone review --url http://HOST:8080/RCM --user admin --password password
```

> Not installed? Each command also runs as `python -m actone.<module>`
> (e.g. `python -m actone.provision_from_url --url ...`). Outputs are written under the
> current directory, or `ACTONE_WORKDIR` when set. The JS contract tooling
> (portman/newman) lives in `postman/` and is driven via `npm run`.

Secrets (`POSTMAN_API_KEY`, optional `ACTONE_URL/USER/PASSWORD`) go in `postman/.env` (gitignored).

## Workflows

**Build a collection for a new ActOne instance**
1. `actone provision --url ... --user ... --password ...` (omit `--push` to dry-run).
2. It logs in, reads `/api/v1/system/diagnostics` for the version, discovers the spec
   via `/api/swagger-resources`, downloads `/api/api-docs` (springfox Swagger 2.0) or
   `/v3/api-docs*` (springdoc OAS3), auto-converts Swagger 2.0 → OpenAPI 3.0, and
   falls back to the bundled spec only if no api-docs is exposed.
3. Collection name = `ActOne Extend REST APIs — Full (v{version})`; env per server.

**Contract-test in CI**
1. `actone sanitize` → portman-safe spec (flattens self-ref enums, breaks
   circular `$ref` cycles — strict parsers crash otherwise).
2. `npm run gen:contract` → `generated/ActOne.contract.postman_collection.json`.
3. `.github/workflows/postman-contract-tests.yml` runs this on hosted runners;
   live tests need a self-hosted runner on the ActOne network.

**Review an instance** — `actone review` calls a curated set of SAFE GETs
(diagnostics, modules, licenses, work-item-types, permissions, tenants) and writes
a Markdown report to `postman/reports/`. Never mutates the instance.

## ActOne save-step quirks (must-know)

See [REFERENCE.md](REFERENCE.md) for the full quirks catalog and the **recipe model**
for generalizing this to other Actimize REST APIs (RCM, IFM, SAM, WLM, etc.).
Critical: save-step needs `multipart/form-data`; `workItemIdentifiers` is a JSON
array; `note` is a JSON object; pre-encode `{}[]"` in query params; step ids are
case-sensitive; `forceStatus` requires 10.1.0 SP5+.

## Generalize to other Actimize APIs

This is a **recipe-driven** approach. A recipe = `{spec, baseUrl, auth, quirks}`.
To target a new Actimize product, supply its OpenAPI spec + an auth recipe and reuse
`generate_collection.py` / `sanitize_spec.py` unchanged. See REFERENCE.md.
