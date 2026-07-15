# CLI full reference

> Auto-generated from each CLI's top-level `--help`. Do not edit by hand — run `python components/wiki/scripts/gen_cli_reference.py` to refresh. For per-command detail and worked examples, see the individual CLI pages.

## `docenter`

```text
                                                                                                   
 Usage: docenter [OPTIONS] COMMAND [ARGS]...                                                       
                                                                                                   
 Browse and download NICE Actimize documentation.                                                  
                                                                                                   
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --install-completion          Install completion for the current shell.                         │
│ --show-completion             Show completion for the current shell, to copy it or customize    │
│                               the installation.                                                 │
│ --help                        Show this message and exit.                                       │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
┌─ Commands ──────────────────────────────────────────────────────────────────────────────────────┐
│ list-categories  List all product categories from the local catalog, with product/bundle        │
│                  counts.                                                                        │
│ list-products    List all products from the local catalog, grouped by category.                 │
│ list-docs        List doc bundles for a product, grouped by version and doc type.               │
│ download         Download doc bundles as Markdown or PDF.                                       │
│ sync             Re-extract only the bundles that changed on the portal since the last sync.    │
│ search           Search NICE Actimize docs — the live portal by default, or the local corpus    │
│                  with --local.                                                                  │
│ auth             Manage authentication with the Zoomin doc portal.                              │
│ sharepoint       Upload documents to SharePoint.                                                │
│ catalog          Manage the local docs/catalog.yaml product catalog.                            │
│ skill            Maintain the actimize-docenter AI skill file.                                  │
│ wiki             Generate a deterministic, cross-linked documentation wiki from raw_docs/.      │
│ index            Generate the catalog taxonomy index (category -> product -> bundle).           │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

## `actone`

```text
                                                                                                   
 Usage: actone [OPTIONS] COMMAND [ARGS]...                                                         
                                                                                                   
 ActOne API -> Postman automation suite (spec download, collection generation, review).            
                                                                                                   
+- Options ---------------------------------------------------------------------------------------+
| --help          Show this message and exit.                                                     |
+-------------------------------------------------------------------------------------------------+
+- Commands --------------------------------------------------------------------------------------+
| fetch-spec  Download the live OpenAPI spec from an ActOne URL (auto-converts Swagger 2.0 ->     |
|             OAS3).                                                                              |
| generate    Generate a logically-organized Postman collection from an OpenAPI spec.             |
| provision   One-shot: fetch spec -> generate collection -> optionally push to a Postman         |
|             workspace.                                                                          |
| sanitize    Flatten self-referential enums and break $ref cycles to produce a portman-safe      |
|             spec.                                                                               |
| review      Read-only review of key ActOne configuration via its REST API.                      |
| ops         Spec-driven runtime ops over the ActOne Extend REST API (discovery:                 |
|             search/describe/call). Read-only in P1.                                             |
+-------------------------------------------------------------------------------------------------+
```

## `actone-data`

```text
                                                                                                   
 Usage: actone-data [OPTIONS] COMMAND [ARGS]...                                                    
                                                                                                   
 ActWise Data -> read-only query engine over ActOne v_acm_* views.                                 
                                                                                                   
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --help          Show this message and exit.                                                     │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
┌─ Commands ──────────────────────────────────────────────────────────────────────────────────────┐
│ ping     Test the DB connection: prints server version, schema, and the ActOne sentinel check.  │
│ version  Detect the ActOne product version from the DB (falls back to the bundled doc version). │
│ eval     Run the NL->SQL eval set through the guardrail + execute path and print a scoreboard.  │
│ schema   Introspect the live ActOne schema (v_acm_* views).                                     │
│ query    Validate or run a read-only SELECT over the v_acm_* views.                             │
│ audit    Inspect the query audit log.                                                           │
│ env      List the configured ActOne environments (DB profiles).                                 │
│ docs     Parse the v_acm_* doc pages (descriptions + FK graph).                                 │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

## `actone-utils`

