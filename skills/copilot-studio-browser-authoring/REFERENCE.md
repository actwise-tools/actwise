# Reference — Copilot Studio Browser Authoring

Copy-paste command cookbook for `agent-browser` + Edge/CDP against the Copilot Studio
maker UI, plus the concrete ActWise orchestrator run this skill was distilled from.

All commands assume PowerShell on the user's managed Windows device with
`agent-browser` on PATH.

---

## Command cookbook

### Launch Edge + verify CDP
```powershell
$edge = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
$udd  = "$env:TEMP\edge-debug-profile"
New-Item -ItemType Directory -Force -Path $udd | Out-Null
Start-Process -FilePath $edge -ArgumentList @(
  "--remote-debugging-port=9222","--user-data-dir=`"$udd`"",
  "--no-first-run","--no-default-browser-check",
  "https://copilotstudio.microsoft.com/environments/<ENV_ID>/agents/<AGENT_ID>")
Start-Sleep 5
(Invoke-WebRequest -UseBasicParsing "http://localhost:9222/json/version").Content
```

### Connect + orient
```powershell
agent-browser connect 9222
agent-browser get url
agent-browser snapshot -i | Select-Object -First 60          # interactive elements + refs
agent-browser screenshot "C:\path\shot.png"                  # then view the image
```

### Resolve a ref by label, then click (refs shift after nav)
```powershell
$line = agent-browser snapshot -i | Select-String 'button "Publish" \[ref=' | Select-Object -First 1
if ($line -match "ref=(e\d+)") { agent-browser click ("@" + $matches[1]) }
```

### Enter text into the rich Instructions editor (fill() won't register)
```powershell
$body = @'
...multi-line instructions...
'@
agent-browser click "@e35"                 # the "Agent instructions" textbox
agent-browser keyboard inserttext $body    # updates model without markdown auto-format
# force reconciliation + verify:
agent-browser click "@e35"; agent-browser press "Control+End"; agent-browser keyboard type "."; agent-browser press "Backspace"
agent-browser eval "document.querySelector('[contenteditable=true]').innerText.length"
```

### Type into a plain textbox (name, description) — real keystrokes register fine
```powershell
agent-browser click "@e20"                 # focus first
agent-browser keyboard type "Actwise-Main-Dev"
agent-browser get value "@e20"
```

### Publish a new agent (Publish = Save + Publish)
```powershell
$p = agent-browser snapshot -i | Select-String 'button "Publish" \[ref=' | Select-Object -First 1
if ($p -match "ref=(e\d+)") { agent-browser click ("@" + $matches[1]) }
# confirm the "Save and publish this agent?" dialog by its BUTTON ref (text matches 3 nodes):
$c = agent-browser snapshot -i | Select-String 'button "Save and publish"' | Select-Object -First 1
if ($c -match "ref=(e\d+)") { agent-browser click ("@" + $matches[1]) }
```

### Add a connected agent
```powershell
agent-browser click "@<AddConnectedAgentRef>"
# pick child:
$k = agent-browser snapshot -i | Select-String 'button "Actwise-Docs-Dev"' | Select-Object -First 1
if ($k -match "ref=(e\d+)") { agent-browser click ("@" + $matches[1]) }
# required Description = routing signal (click the textbox, NOT "More info"):
$tb = agent-browser snapshot -i | Select-String 'textbox "Description' | Select-Object -First 1
if ($tb -match "ref=(e\d+)") { agent-browser click ("@" + $matches[1]) }
agent-browser keyboard type "Route here for ..."
$cn = agent-browser snapshot -i | Select-String '^- button .Connect.' | Select-Object -First 1
if ($cn -match "ref=(e\d+)") { agent-browser click ("@" + $matches[1]) }
```

### Test in Preview
```powershell
$pv = agent-browser snapshot -i | Select-String 'tab "Preview"' | Select-Object -First 1
if ($pv -match "ref=(e\d+)") { agent-browser click ("@" + $matches[1]) }
# New chat, then send a probe:
agent-browser click "@<ChatInputRef>"
agent-browser keyboard type "What is a blotter in ActOne?"
agent-browser press "Enter"
Start-Sleep 25
agent-browser screenshot "C:\path\resp.png"
```

---

## Symptom → cause → fix quick table

| Symptom | Cause | Fix |
|---|---|---|
| "You can't get there from here … compliance policy" | Non-compliant browser hitting Conditional Access | Use **Edge** on the **managed device** with a dedicated `--user-data-dir` |
| Every turn: "BotDefinitionOverride … InvalidContent" | pac-serialized component invalid at runtime (e.g. single-line Power Fx `condition` with `""x""`) | **Delete + recreate the agent in the UI**; fold guardrails into instructions |
| `fill` shows text but **Save stays disabled** | Rich editor model didn't get the change | `keyboard inserttext` + one real keystroke to reconcile |
| Save disabled on a **new** agent, can't save | Normal for uncreated agents | **Publish** — it saves + publishes and creates the agent |
| "Add connected agent" is disabled | Agent not created/published yet | Publish once first, then add connected agents |
| `find text "X" click` → "strict mode violation: N elements" | Label matches heading + button + toast | Snapshot for the exact `ref`, `click @eN` |
| "Daemon failed to start (…\<name>.sock)" | `--session <name>` raced an already-running daemon | Use the **default** session for `connect` |
| pac `push` → "Remote changes conflict" | Stale local change-token after a crashed push | `pac copilot pull`, resolve keeping your edits, `push` again |
| pac `publish` → 404 "Entity 'bot' Does Not Exist" | Island AgentId has no Dataverse `bot` row (deleted/split identity) | Publish the id that resolves in Dataverse, or rebuild in UI |

---

## ActWise orchestrator — concrete run (2026-07-13)

**Environment:** `NiCE-All-PlayGround` = `b726c6c7-89b4-e8a5-9ea2-25821f40d34d`
**Sign-in:** `Vinay.Guda@niceactimize.com` (managed device; Edge passed CA where sandbox Chrome was blocked).

**What happened:** the pac-pushed `Actwise-Main-Dev` (old id `1f7666a6-…`) was corrupted —
every turn returned *InvalidContent*. Root cause (Advisor-diagnosed): the
`suppress-tool-call-leaks` topic's single-line Power Fx `condition` used doubled quotes
`""tool_call""` / `""botschemaname""`; valid as a block scalar in `.mcs.yml` (LSP clean) but
mis-serialized into the runtime BotDefinitionOverride. pac push/publish was also blocked
(Dataverse 404 on the island id, pac read-back crashes). So we **deleted it and rebuilt in
the UI**.

**Rebuilt agent (canonical, live):**
- Name: `Actwise-Main-Dev`  •  botid `1101ff7f-357b-4e1d-94d6-32b2b61323c3`
- Model: Claude Sonnet 4.6  •  Router instructions authored in the UI (delegate-don't-answer,
  intent→child rubric, `list_environments` clarify-first, output hygiene) — no custom topic.
- Connected agents (each with a "route here when…" Description = the routing signal):
  - `Actwise-Docs-Dev`  — product knowledge & documentation (foundation)
  - `Actwise-Data-Dev`  — read-only reporting / analytics (v_acm_* views)
  - `Actwise-Ops-Dev`   — live operations (Extend REST + SOAP admin), confirm-before-write
  - (`ActWise-Utility-Dev` intentionally left OUT for now.)

**Validated in Preview:** clean greeting (no InvalidContent); "What is a blotter in ActOne?"
routed to **Actwise-Docs-Dev**, which returned its native answer (states table + summary +
"Based on ActOne 10.2 documentation" citation) passed straight through. Docs routing confirmed;
Data / Ops / clarify-first probes are the recommended next tests.

**Orphaned artifacts (safe to ignore / clean up):**
- Cloud: a pac draft was pushed to the **deleted** old island id `1f7666a6` (never published) —
  dies with the deleted agent.
- Local: `agents\_authoring\Actwise-Main-Dev\` (pac clone of the old, deleted `_21Of1F`
  identity) and `agents\_authoring\.fix-backup\` are now stale — the live agent is UI-authored,
  not represented by these files. Re-clone from `1101ff7f` if you want a local pac copy.

---

## Validation record — 2026-07-13 (all routing + safety probes PASS)

All four probes were run in the maker **Preview** pane over the live Edge/CDP session
against `Actwise-Main-Dev` (`1101ff7f-357b-4e1d-94d6-32b2b61323c3`):

| Probe | Utterance | Result |
|-------|-----------|--------|
| Docs | "What is a blotter in ActOne?" | Routed to `Actwise-Docs-Dev`; native answer + "Based on ActOne 10.2 documentation" citation. |
| Data | "How many open alerts are there?" | Routed to `Actwise-Data-Dev`; live read-only SQL returned **6 open alerts** + result table. |
| Ops (write, no-confirm) | "Close alert AL-1001…" | Routed to `Actwise-Ops-Dev`; proposed `updateWorkItem PUT /RCM/api/v2/work-items/{id}`, statusIdentifier→Closed, **⚠️ Confirmation Required — no execution**. |
| Clarify-first | "What environments exist?" | Asked one clarifying question (query-data vs run-ops); answering "operations" then routed to Ops and listed 3 configured ActOne environments. |

**Confirm → execute path (end-to-end write test):** re-ran the Ops write and this time
**confirmed** ("Yes, please proceed and close it."). On confirmation the Ops agent actually
executed the REST call and returned an honest result:

> *"The operation was attempted, but both the Work Items API and the Alert Details API
> returned **404 — Could not find Work Item AL-1001** on the `vinay-local-dev` instance."*

…followed by likely-cause diagnostics and next-step options. This proves: (1) the
confirm-before-write gate holds, (2) on explicit confirmation the write is genuinely executed
against the live REST API, and (3) real API errors are surfaced truthfully (no hallucinated
success). `AL-1001` was a non-existent id, so nothing was mutated — safe.

**Backup:** the live agent YAML is saved at
`agents/Actwise-Main-Dev/Actwise-Main-Dev-13Jul2026-published.yaml` (maker single-file export).

**Reusable eval set:** `agents/eval/actwise-main-dev-workflows.csv` (10 rows incl. the
canonical Data→Ops "find last 3 QA-review workitems → progress step" workflow with
confirm-before-write). Programmatic upload is blocked (no PPAPI create-testset API + 403
InsufficientDelegatedPermissions) → import once via the **Evaluate** tab. See the eval README.

**Cleanup done:** stale `agents/_authoring/` (pac clone of the deleted old identity) removed.
