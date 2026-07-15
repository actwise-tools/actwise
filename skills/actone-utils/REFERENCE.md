# actone-utils — Reference

Typed runner for ActOne server-side maintenance utilities (C-U in the ActWise
blueprint). Wraps the ActOne `.bat/.sh` tools driven by `utilities.env` behind a
CLI + MCP server with a pluggable execution backend.

## Install / entry points

Part of the `actimize-docenter` distribution (root `pyproject.toml`):

- CLI: `actone-utils` (or `python -m actone_utils`)
- MCP (stdio): `actone-utils-mcp` (or `python -m actone_utils.server`)
- MCP (HTTP): `python -m uvicorn actone_utils.server:app --host 0.0.0.0 --port 8766`
  - endpoint `http://<host>:8766/mcp`, health `/healthz`, optional `X-API-Key`.

## Commands

| command | purpose |
|---------|---------|
| `list [--json]` | list all utilities (name, access, tags, title) |
| `search <query> [--limit] [--json]` | keyword search over name/title/tool/tags/summary |
| `describe <name> [--json]` | parameters, access, notes, source doc |
| `run <name> -s KEY=VALUE ... [--dry-run/--execute] [--yes] [--backend B]` | assemble + (optionally) run |
| `backends [--config]` | show local/ssh/winrm backends and their config |
| `doctor [--backend B] [--config]` | print the effective config (paths, JDK, utilities.env) |

`run` is **dry-run by default**. Use `--execute` to actually run; a state-changing
utility also needs `--yes`. Parameters are passed as repeatable `-s/--set KEY=VALUE`.

### Examples

```bash
actone-utils list
actone-utils describe dart-runner
# preview (no execution) on the default (local) backend
actone-utils run dart-runner -s action=execute -s eds_identifier=EDS_ALERTS \
  -s reference_date=2026-07-08 -s acm_nodes=http://acm:8080/actimize -s user=dan -s password=pw --dry-run
# preview against a remote Linux host over ssh
actone-utils run blotter-maintenance -s acm_nodes=http://acm:8080/actimize -s user=dan \
  -s password=pw -s pool_size=4 --backend ssh --dry-run
# real run (state-changing → requires --yes)
actone-utils run blotter-maintenance -s acm_nodes=http://acm:8080/actimize -s user=dan \
  -s password=pw --execute --yes
```

## Configuration

Precedence: dataclass defaults → `actone-utils.yaml` (repo root) → `ACTONE_UTILS_*`
environment variables (env wins).

### Environment variables

| var | meaning | default |
|-----|---------|---------|
| `ACTONE_UTILS_BACKEND` | `local` \| `ssh` \| `winrm` \| `container` | `local` |
| `ACTONE_UTILS_HOME` | ActOne install root (contains the utilities dir) | (unset) |
| `ACTONE_UTILS_DIR` | utilities subdir under HOME | `utilities` |
| `ACTONE_UTILS_ENV` | explicit path to `utilities.env` | `<utilities>/utilities.env` |
| `ACTONE_UTILS_JDK` | `JAVA_HOME` exported before the run (falls back to `JAVA_HOME`) | (inherit) |
| `ACTONE_UTILS_SHELL` | `auto` \| `sh` \| `bat` | `auto` (bat only for local+Windows) |
| `ACTONE_UTILS_TIMEOUT` | run timeout, seconds | `900` |
| `ACTONE_UTILS_SSH_HOST/USER/PORT/KEY/OPTIONS` | ssh backend target | port `22` |
| `ACTONE_UTILS_WINRM_HOST/USER/PASSWORD/PORT/TRANSPORT/SCHEME` | winrm backend target | port `5985`, `ntlm`, `http` |
| `ACTONE_UTILS_CONTAINER` | container backend: target container name | `actone` |
| `ACTONE_UTILS_DOCKER_BIN` | container backend: `docker` or `podman` | `docker` |
| `ACTONE_UTILS_ALLOW_RUN` | MCP-only: truthy permits real state-changing runs | unset (gated) |
| `ACTONE_UTILS_API_KEY` | HTTP MCP shared secret (`X-API-Key`) | unset (open) |

### `actone-utils.yaml` (example)

```yaml
backend: ssh
actone_home: /opt/actimize/actone
utilities_dir: utilities
jdk_home: /opt/jdk21
shell: sh
default_timeout: 1800
ssh:
  host: rcm01.lab
  user: acmadmin
  port: 22
  key: ~/.ssh/actone_ed25519
# winrm:
#   host: rcm-win.lab
#   user: svc_actone
#   transport: ntlm
```

## Execution backends

- **local** — `subprocess` on this host. `.bat` when local+Windows, else `.sh`.
- **ssh** — pipes through the system OpenSSH client:
  `ssh [user@host] 'cd <utilities> && export JAVA_HOME=... && <script> <args>'`.
  Uses the ssh agent / default key unless `key` is set. No extra Python deps.
- **winrm** — builds a Windows `cmd` chain and runs it via **pywinrm**
  (`pip install pywinrm`). Dry-run assembles the command and needs no dependency;
  only a real run imports pywinrm (clear error if missing).
