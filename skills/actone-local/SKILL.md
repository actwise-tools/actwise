---
name: actone-local
description: Stand up ActOne core (10.2) locally on Docker + PostgreSQL using the idempotent, disk-aware `actone-local` CLI. Use when the user wants to run ActOne on their own machine / laptop for a dev or demo environment — build the ActOne image from a downloaded package, start a lightweight Postgres, initialise the schema, render acm.ini, and run the container. It is the **run-it-locally** counterpart to actimize-nicedl (which *downloads* the package), actimize-installer (which drives the DB/product *installer*), and actimize-docenter (which covers *documentation*). Every phase is safe to re-run; the heavy image build is disk-guarded.
---

# ActOne Local Setup Skill

This skill stands up **ActOne core** on the user's own machine using Docker + PostgreSQL,
via the `actone-local` CLI. It automates the local install plan in
`docs/components/installer/2026-07-02-actone-10.2-local-docker-install-plan.md`. Each phase is a subcommand,
**idempotent** (safe to re-run), and tuned for a **low-resource laptop** (alpine Postgres,
trimmed JVM heap, no SSL). The expensive image build is **disk-guarded**.

It is the **run-locally** step of the ActWise chain:

- "How do I install/configure ActOne?" → **actimize-docenter** (docs).
- "Get me the ActOne 10.2 package" → **actimize-nicedl** (`ndc find` / `ndc download`).
- "Drive the product's own installer / DB tasks" → **actimize-installer**.
- "Run ActOne locally on my laptop" → **this skill** (`actone-local`).

## When to use

Activate when the user wants to:
- **Spin up ActOne core locally** for dev/demo (Docker image + Postgres).
- **Preflight** their machine for an ActOne build (docker, disk headroom, package, license).
- Run **individual phases** (extract WAR, start DB, init schema, render config, build, run).

Do NOT use this to download packages (**actimize-nicedl**), drive the shipped product installer
(**actimize-installer**), or answer documentation questions (**actimize-docenter**).

## Prerequisites

- **Docker Desktop** running.
- The **ActOne 10.2 payload** on disk. Default source is
  `packages/ActOne-10.2.0-inner.zip` (the inner payload of NDC element `7955981`, plne
  `792217`). Get it with `ndc download 7955981 --plne 792217 --match "ActOne 10.2.zip"`,
  then extract the inner zip. (`config.package_zip` points here.)
- For a **fully running container**, a valid **`license.lic`** from NICE (dropped at
  `packages/actone-local/license.lic`). The DB + build phases work without it; only `run` needs it.
- **Disk:** the image build needs **≥ 6 GB free** (guarded). The safe phases
  (extract + Postgres pull + schema) need **~0.5 GB**.

## CLI commands

```
actone-local doctor                 # preflight: docker, disk, package, WAR, license, image
actone-local config [--init]        # show effective config (or scaffold actone-local.yaml)

actone-local extract                # extract ONLY RCM.war + Docker/ from the payload (lean)
actone-local db-up                  # start postgres:16-alpine (idempotent)
actone-local db-init                # create the 'actone' schema + search_path
actone-local db-schema              # populate the ActOne DDL (600+ tables) — dbupgrade -exec -new
actone-local render-config          # write acm.ini (Postgres connection, PLAINTEXT password)
actone-local encrypt-config         # AES-encrypt the DB password (bundled tool) + write the IV
actone-local build [--force]        # build the ActOne image (disk-guarded; --force overrides)
actone-local run                    # run the ActOne container (needs license.lic)

actone-local up [--skip-build] [--force]   # orchestrate every phase end-to-end
actone-local status                 # container status (ActOne + DB)
actone-local down [--purge]         # stop/remove containers (--purge also drops the DB volume)
```

All commands accept `--config/-c PATH` to point at an alternate `actone-local.yaml`.

## Instructions

### 1. Always start with `doctor`

```
actone-local doctor
```

It reports each prerequisite as `OK` / `XX`:
- **docker** engine reachable.
- **disk** free vs the 6 GB build line and 8 GB comfort line.
- **package** payload present.
- **RCM.war** extracted yet (run `extract`).
- **license.lic** present (required only for `run`).
- **image** built yet (run `build`).

Use it to decide which phases are safe. **If disk is below ~6 GB, do NOT build** — run the
light phases and ask the user to free space (or accept `--force` at their own risk).

### 2. Run the safe/light phases first

These fit in well under 1 GB and are the right default on a constrained laptop:

```
actone-local extract          # ~292 MB RCM.war + Docker/ build tree
actone-local db-up            # pulls postgres:16-alpine (~250 MB), starts it
actone-local db-init          # creates the 'actone' schema (lower-case) + search_path
actone-local db-schema        # populates the ActOne DDL (600+ tables) — a few minutes
actone-local render-config    # writes packages/actone-local/acm.ini (plaintext password)
actone-local encrypt-config   # rewrites acm.ini with an AES-encrypted password + IV
```

Everything is idempotent — re-running `db-up`/`db-init`/`db-schema` skips work already done
(`db-schema` checks for `acm_md_config_params` and skips if the schema is already populated).

> **`db-schema` — the ActOne DDL install (Phase C).** `db-init` only creates an *empty* schema;
> ActOne needs 600+ tables (`acm_md_config_params`, `alerts`, …) or RCM fails to start. `db-schema`
> extracts the bundled RCM DB-install engine (`Installer/.../DB_Scripts/Infrastructure`, class
> `com.actimize.util.dbupgrade.Main`) to `packages/actone-local/dbscripts/`, writes a filled
> `postgresql.env.filled` (db/schema/user from config), and runs **`dbupgrade -exec -new`** in a
> throwaway `amazoncorretto:21-al2023` container on the ActOne network. On a laptop this creates
> **617 tables in ~3–4 minutes**. The `actone` DB user (superuser + schema owner) is used directly —
> the documented least-privilege app users/roles are skipped for a single-user local core.

