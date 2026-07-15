# ActWise buckets

> One bucket per capability under `components/`. Each bucket owns its packages,
> CLI console scripts, MCP server(s), Copilot skill(s), and (where relevant) a
> Copilot Studio agent.

ActWise is a NICE Actimize engineering toolkit packaged as a **single Python
distribution** (`actwise`). Everything installs as one tool and shares one
config-resolution layer ([core](core.md)). The buckets below are the capability
seams: docs, ops, data, utilities, downloads, and installer, plus the shared
core.

> **Unofficial project.** ActWise is an unofficial, experimental personal side
> project — **not** a NICE Actimize product, and not affiliated with, endorsed by,
> or supported by NICE Ltd. It ships no NICE Actimize content.

## Project map

| Bucket | Packages | CLI | MCP | Skill | Copilot agent |
|--------|----------|-----|-----|-------|---------------|
| [`core`](core.md) | `actwise` | — | — | — | — |
| [`docenter`](docenter.md) | `docenter`, `docenter_mcp`, `extractor`, `mcp_server`, `copilot_proxy`, `sharepoint` | [`docenter`](../cli/docenter.md) | [`docenter-mcp`](../mcp/docenter-mcp.md), [`actimize-docs-mcp`](../mcp/actimize-docs-mcp.md) | [`actimize-docenter`](../skills/actimize-docenter.md) | [ActWise Docs](../agents/docs.md) |
| [`ops`](ops.md) | `actone`, `actone_mcp`, `postman` | [`actone`](../cli/actone.md) | [`actone-mcp`](../mcp/actone-mcp.md) | [`actone-ops`](../skills/actone-ops.md) (+ `actone-api-suite`) | [ActWise Ops](../agents/ops.md) |
| [`data`](data.md) | `actone_data`, `actone_data_mcp` | [`actone-data`](../cli/actone-data.md) | [`actone-data-mcp`](../mcp/actone-data-mcp.md) | [`actone-data`](../skills/actone-data.md) | [ActWise Data](../agents/data.md) |
| [`utils`](utils.md) | `actone_utils` | [`actone-utils`](../cli/actone-utils.md) | [`actone-utils-mcp`](../mcp/actone-utils-mcp.md) | [`actone-utils`](../skills/actone-utils.md) | — |
| [`nicedl`](nicedl.md) | `nicedl` | [`ndc`](../cli/ndc.md) | — | [`actimize-nicedl`](../skills/actimize-nicedl.md) | — |
| [`installer`](installer.md) | `actinstaller`, `actone_local` | [`actimize-installer`](../cli/actimize-installer.md), [`actone-local`](../cli/actone-local.md) | — | [`actimize-installer`](../skills/actimize-installer.md), [`actone-local`](../skills/actone-local.md) | — |

Console scripts installed by the distribution: `docenter` `docenter-mcp`
`actimize-docs-mcp` `actone` `actone-mcp` `actone-utils` `actone-utils-mcp`
`actone-data` `actone-data-mcp` `ndc` `actimize-installer` `actone-local`.

## Install

```powershell
uv tool install "git+ssh://git@github.com/vinayguda/actwise.git"
```

This puts every console script above on your PATH. All components resolve config
through `actwise.paths.find_config()` — see [core](core.md).

## See also

- [MCP servers hub](../mcp/index.md)
