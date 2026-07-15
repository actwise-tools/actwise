# ActOne API Suite

> Turn an ActOne URL and credentials (or a bundled OpenAPI spec) into a categorized, quirk-aware Postman collection, contract tests, and a configuration review — via the `actone` CLI.

## Goal
Testing the ActOne Extend REST API by hand is painful: the spec has to be fetched and sanitized, ActOne's save-step quirks trip up naive requests, and a fresh instance needs a per-server collection. This skill teaches an AI agent to provision a ready-to-use Postman collection from a live instance or spec, generate contract tests for CI, and produce a read-only configuration review — without hand-writing requests.

## How it fits
This skill drives the build-time half of the `actone` CLI (`provision`/`generate`/`sanitize`/`review`) in the **ops** bucket. It complements **actone-ops**, which drives the run-time discovery loop over the same Extend REST API. The JS contract tooling (portman/newman) lives under `postman/` and is run via `npm run`.

## When to use it
Activate when the user wants to:
- Build a Postman collection for ActOne.
- Test ActOne REST APIs (login, save-step, work items, alerts, cases).
- Download/detect an ActOne spec, or generalize an OpenAPI spec into an Actimize API testing suite.
- Run a read-only configuration review of a live ActOne instance.

For interactively invoking live operations, use **actone-ops** instead.

## What it does
- **Provisions** a collection from a URL: `actone provision --url … --user … --password … [--push]` — logs in, detects the version, discovers and downloads the api-docs (Swagger 2.0 or OAS3), auto-converts to OpenAPI 3.0, and falls back to the bundled spec only if none is exposed.
- **Generates** a categorized full collection from the bundled spec (`actone generate`).
- **Sanitizes** the spec for strict parsers (`actone sanitize`) and generates portman contract tests (`npm run gen:contract`).
- **Reviews** an instance read-only (`actone review …`) via a curated set of safe GETs, writing a Markdown report to `postman/reports/`.
- Encodes the known ActOne save-step quirks (multipart/form-data, JSON-array `workItemIdentifiers`, pre-encoded query params, case-sensitive step ids, `forceStatus` needing 10.1.0 SP5+).

## Install / enable
Skills follow the open Agent Skills spec and install via the `skills` CLI:
```powershell
npx skills add https://github.com/vinayguda/actwise.git --skill actone-api-suite -a claude-code -g
```
Skills are instructions only — they drive the ActWise CLIs, so install the `actwise` distribution too. This skill requires the **`actone`** console script (subcommands also run as `python -m actone.<module>`); the contract tooling under `postman/` uses `npm run`. Put `POSTMAN_API_KEY` (and optional `ACTONE_URL/USER/PASSWORD`) in `postman/.env`.

## Walkthrough
- *"Build me a Postman collection for this ActOne instance and push it."* → `actone provision --url http://HOST:8080/RCM --user admin --password … --push`.
- *"Generate contract tests for CI."* → `actone sanitize` then `npm run gen:contract` → `generated/ActOne.contract.postman_collection.json`.
- *"Review this instance's configuration."* → `actone review --url … --user … --password …` writes a Markdown report and never mutates the instance.

## Limits & safety
- `review` calls only SAFE GETs (diagnostics, modules, licenses, work-item-types, permissions, tenants) and never mutates the instance.
- `provision` without `--push` is a dry-run. Live contract tests require a self-hosted runner on the ActOne network; hosted-runner CI runs the generated collection only.
- Secrets live in `postman/.env` (gitignored). See `REFERENCE.md` for the full save-step quirks catalog and the recipe model for other Actimize REST APIs.

## See also
- CLI: [../cli/actone.md](../cli/actone.md)
- Bucket: [../buckets/ops.md](../buckets/ops.md)
- Related skills: [actone-ops](actone-ops.md), [actone-data](actone-data.md)
