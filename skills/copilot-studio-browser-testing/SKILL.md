---
name: copilot-studio-browser-testing
description: Test, benchmark, and record demo videos of Microsoft Copilot Studio agents by driving the maker Preview pane in a real browser via the agent-browser CLI over Chrome DevTools Protocol (CDP). Use this when you need to run a batch of probe/benchmark questions against a live agent and capture answers, citations, and rough latency — or produce a WebM/screen-capture video of an agent conversation for a demo or video-generation pipeline — and the backend test channels (PPAPI evaluations, DirectLine/SDK) are blocked by tenant Conditional Access (device compliance) or a missing App Registration with delegated Power Platform permissions. It is the run/observe/record counterpart to copilot-studio-browser-authoring (which creates/edits/publishes agents in the same browser session). Not for normal backend testing — use the copilot-studio Test skill (PPAPI/DirectLine/Kit) when the backend works.
---

# Copilot Studio — Browser Testing & Demo Recording (CDP)

Run probe/benchmark questions against a **live** Copilot Studio agent through the
maker **Preview** pane, capture the answers/citations/latency, and optionally
**record the session to video** for a demo — all by driving a real browser with the
[`agent-browser`](https://www.npmjs.com/package/agent-browser) CLI over CDP.

```
launch Edge (managed device, --remote-debugging-port)  →  user signs in ONCE
   →  agent-browser connect <port>  →  open Preview  →  [record start]
   →  ask questions, capture answers  →  [record stop]  →  score / save video
```

This is the sibling of **copilot-studio-browser-authoring**: same Edge/CDP session
mechanics, but focused on *exercising and recording* an agent rather than editing it.

## When to use this skill

- You want to **benchmark or regression-test** an agent's answers (quality, grounding,
  citations, approximate latency) but the API test paths are walled off:
  - **Conditional Access** blocks non-managed/automation browsers ("You can't get there
    from here … compliance policy") → PPAPI/DirectLine/SDK 403 or redirect forever.
  - **No App Registration** with delegated Power Platform scopes
    (`CopilotStudio.Copilots.Invoke`, `CopilotStudio.MakerOperations.Read/ReadWrite`),
    admin consent pending IT.
- You want a **demo video** of an agent conversation for a deck, README, or an
  automated video-generation pipeline.
- You want to **compare two agents** (or an agent vs another system) on the same
  question set, front-ending the same tools.

If the backend works, prefer the `copilot-studio` **Test** skill (PPAPI evaluations,
DirectLine, the Copilot Studio Kit) — it's faster, headless, and gives exact timings.

## Prerequisites

- `agent-browser` installed (`npm i -g agent-browser && agent-browser install`).
  Load its own guide first: `agent-browser skills get core`.
- **Run on the user's managed / Intune-compliant device**, using **Microsoft Edge**
  (not Chrome). Edge presents the device compliance state through the Windows account
  broker (WAM), so a fresh Edge profile passes Conditional Access after one interactive
  sign-in. See copilot-studio-browser-authoring for the full CA rationale.
- The **user completes interactive sign-in** (password + MFA). Never handle their
  password. Confirm the Edge window is visible to them first.

## The core pattern

### 1. Launch Edge with remote debugging + connect

Same as authoring — a dedicated profile dir; device compliance comes from the OS.

```powershell
$edge = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
$udd  = "$env:TEMP\edge-debug-profile"
New-Item -ItemType Directory -Force -Path $udd | Out-Null
Start-Process -FilePath $edge -ArgumentList @(
  "--remote-debugging-port=9222","--user-data-dir=`"$udd`"",
  "--no-first-run","--no-default-browser-check",
  "https://copilotstudio.microsoft.com/environments/<ENV_ID>/agents/<AGENT_ID>")
