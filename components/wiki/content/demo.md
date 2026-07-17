# Demo overview

A narrated, two-host walkthrough of ActWise in action — the Copilot Studio agent
answering a real question with **cited** documentation, querying the ActOne
database in plain English (**read-only**), performing **gated** live operations,
and composing all three into a reusable skill. It then tells the bigger story:
how the **Doc Center MCP is the foundation** every other capability is built on,
and how you can try it yourself.

<video controls preload="metadata" width="100%" poster="assets/actwise-architecture.png" markdown>
  <source src="assets/actwise-demo-overview.mp4" type="video/mp4">
  Your browser does not support the video tag.
  [Download the demo video](assets/actwise-demo-overview.mp4).
</video>

!!! info "What you're seeing"
    Every clip is the **real** ActWise prototype running live — no mockups. The
    agent chooses the right MCP server itself, cites each answer back to
    `docs.niceactimize.com`, keeps data access read-only by default, and asks for
    consent before any write.

## What the demo covers

| Segment | Capability |
| --- | --- |
| **Grounded answers + citations** | The [ActWise Docs](agents/docs.md) path uses the Doc Center MCP to find the latest ActOne release and compatibility matrix, with inline citations. |
| **Products via API** | Queries Doc Center's API directly to list every reachable product. |
| **Natural-language data** | The [ActOne Data MCP](mcp/actone-data-mcp.md) turns plain English into validated, read-only SQL over approved views. |
| **Act on ActOne** | The [ActOne Ops MCP](mcp/actone-mcp.md) exposes the Extend REST API — 200+ operations — with consent-gated writes. |
| **Compose + save as skill** | The data and ops paths combine, then save the whole workflow as a reusable skill. |
| **The foundation** | Doc Center MCP is the plumbing — grounding AI in product knowledge so each capability (Download Center, Installer, ActOne Local, Data, Ops, Utilities) is built as a CLI + Skill + MCP without hand-explaining the products. |
| **Build anything on the scaffold** | With the ecosystem grounded, the agent can orchestrate across MCPs to automate real work — and the same base supports diagrams, specs, sizing, plugins, and more. |
| **Try it yourself** | Two ways in — the Microsoft Copilot agent and the ActWise portal — with a path to offer it to customers as part of a NICE AI package. |

See [Ecosystem](ecosystem.md) for the architecture behind the demo, and
[Copilot Studio agents](agents/index.md) to reproduce the agent shown here.
