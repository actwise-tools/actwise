# ActOne API Testing with Postman — Build Notes & Reusable Approach

A complete record of how we built and debugged a working Postman suite for the
**ActOne Extend REST APIs**, plus a blueprint for turning this into a reusable
**Actimize API testing suite / AI skill**.

> **Looking for install + command usage?** See the package README at
> [`../actone/README.md`](../actone/README.md) — it covers installing the `actone`
> CLI, every command and flag, env vars, and the workdir model. This document is the
> deeper **build notes + quirks catalog**; the two are complementary.

---

## 1. What we built

```
actone/                                    # installable Python package (the pipeline)
├─ cli.py                                  # `actone` console entry (Typer): fetch-spec|generate|provision|sanitize|review
├─ paths.py                                # PKG data (read-only) vs WORKDIR (per-run outputs/.env)
├─ fetch_spec.py                           # URL -> login -> detect version -> download/convert/fallback spec
├─ sanitize_spec.py                        # make a spec portman-safe (enums + circular $ref)
├─ generate_collection.py                  # reusable generator: spec -> full collection
├─ provision_from_url.py                   # orchestrator: fetch -> generate -> optional push
├─ review_config.py                        # read-only config review of a live instance -> reports/
└─ data/ActOne_Extend_Rest_APIs.bundled.yaml  # bundled version-matched fallback spec (ships in wheel)

postman/                                   # working dir for runs + JS contract tooling
├─ ActOne.postman_collection.json          # Hand-built: Login -> Save Step (the deliverable)
├─ ActOne.local.postman_environment.json   # Server URL + creds + work-item defaults
├─ .env                                     # POSTMAN_API_KEY + workspace/UIDs (GITIGNORED)
├─ package.json                            # npm scripts -> `python -m actone.*` + portman/newman
├─ specs/                                  # sanitized specs written here when run from postman/ (GITIGNORED bar bundled)
├─ generated/                              # generated collections (GITIGNORED)
├─ reports/                                # generated config-review Markdown (GITIGNORED)
├─ portman-cli-options.json                # portman CLI options (spec path, output)
├─ portman-config.json                     # portman contract-test rules + auth overwrites
├─ push-to-postman.ps1                     # Create/Update collection+env via Postman API
└─ README.md                               # this file
```

> **Installable CLI.** The pipeline is packaged like `docenter`: a console command
> `actone` (Typer) defined in the root `pyproject.toml` (`[project.scripts] actone = "actone:app"`).
> Install with `pip install -e .` (or `uv tool install`, `pipx install`, `uvx --from git+<repo> actone`).
> Each subcommand forwards its flags to the underlying module; run `actone <cmd> --help`
> for that command's options. Outputs (`specs/`, `generated/`, `reports/`, `.env`) are
> read/written under the **current directory**, or `ACTONE_WORKDIR` when set — so running
> from `postman/` keeps artifacts in `postman/specs` etc. The JS contract tooling
> (portman/newman) stays in `postman/` and is driven via `npm run`.


Already pushed to workspace **My-Workspace** (`50bd916a-…`):

| Asset       | UID                                          |
|-------------|----------------------------------------------|
| Collection  | `9702029-f7c1df6a-266a-4c08-a850-dff2b58d3ff6` |
| Environment | `9702029-4147dff9-e4d0-478c-906b-1384f1f978bc` |

---

## 2. The two ActOne endpoints

### Login — `POST /RCM/api/public/v1/auth/login`
- `Content-Type: application/json`, body `{"username":"admin","password":"password"}`.
- Returns **200** + a `CSRFTOKEN` **response header** + a session **cookie**.
- The collection's test script captures `CSRFTOKEN` into the environment; the
  cookie is carried automatically by Postman's cookie jar.

### Save Step — `POST /RCM/api/v1/work-items/workflow/save-step`
- **All inputs are query parameters** (the OpenAPI spec defines no JSON body).
- Auth = session cookie (from Login) + `CSRFTOKEN` header.

---

## 3. Every gotcha we discovered (the hard part)

These were found empirically against the live server. They are the real value of
this exercise — a generated collection alone would not have worked.