Start-Sleep 8
(Invoke-RestMethod "http://localhost:9222/json/version").Browser   # verify CDP
```

Ask the user to sign in. Then connect on the **default** session (passing
`--session <name>` to a running daemon can race → "Daemon failed to start"):

```powershell
$env:AGENT_BROWSER_TIMEOUT=15000   # connect can hang taking the first SPA snapshot
agent-browser connect 9222
agent-browser get url              # confirm on the agent page, not a login redirect
```

### 2. Open the Preview pane

```
click tab "Preview"   →   (optional) click "New chat" for a clean transcript
```

Refs shift after every navigation — **re-run `agent-browser snapshot -i` and re-resolve
`ref=(e\d+)` before each interaction**. The chat input is `textbox "Chat message input"`
and the send button is `button "Send"`.

### 3. Run a batch of questions (the test loop)

For each question: resolve the input/Send refs → type → click Send → wait → capture.

```powershell
# refs move every turn, so re-resolve right before sending:
$in = agent-browser snapshot -i | Select-String 'Chat message input' | Select-Object -First 1
$sn = agent-browser snapshot -i | Select-String '"Send"'            | Select-Object -First 1
if ($in -match 'ref=(e\d+)') { $inRef = $matches[1] }
if ($sn -match 'ref=(e\d+)') { $snRef = $matches[1] }
$t0 = Get-Date
agent-browser type   "$inRef" "What is DART in ActOne?"
agent-browser click  "$snRef"
Start-Sleep 40                                   # answer streams + renders
```

Then capture the result. Prefer a **filtered snapshot** for text/citations, and fall
back to a **screenshot** when the DOM is mid-render:

```powershell
$s = agent-browser snapshot 2>&1 | Out-String
if ($s -match 'Timeout') { Start-Sleep 25; agent-browser screenshot "C:\...\q1.png" }
else { $s | Select-String 'You said|heading|/url:.*niceactimize|Based on ActOne|Citations' }
```

Record wall-clock latency, whether the answer cites `docs.niceactimize.com`
(citation links appear as `link "N { \"title\": ... "` with a `/url:` to the doc), and a
short answer summary. Persist to a table (see REFERENCE.md `bench`-style schema).

> **Latency caveat:** browser Preview timing = wall-clock including render + your
> `Start-Sleep` buffers, so it's an **approximate upper bound**, not a like-for-like
> number vs a stream-terminal API measurement. State this in any comparison.

### 4. Record a demo video

`agent-browser` records WebM via Playwright's native recorder. **Key caveat:**
`record start` spins up a **fresh Playwright browser context** (it copies cookies +
localStorage but is not the CDP-attached Edge window). For Copilot Studio this fresh
context **may re-hit Conditional Access** because it doesn't carry the WAM/device broker
state. So there are two recording paths — pick per reliability:

**A. agent-browser native WebM (try first, verify it stays signed in):**
```powershell
agent-browser record start "C:\...\demo.webm"    # defaults to current URL
# ...drive the Preview conversation as in step 3...
agent-browser record stop
agent-browser get url    # if it bounced to a login page, the fresh context lost CA → use path B
```

**B. OS screen capture of the visible Edge window (CA-safe, WYSIWYG — recommended for
Copilot Studio demos):** capture exactly what the signed-in user sees.
```powershell
# ffmpeg gdigrab (whole desktop). Install ffmpeg if absent (winget install Gyan.FFmpeg).
$ff = "ffmpeg"; $out = "C:\...\demo.mp4"
Start-Process $ff -ArgumentList @("-y","-f","gdigrab","-framerate","15","-i","desktop",
  "-c:v","libx264","-pix_fmt","yuv420p",$out) -PassThru | Tee-Object -Variable rec | Out-Null
# ...drive the Preview conversation...
Stop-Process -Id $rec.Id           # stops the capture and finalizes the file
```
(Windows Game Bar `Win+Alt+R` is a zero-install manual alternative the user can trigger.)

For a clean demo take: `New chat` first, toggle **End user preview** on (hides the
maker-only routing trace), type at a human-readable pace, and pause ~2s on the final
answer before stopping. See REFERENCE.md for a full record-a-demo recipe.

### 5. Score and report

Summarize per question: grounded? cited (source_url present)? approx latency. For an
A/B comparison, keep one row per question with both agents' columns and note the shared
tool backend (so the comparison isolates agent behavior, not the data source). See the
`bench` pattern in REFERENCE.md.

## Cleanup

Always tear down when done (frees port 9222, removes the throwaway profile):
```powershell
# stop daemon + the debug Edge, then delete the profile
Get-CimInstance Win32_Process | ? { $_.Name -eq 'node.exe' -and $_.CommandLine -match 'daemon.js' } |
  % { Stop-Process -Id $_.ProcessId -Force }
Get-CimInstance Win32_Process -Filter "Name='msedge.exe'" | ? { $_.CommandLine -match 'edge-debug-profile' } |
  % { Stop-Process -Id $_.ProcessId -Force }
Start-Sleep 4; Remove-Item "$env:TEMP\edge-debug-profile" -Recurse -Force -ErrorAction SilentlyContinue
```
Keep any demo videos; delete throwaway screenshots.

## Safety

- Never type or store the user's password/MFA — hand off interactive sign-in to them.
- Only stop processes with `Stop-Process -Id <PID>` (never name/image-based kills).
- When probing an agent that can perform **writes** (e.g. an Ops child with
  confirm-before-write), verify the confirm prompt appears and **stop** — do not confirm
  a real write during a test/demo unless the user explicitly asks.

See `REFERENCE.md` for a copy-paste cookbook (test loop, both recording paths, the
`bench` schema) and the concrete eve-vs-Copilot benchmark this skill was distilled from.
