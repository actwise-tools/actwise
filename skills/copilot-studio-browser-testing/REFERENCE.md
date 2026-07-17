# Reference — Copilot Studio Browser Testing & Demo Recording

Copy-paste cookbook for driving the Copilot Studio maker **Preview** pane with
`agent-browser` + Edge/CDP to run batch tests and record demo videos, plus the concrete
ActWise benchmark this skill was distilled from.

All commands assume PowerShell on the user's managed Windows device with
`agent-browser` on PATH. For the Edge launch + CA rationale, see the
**copilot-studio-browser-authoring** skill (shared session mechanics).

---

## Command cookbook

### Launch Edge, verify CDP, connect
```powershell
$edge = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
$udd  = "$env:TEMP\edge-debug-profile"
New-Item -ItemType Directory -Force -Path $udd | Out-Null
Start-Process -FilePath $edge -ArgumentList @(
  "--remote-debugging-port=9222","--user-data-dir=`"$udd`"",
  "--no-first-run","--no-default-browser-check",
  "https://copilotstudio.microsoft.com/environments/<ENV_ID>/agents/<AGENT_ID>")
Start-Sleep 8
(Invoke-RestMethod "http://localhost:9222/json/version").Browser
# user signs in, then:
$env:AGENT_BROWSER_TIMEOUT=15000     # connect can hang on the first heavy SPA snapshot
agent-browser connect 9222
agent-browser get url
```

### Open Preview + confirm the tool backend
```powershell
$pv = agent-browser snapshot -i | Select-String 'tab "Preview"' | Select-Object -First 1
if ($pv -match 'ref=(e\d+)') { agent-browser click ($matches[1]) }
Start-Sleep 6
# (optional) confirm the agent's tool, e.g.:
agent-browser snapshot -i | Select-String 'MCP Server|Add tool'
```

### One test turn (re-resolve refs every turn — they shift after each message)
```powershell
$in = agent-browser snapshot -i | Select-String 'Chat message input' | Select-Object -First 1
$sn = agent-browser snapshot -i | Select-String '"Send"'            | Select-Object -First 1
if ($in -match 'ref=(e\d+)') { $inRef = $matches[1] }
if ($sn -match 'ref=(e\d+)') { $snRef = $matches[1] }
$t0 = Get-Date
agent-browser type  "$inRef" "What is DART in ActOne?"
agent-browser click "$snRef"
Start-Sleep 40
```

### Capture the answer (snapshot text, fall back to screenshot when mid-render)
```powershell
$s = agent-browser snapshot 2>&1 | Out-String
if ($s -match 'Timeout') {
  Start-Sleep 25
  agent-browser screenshot "C:\path\q1.png"          # then view the image
} else {
  $s | Select-String 'You said|heading .*level=|/url:.*niceactimize|Based on ActOne|Citations'
}
$elapsedMs = [int]((Get-Date) - $t0).TotalMilliseconds
```
Citation links render as `link "N { \"title\": \"...\" ... "` with a child `/url:` line
pointing at the doc page — presence of a real `docs.niceactimize.com` `/url:` = cited.

### Loop a whole question set from SQL/CSV
```powershell
$qs = @(
  "What is DART in ActOne?",
  "How do I configure workflows in ActOne?",
  "What's new in the latest ActOne release?"
)
foreach ($q in $qs) {
  $in = agent-browser snapshot -i | Select-String 'Chat message input' | Select-Object -First 1
  $sn = agent-browser snapshot -i | Select-String '"Send"'            | Select-Object -First 1
  if ($in -match 'ref=(e\d+)') { $inRef = $matches[1] }
  if ($sn -match 'ref=(e\d+)') { $snRef = $matches[1] }
  agent-browser type "$inRef" $q; agent-browser click "$snRef"
  Start-Sleep 45
  agent-browser screenshot ("C:\path\{0}.png" -f ($q -replace '\W','_').Substring(0,20))
}
```

---

## Recording a demo video

### Path A — agent-browser native WebM (fast; verify it stays signed in)
```powershell
agent-browser record start "C:\path\demo.webm"     # no URL = current page
# ...drive the Preview conversation...
agent-browser record stop
agent-browser get url        # bounced to login? fresh context lost CA → use Path B
```
`record start` creates a **fresh Playwright context** (copies cookies/localStorage but is
NOT the CDP Edge window). It may re-trigger Conditional Access for Copilot Studio.

### Path B — OS screen capture of the real signed-in window (CA-safe, recommended)
```powershell
# ffmpeg gdigrab (whole desktop). winget install Gyan.FFmpeg  (if absent)
$out = "C:\path\demo.mp4"
$rec = Start-Process ffmpeg -PassThru -ArgumentList @(
  "-y","-f","gdigrab","-framerate","15","-i","desktop",
  "-c:v","libx264","-pix_fmt","yuv420p",$out)
