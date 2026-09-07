# design-src — vendored NiCE Design System reference

Files copied on 2026-07-14 from the claude.ai/design project **"NiCE Design System"**
(`a277f0b7-819a-441e-8c07-2ae0aa6409a5`) so the portal can be implemented without access to
claude.ai. Reference material only — the portal serves its own copies from `../web/`.

| File | Origin path in the design project |
|---|---|
| `colors_and_type.css` | `colors_and_type.css` |
| `nicewise-styles.css` | `ui_kits/nicewise/styles.css` |
| `nicewise-components.jsx` | `ui_kits/nicewise/components.jsx` |
| `nicewise-screens.jsx` | `ui_kits/nicewise/screens.jsx` |
| `assets/nice-logo.svg` | `assets/logos/nice-logo.svg` (placeholder approximation, not master artwork) |
| `assets/nice-smile.svg` | `assets/logos/nice-smile.svg` (placeholder approximation) |
| `assets/ai-sparkle-blue.png` | `assets/icons/product/ai-sparkle-blue.png` |
| `assets/analytics-blue.png` | `assets/icons/product/analytics-blue.png` |
| `assets/ai-automation-blue.png` | `assets/icons/product/ai-automation-blue.png` |
| `assets/gradient-lavender-blue-small.png` | `assets/gradients/gradient-lavender-blue-small.png` |

The wide hero gradient JPGs (`gradient-*-wide.jpg`) exceed the export pipeline's 256 KiB
per-file limit and were not vendored — use the small gradient PNG cover-scaled, or the CSS
gradient tokens in `colors_and_type.css`.

Implementation spec: `docs/components/portal/HANDOFF-actwise-portal.md`.
