# CLI full reference

> Auto-generated from each CLI's live `--help`, recursively covering every sub-command, argument, and option. Do not edit by hand — run `python components/wiki/scripts/gen_cli_reference.py` to refresh. For narrative and worked examples, see the individual CLI pages.

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

### `docenter list-categories`

```text
                                                                                                   
 Usage: docenter list-categories [OPTIONS]                                                         
                                                                                                   
 List all product categories from the local catalog, with product/bundle counts.                   
                                                                                                   
 Examples:                                                                                         
 docenter list-categories                                                                          
 docenter list-categories --json                                                                   
                                                                                                   
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --json          Output machine-readable JSON instead of a table                                 │
│ --help          Show this message and exit.                                                     │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### `docenter list-products`

```text
                                                                                                   
 Usage: docenter list-products [OPTIONS]                                                           
                                                                                                   
 List all products from the local catalog, grouped by category.                                    
                                                                                                   
 Examples:                                                                                         
 docenter list-products                                                                            
 docenter list-products --category aml                                                             
 docenter list-products --aliases                                                                  
                                                                                                   
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --category  -c      TEXT  Filter to one category (e.g. aml, plt, ifm, fmc, xsight). Run without │
│                           to see all.                                                           │
│ --aliases                 Include the alias column                                              │
│ --json                    Output machine-readable JSON instead of a table                       │
│ --help                    Show this message and exit.                                           │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### `docenter list-docs`

```text
                                                                                                   
 Usage: docenter list-docs [OPTIONS] PRODUCT                                                       
                                                                                                   
 List doc bundles for a product, grouped by version and doc type.                                  
                                                                                                   
 Queries the Zoomin API live to discover ALL bundles — including Product Info,                     
 Patch Release Notes, and Release Notifications not in the static config.                          
                                                                                                   
 Examples:                                                                                         
   docenter list-docs actone                                                                       
   docenter list-docs actone --version 10.1                                                        
   docenter list-docs actone --type "Product Info"                                                 
   docenter list-docs actone --type "Patch"                                                        
   docenter list-docs actone --no-discover    (fast, config only)                                  
                                                                                                   
┌─ Arguments ─────────────────────────────────────────────────────────────────────────────────────┐
│ *    product      TEXT  Product slug or alias (e.g. actone, sam, cdd, ifm, xse-sam, svx, hba,   │
│                         surveil-x). Run `list-products` for all 90.                             │
│                         [required]                                                              │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --version      -v      TEXT  Filter by version, e.g. 10.1                                       │
│ --type         -t      TEXT  Filter by doc type (partial match): 'Product Info', 'Product       │
│                              Documentation', 'Release Notes', 'Release Notifications', 'Patch   │
│                              Release Notes'                                                     │
│ --pages        -p            Fetch live page count per bundle                                   │
│ --no-discover                Skip live API discovery; show configured bundles only              │
│ --json                       Output machine-readable JSON instead of a table                    │
│ --help                       Show this message and exit.                                        │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### `docenter download`

```text
                                                                                                   
 Usage: docenter download [OPTIONS] PRODUCT                                                        
                                                                                                   
 Download doc bundles as Markdown or PDF.                                                          
                                                                                                   
 Delegates to extractor/extractor.py (md) or extractor/pdf_exporter.py (pdf).                      
                                                                                                   
┌─ Arguments ─────────────────────────────────────────────────────────────────────────────────────┐
│ *    product      TEXT  Product slug or alias (run `list-products` to see all 90) [required]    │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ *  --format   -f      TEXT  Format: md or pdf [required]                                        │
│    --version  -v      TEXT  Limit to a specific version, e.g. 10.1                              │
│    --bundle   -b      TEXT  Limit to a specific bundle name (partial match)                     │
│    --dry-run                Show what would be downloaded without running                       │
│    --help                   Show this message and exit.                                         │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### `docenter sync`

```text
                                                                                                   
 Usage: docenter sync [OPTIONS]                                                                    
                                                                                                   
 Re-extract only the bundles that changed on the portal since the last sync.                       
                                                                                                   
 Scope is category > product > (default) all locally-present products.                             
 Freshness signal is each bundle's portal 'Updated on' timestamp compared                          
 against docs/sync-state.json.                                                                     
                                                                                                   
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --product      -p      TEXT  Sync one product (slug or alias)                                   │
│ --category     -c      TEXT  Sync all products in a category (e.g. aml, plt, ifm)               │
│ --bundle       -b      TEXT  Limit to bundles whose name contains this text                     │
│ --version      -v      TEXT  Limit to bundles whose name contains this version, e.g. 10.1       │
│ --since                TEXT  Only bundles updated after this date/ISO timestamp, e.g.           │
│                              2026-01-01                                                         │
│ --since-last                 Only bundles updated since the last sync (state.last_sync)         │
│ --format       -f      TEXT  Format to re-extract: md or pdf [default: md]                      │
│ --dry-run                    Show the change set without downloading                            │
│ --force                      Re-extract in-scope bundles regardless of timestamp                │
│ --include-new                Also download in-scope bundles not present locally (backfill).     │
│                              Default only refreshes existing.                                   │
│ --no-refresh                 Diff against committed catalog.yaml instead of live /bundlelist    │
│ --json                       Output machine-readable JSON                                       │
│ --help                       Show this message and exit.                                        │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### `docenter search`

```text
                                                                                                   
 Usage: docenter search [OPTIONS] QUERY                                                            
                                                                                                   
 Search NICE Actimize docs — the live portal by default, or the local corpus with --local.         
                                                                                                   
 Online filtering (hybrid): --product/--doc-version use the portal's                               
 server-side facet filter (labelkeys) for true narrowing; --guide is applied                       
 as a client-side post-filter on the bundle name (the portal has no                                
 guide-type facet). All three already work offline with --local.                                   
                                                                                                   
┌─ Arguments ─────────────────────────────────────────────────────────────────────────────────────┐
│ *    query      TEXT  Search query, e.g. 'LexisNexis Bridger' [required]                        │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --max          -n      INTEGER  Max results to display (default 10) [default: 10]               │
│ --page         -p      INTEGER  Page number (default 1) [default: 1]                            │
│ --local                         Search the local extracted corpus (raw_docs/) instead of the    │
│                                 live portal — no auth needed                                    │
│ --product              TEXT     Filter by product key/name, e.g. actone, ifm, sam               │
│ --doc-version          TEXT     Filter by doc version, e.g. 10.1                                │
│ --guide                TEXT     Filter by guide type, e.g. implementer (online: post-filtered   │
│                                 on bundle name)                                                 │
│ --no-retry                      Don't auto-retry with the portal's spelling suggestion when a   │
│                                 search returns no results.                                      │
│ --json                          Output machine-readable JSON instead of a table                 │
│ --help                          Show this message and exit.                                     │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### `docenter auth`

