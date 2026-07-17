# ActWise content kit

Source material for turning the wiki into **presentations, blog posts, and videos**.
These files live outside `content/` on purpose — they are production inputs, not
published wiki pages.

Each wiki page already follows a repurposable template (Goal → How it fits → Install
→ Reference → Walkthrough → Under the hood → FAQ), so lifting content into a deck or
script is mostly copy-and-trim.

## Layout

```
kit/
├─ video/    video scripts (hook → problem → demo beats → CTA)
└─ decks/    slide outlines (Marp / PPTX-ready markdown)
```

## Producing artifacts

- **Slides:** the `decks/*.md` outlines are [Marp](https://marp.app/)-compatible;
  the ActWise Utility agent (or the `pptx` skill) can render them to PPTX.
- **Video:** `video/*.md` scripts are structured as timed beats with on-screen
  actions and voiceover, ready for a screen-capture recording.
- **Blog:** each wiki page's *Goal* + *Walkthrough* sections form the spine of a blog
  post; the MkDocs Material blog plugin can host them under `content/blog/` later.

## Convention

Keep artifacts grounded in the wiki (single source of truth). If a fact changes,
update the wiki page first, then regenerate the derived deck/script.