- **container** — runs inside a live container via `docker exec` (or podman):
  `docker exec -w <utilities> -e JAVA_HOME=... <container> <script> <args>`.
  Pairs with `actone_local` (default container name `actone`). Target is Linux, so
  scripts are always `.sh`.

All backends implement the same `run(argv, cwd, env, dry_run, timeout)` contract
(`actone_utils/backends.py`), so adding a new backend (e.g. container `exec`) is a
single subclass + factory entry.

## Catalog

Utilities live in `actone_utils/catalog.py` as declarative `Utility`/`Param`
records. The catalog covers the **full ActOne 10.2 installer Utilities package**
(33 tools under `Utilities/bin`). Every entry's parameters are **verified against
the shipped `<tool>_readme.txt`** (and, for the six async/forms/blotter tools, the
ActOne 10.2 Implementer Guide RCM Utilities / RCM Blotters pages — see each
`doc_url`). ActOne utilities use the `-name=value` flag convention (single dash,
`=`); the runner renders params that way. Use `--arg` for any option not modelled.

| name | tool (script) | access | key params (beyond shared auth/SSL) |
|------|---------------|--------|------------|
| `blotter-maintenance` | `materialization_asynch_execution_tool` | write | `acm_nodes` (req), `timeout` (int), `pool_size` (int) |
| `dart-runner` | `query_asynch_execution_tool` | write | `action` (req, execute/stop/abort), `eds_identifier` (req), `reference_date` (req, date), `pool_size` (int), `force_execution` (bool), `timeout` (int), `acm_nodes` (req) |
| `workflow-async` | `workflow_asynch_execution_tool` | write | *(shared auth/SSL only; uses `acm_nodes`)* |
| `efile` | `efiling_tool` | write | `formTypeIdentifiers`, `task` (all/efile/ack) |
| `historical-entities` | `historical_external_entities_extraction` | write | `acmqueryidentifier`, `acmqueryparameters`, `countinprogress` (flag) — no NTLM |
| `get-form-pdf` | `get_form_as_pdf` | read | `save_to_path` (req), `save_pdf_in_db` (bool), `form_identifiers`, `ddq_identifer` |
| `import-data` | `import_data` | write | `source` (req), `batchsize` (int), `validate` (bool), `schemalocation` |
| `export-data` | `export_data` | read | `module` (req, alerts/cases), `drillDownQueryIdentifier` (req), `drillDownQueryParameters`, `out` (req) |
| `import-package` | `import` | write | `filename` (req), `importPolicy` (req), `brokenlinkpolicy` (req), `processId` |
| `export-to-apf` | `export_to_apf` | read | `source` (req), `out` (req), `includeDependencies` (flag) |
| `import-attachment` | `import_attachment` | write | `file` (req), `module` (req, item/case), `identifier` (req), `description`, `note` |
| `import-virtualfs` | `import_virtualfs` | write | `rcm` (req, **not** `acm`), `filename` (req), `virtual_path` (app_gui_items/external_items) |
| `import-platform-list` | `import_platform_list` | write | `identifier` (req), `fileName` (req), `log`, `onlyIfEmpty` (flag) |
| `export-platform-list` | `export_platform_list` | read | `identifier` (req), `out` (req) |
| `import-resource-strings` | `import_resource_strings` | write | `filename` (req), `importPolicy` (req, Overwrite/Selective) |
| `import-resource-strings-by-value` | `import_resource_strings_by_value` | write | `filename` (req), `module` (req) |
| `export-resource-strings` | `export_resource_strings` | read | `last_update_date`, `identifiers`, `modules`, `out` |
| `archive-alerts` | `archive_alerts` | write | `acmQueryIdentifier` (req), `acmQueryParameters`, `type`, `prefix`, `suffix`, `extension`, `overwrite` (bool), `zip` (bool), `objectdir` (bool), `generateFile` (bool) |
| `archive-cases` | `archive_cases` | write | `acmQueryIdentifier` (req), `acmQueryParameters`, `prefix`, `suffix`, `extension`, `overwrite` (bool), `zip` (bool), `objectdir` (bool), `generateFile` (bool) |
| `delete-alerts` | `delete_alerts` | write | `acmQueryIdentifier` (req), `acmQueryParameters`, `physicalDelete` (bool), `requiresAudit` (bool), `forceDependency` (bool), `continueOnError` (bool) |
| `delete-cases` | `delete_cases` | write | `acmQueryIdentifier` (req), `acmQueryParameters`, `forceDependency` (bool) |
| `render-alerts` | `render_alerts` | read | `acmQueryIdentifier` (req), `acmQueryParameters`, `type` (req), `prefix`, `suffix`, `extension`, `overwrite` (bool), `zip` (bool), `objectdir` (bool) |
| `case-migration` | `case_migration` | write | `acmQueryIdentifier` (req), `acmQueryParameters`, `mappingfile`, `numOfThreads` (int) |
| `policy-type-deployment` | `policy_type_deployment` | write | `policy_type_identifiers` (req) |
| `manage-product-info` | `manage_product_info` | write | `action` (req, add/get/delete), `productName` (req), `infoType` (req, version/third_party/all), `filePath`, `overwrite` (flag), `out`, `files` |
| `manage-virtual-plugin` | `manage_virtual_plugin` | write | `pluginId` (req), `action` (req, upload), `zipFile` |
| `manage-failover` | `manage_failover` | write | `mode` (req, active/standby) |
| `form-filing` | `formFilingTool` | write | `forms` (req), `newStatusIdentifier`, `reference` |
| `vla-graphs` | `vla_tool` | write | `task` (req, add/delete), `graphFile`, `alertIdentifier`, `graphIdentifer` |
| `merge-aho-files` | `merge_aho_files` | read | `source` (req), `out` (req) — **local**, no auth |
| `run-encryptor` | `run_encryptor` | read | `encrypt`, `iv`, `iv_gen` (flag), `DES` (flag) — **local**, no auth |
| `dbupgrade` | `dbupgrade` | write | **DB** `db`/`user`/`password`; `dbtype` (req, oracle/mssql/nmssql/postgresql), `catalog`, `new` (flag), `exec` (flag), `out`, `env`, `summary`, `help` (flag) |
| `rcm-users-and-roles` | `RCM_UsersAndRoles` | read | `dbtype` (req, mssql/oracle/postgresql), `env` (req), `out` (req) |