```text
                                                                                                   
 Usage: docenter auth [OPTIONS] COMMAND [ARGS]...                                                  
                                                                                                   
 Manage authentication with the Zoomin doc portal.                                                 
                                                                                                   
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --help          Show this message and exit.                                                     │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
┌─ Commands ──────────────────────────────────────────────────────────────────────────────────────┐
│ login       Login to the Zoomin doc portal via browser SSO (default).                           │
│ status      Show current Zoomin authentication status and session expiry.                       │
│ logout      Remove saved Zoomin session cookies.                                                │
│ sharepoint  Manage authentication with SharePoint.                                              │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

#### `docenter auth login`

```text
                                                                                                   
 Usage: docenter auth login [OPTIONS]                                                              
                                                                                                   
 Login to the Zoomin doc portal via browser SSO (default).                                         
                                                                                                   
 Opens a browser window — complete your Microsoft/NICE SSO login interactively.                    
 The CLI captures your session automatically when done.                                            
                                                                                                   
 Use --creds to auto-fill the login form from .env instead of SSO.                                 
 Use --http for a browser-free login from .env (fastest; password accounts only).                  
 Use --url to target the alternate Zoomin URL.                                                     
                                                                                                   
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --creds                Auto-fill login form using DOCENTER_EMAIL / DOCENTER_PASSWORD from .env  │
│ --url    -u      TEXT  Override portal URL (e.g. the alternate niceactimize.zoominsoftware.io   │
│                        site)                                                                    │
│ --http                 Log in via the browser-free HTTP API using DOCENTER_EMAIL /              │
│                        DOCENTER_PASSWORD (no Playwright).                                       │
│ --help                 Show this message and exit.                                              │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

#### `docenter auth status`

```text
                                                                                                   
 Usage: docenter auth status [OPTIONS]                                                             
                                                                                                   
 Show current Zoomin authentication status and session expiry.                                     
                                                                                                   
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --help          Show this message and exit.                                                     │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

#### `docenter auth logout`

```text
                                                                                                   
 Usage: docenter auth logout [OPTIONS]                                                             
                                                                                                   
 Remove saved Zoomin session cookies.                                                              
                                                                                                   
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --help          Show this message and exit.                                                     │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

#### `docenter auth sharepoint`

```text
                                                                                                   
 Usage: docenter auth sharepoint [OPTIONS] COMMAND [ARGS]...                                       
                                                                                                   
 Manage authentication with SharePoint.                                                            
                                                                                                   
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --help          Show this message and exit.                                                     │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
┌─ Commands ──────────────────────────────────────────────────────────────────────────────────────┐
│ login   Open a browser for SharePoint SSO login and save session cookies.                       │
│ status  Show current SharePoint authentication status.                                          │
│ logout  Remove saved SharePoint session cookies.                                                │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

##### `docenter auth sharepoint login`

```text
                                                                                                   
 Usage: docenter auth sharepoint login [OPTIONS]                                                   
                                                                                                   
 Open a browser for SharePoint SSO login and save session cookies.                                 
                                                                                                   
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --help          Show this message and exit.                                                     │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

##### `docenter auth sharepoint status`

```text
                                                                                                   
 Usage: docenter auth sharepoint status [OPTIONS]                                                  
                                                                                                   
 Show current SharePoint authentication status.                                                    
                                                                                                   
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --help          Show this message and exit.                                                     │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

##### `docenter auth sharepoint logout`

```text
                                                                                                   
 Usage: docenter auth sharepoint logout [OPTIONS]                                                  
                                                                                                   
 Remove saved SharePoint session cookies.                                                          
                                                                                                   
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --help          Show this message and exit.                                                     │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### `docenter sharepoint`

```text
                                                                                                   
 Usage: docenter sharepoint [OPTIONS] COMMAND [ARGS]...                                            
                                                                                                   
 Upload documents to SharePoint.                                                                   
                                                                                                   
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --help          Show this message and exit.                                                     │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
┌─ Commands ──────────────────────────────────────────────────────────────────────────────────────┐
│ upload  Upload extracted docs to SharePoint.                                                    │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

#### `docenter sharepoint upload`

```text
                                                                                                   
 Usage: docenter sharepoint upload [OPTIONS] PRODUCT                                               
                                                                                                   
 Upload extracted docs to SharePoint.                                                              
                                                                                                   
 Requires: docenter auth sharepoint login                                                          
                                                                                                   
 Examples:                                                                                         
   docenter sharepoint upload actone --version 10.1                                                
   docenter sharepoint upload actone --format pdf --dest "Shared Documents/ActWise/pdfs"           
                                                                                                   
┌─ Arguments ─────────────────────────────────────────────────────────────────────────────────────┐
│ *    product      TEXT  Product slug or alias (run `list-products` to see all 90) [required]    │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --format   -f      TEXT  Format to upload: md or pdf [default: md]                              │
│ --version  -v      TEXT  Limit to a specific version, e.g. 10.1                                 │
│ --dest     -d      TEXT  Destination folder path within the SharePoint site                     │
│                          [default: Shared Documents/ActWise]                                    │
│ --dry-run                List files without uploading                                           │
│ --help                   Show this message and exit.                                            │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### `docenter catalog`

```text
                                                                                                   
 Usage: docenter catalog [OPTIONS] COMMAND [ARGS]...                                               
                                                                                                   
 Manage the local docs/catalog.yaml product catalog.                                               
                                                                                                   
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --help          Show this message and exit.                                                     │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
┌─ Commands ──────────────────────────────────────────────────────────────────────────────────────┐
│ refresh  Rebuild docs/catalog.yaml from the live Zoomin API.                                    │
│ status   Show local catalog metadata: when it was last refreshed and totals.                    │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

#### `docenter catalog refresh`

```text
                                                                                                   
 Usage: docenter catalog refresh [OPTIONS]                                                         
                                                                                                   
 Rebuild docs/catalog.yaml from the live Zoomin API.                                               
                                                                                                   
 Walks /api/categories + /api/taxonomy, then calls /api/bundlelist for every                       
 label key in the expanded set. Takes 10-20 min on a full portal pass.                             
 Requires a valid session — run docenter auth login first.                                         
                                                                                                   
 After the YAML is regenerated, the rendered docs/catalog.md is rebuilt                            
 unless --skip-md is given.                                                                        
                                                                                                   
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --skip-md          Skip regenerating docs/catalog.md                                            │
│ --help             Show this message and exit.                                                  │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

#### `docenter catalog status`

```text
                                                                                                   
 Usage: docenter catalog status [OPTIONS]                                                          
                                                                                                   
 Show local catalog metadata: when it was last refreshed and totals.                               
                                                                                                   
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --help          Show this message and exit.                                                     │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### `docenter skill`

```text
                                                                                                   
 Usage: docenter skill [OPTIONS] COMMAND [ARGS]...                                                 
                                                                                                   
 Maintain the actimize-docenter AI skill file.                                                     
                                                                                                   
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --help          Show this message and exit.                                                     │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
┌─ Commands ──────────────────────────────────────────────────────────────────────────────────────┐
│ sync-reference  Regenerate the Product Keys Reference table in the actimize-docenter skill      │
│                 from the live catalog, so product names and versions never go stale.            │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

