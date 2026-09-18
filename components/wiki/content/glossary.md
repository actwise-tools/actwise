# Glossary

Terms used across the ActWise wiki. NICE Actimize product terms are described only
to explain how ActWise interoperates with them.

| Term | Meaning |
| --- | --- |
| **ActWise** | This unofficial toolkit — CLIs, MCP servers, skills, and Copilot Studio agents around NICE Actimize ActOne. Not a NICE product. |
| **NICE Actimize** | The vendor whose financial-crime products (ActOne, SAM, CDD, IFM…) ActWise interoperates with. Trademarks of NICE Ltd. |
| **ActOne** | The Actimize case/alert management platform ActWise targets — its docs, REST surface, database, utilities, and install media. |
| **Bucket** | A capability slice under `components/` (core, docenter, ops, data, utils, nicedl, installer). Each owns its packages, CLI, MCP, and skills. |
| **CLI** | A command-line console script installed by the `actwise` distribution (e.g. `docenter`, `actone`, `ndc`). |
| **MCP** | Model Context Protocol — the standard by which AI agents call tools. ActWise ships MCP **servers** that expose each capability as callable tools. |
| **MCP server** | A process (stdio or HTTP) exposing tools to an AI client. ActWise MCP servers wrap the same code as the CLIs. |
| **Skill** | An [Agent Skills](https://agentskills.io) instruction bundle (`SKILL.md`) that teaches an AI agent *when and how* to drive an ActWise CLI. Instructions only — no code. |
| **Copilot Studio agent** | A Microsoft Copilot Studio agent (ActWise Docs/Data/Ops/Utility/Main) that consumes an ActWise MCP server. |
| **Orchestrator** | The [ActWise Main](agents/main.md) agent that routes each request to one specialist child agent. |
| **docenter** | The docs bucket's CLI — search, download, and sync the NICE Actimize documentation portal. |
| **Zoomin** | The platform behind the NICE Actimize docs portal (`docs.niceactimize.com`); `docenter` uses its REST API. |
| **Extend REST API** | ActOne's REST surface, driven by the [ops](buckets/ops.md) bucket for discovery and gated operations. |
| **`v_acm_*` views** | The ActOne PostgreSQL reporting views the [data](buckets/data.md) bucket queries read-only (work items, alerts, cases, blotters, queues, users, policies). |
| **Blotter** | An ActOne work-list surface. The [utils](buckets/utils.md) bucket can rematerialize blotters via server-side utilities. |
| **DART** | An ActOne server-side query/reporting tool runnable through the utils bucket. |
| **NICE Download Center** | Flexera SubscribeNet portal for official install media; the [nicedl](buckets/nicedl.md) bucket (`ndc`) searches and downloads from it. |
| **CoreAI / DOCenter MCP** | NICE Actimize's own internal AI platform and hosted docs MCP; ActWise can adopt these where available. |
| **`find_config()`** | The shared `actwise.paths` resolver every component uses to locate config. See [Configuration](config.md). |
| **`ACTWISE_CONFIG_DIR`** | Env var that overrides the config search path for every component. |