# ...drive the Preview conversation...
Stop-Process -Id $rec.Id     # finalizes the MP4
```
To crop to just the Edge window instead of the full desktop, add
`-offset_x <X> -offset_y <Y> -video_size <W>x<H>` before `-i desktop`.

Manual zero-install alternative: **Win+Alt+R** (Windows Game Bar) — the user starts/stops
the capture themselves.

### Clean-take tips
- `New chat` first; toggle **End user preview** ON to hide the maker-only routing trace.
- Type at a readable pace; pause ~2s on the final answer before stopping.
- Record the whole run (login excluded) in one take, or use
  `agent-browser record restart <newfile>` to split takes.

---

## `bench` result schema (per-question, A/B friendly)

```sql
CREATE TABLE bench (
  id        TEXT PRIMARY KEY,   -- q1..qN
  q         TEXT,               -- the question
  tool_path TEXT,               -- shared backend (e.g. docenter-mcp) so A/B isolates the agent
  a_ms      INTEGER, a_answer TEXT, a_cited INTEGER,   -- agent A (e.g. eve)
  b_ms      INTEGER, b_answer TEXT, b_cited INTEGER    -- agent B (e.g. Copilot Studio)
);
```
Store approx latency (ms), a one-line answer summary, and cited=1/0. Note the shared
`tool_path` in the writeup so readers know the comparison isolates agent behavior
(prompt/routing/model/latency), not the data source.

---

## Symptom → cause → fix

| Symptom | Cause | Fix |
|---|---|---|
| `connect 9222` hangs forever | First `ariaSnapshot` of the heavy SPA times out | `$env:AGENT_BROWSER_TIMEOUT=15000` then retry `connect`; use the **default** session |
| "You can't get there from here … compliance policy" | Non-compliant browser hitting Conditional Access | Use **Edge** on the **managed device** with a dedicated `--user-data-dir` |
| `snapshot` → "locator.ariaSnapshot: Timeout 10000ms" | Page mid-stream/render (big tables) | `Start-Sleep 25` and take a **screenshot** instead; re-snapshot after render |
| Clicks land on the wrong element | Refs shifted after the last message | Re-run `snapshot -i` and re-resolve `ref=(e\d+)` **before every** turn |
| `record start` bounces to a login page | Fresh Playwright context lost the device-broker/CA state | Use **Path B** OS screen capture of the real Edge window |
| "Daemon failed to start (…\<name>.sock)" | `--session <name>` raced a running daemon | Use the **default** session for `connect` |
| Snapshot output "too large to read" | Full transcript grew past the tool cap | Save to file and `Select-String` for `You said|heading|/url:` only |

---

## Concrete run — eve Portal vs Copilot Studio (Actwise-Docs-Dev), 2026-07-17

**Environment:** `NiCE-All-PlayGround` = `b726c6c7-89b4-e8a5-9ea2-25821f40d34d`
**Agent:** `Actwise-Docs-Dev` botid `80fb3cf6-00f2-49a5-a371-e91870c91b9e`
**Sign-in:** `Vinay.Guda@niceactimize.com` (managed device; Edge passed CA).
**Shared backend:** both agents front the **same `docenter-mcp`** (the Copilot agent's
only tool is "ActWise docenter MCP Server") → the A/B isolates agent behavior, not docs.

Ran the 6-question set in the Preview pane, one turn at a time (type → Send → wait ~40s →
snapshot/screenshot), capturing answer summary, citation `/url:`, and approx latency:

| # | Question | eve (s) | eve cited | Copilot (s, approx) | Copilot cited |
|---|----------|--------:|:--------:|--------------------:|:------------:|
| q1 | What is DART? | 36.3 | yes | ~42 | yes |
| q2 | Configure workflows | 38.6 | yes | ~45 | yes |
| q3 | Latest release | 65.3 | yes | ~90 | yes |
| q4 | Install QAS | 37.1 | yes | ~80 | yes |
| q5 | Policy Manager | 30.6 | yes | ~60 | yes |
| q6 | Versions available | 13.1 | no  | ~15 | no |
| | **Avg** | **36.8** | 5/6 | **~55** | 5/6 |

**Findings:** both grounded and hallucination-free, citing real
`docs.niceactimize.com` pages (5/6; q6 is a catalog listing with no single source page).
Copilot's answers rendered richer (markdown tables, citation chips, follow-ups); eve was
~1.5× faster. Latency is **approximate** for Copilot (browser wall-clock incl. render +
`Start-Sleep`) vs eve's precise stream-terminal timing — always flag this caveat.

**Recording note:** for this run answers were captured via snapshot/screenshot. For a
demo video of the same flow, use **Path B** (OS screen capture) because the agent-browser
native recorder's fresh context risks a CA bounce on Copilot Studio.

**Gotchas hit this run:** `connect` hung on the first SPA snapshot (fixed with
`AGENT_BROWSER_TIMEOUT`); release-notes and QAS turns rendered large tables that timed out
`ariaSnapshot` (fell back to screenshots); refs shifted every turn (re-resolved each time).