#### `docenter skill sync-reference`

```text
                                                                                                   
 Usage: docenter skill sync-reference [OPTIONS]                                                    
                                                                                                   
 Regenerate the Product Keys Reference table in the actimize-docenter skill from the live catalog, 
 so product names and versions never go stale.                                                     
                                                                                                   
 Updates only the block between the generated-section markers in SKILL.md.                         
                                                                                                   
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --check            Exit non-zero if the skill table is out of date (no write). For CI.          │
│ --dry-run          Print the regenerated table without writing.                                 │
│ --json             Machine-readable output.                                                     │
│ --help             Show this message and exit.                                                  │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### `docenter wiki`

```text
                                                                                                   
 Usage: docenter wiki [OPTIONS] COMMAND [ARGS]...                                                  
                                                                                                   
 Generate a deterministic, cross-linked documentation wiki from raw_docs/.                         
                                                                                                   
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --help          Show this message and exit.                                                     │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
┌─ Commands ──────────────────────────────────────────────────────────────────────────────────────┐
│ build  Generate a navigable, citation-backed wiki under wiki/ - purely from raw_docs/.          │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

#### `docenter wiki build`

```text
                                                                                                   
 Usage: docenter wiki build [OPTIONS]                                                              
                                                                                                   
 Generate a navigable, citation-backed wiki under wiki/ - purely from raw_docs/.                   
                                                                                                   
 Emits a global landing page, a per-product index, and a per-bundle index that                     
 lists every topic with a link to its official portal page. No LLM, no network:                    
 re-running produces identical output (a pure function of the corpus).                             
                                                                                                   
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --product  -p      TEXT  Build only one product (slug), e.g. actone                             │
│ --json                   Output a machine-readable build summary                                │
│ --help                   Show this message and exit.                                            │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### `docenter index`

```text
                                                                                                   
 Usage: docenter index [OPTIONS] COMMAND [ARGS]...                                                 
                                                                                                   
 Generate the catalog taxonomy index (category -> product -> bundle).                              
                                                                                                   
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --help          Show this message and exit.                                                     │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
┌─ Commands ──────────────────────────────────────────────────────────────────────────────────────┐
│ build   Emit raw_docs/index/ from the catalog - the taxonomy as data, not folders.              │
│ status  Show whether raw_docs/index/ exists and summarize its contents.                         │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

#### `docenter index build`

```text
                                                                                                   
 Usage: docenter index build [OPTIONS]                                                             
                                                                                                   
 Emit raw_docs/index/ from the catalog - the taxonomy as data, not folders.                        
                                                                                                   
 Writes by_product.json, by_category.json, and bundles.json (a reverse index                       
 that records, for every bundle, all products that reference it plus a single                      
 canonical owner). Pure function of docs/catalog.yaml: no corpus mutation, no                      
 network. This is the foundation the dedup/migration and publish steps read.                       
                                                                                                   
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --json          Output a machine-readable build summary                                         │
│ --help          Show this message and exit.                                                     │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

#### `docenter index status`

```text
                                                                                                   
 Usage: docenter index status [OPTIONS]                                                            
                                                                                                   
 Show whether raw_docs/index/ exists and summarize its contents.                                   
                                                                                                   
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --json          Output machine-readable status                                                  │
│ --help          Show this message and exit.                                                     │
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

### `actone fetch-spec`

```text
usage: python.exe -m actone.fetch_spec [-h] [--url URL] [--user USER] [--password PASSWORD]

options:
  -h, --help           show this help message and exit
  --url URL
  --user USER
  --password PASSWORD
```

### `actone generate`

```text
usage: python.exe -m actone.generate_collection [-h] [--spec SPEC] [--version VERSION]
                                                [--name NAME] [--out OUT]

options:
  -h, --help         show this help message and exit
  --spec SPEC        OpenAPI spec (yaml or json)
  --version VERSION  ActOne version label, e.g. 10.0.0.69_SP15
  --name NAME        Collection name (overrides default)
  --out OUT          Output collection path
```

### `actone provision`

```text
usage: python.exe -m actone.provision_from_url [-h] [--url URL] [--user USER]
                                               [--password PASSWORD] [--push]

options:
  -h, --help           show this help message and exit
  --url URL
  --user USER
  --password PASSWORD
  --push
```

### `actone sanitize`

```text
usage: python.exe -m actone.sanitize_spec [-h] [--in INP] [--out OUT]

options:
  -h, --help  show this help message and exit
  --in INP
  --out OUT
```

### `actone review`

```text
usage: python.exe -m actone.review_config [-h] [--url URL] [--user USER] [--password PASSWORD]

options:
  -h, --help           show this help message and exit
  --url URL
  --user USER
  --password PASSWORD
```

### `actone ops`

```text
                                                                                                   
 Usage: actone ops [OPTIONS] COMMAND [ARGS]...                                                     
                                                                                                   
 Spec-driven runtime ops over the ActOne Extend REST API (discovery: search/describe/call).        
 Read-only in P1.                                                                                  
                                                                                                   
+- Options ---------------------------------------------------------------------------------------+
| --help          Show this message and exit.                                                     |
+-------------------------------------------------------------------------------------------------+
+- Commands --------------------------------------------------------------------------------------+
| search      Find operations by keyword over operationId/summary/tags/path.                      |
| describe    Show full detail (params, body example, access) for one operationId.                |
| tags        List operation tags (domains) and counts.                                           |
| list        List ALL operations (no cap), optionally by tag or grouped.                         |
| call        Invoke an operation live. Reads always run; writes need --allow-write (or           |
|             ACTONE_ALLOW_WRITES).                                                               |
| env         List configured ActOne environments (never shows passwords).                        |
| version     Login and report the detected ActOne version.                                       |
| sync-skill  Regenerate the auto-generated domains table in skills/actone-ops/SKILL.md from the  |
|             spec.                                                                               |
| soap        Curated ActOne SOAP ops (admin surface the REST API lacks, e.g. create a Business   |
|             Unit). Reads always run; writes need --allow-write.                                 |
+-------------------------------------------------------------------------------------------------+
```

#### `actone ops search`

```text
                                                                                                   
 Usage: actone ops search [OPTIONS] [QUERY]                                                        
                                                                                                   
 Find operations by keyword over operationId/summary/tags/path.                                    
                                                                                                   
+- Arguments -------------------------------------------------------------------------------------+
|   [query]      TEXT  Search terms (empty lists everything).                                     |
+-------------------------------------------------------------------------------------------------+
+- Options ---------------------------------------------------------------------------------------+
| --limit       -n      INTEGER  [default: 25]                                                    |
| --reads-only                   Only show read (GET) operations.                                 |
| --spec                TEXT     Spec path override (else cached/bundled).                        |
| --help                         Show this message and exit.                                      |
+-------------------------------------------------------------------------------------------------+
```

