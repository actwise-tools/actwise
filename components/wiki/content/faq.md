# FAQ

### Is ActWise a NICE Actimize product?

No. ActWise is an **unofficial, experimental** project. It is **not** affiliated
with, endorsed by, or supported by NICE Ltd. See [Legal & disclaimer](legal.md).

### Does ActWise contain NICE Actimize documentation or data?

No. It ships **no** NICE content. Every tool fetches documentation, data, or media
on demand using **your own** authenticated session (docs portal, ActOne, database,
or Download Center).

### What do I actually install?

One Python distribution (`actwise`) that puts ~12 console scripts on your PATH — the
seven [CLIs](cli/index.md) plus five [MCP servers](mcp/index.md). The
[skills](skills/index.md) install separately via the `skills` CLI. See
[Install & onboarding](install.md).

### What's the difference between a CLI, an MCP server, and a skill?

They're three forms of the **same capability**. The **CLI** is the executable core;
the **MCP server** exposes that logic as tools for an AI agent; the **skill** is
instructions that teach an AI agent when and how to call the CLI. See
[Ecosystem](ecosystem.md).

### Can ActWise change my ActOne system or data?

- **Data** is strictly read-only (`SELECT` only).
- **Ops** reads freely but asks you to confirm before any write.
- **Utilities** and the **installer** are dry-run by default and require an explicit
  `--yes` / `--execute` for state-changing runs.

See [Security & secrets](security.md).

### Which AI agents can use the skills?

Any agent supported by the [Agent Skills](https://agentskills.io) spec — Claude
Code, Cursor, Codex, GitHub Copilot, Gemini, Windsurf, and more.

### Do I need the MCP servers to use the CLIs?

No. The CLIs work standalone in a terminal. The MCP servers are only needed when an
AI agent (or a Copilot Studio agent) should call the capability as a tool.

### There are two "Main" agents — which do I use?

[ActWise Main](agents/main.md) is an *orchestrator* that routes to three specialist
child agents; [ActWise Main1](agents/main1.md) is a *single agent* with all three
MCP servers attached directly. The [agents overview](agents/index.md) has an A/B
comparison.

### How do I keep the wiki's CLI reference accurate?

The command tables come from each CLI's live `--help`. Regenerate them from the repo
(see the [wiki bucket README](https://github.com/vinayguda/actwise)).

### Where's the official NICE documentation?

At `docs.niceactimize.com`. The [docenter](cli/docenter.md) CLI searches it and
links every answer back to the official source.