| # | Symptom | Root cause | Fix |
|---|---------|-----------|-----|
| 1 | **415 Unsupported Media Type** | Endpoint **only** accepts `multipart/form-data`. `none`, `application/json`, `x-www-form-urlencoded`, `text/plain` all 415. | Body mode = **form-data** with one placeholder part (`_`). Let Postman set the boundary — do **not** set Content-Type manually. |
| 2 | **400 Bad JSON syntax** on `workItemIdentifiers` | Must be a **JSON array**, e.g. `["QAS_…"]`. A bare id or a JSON string fails. | Send `["{{work_item_id}}"]`. |
| 3 | **400 Bad JSON syntax** on `note` | Must be a JSON object with **only** the `note` key: `{"note":"text"}`. Extra keys / plain text fail (strict `FAIL_ON_UNKNOWN_PROPERTIES`). | Send `{"note":"…"}`. Required when the target step has `requiresNote=true`. |
| 4 | **400 Invalid character in request target** (newman/Postman, but curl worked) | **Tomcat 9.0.22 rejects raw `{ } [ ] "` in the URL.** curl worked only because we pre-encoded. Postman/newman sent them raw. | **Pre-request script** percent-encodes the JSON params into `{{wi_q}}` / `{{note_q}}` (see below). |
| 5 | **500 Failed to find status for provided identifier** | Step identifiers are **case-sensitive**: `QA_Completed_3`, not `QA_COMPLETED_3`. Also an empty `statusIdentifier` 500s — there is no no-op save-step. | Use the exact identifier from the workflow metadata. |
| 6 | **500 Cannot change step / workflow rules changed** | `save-step` only allows transitions to a **valid next step**. Multi-hop jumps (e.g. to terminal `QA_Completed_3`) are rejected. | Walk the workflow one valid step at a time. |
| 7 | `forceStatus=true` silently ignored | `forceStatus` was added in **ActOne 10.1.0 SP5** (Wiser CS4290147 / ACTONE-732339) and only relaxes in-step/isolated-step checks — **not** arbitrary jumps. The test server is pre-SP5. | Upgrade to SP5+ for force behavior; otherwise it's a no-op. |

### The pre-request encoding fix (gotcha #4)

```javascript
// Tomcat rejects raw { } [ ] " in the URL. Pre-encode JSON-valued query params.
var wid  = pm.environment.get('work_item_id');
var note = pm.environment.get('note') || '';
pm.variables.set('wi_q',   encodeURIComponent(JSON.stringify([wid])));
pm.variables.set('note_q', encodeURIComponent(JSON.stringify({ note: note })));
```

The URL then references `workItemIdentifiers={{wi_q}}` and `note={{note_q}}`.
Verified green via newman: **Login 200 + Save Step 200, 3/3 assertions.**

> The workflow is **stateful**: each successful Save Step advances the real work
> item. `status_identifier` is left empty by default — set it to a current valid
> next step (`GET /RCM/api/v1/work-items/{id}/workflow/next-steps`) before running.

### Why your "CUBI" collection still 415s

The screenshot error is a **different collection** ("CUBI- Bluk Closure using API")
whose Save Step request has the **old** setup: the **Body is not form-data**
(→ 415), and the query params are `{{work_item_id}}` / `{{note}}` instead of the
JSON-array / JSON-object / pre-encoded forms. Either use the fixed
**"ActOne Extend REST APIs"** collection, or apply fixes #1–#4 to the CUBI request.

---

## 4. Useful discovery endpoints (GET, auth via cookie + CSRFTOKEN)

| Purpose | Endpoint |
|---------|----------|
| Current step of an item | `/RCM/api/v1/work-items/{id}/workflow/current-step` |
| Valid next steps | `/RCM/api/v1/work-items/{id}/workflow/next-steps` |
| All work-item types | `/RCM/api/v1/md/work-item-types` |
| Full workflow graph | `/RCM/api/v1/md/work-item-types/{type}/workflow/all-steps?includeBUs=true` |
| Caller permissions | `/RCM/api/v1/users/permissions` |

(QAS_ items are type `QA_Review_Item`, BU `BPPR_CDD_QA_Confidential`.)

---

## 5. Tooling set up in this repo

### Postman MCP server (AI-driven, inside Copilot)
`.vscode/mcp.json` now has a `postman` server: `npx @postman/postman-mcp-server`,
with the API key loaded from `postman/.env` via `envFile`. This lets the AI
create/inspect collections, environments, and run requests in your workspace by
natural language. Restart the MCP client to pick it up.