#### `actone ops describe`

```text
                                                                                                   
 Usage: actone ops describe [OPTIONS] OP_ID                                                        
                                                                                                   
 Show full detail (params, body example, access) for one operationId.                              
                                                                                                   
+- Arguments -------------------------------------------------------------------------------------+
| *    op_id      TEXT  operationId (from `ops search`). [required]                               |
+-------------------------------------------------------------------------------------------------+
+- Options ---------------------------------------------------------------------------------------+
| --spec        TEXT                                                                              |
| --help              Show this message and exit.                                                 |
+-------------------------------------------------------------------------------------------------+
```

#### `actone ops tags`

```text
                                                                                                   
 Usage: actone ops tags [OPTIONS]                                                                  
                                                                                                   
 List operation tags (domains) and counts.                                                         
                                                                                                   
+- Options ---------------------------------------------------------------------------------------+
| --spec        TEXT                                                                              |
| --help              Show this message and exit.                                                 |
+-------------------------------------------------------------------------------------------------+
```

#### `actone ops list`

```text
                                                                                                   
 Usage: actone ops list [OPTIONS]                                                                  
                                                                                                   
 List ALL operations (no cap), optionally by tag or grouped.                                       
                                                                                                   
+- Options ---------------------------------------------------------------------------------------+
| --reads-only              Only read (GET) operations.                                           |
| --tag               TEXT  Filter to one domain/tag.                                             |
| --group                   Group results by tag.                                                 |
| --spec              TEXT                                                                        |
| --help                    Show this message and exit.                                           |
+-------------------------------------------------------------------------------------------------+
```

#### `actone ops call`

```text
                                                                                                   
 Usage: actone ops call [OPTIONS] OP_ID                                                            
                                                                                                   
 Invoke an operation live. Reads always run; writes need --allow-write (or ACTONE_ALLOW_WRITES).   
                                                                                                   
+- Arguments -------------------------------------------------------------------------------------+
| *    op_id      TEXT  operationId to invoke. [required]                                         |
+-------------------------------------------------------------------------------------------------+
+- Options ---------------------------------------------------------------------------------------+
| --p                  TEXT  Param as key=value (repeatable).                                     |
| --params             TEXT  All params as one JSON object.                                       |
| --body               TEXT  Request body as JSON.                                                |
| --spec               TEXT                                                                       |
| --env                TEXT  Named ActOne environment (see `actone ops env`).                     |
| --url                TEXT  ActOne base URL (else .env).                                         |
| --user               TEXT                                                                       |
| --password           TEXT                                                                       |
| --allow-write              Permit write ops (POST/PUT/DELETE/PATCH). Also honored via           |
|                            ACTONE_ALLOW_WRITES=true. Off by default (read-only gate).           |
| --help                     Show this message and exit.                                          |
+-------------------------------------------------------------------------------------------------+
```

#### `actone ops env`

```text
                                                                                                   
 Usage: actone ops env [OPTIONS]                                                                   
                                                                                                   
 List configured ActOne environments (never shows passwords).                                      
                                                                                                   
+- Options ---------------------------------------------------------------------------------------+
| --help          Show this message and exit.                                                     |
+-------------------------------------------------------------------------------------------------+
```

#### `actone ops version`

```text
                                                                                                   
 Usage: actone ops version [OPTIONS]                                                               
                                                                                                   
 Login and report the detected ActOne version.                                                     
                                                                                                   
+- Options ---------------------------------------------------------------------------------------+
| --env             TEXT  Named ActOne environment (see `actone ops env`).                        |
| --url             TEXT                                                                          |
| --user            TEXT                                                                          |
| --password        TEXT                                                                          |
| --help                  Show this message and exit.                                             |
+-------------------------------------------------------------------------------------------------+
```

#### `actone ops sync-skill`

```text
                                                                                                   
 Usage: actone ops sync-skill [OPTIONS]                                                            
                                                                                                   
 Regenerate the auto-generated domains table in skills/actone-ops/SKILL.md from the spec.          
                                                                                                   
+- Options ---------------------------------------------------------------------------------------+
| --check                Exit non-zero if the table is stale (no write). For CI.                  |
| --dry-run              Print the regenerated table without writing.                             |
| --spec           TEXT                                                                           |
| --help                 Show this message and exit.                                              |
+-------------------------------------------------------------------------------------------------+
```

#### `actone ops soap`

```text
                                                                                                   
 Usage: actone ops soap [OPTIONS] COMMAND [ARGS]...                                                
                                                                                                   
 Curated ActOne SOAP ops (admin surface the REST API lacks, e.g. create a Business Unit). Reads    
 always run; writes need --allow-write.                                                            
                                                                                                   
+- Options ---------------------------------------------------------------------------------------+
| --help          Show this message and exit.                                                     |
+-------------------------------------------------------------------------------------------------+
+- Commands --------------------------------------------------------------------------------------+
| list      List the curated SOAP operations (offline).                                           |
| describe  Show one SOAP op's service/operation/access/params.                                   |
| call      Invoke a curated SOAP op. Reads always run; writes need --allow-write.                |
+-------------------------------------------------------------------------------------------------+
```

##### `actone ops soap list`

```text
                                                                                                   
 Usage: actone ops soap list [OPTIONS]                                                             
                                                                                                   
 List the curated SOAP operations (offline).                                                       
                                                                                                   
+- Options ---------------------------------------------------------------------------------------+
| --help          Show this message and exit.                                                     |
+-------------------------------------------------------------------------------------------------+
```

##### `actone ops soap describe`

```text
                                                                                                   
 Usage: actone ops soap describe [OPTIONS] OP_ID                                                   
                                                                                                   
 Show one SOAP op's service/operation/access/params.                                               
                                                                                                   
+- Arguments -------------------------------------------------------------------------------------+
| *    op_id      TEXT  SOAP opId (from `ops soap list`). [required]                              |
+-------------------------------------------------------------------------------------------------+
+- Options ---------------------------------------------------------------------------------------+
| --help          Show this message and exit.                                                     |
+-------------------------------------------------------------------------------------------------+
```

##### `actone ops soap call`

