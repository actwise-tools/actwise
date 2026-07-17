---
name: copilot-studio-browser-authoring
description: Author, publish, and test Microsoft Copilot Studio agents by driving the maker UI in a real browser via the agent-browser CLI over Chrome DevTools Protocol (CDP). Use this as the FALLBACK path when the backend tooling (pac / Power Platform CLI, PPAPI evaluations, DirectLine/SDK) is blocked by tenant Conditional Access (device-compliance) or a missing App Registration with delegated Power Platform permissions, or when a pac-pushed agent definition is corrupted (runtime "BotDefinitionOverride contains invalid YAML / InvalidContent"). Covers: launching Edge with remote debugging on a managed/compliant device to satisfy Conditional Access, connecting agent-browser over CDP, creating a new agent from scratch, setting instructions, adding connected agents (orchestrator/router pattern), publishing, and testing routing in the Preview pane. Not for normal pac-based authoring — use the copilot-studio Author/Manage skills when the backend works.
---

# Copilot Studio — Browser Authoring (CDP fallback)

Create, edit, publish, and test **Copilot Studio agents entirely through the maker
UI** by driving a real browser with the [`agent-browser`](https://www.npmjs.com/package/agent-browser)
CLI over CDP. This is the escape hatch for when the "proper" backend path is walled off.

```
launch Edge (managed device, --remote-debugging-port)  →  user signs in ONCE
   →  agent-browser connect <port>  →  drive maker UI  →  Publish  →  test in Preview
```

## When to use this skill

Reach for browser authoring when the backend path fails and you've confirmed it's a
**policy/permissions wall**, not a fixable code issue:

- **Conditional Access blocks non-managed browsers.** The tenant shows
  *"You can't get there from here — this application can only be accessed from devices
  that meet … compliance policy."* Sandboxed/automation Chrome profiles are not
  compliant devices, so API and headless approaches 403 or get redirected forever.
- **No App Registration with delegated Power Platform permissions.** PPAPI evaluations,
  the Copilot Studio SDK, and DirectLine all need delegated scopes
  (`CopilotStudio.Copilots.Invoke`, `CopilotStudio.MakerOperations.Read/ReadWrite`) with
  admin consent. If that consent is pending IT approval, automated test channels are dead.
- **pac CLI is unreliable against the org.** e.g. `pac copilot` crashes on post-write
  read-back (`bolt.Session :: Improper response, not implemented`), `pac copilot status`
  is broken, or a version mismatch corrupts pushes.
- **A pac-pushed definition is corrupted.** The published agent replies on *every* turn
  with *"BotDefinitionOverride contains invalid YAML and could not be parsed
  (InvalidContent)"*. The clean fix is to **delete the agent and recreate it in the UI**
  (see "Recovering a corrupted agent" below).

If the backend works, prefer the normal `copilot-studio` Author/Manage skills — this
skill is slower and manual by nature.

## Prerequisites

- `agent-browser` installed (`npm i -g agent-browser && agent-browser install`).
  Load its own guide first: `agent-browser skills get core`.
- **You must run on the user's managed / Intune-compliant device.** Conditional Access
  device-compliance is satisfied at the *device/broker* level, not the profile level —
  which is why a browser on this machine passes where a cloud/sandbox browser cannot.
- Use **Microsoft Edge**, not Chrome. Edge natively presents the device's compliance
  state through the Windows account broker (WAM), so a fresh Edge profile on a managed
  device passes CA after one interactive sign-in. (Chrome would need the
  "Windows 10 Accounts" / "Microsoft Single Sign On" extension AND may still fail.)
- The **user completes the interactive sign-in (password + MFA)**. Never handle their
  password. Confirm the browser window is visible to them first.

## The core pattern

### 1. Launch Edge with remote debugging (the CA bypass)

Modern Edge/Chrome refuse `--remote-debugging-port` on the default user-data-dir, so use
a dedicated profile dir. A fresh profile is fine — device compliance comes from the OS.

```powershell
$edge = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
$udd  = "$env:TEMP\edge-debug-profile"   # dedicated profile
New-Item -ItemType Directory -Force -Path $udd | Out-Null
Start-Process -FilePath $edge -ArgumentList @(
  "--remote-debugging-port=9222",
  "--user-data-dir=`"$udd`"",
  "--no-first-run","--no-default-browser-check",
  "https://copilotstudio.microsoft.com/environments/<ENV_ID>/agents/<AGENT_ID>"
)
# verify CDP is up:
(Invoke-WebRequest -UseBasicParsing "http://localhost:9222/json/version").Content
```

Ask the user to **sign in** in that Edge window. It should NOT show the
"you can't get there from here" block, because Edge presents device compliance.

### 2. Connect agent-browser over CDP

```powershell
agent-browser connect 9222      # use the DEFAULT session
agent-browser get url           # confirm you're on the agent page, not a login redirect
```

> **Gotcha:** passing `--session <name>` to an already-running daemon can race
> ("Daemon failed to start"). `connect` on the default session is the reliable path.

### 3. Drive the maker UI — golden rules

- **Element refs shift after every navigation** — re-run `agent-browser snapshot -i`
  and re-resolve refs (grep the line, extract `ref=(e\d+)`) before each click.
- **Programmatic `fill` does NOT register in the rich-text Instructions editor.** The
  DOM shows your text but the editor's model/React state doesn't update (Save stays
  disabled). Use `keyboard inserttext` (fast, no markdown auto-format) or `keyboard type`,
  then a single real keystroke (`Control+End` then type a char) to force reconciliation.
  Verify with `agent-browser eval "document.querySelector('[contenteditable=true]').innerText.length"`.
- **On a brand-new (unsaved) agent, the Save button is permanently disabled** — that's
  normal, not lost content. **Publish = Save + Publish.** Clicking Publish on a new agent
  shows a "Save and publish this agent?" dialog; confirming it creates, saves, and
  publishes in one step (and the URL changes to the new agent id).
- **`agent-browser find` arg order** is `find <locator> <value> <action> [text]`
  (e.g. `find role button Next click`). When text matches multiple nodes ("strict mode
  violation"), snapshot for the exact `ref` and `click @eN` instead.

### 4. Create an agent from scratch

The `copilot-studio` Author skill can only *edit* existing agents. To create one:

1. Go to the environment's agent list (`/environments/<ENV_ID>/bots`), click **New Agent**.
   It lands directly on the configure canvas (`/agents/new`).
2. Type the **name** (the name field is pre-focused/selected — just type).
3. Click into **Agent instructions** and enter text via `keyboard inserttext`.
4. Click **Publish** → confirm **Save and publish** → the agent is created + published.
   (Connected-agent add is disabled until the agent exists — publish first.)

### 5. Add connected agents (orchestrator / router pattern)

After the agent exists and is published, **Add connected agent** is enabled. For each child:

1. Click **Add connected agent** → pick the child agent from the list.
2. A **Connect agent** dialog opens with a **required Description** field — this is the
   *routing signal* the parent uses to decide when to delegate. Fill it with a crisp
   "route here when …" description (click the actual `textbox "Description …"`, not the
   "More info" button next to it). **Connect** enables once the description is non-empty.
3. Repeat for each child, then **Publish** again to make the routes live.

### 6. Test routing in the Preview pane

```
click tab "Preview"  →  click "New chat"  →  type a probe  →  press Enter  →  screenshot
```

- A healthy orchestrator greets cleanly (`Hello! I'm <Agent>. How can I help you today?`).
  If instead every turn says *"BotDefinitionOverride … InvalidContent"*, the definition is
  corrupted — recreate it (below).
