# ActOne API Suite — Reference

## 1. ActOne quirks catalog

These are baked into `generate_collection.py` and the hand-built collection. They are
the hard-won, non-obvious behaviors of the ActOne Extend REST API.

| # | Quirk | Why / Fix |
|---|-------|-----------|
| 1 | **Save-step returns 415** with `application/json` | Endpoint expects `multipart/form-data`. Send fields as form-data, not a JSON body. |
| 2 | `workItemIdentifiers` must be a **JSON array string** | e.g. `["QAS_00000000058"]`, not a bare id. |
| 3 | `note` must be a **JSON object string** | e.g. `{"note":"text"}`. |
| 4 | Tomcat 9.0.22 **rejects raw `{ } [ ] "`** in the URL | Pre-encode in a Postman pre-request script: `pm.variables.set('wi_q', encodeURIComponent(JSON.stringify([id])))` then use `{{wi_q}}`. |
| 5 | **Step ids are case-sensitive** and use *identifiers*, not display names | From the save-step spec screen, pass the step **identifier** (e.g. `QA_COMPLETED_3`), not the human label. |
| 6 | `forceStatus=true` (force step change) **requires ActOne 10.1.0 SP5+** | Silently ignored on older builds (this lab is 10.0.0.69 SP15). Confirm via release notes / `docenter`. |
| 7 | Workflow is **stateful** | Each successful save-step advances the *real* work item; re-running may hit a "no valid transition" error. Use a throwaway work item for smoke tests. |
| 8 | **Auth flow** | `POST /api/public/v1/auth/login` JSON `{username,password}` → 200 + `CSRFTOKEN` response header + `JSESSIONID` cookie (Path=`/RCM`). Every later call needs the cookie **and** a `CSRFTOKEN` header. |
| 9 | **Public endpoints clobber the session** | Calling `/api/public/...` on the same cookie jar can replace the authed `JSESSIONID`. Probe public endpoints with a separate opener (see `review_config.py`). |
| 10 | **Spec lives at the springfox path, not springdoc** | ActOne exposes **Swagger 2.0 at `/api/api-docs`** (advertised by `/api/swagger-resources`). The springdoc `/v3/api-docs*` paths return **403**. Download `/api/api-docs` with the normal REST session, then convert Swagger 2.0 → OpenAPI 3.0 (swagger2openapi `--patch --warnOnly`). Bundle is a fallback only. |
| 11 | **Spec version ≠ instance version** | The bundled `docs/ActOne_Extend_Rest_APIs.yaml` declares 10.2.0.20; the lab runs 10.0.0.69. Name collections by detected instance version. |
| 12 | **Self-referential enums + circular `$ref`** in the spec | Java enums render as objects whose props `$ref` themselves; some DTOs are genuinely recursive. Strict parsers (portman/swagger-parser) crash. Run `sanitize_spec.py` first. |

## 2. Version detection

`GET /api/v1/system/diagnostics` → `content.acmVersion` (e.g. `10.0.0.69`) and a nested
`servicePackVersion` (e.g. `15`). Compose as `10.0.0.69_SP15`. `dbVersion`, `acmMode`,
`availableProcessors`, `clusterMembers`, and `plugins` are also here — useful for config review.

## 3. The recipe model (generalizing to any Actimize REST API)

A **recipe** captures everything product-specific so the generator/sanitizer stay generic:

```yaml
recipe:
  product: ActOne            # ActOne | RCM | IFM | SAM | WLM | ...
  baseUrl: "{{rcm}}"          # Postman variable for the host root
  auth:
    type: login-csrf          # login-csrf | basic | bearer | apikey
    loginPath: /api/public/v1/auth/login
    bodyTemplate: '{"username":"{{username}}","password":"{{password}}"}'
    csrfResponseHeader: CSRFTOKEN     # captured -> sent on every later call
    sessionCookie: JSESSIONID
  spec:
    bundled: specs/<product>_<version>.yaml
    liveCandidates:                    # discovered via /api/swagger-resources, tried in order
      - /api/api-docs                  # springfox / Swagger 2.0 (ActOne) -> convert to OAS3
      - /v3/api-docs.json              # springdoc / OAS3
      - /v3/api-docs
  quirks:
    - id: multipart-save-step
      match: { operationId: saveStep }
      apply: { contentType: multipart/form-data, preEncodeParams: [workItemIdentifiers, note] }
    - id: force-status-min-version
      minVersion: 10.1.0_SP5
  domains:                              # tag -> top-level folder map (logical grouping)
    Authentication: [auth, login]
    "Work Items": [work-items, work-item-types, save-step]
    Alerts: [alerts]
    Cases: [cases]
    # ... 11 ActOne domains fold 26 tags
```

To target a new product: drop in its OpenAPI spec, write the `auth` + `quirks` + `domains`
sections, and reuse `actone sanitize` and `actone generate` unchanged. The same
`actone provision` orchestration (fetch → detect version → generate → push) applies.

## 4. Script map

All modules live in the installable `actone/` package and are invoked as
`actone <command>` (console script) or `python -m actone.<module>`. Per-run artifacts
(`specs/`, `generated/`, `reports/`, `.env`) are read/written under the current
directory, or `ACTONE_WORKDIR` when set; bundled assets ship in `actone/data/`.

| Module (`actone.*`) | CLI command | Role |
|--------|------|------|
| `fetch_spec` | `actone fetch-spec` | URL → login → detect version → **discover via `/api/swagger-resources`** → download `/api/api-docs` (Swagger 2.0) or `/v3/api-docs*` (OAS3) → **convert 2.0→3.0** → bundled fallback. Prints `{version, spec, source}`. |
| `sanitize_spec` | `actone sanitize` | Flatten self-ref enums + break circular `$ref` cycles → portman-safe spec copy. |
| `generate_collection` | `actone generate` | Spec → multi-domain categorized collection with quirks baked in. Version-aware (`--spec/--version/--name/--out`). |
| `provision_from_url` | `actone provision` | Orchestrator: fetch → generate → optional `--push` (collection + per-server env). |
| `review_config` | `actone review` | Read-only config review → Markdown report in `reports/`. |
| `push-to-postman.ps1` (in `postman/`) | `npm run push` | Create/update push to Postman via API (raw body, no `ConvertTo-Json` mangling). |

## 5. Postman push gotcha

Push the collection as a raw-text body `'{"collection":' + fileText + '}'` (PowerShell
`HttpWebRequest` or Python `urllib`) with an `X-API-Key` header. A `ConvertTo-Json`
round-trip mangles the collection structure — avoid it. `POST /collections?workspace=<id>`
to create, `PUT /collections/<uid>` to update.

## 6. ActWise vision tie-in

End state: give the agent an ActOne URL → it detects the version, extracts key info
(work-item types, plugins, licenses, tenants via `review_config.py`), builds automation
collections (`provision_from_url.py`), and reviews configuration — a self-service
"point-at-an-instance" Actimize automation + audit assistant.