```text
                                                                                                   
 Usage: actone ops soap call [OPTIONS] OP_ID                                                       
                                                                                                   
 Invoke a curated SOAP op. Reads always run; writes need --allow-write.                            
                                                                                                   
+- Arguments -------------------------------------------------------------------------------------+
| *    op_id      TEXT  SOAP opId (from `ops soap list`). [required]                              |
+-------------------------------------------------------------------------------------------------+
+- Options ---------------------------------------------------------------------------------------+
| --p                  TEXT  Arg as key=value (repeatable).                                       |
| --params             TEXT  All args as one JSON object.                                         |
| --env                TEXT  Named ActOne environment (see `actone ops env`).                     |
| --url                TEXT  ActOne base URL (else .env).                                         |
| --user               TEXT                                                                       |
| --password           TEXT                                                                       |
| --allow-write              Permit write SOAP ops (create/remove). Also honored via              |
|                            ACTONE_ALLOW_WRITES=true. Off by default (read-only gate).           |
| --help                     Show this message and exit.                                          |
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

### `actone-data ping`

```text
                                                                                                   
 Usage: actone-data ping [OPTIONS]                                                                 
                                                                                                   
 Test the DB connection: prints server version, schema, and the ActOne sentinel check.             
                                                                                                   
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --profile   -p      TEXT     Named profile from actone-data.yaml (default: built-in local).     │
│                              [default: local]                                                   │
│ --host              TEXT     DB host (overrides profile/env).                                   │
│ --port              INTEGER  DB port.                                                           │
│ --name              TEXT     Database name.                                                     │
│ --user              TEXT     DB user.                                                           │
│ --password          TEXT     DB password (prefer env ACTONE_DB_PASSWORD).                       │
│ --schema            TEXT     Schema (default: actone).                                          │
│ --dsn               TEXT     Full libpq DSN (wins over discrete fields).                        │
│ --help                       Show this message and exit.                                        │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### `actone-data version`

```text
                                                                                                   
 Usage: actone-data version [OPTIONS]                                                              
                                                                                                   
 Detect the ActOne product version from the DB (falls back to the bundled doc version).            
                                                                                                   
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --profile  -p      TEXT  Named profile (default: built-in local). [default: local]              │
│ --dsn              TEXT  Full libpq DSN (wins over profile/env).                                │
│ --help                   Show this message and exit.                                            │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### `actone-data eval`

```text
                                                                                                   
 Usage: actone-data eval [OPTIONS]                                                                 
                                                                                                   
 Run the NL->SQL eval set through the guardrail + execute path and print a scoreboard.             
                                                                                                   
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --profile  -p      TEXT  Named profile (default: built-in local). [default: local]              │
│ --dsn              TEXT  Full libpq DSN (wins over profile/env).                                │
│ --set              TEXT  A single eval-set YAML (default: all under actone_data/data/evals/).   │
│ --verbose  -v            Show per-case detail (views/rows or failure reasons).                  │
│ --help                   Show this message and exit.                                            │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### `actone-data schema`

```text
                                                                                                   
 Usage: actone-data schema [OPTIONS] COMMAND [ARGS]...                                             
                                                                                                   
 Introspect the live ActOne schema (v_acm_* views).                                                
                                                                                                   
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --help          Show this message and exit.                                                     │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
┌─ Commands ──────────────────────────────────────────────────────────────────────────────────────┐
│ list     List the live v_acm_* views and their column counts.                                   │
│ build    Build the schema pack (introspection + doc enrichment) and write JSON.                 │
│ show     Show a view's family/preference/FKs and columns from the schema pack.                  │
│ summary  Summarize the schema pack (view/column/coverage/preference counts).                    │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

#### `actone-data schema list`

```text
                                                                                                   
 Usage: actone-data schema list [OPTIONS]                                                          
                                                                                                   
 List the live v_acm_* views and their column counts.                                              
                                                                                                   
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --profile     -p      TEXT  Named profile (default: built-in local). [default: local]           │
│ --dsn                 TEXT  Full libpq DSN (wins over profile/env).                             │
│ --names-only                Print bare view names (no table), one per line.                     │
│ --help                      Show this message and exit.                                         │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

#### `actone-data schema build`

```text
                                                                                                   
 Usage: actone-data schema build [OPTIONS]                                                         
                                                                                                   
 Build the schema pack (introspection + doc enrichment) and write JSON.                            
                                                                                                   
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --profile      -p      TEXT  Named profile (default: built-in local). [default: local]          │
│ --dsn                  TEXT  Full libpq DSN (wins over profile/env).                            │
│ --bundle               TEXT  Doc bundle dir (default: ActOne 10.2 Implementer Guide).           │
│ --doc-version          TEXT  Override the doc/pack version when the DB carries no stamp.        │
│ --out                  TEXT  Output path (default: bundled data/schema-pack-actone-<ver>.json). │
│ --help                       Show this message and exit.                                        │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

#### `actone-data schema show`

```text
                                                                                                   
 Usage: actone-data schema show [OPTIONS] VIEW                                                     
                                                                                                   
 Show a view's family/preference/FKs and columns from the schema pack.                             
                                                                                                   
┌─ Arguments ─────────────────────────────────────────────────────────────────────────────────────┐
│ *    view      TEXT  View name, e.g. v_acm_items. [required]                                    │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --pack        TEXT  Pack path (default: ACTONE_DATA_PACK or bundled).                           │
│ --help              Show this message and exit.                                                 │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

#### `actone-data schema summary`

```text
                                                                                                   
 Usage: actone-data schema summary [OPTIONS]                                                       
                                                                                                   
 Summarize the schema pack (view/column/coverage/preference counts).                               
                                                                                                   
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --pack        TEXT  Pack path (default: ACTONE_DATA_PACK or bundled).                           │
│ --help              Show this message and exit.                                                 │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### `actone-data query`

```text
                                                                                                   
 Usage: actone-data query [OPTIONS] COMMAND [ARGS]...                                              
                                                                                                   
 Validate or run a read-only SELECT over the v_acm_* views.                                        
                                                                                                   
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --help          Show this message and exit.                                                     │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
┌─ Commands ──────────────────────────────────────────────────────────────────────────────────────┐
│ validate  Dry-run the guardrail pipeline on a SQL string (no execution).                        │
│ run       Validate and execute a read-only SELECT; prints results.                              │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

#### `actone-data query validate`

```text
                                                                                                   
 Usage: actone-data query validate [OPTIONS] SQL                                                   
                                                                                                   
 Dry-run the guardrail pipeline on a SQL string (no execution).                                    
                                                                                                   
┌─ Arguments ─────────────────────────────────────────────────────────────────────────────────────┐
│ *    sql      TEXT  SQL to validate. [required]                                                 │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --profile   -p      TEXT     Profile used to fetch the live allowlist. [default: local]         │
│ --dsn               TEXT     Full libpq DSN (wins over profile/env).                            │
│ --max-rows          INTEGER  Row limit to inject/clamp to (cap 1000). [default: 100]            │
│ --help                       Show this message and exit.                                        │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

#### `actone-data query run`

```text
                                                                                                   
 Usage: actone-data query run [OPTIONS] SQL                                                        
                                                                                                   
 Validate and execute a read-only SELECT; prints results.                                          
                                                                                                   
