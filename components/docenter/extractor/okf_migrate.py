#!/usr/bin/env python3
"""Open Knowledge Format (OKF) frontmatter migration.

Walks every Markdown file under ``raw_docs/`` and ADDS the five OKF frontmatter
keys (``type``, ``title``, ``resource``, ``tags``, ``timestamp``) to the leading
``---`` frontmatter block, alongside the seven legacy keys already present
(product, version, bundle, guide_type, page_title, source_url, updated).

Behaviour / guarantees:
  * Frontmatter-only: the Markdown body is never touched.
  * Additive: existing keys keep their original order, content, and quoting.
    New keys are appended just before the closing ``---`` fence, so the git diff
    contains only ADDED lines.
  * Idempotent: a file that already has all five OKF keys is skipped. Running
    the script a second time is a complete no-op (zero files migrated).

Known limitation:
  During migration there is NO network access, so only the date-only ``updated``
  value is available on disk. We therefore set ``timestamp`` to that date-only
  value. Freshly extracted/synced files (via extractor.build_front_matter) get a
  full ISO 8601 timestamp; migration of existing files is best-effort date-only.
"""

from pathlib import Path

RAW_DOCS = Path(__file__).parent.parent / "raw_docs"

OKF_KEYS = ("type", "title", "resource", "tags", "timestamp")


def parse_frontmatter(lines: list[str]) -> tuple[int, dict[str, str]]:
    """Return (closing_fence_index, {key: raw_value}) for the leading block.

    closing_fence_index is the index of the closing ``---`` line, or -1 if the
    file has no well-formed frontmatter block.
    """
    if not lines or lines[0].rstrip("\n") != "---":
        return -1, {}

    fields: dict[str, str] = {}
    for i in range(1, len(lines)):
        stripped = lines[i].rstrip("\n")
        if stripped == "---":
            return i, fields
        if ":" in stripped:
            key, value = stripped.split(":", 1)
            fields[key.strip()] = value.strip()
    return -1, {}


def derive_okf_lines(fields: dict[str, str]) -> list[str]:
    """Build the new OKF frontmatter lines from existing legacy fields."""
    def unquote(v: str) -> str:
        if len(v) >= 2 and v[0] == '"' and v[-1] == '"':
            return v[1:-1]
        return v

    product = unquote(fields.get("product", ""))
    version = unquote(fields.get("version", ""))
    bundle = unquote(fields.get("bundle", ""))
    guide_type = unquote(fields.get("guide_type", ""))
    page_title = unquote(fields.get("page_title", ""))
    source_url = unquote(fields.get("source_url", ""))
    updated = unquote(fields.get("updated", ""))

    okf_type = "Documentation Topic" if guide_type == "unknown" else guide_type

    return [
        f'type: "{okf_type}"\n',
        f'title: "{page_title}"\n',
        f"resource: {source_url}\n",
        f'tags: ["{product}", "{version}", "{bundle}", "{guide_type}"]\n',
        f'timestamp: "{updated}"\n',
    ]


def migrate_file(path: Path) -> bool:
    """Add OKF keys to a single file. Return True if the file was modified."""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)

    fence_idx, fields = parse_frontmatter(lines)
    if fence_idx == -1:
        return False

    if all(key in fields for key in OKF_KEYS):
        return False

    new_lines = derive_okf_lines(fields)
    updated_lines = lines[:fence_idx] + new_lines + lines[fence_idx:]

    path.write_text("".join(updated_lines), encoding="utf-8", newline="")
    return True


def main() -> None:
    scanned = 0
    migrated = 0
    skipped = 0

    for path in sorted(RAW_DOCS.rglob("*.md")):
        scanned += 1
        if migrate_file(path):
            migrated += 1
        else:
            skipped += 1

    print("OKF frontmatter migration complete.")
    print(f"  Files scanned : {scanned}")
    print(f"  Files migrated: {migrated}")
    print(f"  Files skipped : {skipped}")


if __name__ == "__main__":
    main()
