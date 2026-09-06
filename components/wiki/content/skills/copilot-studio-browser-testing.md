# Copilot Studio — Browser Testing & Demo Recording (CDP)

> Test, benchmark, and record demo videos of Microsoft Copilot Studio agents by driving the maker **Preview** pane in a real browser via the `agent-browser` CLI over Chrome DevTools Protocol — the run/observe/record counterpart to browser authoring.

## Goal
When the backend test channels for a Copilot Studio agent — PPAPI evaluations, DirectLine, the Copilot Studio Kit — are blocked by tenant Conditional Access or a missing App Registration, you still need to exercise the agent: run a batch of probe/benchmark questions, capture answers/citations/latency, and produce a demo video. This skill teaches an AI agent to drive the maker **Preview** pane directly in a compliant browser and record the result.

## How it fits
This skill drives the external [`agent-browser`](https://www.npmjs.com/package/agent-browser) CLI over CDP rather than an ActWise bucket CLI. It is the sibling of [copilot-studio-browser-authoring](copilot-studio-browser-authoring.md): the two share the exact Edge/CDP session mechanics, but authoring *creates/edits/publishes* an agent while this skill *runs, observes, and records* one. Prefer the normal `copilot-studio` **Test** skill (PPAPI/DirectLine/Kit) when the backend works — it is faster, headless, and gives exact timings.

## When to use it
- You need to **benchmark or regression-test** an agent's answers (quality, grounding, citations, approximate latency) but the API test paths are walled off (Conditional Access blocks non-managed browsers, or no consented delegated Power Platform scopes).
- You want a **demo video** of an agent conversation for a deck, README, or an automated video-generation pipeline.
- You want to **compare two agents** on the same question set (A/B), especially when they front the same tools/backend so the comparison isolates agent behavior.

## What it does
- Launches Edge with `--remote-debugging-port` on the user's managed/Intune-compliant device to satisfy Conditional Access after one interactive sign-in, then connects `agent-browser` over CDP.
- Opens the **Preview** pane and runs a batch of questions one turn at a time (re-resolving element refs before every turn, since they shift after each message).
- Captures each answer via filtered snapshot, falling back to a screenshot when a big table is mid-render, and records whether the answer cites a real `docs.niceactimize.com` page plus approximate wall-clock latency.
- **Records a demo video** via one of two paths: `agent-browser record start/stop` (native WebM) or — recommended for Copilot Studio — an OS screen capture (`ffmpeg gdigrab` / Windows Game Bar) of the real signed-in window, which avoids the Conditional Access bounce that the native recorder's fresh browser context can hit.
- Scores results and produces an A/B report, then tears down the session (frees the debug port, removes the throwaway profile).

## Install / enable
Skills follow the open Agent Skills spec and install via the `skills` CLI:
```powershell
npx skills add https://github.com/vinayguda/actwise.git --skill copilot-studio-browser-testing -a claude-code -g
```
Skills are instructions only. Like browser authoring, this skill drives the external **`agent-browser`** CLI (`npm i -g agent-browser && agent-browser install`; load its guide with `agent-browser skills get core`) plus Microsoft Edge on a managed device — not an `actwise` console script. Video path B additionally uses `ffmpeg` (`winget install Gyan.FFmpeg`).

## Walkthrough
- *"Benchmark the Docs agent on these 6 questions."* → launch Edge on the managed device, connect over CDP, open Preview, loop the questions (type → Send → wait → capture answer + citation + latency), then report.
- *"Record a demo of the agent answering a DART question."* → New chat, toggle End user preview on, start an OS screen capture, ask the question, pause on the answer, stop the capture.
- *"Compare our portal agent vs the Copilot Studio agent."* → run the same set against both, store one row per question with both agents' columns, and note the shared tool backend so the A/B isolates agent behavior.

## Limits & safety
- **Never type or store the user's password/MFA** — hand off the interactive sign-in to them; confirm the browser window is visible first.
- Must run on the user's managed/compliant device (device compliance is satisfied at the device/broker level, which is why a cloud/sandbox browser cannot pass).
- Browser Preview latency is an **approximate upper bound** (wall-clock including render + wait buffers), not a like-for-like number vs a stream-terminal API measurement — always flag this caveat in any comparison.
- When probing an agent that can perform **writes** (e.g. an Ops child with confirm-before-write), verify the confirm prompt appears and **stop** — do not confirm a real write during a test/demo unless the user explicitly asks.

## See also
- CLI: [`agent-browser`](https://www.npmjs.com/package/agent-browser) (external)
- Related skill: [copilot-studio-browser-authoring](copilot-studio-browser-authoring.md) (create/edit/publish over the same Edge/CDP session)
- Prefer the normal `copilot-studio` Test skill (PPAPI/DirectLine/Kit) when the backend works.