> **acm.ini + password encryption:** `render-config` writes the DB password in **PLAINTEXT**.
> ActOne **always** decrypts `actimize.repository.password` at startup (`PasswordManager.decryptArray`),
> so RCM will **not** start with a plaintext value. `encrypt-config` closes this: it extracts the
> bundled RCM Encryption Tool (`Utilities/{bin,etc,lib}`, class `com.actimize.encriptor.Encryptor`)
> from the package, runs it in a throwaway `amazoncorretto:21-al2023` container to AES-encrypt the
> password, and rewrites acm.ini with the ciphertext plus `actimize.bootstrap.encryption.iv`
> (`encrypt_iv`, default `ActoneLocalIV01`). Always run `encrypt-config` after `render-config` and
> before `run`. Ref: ActOne 10.2 Installation Guide, "The Encryption Utility".

### 3. Build the image (disk-guarded — get consent first)

The image build pulls a Java base (`amazoncorretto:21-al2023`), downloads **Tomcat 10.1.x**, and
bakes in the 292 MB WAR — it grows the Docker vhdx by **~1.5–2 GB**. It **refuses to run below
6 GB free** unless `--force`:

```
actone-local build            # blocks if disk is tight
actone-local build --force    # only if the user accepts the risk
```

Confirm the user has freed disk **before** building on a near-full drive.

> **Two build facts baked into the utility (learned the hard way):**
> - **Tomcat 10.1, not 9.** RCM.war is **Jakarta EE 10** (`jakarta.*` namespace), so it needs
>   Tomcat **10.1.x** (`tomcat_version`, default `10.1.44`). The package Dockerfile's default
>   `TOMCAT_VERSION=9.0.104` is a stale `javax` fallback that fails with
>   `ClassNotFoundException: jakarta.servlet.ServletContextListener`.
> - **Corporate TLS proxy.** In-container downloads of the Tomcat tarball from archive.apache.org
>   fail behind an SSL-inspection proxy. The build therefore downloads Tomcat on the **host**
>   (urllib → `curl.exe --ssl-no-revoke` fallback, cached under `packages/actone-local/`) and
>   serves it locally over plain HTTP so the container never does external TLS.

### 4. Run the container

Needs a valid license file. `run` mounts it to **`/usr/local/tomcat/bin/acm/license/license.lic`**
(the path RCM's `LicenseManager` checks). Drop the file at `packages/actone-local/license.lic`;
without it, RCM boots all the way to the license gate and then fails
(`License file … not found`).

```
actone-local run
actone-local status
```

ActOne serves on the configured `http_port` (default host **8082** → container 8080; non-SSL by
default). Point the user there once healthy.

> **Boot progression (with `db-schema` done + encrypted acm.ini):** Tomcat 10.1 → RCM deploys →
> password decrypts → DB connects → JPA EntityManagerFactory initialises → **config/schema load OK**
> (no more `acm_md_config_params` error) → **license gate** (`license.lic` required). The license is
> the only remaining external dependency — obtain it from NICE.

### 5. Or orchestrate everything

```
actone-local up --skip-build      # doctor + extract + db-up + db-init + db-schema + render-config + encrypt-config (safe)
actone-local up                   # full chain incl. build + run (respects the disk guard)
actone-local up --force           # full chain, overriding the disk guard
```

### 6. Tear down

```
actone-local down                 # stop/remove containers, KEEP the DB volume
actone-local down --purge         # also delete the Postgres data volume
```

## Configuration

Defaults live in `actone_local/config.py` and target a laptop:
`postgres:16-alpine`, heap `-Xmx2048m` (vs the 8 GB container default), `use_ssl=False`,
base image `amazoncorretto:21-al2023`, image `actone:10.2`, http port 8082.

Override any knob by scaffolding and editing a YAML file:

```
actone-local config --init        # writes actone-local.yaml with current values
# edit actone-local.yaml, then any command picks it up (or pass --config PATH)
```

This is also how the tooling **generalises to other solutions** later — ship a different config.

## Pair with the other skills

- **actimize-docenter** — the ActOne *Installation/Implementer* guide (prereqs, DB sizing, acm.ini
  field meanings) before you build.
- **actimize-nicedl** (`ndc`) — obtain/refresh the 10.2 package this skill consumes.
- **actimize-installer** — when you need to drive ActOne's own `rcm-installer` DB tasks rather than
  the container's entrypoint.

## Error handling

| Symptom | Action |
|---------|--------|
| `docker engine not reachable` | Start Docker Desktop; re-run `doctor`. |
| `disk … below … build needs >= 6.0 GB` | Free space, or accept risk with `build --force`. Prefer running only the light phases. |
| `package … not found` | Download via `ndc` and extract the inner payload to `packages/ActOne-10.2.0-inner.zip`. |
| `RCM.war — not yet` | Run `actone-local extract`. |
| `license.lic — MISSING` | Obtain a license from NICE; drop it at `packages/actone-local/license.lic`. DB/build phases still work without it. |
| `actone-local: command not found` | Run via `python -m actone_local <cmd>`, or install the repo package (`pip install -e .`, or via uv like the other ActWise CLIs). |
