# ActWise-Utility-Dev

> A productivity toolkit that turns ActWise work into deliverables — diagrams, decks, and specs.

## Goal

`ActWise-Utility-Dev` (ActWise Utility) is a **productivity toolkit** for turning
ActWise work into deliverables. It hosts add-on capabilities such as generating
architecture diagrams, building PowerPoint decks, and drafting functional and
technical specification documents — the artifacts that go *around* your Actimize
work. Capabilities are enabled incrementally as they come online.

## How it fits

- **Role:** productivity / add-on **toolkit** agent (not a grounded Docs/Data/Ops
  specialist).
- **Surface:** Microsoft Copilot Studio agent.
- **Scope:** produces visuals, presentations, and written specs so you don't have to
  leave the ActWise experience. It is complementary to the three grounded specialists
  rather than a routing target of the front doors.

## What it can do

- Generate **architecture diagrams** (Excalidraw / draw.io).
- Build **PowerPoint decks**.
- Draft **functional and technical specification** documents.
- Produce the deliverables that surround Actimize work — visuals, presentations, and
  written specs — inside the ActWise experience.

> **Note:** capabilities are enabled **incrementally as they come online**, so the
> available toolset grows over time.

## Example prompts

The Long description does not enumerate example prompts; the following illustrate the
stated capabilities:

- **"Generate an architecture diagram of the ActWise MCP topology."** — diagram
  generation (Excalidraw / draw.io).
- **"Build a slide deck summarizing this design."** — PowerPoint deck generation.
- **"Draft a functional spec for this feature."** — specification-document drafting.

## Safety & boundaries

- **Deliverable-focused** — it produces artifacts (diagrams, decks, specs); it is not
  a grounded product-docs, data, or live-operations agent.
- **Incremental availability** — only the capabilities that have come online are
  active; others are enabled over time.

## Copilot Studio descriptions

**Short description** (≤ 80 chars)

```text
Utility toolkit: diagrams, slide decks, and spec generation for ActWise.
```

**Long description**

```text
ActWise Utility is a productivity toolkit for turning ActWise work into deliverables. It hosts add-on capabilities such as generating architecture diagrams (Excalidraw / draw.io), building PowerPoint decks, and drafting functional and technical specification documents. Use it to produce the artifacts that go around your Actimize work — visuals, presentations, and written specs — without leaving the ActWise experience. Capabilities are enabled incrementally as they come online.
```

## See also

- Front doors: [`Actwise-Main-Dev`](main.md) · [`ActWise-Main1-Dev`](main1.md).
- Grounded specialists: [`Actwise-Docs-Dev`](docs.md) ·
  [`Actwise-Data-Dev`](data.md) · [`Actwise-Ops-Dev`](ops.md).
- [Agents hub](index.md) — the full roster.
