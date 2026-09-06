# Actwise-Ops-Dev

> Runs and inspects live ActOne operations via REST and curated SOAP admin — with confirm-before-write on any change.

## Goal

`Actwise-Ops-Dev` (ActWise Ops) performs and inspects **live operations** on a
running ActOne instance through the Extend REST API and curated SOAP admin
operations. It can discover, describe, and invoke read operations directly, and for
anything that changes the system it runs a **confirm-before-write** safety step —
nothing is mutated until you say yes. It reports real API results truthfully,
including errors, and never fabricates success.

## How it fits

- **Role:** grounded **specialist** — the Ops domain of ActWise.
- **Surface:** Microsoft Copilot Studio agent.
- **Grounding / MCP:** fronts the [live ActOne REST MCP](../mcp/actone-mcp.md)
  (`search_ops`, `list_ops`, `describe_op`, `invoke_op`, `list_soap_operations`,
  `invoke_soap_operation`, `list_environments`, `list_tags`), served from a hosted
  MCP endpoint (self-hosted, via a named tunnel). See the [ops bucket](../buckets/ops.md)
  for the REST client and API tooling.
- **Consumed by the front doors:** routed to by [`Actwise-Main-Dev`](main.md)
  (orchestrator) and attached directly in [`ActWise-Main1-Dev`](main1.md)
  (single-agent variant).

## What it can do

- **Discover, describe, and invoke read operations** directly — list work-item types,
  check configured environments, read live status, run diagnostics.
- Invoke operations through the **Extend REST API** and **curated SOAP admin**
  operations (SOAP is used when REST cannot perform the action — e.g. creating a
  business unit).
- For any change — create, update, configure, assign, close, progress, or invoke a
  write — run a **confirm-before-write** step: propose the exact operation, target,
  change set, and environment, then wait for explicit confirmation before executing.
- Reference the executed `operationId` in its results and render lists as Markdown
  tables.

## Example prompts

- **"What environments are configured?"** — a read operation, invoked directly and
  answered from the live API.
- **"List the available work item types."** — a read/discovery operation returned as
  a table.
- **"Progress work item 4821 to the next step."** — a write; it proposes the change
  and asks you to confirm first.
- **"Create a business unit called Fraud-EU."** — a write (via curated SOAP); it asks
  you to confirm first.

## Safety & boundaries

- **Confirm-before-write** — any change (REST POST/PUT/PATCH/DELETE or SOAP writes
  like `bu.create` / `bu.remove`) states the operation, target, intended change, and
  environment, and proceeds only after **explicit user confirmation**. Read-only
  operations need no confirmation.
- **Environment guardrails** — the default write target is a local dev environment;
  all non-local environments are treated as **sensitive** and are never written to
  unless you explicitly name them.
- **Truthful reporting** — it reports real API results, including errors, and
  **never fabricates success**.
- **No guessing** — it never guesses `operationId` or parameter names; it describes
  an operation before invoking it.

## Copilot Studio descriptions

**Short description** (≤ 80 chars)

```text
Runs live ActOne operations via REST, with confirm-before-write on any change.
```

**Long description**

```text
ActWise Ops performs and inspects live operations on a running ActOne instance through the Extend REST API and curated SOAP admin operations. It can discover, describe, and invoke read operations directly — list work-item types, check configured environments, read live status, run diagnostics.

For anything that changes the system — create, update, configure, assign, close, progress, or invoke a write — it runs a confirm-before-write safety step: it proposes the exact operation, target, change set, and environment, then waits for your explicit confirmation before executing. Nothing is mutated until you say yes.

Examples:
• What environments are configured?
• List the available work item types.
• Progress work item 4821 to the next step. (asks you to confirm first)
• Create a business unit called Fraud-EU. (asks you to confirm first)

It reports real API results truthfully, including errors, and never fabricates success.
```

## See also

- MCP backend: [actone-mcp](../mcp/actone-mcp.md).
- Bucket: [ops](../buckets/ops.md) — live ActOne REST tooling.
- Front doors: [`Actwise-Main-Dev`](main.md) · [`ActWise-Main1-Dev`](main1.md).
- Sibling specialists: [`Actwise-Docs-Dev`](docs.md) · [`Actwise-Data-Dev`](data.md).