### portman + Postman CLI (deterministic CI contract testing)
- `npm install` (in `postman/`) — installs `@apideck/portman` + `newman`.
- `npm run gen:contract` — **sanitizes** the spec (`sanitize_spec.py`) then generates
  a **contract** collection from the OpenAPI spec with status/schema/header tests
  (config in `portman-config.json`). The sanitize step is required: the raw spec
  has self-referential enums and circular `$ref`s that crash strict parsers.
- `npm run test:local` — runs the **hand-built** suite with newman.
- `npm run test:cloud` — runs the pushed collection via the Postman CLI.
- `npm run push` — create/update collection+env in the workspace (`push-to-postman.ps1`).
- CI: `.github/workflows/postman-contract-tests.yml` regenerates the contract
  collection on every spec change; a `live-tests` job (disabled, self-hosted)
  runs the real suite where the private network is reachable.

> **Split of responsibility:** portman gives you fast, regenerable *schema/contract*
> tests straight from the spec. The hand-built collection encodes the *behavioural*
> knowledge (auth flow, multipart, encoding, workflow rules) that a spec can't express.

### Full reference collection — `generate_collection.py`
`npm run gen:full` builds **"ActOne Extend REST APIs — Full"** — all **217**
operations from the spec, organized into **11 logical domain folders** (Auth first),
with the ActOne specifics baked in:
- `CSRFTOKEN` header on every authenticated request; Login captures the token.
- The **save-step quirk** (multipart body + pre-request percent-encoding) applied automatically.
- JSON request-body skeletons generated from the OpenAPI schemas.
- Path params as `:var`; destructive/admin ops prefixed **⚠** and flagged in their description.

It lives in a dedicated workspace, **"ActOne API Library"** (`8e55e8d0-…`), kept
separate from the scratch/working collections. This script is the concrete
implementation of the reusable generator described in §6 — extend the `DOMAINS`
map and quirks to onboard another Actimize API. Output is gitignored
(`generated/`) because it is regenerated from the spec.

### URL-driven pipeline — point at an instance, get a collection

The end-to-end "ActWise" flow: from just a **URL + creds**, detect the version,
obtain a version-matched spec, generate a collection, and (optionally) push it.

| Command | What it does |
|---------|--------------|
| `actone fetch-spec --url <RCM> --user <u> --password <p>` | Logs in, reads `/api/v1/system/diagnostics` for the version, **discovers the spec via `/api/swagger-resources`**, downloads `/api/api-docs` (springfox **Swagger 2.0**) or `/v3/api-docs*` (springdoc OAS3), and **auto-converts Swagger 2.0 → OpenAPI 3.0** (swagger2openapi). Falls back to the bundled spec only if no api-docs is exposed. Prints `{version, spec, source}`. |
| `actone provision --url <RCM> --user <u> --password <p> [--push]` | Orchestrates fetch → generate → optional push. Names the collection by **detected** instance version and creates a per-server environment (`rcm` = URL). |
| `actone review --url <RCM> --user <u> --password <p>` | **Read-only** config review: samples safe GETs (diagnostics, modules, licenses, work-item-types, permissions, tenants) and writes Markdown to `reports/`. Never mutates the instance. Verified against the lab: 10.0.0.69 SP15, DB V10.0.0.70, 42 plugins, 70 work-item types, 3 tenants. |
| `actone sanitize` | Flattens self-referential enums → string enums and **breaks circular `$ref` cycles**, emitting a portman-safe spec under `specs/`. Run before portman. |

