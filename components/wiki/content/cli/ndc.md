# `ndc`

> Search and download official Actimize **installation packages** from the NICE
> Download Center (Flexera SubscribeNet).

## Goal

Find and fetch the right install media — installers, service packs, patches — for an
Actimize product and version, with **MD5-verified** downloads. `ndc` is the
packages counterpart to [`docenter`](docenter.md) (documentation).

## How it fits

`ndc` is the CLI core of the [nicedl bucket](../buckets/nicedl.md) and is driven by
the [actimize-nicedl](../skills/actimize-nicedl.md) skill. It sits upstream of the
[installer](../buckets/installer.md) bucket: **docs → packages → install**.

## Install / enable

Installed with the `actwise` distribution. Authenticate to the Download Center first:

```powershell
ndc auth
```

## Command reference

| Command | Description |
| --- | --- |
| `products` | List curated product keys (friendly aliases for plne ids + components). |
| `find` | Locate a package by product + version — e.g. `ndc find actone 10.2`. |
| `product-lines` | List product lines (manufacturers) available on the portal. |
| `search` | Search product releases. Returns element/plne ids for `list-files` / `download`. |
| `recent` | List recent product releases posted to the portal. |
| `list-files` | List the downloadable files in a release (filename, size, MD5). |
| `download` | Download the installation package files for a release (with MD5 verification). |
| `auth` | Authenticate to the NICE Download Center. |
| `catalog` | Build/inspect the offline package catalog cache. |

Run `ndc <command> --help` for flags.

## Walkthrough

```powershell
# 1. Locate an ActOne 10.2 package
ndc find actone 10.2

# 2. See the files in the release (with sizes + MD5)
ndc list-files <element-id>

# 3. Download with MD5 verification
ndc download <element-id>
```

## Under the hood

- Talks to the **Flexera SubscribeNet** portal that backs the NICE Download Center.
- `products` provides friendly aliases so you don't need raw `plne`/element ids for
  common products; `search`/`find` return those ids for `list-files` and `download`.
- Downloads are **MD5-verified** against the portal's published checksum.

## See also

- Bucket: [nicedl](../buckets/nicedl.md)
- Skill: [actimize-nicedl](../skills/actimize-nicedl.md)
- Next step: [`actimize-installer`](actimize-installer.md) · [`actone-local`](actone-local.md)