### Shared parameter families

Documented once in the guide/readmes and referenced by every ACM-connected utility,
so modelled once via `_acm()` / `_auth()` / `_ssl()` helpers and attached per utility:

- **Connection**: `acm` (single URL) or `acm_nodes` (semicolon-separated cluster URLs);
  `import-virtualfs` uses `rcm`. The DB-script tools (`dbupgrade`, `rcm-users-and-roles`)
  and local helpers (`merge-aho-files`, `run-encryptor`) do **not** take an ACM URL.
- **Authentication** (`Authentication for Utilities`): `user` (req), `password` (req),
  `auth_mode` (`internal`|`ntlm_cl`|`ntlm_full`), `ntlm_domain`, `encrypted` (bool).
  `historical-entities` omits the NTLM options (it does not support NTLM). For `dbupgrade`,
  `user`/`password` are **database** credentials, not the ACM auth family.
- **SSL-Related Options** (only for `https` URLs): `ts`, `tspassword`, `ks`,
  `kspassword`, `kstype`, `tstype`.

> **Read vs. write:** exports, `render-alerts`, script generators (`rcm-users-and-roles`)
> and local helpers are **read**; imports, deletes, archives, migrations, deployments and
> `dbupgrade` are **write** (gated). Destructive/irreversible: `delete-alerts
> -physicalDelete=true`, `delete-cases`, `case-migration`, and `dbupgrade -exec`.

> **Not modelled — intentionally excluded:**
> - `apf_comparer_tool` / **APF Comparer** — a Designer **GUI** feature (File → Compare
>   APFs), not a command-line `.bat/.sh` utility, so it is not a runnable entry.
> - `dart_detection_and_research_tool` — the DART product concept (Reference Guide:
>   "Detection And Research Tool"), not a batch runner. (The DART *scheduling* batch tool
>   `query_asynch_execution_tool` **is** modelled as `dart-runner`.)

### Raw args

Any run accepts `--arg/-a VALUE` (repeatable), appended verbatim after the typed
args — an escape hatch for utility options not modelled in the catalog. Example:
`actone-utils run efile ... --arg -auth_mode=ntlm_full --dry-run`.

### Param types

`str` · `int` · `date` (YYYY-MM-DD) · `enum` (validated against `choices`) ·
`bool` (rendered `-name=true`/`-name=false`, e.g. `-encrypted=true`) ·
`flag` (bare presence switch `-name` when truthy, e.g. `-countinprogress`). Each
value param renders as `-name=value`; declare `positional=True` for an ordered
positional or set `arg` for an explicit flag spelling.

### Add a utility

Append an `Utility(...)` via `_add(...)` in `catalog.py` — no other file changes.
Set `state_changing=False` for read-only/diagnostic tools (skips the `--yes` gate),
include a `doc_url`, and give each `Param` a type + description.

## Command assembly

`<utilities_path><sep><tool><.bat|.sh>` followed by positionals (declared order)
then `-name=value` flags (bare `-name` for presence flags). The working directory is
the utilities dir; `JAVA_HOME` is exported from `jdk_home`. Review the assembled
`command` / `remote_command` from a dry-run before executing.

## Safety model

- Reads and dry-runs always proceed.
- State-changing runs: **CLI** needs `--execute --yes`; **MCP** needs
  `ACTONE_UTILS_ALLOW_RUN=1` in the server environment — the model can't lift it.
- Parameters are verified against the ActOne 10.2 Implementer Guide (linked per
  entry). Still review the `--dry-run` command before any real run, and confirm
  values against your environment's `utilities.env` / config parameters.