> **Spec download:** ActOne uses **springfox (Swagger 2.0) at `/api/api-docs`**, advertised by
> `/api/swagger-resources` — *not* springdoc's `/v3/api-docs` (which returns 403 here). `fetch_spec.py`
> discovers and downloads it with the normal REST session, then converts Swagger 2.0 → OpenAPI 3.0 so
> the generator/portman stay uniform. The bundled spec is only a fallback. Collections are labelled by
> the **detected instance version** (e.g. the live 10.0.0.69 surface is 127 ops vs the bundled
> 10.2.0.20's 217), so each collection matches what's actually deployed.

---

## 6. Generalizing into a reusable Actimize API testing suite / AI skill

The ActOne saga reveals a repeatable pattern. Any Actimize REST surface can be
onboarded with the same recipe.

### 6.1 The recipe (per API)
1. **Inputs:** OpenAPI spec + base URL + an **auth recipe** (how to log in, where
   the token/cookie lives) + a small set of **quirks** (content-type, param
   encoding, stateful resources).
2. **Generate** a contract collection with portman (schema/status tests).
3. **Layer** an auth folder (login request + token-capture test script) on top.
4. **Encode quirks** as reusable pre-request snippets (e.g. the Tomcat
   percent-encoding helper, multipart placeholder, JSON-array wrappers).
5. **Push** to a workspace via the Postman API; **run** via newman/Postman CLI in CI.

### 6.2 Proposed reusable structure
```
actimize-api-suite/
├─ recipes/
│  ├─ actone.recipe.json      # spec path, baseUrl, auth, quirks
│  ├─ ais.recipe.json
│  └─ rcm.recipe.json
├─ snippets/                  # reusable pre-request / test scripts
│  ├─ csrf-login.js
│  ├─ tomcat-url-encode.js
│  └─ multipart-placeholder.js
├─ generator/                 # spec + recipe -> collection + env
└─ pipelines/                 # newman / Postman CLI / CI templates
```

A **recipe** is the key abstraction — a small declarative file:
```json
{
  "name": "ActOne",
  "spec": "docs/components/ops/ActOne_Extend_Rest_APIs.yaml",
  "baseUrl": "http://10.233.194.40:8080/RCM",
  "auth": {
    "type": "csrf-cookie",
    "loginPath": "/api/public/v1/auth/login",
    "tokenHeader": "CSRFTOKEN"
  },
  "quirks": {
    "forceContentType": "multipart/form-data",
    "urlEncodeJsonParams": ["workItemIdentifiers", "note"],
    "jsonArrayParams": ["workItemIdentifiers"],
    "jsonObjectParams": { "note": ["note"] }
  }
}
```
A generator reads the recipe + spec and emits a ready-to-run collection, applying
the matching snippets. New Actimize APIs become a new recipe file, not a new
hand-debugging session.

### 6.3 Packaged as a Copilot skill — `actone-api-suite`

This pipeline is now installed as a reusable skill at
`~/.agents/skills/actone-api-suite/` (`SKILL.md` + `REFERENCE.md`):
- **Triggers:** "build a Postman collection for ActOne", "test ActOne REST APIs",
  "download/detect an ActOne spec", "review an ActOne instance configuration",
  "generalize an OpenAPI spec into an Actimize testing suite".
- **Steps:** detect version → fetch/fallback spec → sanitize → generate categorized
  collection with quirks → push via Postman API → smoke test → report UIDs.
- **Bundled knowledge:** the full **quirks catalog** (415/encoding/workflow/auth/spec
  pitfalls) and the **recipe model** for onboarding other Actimize products, so the
  skill starts already knowing the gotchas in §3.

This converts one-off API debugging into a one-command, repeatable capability.

---

## 7. Security

- `postman/.env` holds the API key and is **gitignored** (`.env`, `*.env`).
- The key was shared in plaintext during setup — **rotate it**: Postman → avatar →
  Settings → API keys → delete the old key → **Generate API Key**, then update
  `postman/.env`.
- Never commit `.env`, `browser-profile/`, or live credentials.

---

## 8. Quick start

```powershell
# 1. Install the CLI once (from the repo root). Pick one:
pip install -e .                 # editable dev install -> `actone` on PATH
# uv tool install .              # or via uv
# pipx install .                 # or isolated via pipx
# uvx --from git+<repo-url> actone --help   # or run without installing

# 2. Run the pipeline. Outputs land under the CURRENT directory (or ACTONE_WORKDIR).
cd postman                       # keeps specs/generated/reports/.env in postman/
npm install                      # portman + newman + swagger2openapi (JS contract tooling)

# Point at a live instance: detect version -> spec -> collection (+ push)
actone provision --url http://HOST:8080/RCM --user admin --password password --push
actone review    --url http://HOST:8080/RCM --user admin --password password

# Spec-only workflows (npm scripts call `python -m actone.*` under the hood)
npm run gen:full               # full categorized collection from the bundled spec
npm run gen:contract           # sanitize spec + regenerate schema/contract collection
npm run test:local             # run Login + Save Step (set status_identifier first)
pwsh -File ./push-to-postman.ps1   # create/update assets in your workspace
```

> Prefer not to install? Every command also runs as a module:
> `python -m actone.provision_from_url --url … --user … --password …`.