- The preview shows the **orchestration trace** (routing reasoning + a green node naming the
  invoked child), then the child's native output (citations / tables / confirm dialogs)
  passes through when the connected agent is configured with output mode "All".
- Toggle **End user preview** on to see what a real user sees (the internal routing trace
  is a maker-only view).

## Recovering a corrupted agent

If a pac-pushed agent returns *InvalidContent* on every turn and the broken component
(often a custom topic's single-line Power Fx `condition` with embedded doubled quotes
`""x""`) isn't cleanly editable in the new declarative UI:

1. **More options (…) → Delete agent**, type the agent name to confirm, Delete.
   (The UI drops you into a fresh "Untitled Agent"; if a "Save flow" guard appears,
   choose **Continue without saving**, then create a New Agent cleanly.)
2. **Recreate in the UI** (steps 4–5). A UI-authored definition is serialized correctly by
   the product, sidestepping the pac round-trip bug entirely.
3. Prefer folding output-hygiene / guardrails into the **instructions** rather than a
   custom topic — it avoids the exact serialization landmine that caused the corruption.

## Safety

- Never type or store the user's password/MFA — hand off interactive sign-in to them.
- When testing an agent that can perform writes (e.g. an Ops child with confirm-before-write),
  **never confirm/execute a write** during routing tests — verify the confirm prompt appears
  and stop.

See `REFERENCE.md` for a copy-paste command cookbook and the ActWise orchestrator specifics.

## Related skill

To **test/benchmark or record a demo video** of an agent (rather than author it) over the
same Edge/CDP Preview session, use **copilot-studio-browser-testing** — it covers the
batch test loop, capturing answers/citations/latency, and both video-recording paths.