┌─ Arguments ─────────────────────────────────────────────────────────────────────────────────────┐
│ *    sql      TEXT  SQL to run. [required]                                                      │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --profile   -p      TEXT     Named profile (default: built-in local). [default: local]          │
│ --dsn               TEXT     Full libpq DSN (wins over profile/env).                            │
│ --max-rows          INTEGER  Max rows to return (cap 1000). [default: 100]                      │
│ --question  -q      TEXT     The user question, recorded for audit.                             │
│ --format    -f      TEXT     Output format: table | json | csv. [default: table]                │
│ --help                       Show this message and exit.                                        │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### `actone-data audit`

```text
                                                                                                   
 Usage: actone-data audit [OPTIONS] COMMAND [ARGS]...                                              
                                                                                                   
 Inspect the query audit log.                                                                      
                                                                                                   
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --help          Show this message and exit.                                                     │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
┌─ Commands ──────────────────────────────────────────────────────────────────────────────────────┐
│ tail  Show the most recent audit records.                                                       │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

#### `actone-data audit tail`

```text
                                                                                                   
 Usage: actone-data audit tail [OPTIONS]                                                           
                                                                                                   
 Show the most recent audit records.                                                               
                                                                                                   
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --n     -n      INTEGER  Number of records to show. [default: 20]                               │
│ --help                   Show this message and exit.                                            │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### `actone-data env`

```text
                                                                                                   
 Usage: actone-data env [OPTIONS] COMMAND [ARGS]...                                                
                                                                                                   
 List the configured ActOne environments (DB profiles).                                            
                                                                                                   
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --help          Show this message and exit.                                                     │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
┌─ Commands ──────────────────────────────────────────────────────────────────────────────────────┐
│ list  List configured environments (metadata only; never passwords).                            │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

#### `actone-data env list`

```text
                                                                                                   
 Usage: actone-data env list [OPTIONS]                                                             
                                                                                                   
 List configured environments (metadata only; never passwords).                                    
                                                                                                   
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --help          Show this message and exit.                                                     │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### `actone-data docs`

```text
                                                                                                   
 Usage: actone-data docs [OPTIONS] COMMAND [ARGS]...                                               
                                                                                                   
 Parse the v_acm_* doc pages (descriptions + FK graph).                                            
                                                                                                   
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --help          Show this message and exit.                                                     │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
┌─ Commands ──────────────────────────────────────────────────────────────────────────────────────┐
│ enrich  Parse the v_acm_* doc pages and resolve the FK graph.                                   │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

#### `actone-data docs enrich`

```text
                                                                                                   
 Usage: actone-data docs enrich [OPTIONS]                                                          
                                                                                                   
 Parse the v_acm_* doc pages and resolve the FK graph.                                             
                                                                                                   
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --profile  -p      TEXT  Profile used to introspect live views for FK reconciliation.           │
│                          [default: local]                                                       │
│ --dsn              TEXT  Full libpq DSN (wins over profile/env).                                │
│ --bundle           TEXT  Doc bundle dir (default: the ActOne 10.2 Implementer Guide).           │
│ --page             TEXT  Dump resolved columns/FKs for a single view (e.g. v_acm_items).        │
│ --offline                Skip DB introspection; reconcile FKs against the parsed page names     │
│                          only.                                                                  │
│ --help                   Show this message and exit.                                            │
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

### `actone-utils list`

```text
                                                                                                   
 Usage: actone-utils list [OPTIONS]                                                                
                                                                                                   
 List all utilities in the catalog.                                                                
                                                                                                   
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --json          Emit JSON.                                                                      │
│ --help          Show this message and exit.                                                     │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### `actone-utils search`

```text
                                                                                                   
 Usage: actone-utils search [OPTIONS] QUERY                                                        
                                                                                                   
 Search utilities by keyword (name/title/tool/tags/summary).                                       
                                                                                                   
┌─ Arguments ─────────────────────────────────────────────────────────────────────────────────────┐
│ *    query      TEXT  [required]                                                                │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --limit        INTEGER  [default: 25]                                                           │
│ --json                                                                                          │
│ --help                  Show this message and exit.                                             │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### `actone-utils describe`

```text
                                                                                                   
 Usage: actone-utils describe [OPTIONS] NAME                                                       
                                                                                                   
 Show a utility's parameters, access, and source doc.                                              
                                                                                                   
┌─ Arguments ─────────────────────────────────────────────────────────────────────────────────────┐
│ *    name      TEXT  [required]                                                                 │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --json                                                                                          │
│ --help          Show this message and exit.                                                     │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### `actone-utils run`

```text
                                                                                                   
 Usage: actone-utils run [OPTIONS] NAME                                                            
                                                                                                   
 Assemble and run a utility. Dry-run by default; --yes for a real state-changing run.              
                                                                                                   
┌─ Arguments ─────────────────────────────────────────────────────────────────────────────────────┐
│ *    name      TEXT  Utility name (see `list`). [required]                                      │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --set      -s               TEXT  Parameter as KEY=VALUE (repeatable).                          │
│ --arg      -a               TEXT  Raw arg appended verbatim (repeatable; for options not in the │
│                                   catalog).                                                     │
│ --dry-run      --execute          Assemble only (default), or actually run. [default: dry-run]  │
│ --yes                             Confirm a state-changing real run.                            │
│ --backend                   TEXT  Override backend: local|ssh|winrm|container.                  │
│ --config                    PATH  Path to actone-utils.yaml.                                    │
│ --json                                                                                          │
│ --help                            Show this message and exit.                                   │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### `actone-utils backends`

```text
                                                                                                   
 Usage: actone-utils backends [OPTIONS]                                                            
                                                                                                   
 Show the available execution backends.                                                            
                                                                                                   
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --config        PATH                                                                            │
│ --help                Show this message and exit.                                               │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### `actone-utils doctor`

```text
                                                                                                   
 Usage: actone-utils doctor [OPTIONS]                                                              
                                                                                                   
 Show the effective config: backend, paths, JDK, utilities.env.                                    
                                                                                                   
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --config         PATH                                                                           │
│ --backend        TEXT                                                                           │
│ --help                 Show this message and exit.                                              │
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

### `ndc products`

```text
                                                                                                   
 Usage: ndc products [OPTIONS]                                                                     
                                                                                                   
 List curated product keys (friendly aliases for plne ids + components).                           
                                                                                                   
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --json                                                                                          │
│ --help          Show this message and exit.                                                     │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### `ndc find`

```text
                                                                                                   
 Usage: ndc find [OPTIONS] PRODUCT [VERSION]                                                       
                                                                                                   
 Locate a package by product + version — e.g. `ndc find actone 10.2`.                              
                                                                                                   
 Answers from the offline catalog cache (fast/offline); use --online to hit                        
 the live portal, or run `ndc catalog refresh` to (re)build the cache.                             
                                                                                                   
┌─ Arguments ─────────────────────────────────────────────────────────────────────────────────────┐
│ *    product        TEXT  Product key or alias (see `ndc products`), e.g. actone [required]     │
│      [version]      TEXT  Version substring, e.g. 10.2                                          │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --variant        TEXT  Full | SP | Patch                                                        │
│ --online               Query the live portal instead of the cache                               │
│ --json                                                                                          │
│ --help                 Show this message and exit.                                              │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### `ndc product-lines`

