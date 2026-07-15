# actone — ActOne API → Postman automation suite

`actone` is an installable CLI that turns a **NICE Actimize ActOne instance URL
(+ credentials)** — or a bundled OpenAPI spec — into a categorized, quirk-aware
**Postman collection**, portman **contract tests**, and a read-only **configuration
review**. It is the first concrete delivery of **C-O (ActOne Ops)** in the ActWise
ecosystem, packaged the same way as the `docenter` CLI.

```
ActOne URL + creds  ──►  detect version  ──►  download + convert spec  ──►  Postman collection (+ optional push)
                                                                       └──►  config review report
bundled spec        ──►  generate / sanitize  ──►  collection + portman contract tests
```

---

## Install

From the repository root (the package is declared in the root `pyproject.toml`):

```powershell
pip install -e .                          # editable dev install -> `actone` on PATH
# or:
uv tool install .                         # isolated, via uv
pipx install .                            # isolated, via pipx
uvx --from git+https://github.com/vinayguda/actwise actone --help   # run without installing
```

Prefer not to install at all? Every command also runs as a module:
`python -m actone.<module>` (e.g. `python -m actone.provision_from_url --url ...`).

**Requirements:** Python ≥ 3.10 (stdlib + PyYAML — both already pulled in by the
package). The Swagger 2.0 → OpenAPI 3.0 conversion in `fetch-spec` shells out to
`npx swagger2openapi`, which is installed under `postman/node_modules` (`npm install`
in `postman/`). Run live `fetch-spec`/`provision` from `postman/` so that dependency
resolves locally.

---

## Quick start

```powershell
cd postman      # run here so specs/ generated/ reports/ .env stay in postman/ (or set ACTONE_WORKDIR)

# Point at a live instance: detect version -> spec -> collection (-> optional push)
actone provision --url http://HOST:8080/RCM --user admin --password password
actone provision --url http://HOST:8080/RCM --user admin --password password --push

# Read-only configuration review of a live instance
actone review --url http://HOST:8080/RCM --user admin --password password

# Spec-only (no network): generate from the packaged bundled spec
actone generate
actone sanitize ; npm run gen:contract     # portman schema/status contract tests
```

---

## Commands

All commands forward their flags to the underlying module; run `actone <cmd> --help`
(or `python -m actone.<module> --help`) for the live list.