```text
                                                                                                   
 Usage: actone-utils [OPTIONS] COMMAND [ARGS]...                                                   
                                                                                                   
 Typed runner for ActOne maintenance utilities (Blotter Maintenance, DART runner) over local / ssh 
 / winrm backends. Discovery loop: list -> describe -> run. Dry-run by default; state-changing     
 runs need --yes.                                                                                  
                                                                                                   
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --help          Show this message and exit.                                                     │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
┌─ Commands ──────────────────────────────────────────────────────────────────────────────────────┐
│ list      List all utilities in the catalog.                                                    │
│ search    Search utilities by keyword (name/title/tool/tags/summary).                           │
│ describe  Show a utility's parameters, access, and source doc.                                  │
│ run       Assemble and run a utility. Dry-run by default; --yes for a real state-changing run.  │
│ backends  Show the available execution backends.                                                │
│ doctor    Show the effective config: backend, paths, JDK, utilities.env.                        │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

## `ndc`

```text
                                                                                                   
 Usage: ndc [OPTIONS] COMMAND [ARGS]...                                                            
                                                                                                   
 NICE Download Center CLI — search & download Actimize installation packages (Flexera              
 SubscribeNet). Complements `docenter` (documentation).                                            
                                                                                                   
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --help          Show this message and exit.                                                     │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
┌─ Commands ──────────────────────────────────────────────────────────────────────────────────────┐
│ products       List curated product keys (friendly aliases for plne ids + components).          │
│ find           Locate a package by product + version — e.g. `ndc find actone 10.2`.             │
│ product-lines  List product lines (manufacturers) available on the portal.                      │
│ search         Search product releases. Returns element/plne ids for `list-files` / `download`. │
│ recent         List recent product releases posted to the portal.                               │
│ list-files     List the downloadable files in a release (filename, size, MD5).                  │
│ download       Download the installation package files for a release (with MD5 verification).   │
│ auth           Authenticate to the NICE Download Center.                                        │
│ catalog        Build/inspect the offline package catalog cache.                                 │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

## `actimize-installer`

```text
                                                                                                   
 Usage: actimize-installer [OPTIONS] COMMAND [ARGS]...                                             
                                                                                                   
 Actimize Installer runner — install a package fetched by `ndc`. Dry-run by default; execution is  
 gated. Complements docenter (docs) and ndc (packages).                                            
                                                                                                   
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --help          Show this message and exit.                                                     │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
┌─ Commands ──────────────────────────────────────────────────────────────────────────────────────┐
│ detect  Inspect a package and report its installer flavor, bin, and CONF files.                 │
│ show    Run the installer's own read-only `show` command (safe to execute).                     │
│ run     Build the install command (dry-run) and, with --execute, run it behind a gate.          │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

## `actone-local`

```text
                                                                                                   
 Usage: actone-local [OPTIONS] COMMAND [ARGS]...                                                   
                                                                                                   
 Stand up ActOne core locally (Docker + PostgreSQL). Idempotent, disk-aware, laptop-friendly.      
 Complements ndc (packages) and actimize-installer (DB tasks).                                     
                                                                                                   
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --help          Show this message and exit.                                                     │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
┌─ Commands ──────────────────────────────────────────────────────────────────────────────────────┐
│ doctor          Preflight: docker, disk headroom, package, WAR, license, image.                 │
│ config          Show the effective config (or --init to scaffold one).                          │
│ extract         Extract only the lean build inputs (RCM.war + Docker/) from the payload.        │
│ db-up           Start the lightweight PostgreSQL container (postgres:16-alpine).                │
│ db-init         Create the ActOne schema (lower-case) + search_path.                            │
│ db-schema       Populate the ActOne DDL + seed data (dbupgrade -exec -new). Takes a few         │
│                 minutes.                                                                        │
│ render-config   Write acm.ini (PostgreSQL, plaintext password) into the work dir.               │
│ encrypt-config  Encrypt the DB password (bundled tool) and rewrite acm.ini with the IV.         │
│ build           Build the ActOne Docker image (disk-guarded).                                   │
│ run             Run the ActOne container (needs a license.lic).                                 │
│ status          Show ActOne + DB container status.                                              │
│ verify          Wait until the RCM webapp actually serves (login redirect) — not just           │
│                 'container started'.                                                            │
│ down            Stop & remove the containers (keep the DB volume unless --purge).               │
│ up              Orchestrate all phases end-to-end (each idempotent).                            │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```