```text
                                                                                                   
 Usage: ndc product-lines [OPTIONS]                                                                
                                                                                                   
 List product lines (manufacturers) available on the portal.                                       
                                                                                                   
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --json                                                                                          │
│ --help          Show this message and exit.                                                     │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### `ndc search`

```text
                                                                                                   
 Usage: ndc search [OPTIONS] [QUERY]                                                               
                                                                                                   
 Search product releases. Returns element/plne ids for `list-files` / `download`.                  
                                                                                                   
 Pass a curated key with --product (see `ndc products`) to auto-scope the                          
 search to one component's plne and title pattern.                                                 
                                                                                                   
┌─ Arguments ─────────────────────────────────────────────────────────────────────────────────────┐
│   [query]      TEXT  e.g. 'ActOne', 'AIS', 'SAM 10.2' (optional if --product given)             │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --product  -p      TEXT     Curated product key (see `ndc products`), e.g. actone               │
│ --variant          TEXT     Filter: Full | SP | Patch                                           │
│ --version          TEXT     Filter by version substring, e.g. 6.0                               │
│ --max              INTEGER  Max rows [default: 40]                                              │
│ --json                                                                                          │
│ --help                      Show this message and exit.                                         │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### `ndc recent`

```text
                                                                                                   
 Usage: ndc recent [OPTIONS]                                                                       
                                                                                                   
 List recent product releases posted to the portal.                                                
                                                                                                   
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --json                                                                                          │
│ --help          Show this message and exit.                                                     │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### `ndc list-files`

```text
                                                                                                   
 Usage: ndc list-files [OPTIONS] ELEMENT                                                           
                                                                                                   
 List the downloadable files in a release (filename, size, MD5).                                   
                                                                                                   
┌─ Arguments ─────────────────────────────────────────────────────────────────────────────────────┐
│ *    element      TEXT  Release element id (from `search`) [required]                           │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --plne            TEXT  Product-line id (from `search`)                                         │
│ --cert-num        TEXT  Optional cert_num from `search`                                         │
│ --json                                                                                          │
│ --help                  Show this message and exit.                                             │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### `ndc download`

```text
                                                                                                   
 Usage: ndc download [OPTIONS] ELEMENT                                                             
                                                                                                   
 Download the installation package files for a release (with MD5 verification).                    
                                                                                                   
┌─ Arguments ─────────────────────────────────────────────────────────────────────────────────────┐
│ *    element      TEXT  Release element id (from `search`) [required]                           │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --plne             TEXT  Product-line id (from `search`)                                        │
│ --cert-num         TEXT  Optional cert_num from `search`                                        │
│ --dest             PATH  Destination directory [default: packages]                              │
│ --match            TEXT  Only files whose name contains this substring                          │
│ --dry-run                List what would be downloaded                                          │
│ --no-verify              Skip MD5 verification                                                  │
│ --help                   Show this message and exit.                                            │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### `ndc auth`

```text
                                                                                                   
 Usage: ndc auth [OPTIONS] COMMAND [ARGS]...                                                       
                                                                                                   
 Authenticate to the NICE Download Center.                                                         
                                                                                                   
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --help          Show this message and exit.                                                     │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
┌─ Commands ──────────────────────────────────────────────────────────────────────────────────────┐
│ login   Log in using credentials from .env (NDC_EMAIL / NDC_PASSWORD) or --email/--password.    │
│ status  Show whether the stored session is still valid.                                         │
│ logout  Clear the stored session.                                                               │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

#### `ndc auth login`

```text
                                                                                                   
 Usage: ndc auth login [OPTIONS]                                                                   
                                                                                                   
 Log in using credentials from .env (NDC_EMAIL / NDC_PASSWORD) or --email/--password.              
                                                                                                   
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --email           TEXT  Override NDC_EMAIL from .env                                            │
│ --password        TEXT  Override NDC_PASSWORD from .env                                         │
│ --help                  Show this message and exit.                                             │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

#### `ndc auth status`

```text
                                                                                                   
 Usage: ndc auth status [OPTIONS]                                                                  
                                                                                                   
 Show whether the stored session is still valid.                                                   
                                                                                                   
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --help          Show this message and exit.                                                     │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

#### `ndc auth logout`

```text
                                                                                                   
 Usage: ndc auth logout [OPTIONS]                                                                  
                                                                                                   
 Clear the stored session.                                                                         
                                                                                                   
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --help          Show this message and exit.                                                     │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### `ndc catalog`

```text
                                                                                                   
 Usage: ndc catalog [OPTIONS] COMMAND [ARGS]...                                                    
                                                                                                   
 Build/inspect the offline package catalog cache.                                                  
                                                                                                   
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --help          Show this message and exit.                                                     │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
┌─ Commands ──────────────────────────────────────────────────────────────────────────────────────┐
│ refresh  Sweep the portal and (re)build the offline catalog cache.                              │
│ status   Show catalog freshness and per-product release counts.                                 │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

#### `ndc catalog refresh`

```text
                                                                                                   
 Usage: ndc catalog refresh [OPTIONS]                                                              
                                                                                                   
 Sweep the portal and (re)build the offline catalog cache.                                         
                                                                                                   
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --product  -p      TEXT  Refresh only this product key (default: all)                           │
│ --help                   Show this message and exit.                                            │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

#### `ndc catalog status`

```text
                                                                                                   
 Usage: ndc catalog status [OPTIONS]                                                               
                                                                                                   
 Show catalog freshness and per-product release counts.                                            
                                                                                                   
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --json                                                                                          │
│ --help          Show this message and exit.                                                     │
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

### `actimize-installer detect`

```text
                                                                                                   
 Usage: actimize-installer detect [OPTIONS]                                                        
                                                                                                   
 Inspect a package and report its installer flavor, bin, and CONF files.                           
                                                                                                   
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ *  --package  -P      PATH  Extracted package dir (or .zip) [required]                          │
│    --extract                Extract if a .zip is given                                          │
│    --json                   Machine-readable output                                             │
│    --help                   Show this message and exit.                                         │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### `actimize-installer show`

```text
                                                                                                   
 Usage: actimize-installer show [OPTIONS] [WHAT]                                                   
                                                                                                   
 Run the installer's own read-only `show` command (safe to execute).                               
                                                                                                   
┌─ Arguments ─────────────────────────────────────────────────────────────────────────────────────┐
│   [what]      TEXT  install | upgrade | properties [default: install]                           │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ *  --package  -P      PATH  Extracted package dir (or .zip) [required]                          │
│    --verbose  -V            Show step detail                                                    │
│    --extract                Extract if a .zip is given                                          │
│    --help                   Show this message and exit.                                         │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### `actimize-installer run`

