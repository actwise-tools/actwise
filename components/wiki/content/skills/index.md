# ActWise Skills

ActWise ships a set of **AI agent skills** — instruction packs that follow the open [Agent Skills](https://github.com/anthropics/skills) spec. Each skill teaches an AI agent (Claude Code, Copilot, Copilot Studio, etc.) when and how to drive one of the ActWise CLIs or MCP servers to do real work against the NICE Actimize toolchain: search documentation, download and install packages, stand up ActOne locally, operate a live instance over REST, query its database read-only, run server-side utilities, and author Copilot Studio agents. Skills are instructions only — they carry no code, so the underlying `actwise` distribution (or, for browser authoring, the external `agent-browser` CLI) must be installed for the commands to run.

> **Note:** ActWise is an **unofficial, experimental** engineering toolkit — not a NICE Actimize product.

## The skills

| Skill | Drives | Purpose |
|-------|--------|---------|
| [actimize-docenter](actimize-docenter.md) | `docenter` CLI | Search, download, and sync official NICE Actimize product documentation. |
| [actimize-nicedl](actimize-nicedl.md) | `ndc` CLI | Find and download install packages, service packs, and patches from the NICE Download Center. |
| [actimize-installer](actimize-installer.md) | `actimize-installer` CLI | Install/upgrade Actimize packages from disk behind a confirmation gate (dry-run by default). |
| [actone-local](actone-local.md) | `actone-local` CLI | Stand up ActOne core (10.2) locally on Docker + PostgreSQL, idempotently. |
| [actone-api-suite](actone-api-suite.md) | `actone` CLI + `postman/` | Generate/test Postman collections and contract tests for the ActOne Extend REST API. |
| [actone-ops](actone-ops.md) | `actone ops` CLI / `actone-ops` MCP | Discover and invoke read-only operations against a live ActOne over REST. |
| [actone-data](actone-data.md) | `actone-data` CLI / MCP | Read-only natural-language-to-SQL over the ActOne `v_acm_*` reporting views. |
| [actone-utils](actone-utils.md) | `actone-utils` CLI / MCP | Run ActOne server-side Java utilities as typed, gated commands. |
| [copilot-studio-browser-authoring](copilot-studio-browser-authoring.md) | `agent-browser` CLI | Author/publish/test Copilot Studio agents via the maker UI when backend tooling is blocked. |

## Installing a skill

All skills install the same way via the `skills` CLI (swap in the skill name):

```powershell
npx skills add https://github.com/vinayguda/actwise.git --skill <name> -a claude-code -g
```

Then install the `actwise` distribution so the console scripts the skill drives are on `PATH` (see each skill's **Install / enable** section for the specific command it requires).