| Command | Module | Purpose |
|---------|--------|---------|
| `actone fetch-spec` | `actone.fetch_spec` | Log in, detect the version, **discover the spec via `/api/swagger-resources`**, download `/api/api-docs` (springfox Swagger 2.0) or `/v3/api-docs*` (springdoc OAS3), **auto-convert 2.0 → 3.0**, else fall back to the bundled spec. Prints `{version, spec, source}` JSON. |
| `actone generate` | `actone.generate_collection` | Turn an OpenAPI spec into a categorized (multi-domain, Auth-first, ⚠-flagged destructive ops) Postman collection with ActOne quirks baked in. |
| `actone provision` | `actone.provision_from_url` | Orchestrator: `fetch-spec` → `generate` → optional `--push` (collection + a per-server environment) to a Postman workspace. |
| `actone sanitize` | `actone.sanitize_spec` | Flatten self-referential Java enums → string enums and **break circular `$ref` cycles** so strict parsers (portman/swagger-parser) don't crash. Emits a portman-safe spec. |
| `actone review` | `actone.review_config` | Read-only config review: a curated set of safe GETs (diagnostics, modules, licenses, work-item-types, permissions, tenants) → Markdown report under `reports/`. Never mutates the instance. |
| `actone ops` | `actone.registry` / `actone.invoke` | **Runtime** spec-driven discovery over the live Extend REST API (`search`/`describe`/`call`/`tags`/`version`). Read-only in P1. See [ActOne Ops](#actone-ops-runtime-discovery). |

### Flags

```
actone fetch-spec  --url <RCM>  --user <u>  --password <p>
actone provision   --url <RCM>  --user <u>  --password <p>  [--push]
actone review      --url <RCM>  --user <u>  --password <p>
actone generate    [--spec <path>] [--version <label>] [--name <name>] [--out <path>]
actone sanitize    [--in <spec>] [--out <portman-safe-spec>]
```

`--url/--user/--password` default to the matching `ACTONE_*` env vars (see below),
then to the lab values. `generate --spec` defaults to the **packaged bundled spec**;
`sanitize --in` defaults to the same bundled spec.

---

## ActOne Ops (runtime discovery)

Everything above is **build-time** (produce/review Postman collections). `actone ops`
is the **run-time** surface: let an AI agent (or you) *perform* ActOne operations over
the Extend REST API. Instead of registering 149 static tools, it exposes three
**discovery** verbs over a spec-driven registry, so tool-selection context stays flat
no matter how large the API is, and it tracks whatever the target instance exposes.

```
actone ops search "<keywords>"   # find operations (operationId/summary/tags/path)
actone ops list                  # list ALL operations (no cap; --tag, --reads-only, --group)
actone ops describe <operationId>  # params, request-body example, read/write access
actone ops call <operationId> [--p k=v ...] [--params JSON] [--body JSON]
actone ops tags                  # list functional domains + counts
actone ops version               # login + report detected ActOne version
```

- **Spec source** (same precedence as the registry): `--spec` → cached spec under
  `<WORKDIR>/postman/specs/` → the packaged bundled spec. `search`/`describe`/`tags`
  work **offline**; only `call`/`version` log in.
- **Read-only gate (P1):** `call` runs only operations classified **read** (GET/HEAD).
  Writes are refused *before* any login with a clear message — they await the
  attribution-wall decision (P2).
- **Credentials:** `--url/--user/--password` or `ACTONE_URL/ACTONE_USER/ACTONE_PASSWORD`
  (process env wins, then `<WORKDIR>/.env`). ActOne auth/quirks (CSRFTOKEN + cookie,
  Tomcat pre-encode, 415→multipart retry) are handled by `actone/client.py`.

### MCP discovery server

`actone_mcp/server.py` (FastMCP, stdio) exposes the same surface to MCP clients
(Copilot CLI/VS Code, Claude Code) as five tools: `search_ops`, `list_ops`,
`describe_op`, `invoke_op` (read-only), `list_tags`. Registered in `.vscode/mcp.json`
as `actone-ops`; console entry point `actone-mcp`.

```
py -m actone_mcp.server          # stdio
```

Design + phase plan: [`docs/components/ops/2026-06-29-actone-ops-design.md`](../docs/components/ops/2026-06-29-actone-ops-design.md).
New here? Start with the friendly walkthrough: [`docs/components/ops/ActOne-Ops-Tutorial.md`](../docs/components/ops/ActOne-Ops-Tutorial.md).

---

## Configuration

### Environment variables

| Variable | Used by | Meaning |
|----------|---------|---------|
| `ACTONE_WORKDIR` | all | Base dir for per-run artifacts (`specs/`, `generated/`, `reports/`) and `.env`. Defaults to the **current directory**. |
| `ACTONE_URL` / `ACTONE_USER` / `ACTONE_PASSWORD` | fetch-spec, provision, review, ops | Defaults for the matching flags. |
| `ACTONE_SPEC` | ops (registry / MCP) | Optional explicit spec path; otherwise cached-then-bundled. |
| `POSTMAN_API_KEY` | provision `--push` | Postman API key for create/update calls. |
| `POSTMAN_WORKSPACE_ID` | provision `--push` | Target workspace for the pushed collection + environment. |

These are read from `<WORKDIR>/.env` (gitignored). Running from `postman/` therefore
loads `postman/.env` and writes outputs into `postman/`.

### Workdir model (packaged data vs per-run output)

`actone/paths.py` separates the two:

- **`PKG` / `DATA`** — read-only assets that ship inside the wheel
  (`actone/data/ActOne_Extend_Rest_APIs.bundled.yaml`, the version-matched fallback spec).
- **`workdir()`** — `ACTONE_WORKDIR` or the current directory; everything the CLI
  *writes* (`specs/`, `generated/`, `reports/`) and the `.env` it reads live here.

So the same installed CLI behaves differently per directory without any reinstall —
run it from a customer folder and its artifacts stay there.

---

## Output layout (under WORKDIR)

```
<WORKDIR>/
├─ specs/        downloaded + converted + sanitized specs (regenerable)
├─ generated/    Postman collections (ActOne.Full.<version>.postman_collection.json, contract collection)
├─ reports/      Markdown config-review reports
└─ .env          secrets + ACTONE_* / POSTMAN_* defaults (gitignored)
```

---

## How the live spec is obtained (the key discovery)

ActOne exposes its OpenAPI via **springfox at `/RCM/api/api-docs`** (Swagger 2.0),
advertised by `/RCM/api/swagger-resources`. The springdoc `/v3/api-docs*` paths return
**403** on this build. `fetch-spec` therefore:

1. Logs in (`POST /api/public/v1/auth/login` → `CSRFTOKEN` header + `JSESSIONID` cookie).
2. Reads `/api/v1/system/diagnostics` for the instance version.
3. Discovers the spec URL via `/api/swagger-resources`.
4. Downloads `/api/api-docs` (Swagger 2.0) and **auto-converts to OpenAPI 3.0** via
   `npx swagger2openapi --patch --warnOnly` (the `--patch` flag is required — the live
   spec has `parameter.type is mandatory` defects).
5. Falls back to the **bundled** spec only if no api-docs endpoint is reachable.

Collections are **named by the detected instance version** and reflect the *installed*
surface (e.g. live 10.0.0.69 ≈ 127 ops vs the bundled 10.2.0.20 = 217 ops).

---

## Contract testing (lives in `postman/`)

The JS contract tooling is intentionally **not** wrapped by the Python CLI (matching
how `docenter` doesn't wrap npm). From `postman/`:

```powershell
npm install                 # portman + newman + swagger2openapi
npm run gen:contract        # actone sanitize -> portman -> generated/ActOne.contract.postman_collection.json
npm run test:local          # newman: Login + Save Step
```

`.github/workflows/postman-contract-tests.yml` regenerates on every spec change
(hosted runner); live API tests need a **self-hosted runner on the ActOne network**.

---

## Security

- `postman/.env` holds the Postman API key and ActOne creds — **gitignored**, never commit it.
- Rotate any key shared in plaintext during setup (Postman → Settings → API keys).
- `actone review` is strictly read-only; `actone provision --push` only writes to your
  Postman workspace, never to the ActOne instance.

---

## Further reading

- **[`docs/components/ops/ActOne-Ops-Tutorial.md`](../docs/components/ops/ActOne-Ops-Tutorial.md)** — beginner-friendly,
  step-by-step tutorial for `actone ops` and the MCP server (written for non-technical users too).
- **`postman/README.md`** — full build notes, the 12-item ActOne quirks catalog, every
  gotcha discovered against the live server, and the generalization blueprint.
- **`~/.agents/skills/actone-api-suite/`** — the reusable AI skill (SKILL.md + REFERENCE.md)
  with the recipe model for extending this to other Actimize REST surfaces (RCM, IFM, SAM, WLM).
- **`docs/2026-06-25-actwise-ecosystem-blueprint.md`** (§C-O.1) — where this fits in ActWise.