```text
                                                                                                   
 Usage: actimize-installer run [OPTIONS]                                                           
                                                                                                   
 Build the install command (dry-run) and, with --execute, run it behind a gate.                    
                                                                                                   
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ *  --package       -P      PATH  Extracted package dir (or .zip) [required]                     │
│    --command               TEXT  install | upgrade | show [default: install]                    │
│    --mode                  TEXT  full | sp | patch (alias for --command)                        │
│    --include       -i      TEXT  Only this task/step (repeatable)                               │
│    --exclude       -x      TEXT  Exclude this task/step (repeatable)                            │
│    --force         -f            Force steps even if already installed                          │
│    --from                  TEXT  Patch upgrade: from version (-F)                               │
│    --to                    TEXT  Patch upgrade: to version (-T)                                 │
│    --conf          -c      PATH  Override CONF folder                                           │
│    --work          -w      PATH  Override work folder                                           │
│    --log           -l      PATH  Override installer log folder                                  │
│    --features              TEXT  setup.exe -f (modeler|monitor|all)                             │
│    --target-path           TEXT  setup.exe -p install path                                      │
│    --upgrade-from          TEXT  setup.exe -v old version                                       │
│    --execute                     Actually run (default: dry-run)                                │
│    --yes                         Skip the confirmation prompt (with --execute)                  │
│    --allow-prod                  Permit a prod-looking CONF                                     │
│    --extract                     Extract if a .zip is given                                     │
│    --json                        Machine-readable plan output                                   │
│    --help                        Show this message and exit.                                    │
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

### `actone-local doctor`

```text
                                                                                                   
 Usage: actone-local doctor [OPTIONS]                                                              
                                                                                                   
 Preflight: docker, disk headroom, package, WAR, license, image.                                   
                                                                                                   
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --config  -c      PATH  Path to actone-local.yaml (else defaults)                               │
│ --help                  Show this message and exit.                                             │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### `actone-local config`

```text
                                                                                                   
 Usage: actone-local config [OPTIONS]                                                              
                                                                                                   
 Show the effective config (or --init to scaffold one).                                            
                                                                                                   
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --config  -c      PATH  Path to actone-local.yaml (else defaults)                               │
│ --init                  Write a default actone-local.yaml                                       │
│ --help                  Show this message and exit.                                             │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### `actone-local extract`

```text
                                                                                                   
 Usage: actone-local extract [OPTIONS]                                                             
                                                                                                   
 Extract only the lean build inputs (RCM.war + Docker/) from the payload.                          
                                                                                                   
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --config  -c      PATH  Path to actone-local.yaml (else defaults)                               │
│ --help                  Show this message and exit.                                             │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### `actone-local db-up`

```text
                                                                                                   
 Usage: actone-local db-up [OPTIONS]                                                               
                                                                                                   
 Start the lightweight PostgreSQL container (postgres:16-alpine).                                  
                                                                                                   
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --config  -c      PATH  Path to actone-local.yaml (else defaults)                               │
│ --help                  Show this message and exit.                                             │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### `actone-local db-init`

```text
                                                                                                   
 Usage: actone-local db-init [OPTIONS]                                                             
                                                                                                   
 Create the ActOne schema (lower-case) + search_path.                                              
                                                                                                   
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --config  -c      PATH  Path to actone-local.yaml (else defaults)                               │
│ --help                  Show this message and exit.                                             │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### `actone-local db-schema`

```text
                                                                                                   
 Usage: actone-local db-schema [OPTIONS]                                                           
                                                                                                   
 Populate the ActOne DDL + seed data (dbupgrade -exec -new). Takes a few minutes.                  
                                                                                                   
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --config  -c      PATH  Path to actone-local.yaml (else defaults)                               │
│ --help                  Show this message and exit.                                             │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### `actone-local render-config`

```text
                                                                                                   
 Usage: actone-local render-config [OPTIONS]                                                       
                                                                                                   
 Write acm.ini (PostgreSQL, plaintext password) into the work dir.                                 
                                                                                                   
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --config  -c      PATH  Path to actone-local.yaml (else defaults)                               │
│ --help                  Show this message and exit.                                             │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### `actone-local encrypt-config`

```text
                                                                                                   
 Usage: actone-local encrypt-config [OPTIONS]                                                      
                                                                                                   
 Encrypt the DB password (bundled tool) and rewrite acm.ini with the IV.                           
                                                                                                   
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --config  -c      PATH  Path to actone-local.yaml (else defaults)                               │
│ --help                  Show this message and exit.                                             │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### `actone-local build`

```text
                                                                                                   
 Usage: actone-local build [OPTIONS]                                                               
                                                                                                   
 Build the ActOne Docker image (disk-guarded).                                                     
                                                                                                   
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --config  -c      PATH  Path to actone-local.yaml (else defaults)                               │
│ --force                 Build even if disk is below the safety line                             │
│ --help                  Show this message and exit.                                             │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### `actone-local run`

```text
                                                                                                   
 Usage: actone-local run [OPTIONS]                                                                 
                                                                                                   
 Run the ActOne container (needs a license.lic).                                                   
                                                                                                   
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --config  -c      PATH  Path to actone-local.yaml (else defaults)                               │
│ --help                  Show this message and exit.                                             │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### `actone-local status`

```text
                                                                                                   
 Usage: actone-local status [OPTIONS]                                                              
                                                                                                   
 Show ActOne + DB container status.                                                                
                                                                                                   
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --config  -c      PATH  Path to actone-local.yaml (else defaults)                               │
│ --help                  Show this message and exit.                                             │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### `actone-local verify`

```text
                                                                                                   
 Usage: actone-local verify [OPTIONS]                                                              
                                                                                                   
 Wait until the RCM webapp actually serves (login redirect) — not just 'container started'.        
                                                                                                   
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --config   -c      PATH     Path to actone-local.yaml (else defaults)                           │
│ --timeout          INTEGER  Seconds to wait for RCM to serve [default: 180]                     │
│ --help                      Show this message and exit.                                         │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### `actone-local down`

```text
                                                                                                   
 Usage: actone-local down [OPTIONS]                                                                
                                                                                                   
 Stop & remove the containers (keep the DB volume unless --purge).                                 
                                                                                                   
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --config  -c      PATH  Path to actone-local.yaml (else defaults)                               │
│ --purge                 Also delete the Postgres data volume                                    │
│ --help                  Show this message and exit.                                             │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### `actone-local up`

```text
                                                                                                   
 Usage: actone-local up [OPTIONS]                                                                  
                                                                                                   
 Orchestrate all phases end-to-end (each idempotent).                                              
                                                                                                   
┌─ Options ───────────────────────────────────────────────────────────────────────────────────────┐
│ --config      -c      PATH  Path to actone-local.yaml (else defaults)                           │
│ --force                     Override the build disk guard                                       │
│ --skip-build                Stop before build/run (safe phases only)                            │
│ --help                      Show this message and exit.                                         │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

