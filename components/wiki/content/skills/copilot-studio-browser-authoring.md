# Copilot Studio — Browser Authoring (CDP fallback)

> Author, publish, and test Microsoft Copilot Studio agents by driving the maker UI in a real browser via the `agent-browser` CLI over Chrome DevTools Protocol — the fallback path when backend tooling is walled off.

## Goal
Sometimes the "proper" way to author Copilot Studio agents — `pac`/Power Platform CLI, PPAPI evaluations, DirectLine/SDK — is blocked by tenant Conditional Access, a missing App Registration, or a corrupted `pac`-pushed definition. This skill teaches an AI agent to fall back to driving the Copilot Studio maker UI directly in a compliant browser: create an agent, set instructions, wire up connected agents, publish, and test routing in the Preview pane.

## How it fits
This skill drives the external [`agent-browser`](https://www.npmjs.com/package/agent-browser) CLI over CDP rather than an ActWise bucket CLI. It is the escape hatch for the Copilot Studio agent projects under `agents/`, complementing the normal `copilot-studio` Author/Manage skills — use those when the backend works; use this only when a policy/permissions wall makes them impossible.

## When to use it
Reach for browser authoring when the backend path fails and you've confirmed it's a policy/permissions wall, not a fixable code issue:
- **Conditional Access blocks non-managed browsers** ("you can't get there from here").
- **No App Registration with delegated Power Platform permissions** — PPAPI, the SDK, and DirectLine all need consented scopes that may be pending IT approval.
- **`pac` CLI is unreliable** against the org (crashes on read-back, broken `status`, version mismatch).
- **A `pac`-pushed definition is corrupted** — the published agent replies on every turn with *"BotDefinitionOverride contains invalid YAML … InvalidContent"*.

## What it does
- Launches Edge with `--remote-debugging-port` on the user's managed/Intune-compliant device to satisfy Conditional Access after one interactive sign-in.
- Connects `agent-browser` over CDP (`agent-browser connect 9222`) and drives the maker UI (snapshot → resolve refs → click/type).
- Creates a new agent from scratch, sets **Agent instructions** via `keyboard inserttext` (programmatic `fill` doesn't register in the rich-text editor), and publishes (Publish = Save + Publish on a new agent).
- Adds connected agents (orchestrator/router pattern) with the required routing **Description**, then re-publishes.
- Tests routing in the **Preview** pane (New chat → probe → screenshot; inspects the orchestration trace).
- Recovers a corrupted agent by deleting and recreating it cleanly in the UI.

## Install / enable
Skills follow the open Agent Skills spec and install via the `skills` CLI:
```powershell
npx skills add https://github.com/vinayguda/actwise.git --skill copilot-studio-browser-authoring -a claude-code -g
```
Skills are instructions only. Unlike the other ActWise skills, this one drives the external **`agent-browser`** CLI (`npm i -g agent-browser && agent-browser install`; load its guide with `agent-browser skills get core`) plus Microsoft Edge on a managed device — not an `actwise` console script.

## Walkthrough
- *"Create a new orchestrator agent in Copilot Studio."* → launch Edge on the managed device, connect over CDP, New Agent → name + instructions → Publish (Save and publish).
- *"Wire the Ops child agent into the orchestrator."* → after publish, Add connected agent → pick child → fill the routing Description → Connect → Publish.
- *"Test that routing works."* → Preview → New chat → send a probe → screenshot the orchestration trace.

## Limits & safety
- **Never type or store the user's password/MFA** — hand off the interactive sign-in to them; confirm the browser window is visible first.
- Must run on the user's managed/compliant device (device compliance is satisfied at the device/broker level, which is why a cloud/sandbox browser cannot pass).
- When testing an agent that can perform writes (e.g. an Ops child with confirm-before-write), **never confirm/execute a write** during routing tests — verify the confirm prompt appears and stop.

## See also
- CLI: [`agent-browser`](https://www.npmjs.com/package/agent-browser) (external)
- Related skills: [actone-ops](actone-ops.md) (a common connected-agent child)
- Prefer the normal `copilot-studio` Author/Manage skills when the backend works.
