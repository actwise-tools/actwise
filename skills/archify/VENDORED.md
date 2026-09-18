# Vendored skill: archify

This directory is a **vendored third-party skill**, not an ActWise-authored one. It is
committed here so it can be packaged and uploaded into ActWise Copilot Studio agents
(GitHub Copilot harness) as an Agent Skill.

| | |
|---|---|
| Upstream | [`tt-a1i/archify`](https://github.com/tt-a1i/archify) · demo: <https://tt-a1i.github.io/archify/> |
| License | MIT (see `LICENSE`, `THIRD_PARTY_NOTICES.md`) — based on `Cocoon-AI/architecture-diagram-generator` (MIT) |
| Vendored version | `2.17` (see `metadata.version` in `SKILL.md`) |
| Vendored on | 2026-09-07 |

## How this differs from the other skills

- The skills under `skills/*` that are pinned in `../../skills-lock.json` are
  ActWise-authored, instructions-only wrappers around the ActWise console scripts.
- **archify is a self-contained Node tool** (zero runtime dependencies, no
  `node_modules`). It is driven as `node bin/archify.mjs <command> …`, and is **not**
  pinned in `skills-lock.json` or distributed via `npx skills add`. Like
  `copilot-studio-browser-authoring/` it lives under `skills/` without a lock entry.

## Local tuning applied

The only change from upstream is a `## Copilot Studio runtime profile (READ FIRST)`
block added near the top of `SKILL.md`. It tells the model, when running inside a
Copilot Studio sandbox, to: invoke `node bin/archify.mjs` from the skill root, skip the
network update-check, produce **HTML only** (no `visual-check`/`preview`/PNG/WebM export,
which need a browser), and hand the delivered `.html` to the agent's OneDrive tool at the
orchestrator layer. The upstream `test/` directory is excluded from the vendored copy.

## Rebuild the uploadable package

The Copilot Studio upload accepts a `.zip` with `SKILL.md` at its root. Rebuild it from
this tracked source (output lands in the gitignored `dist/`):

```powershell
$src = "skills\archify"
$out = "dist\skills\archify-skill-cps.zip"
New-Item -ItemType Directory -Force -Path (Split-Path $out) | Out-Null
if (Test-Path $out) { Remove-Item $out }
Compress-Archive -Path "$src\*" -DestinationPath $out
```

Then upload via the agent's **Build → Skills → Add skill → Upload a skill**. See
`docs/agents/2026-09-07-archify-skill-for-copilot-studio.md` for the full procedure and
sandbox constraints.
