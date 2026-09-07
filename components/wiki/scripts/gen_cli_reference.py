#!/usr/bin/env python
"""Generate an exhaustive CLI reference page from the live ``--help`` output.

Walks every ActWise console script and, recursively, every sub-command group,
capturing ``<cli> [<group> ...] <cmd> --help`` so the reference lists **all
options, arguments, and sub-commands** and never drifts from the installed tool.
Re-run after changing any CLI:

    python components/wiki/scripts/gen_cli_reference.py

Sub-processes run from a throwaway working directory so a malformed repo-root
``.env`` (which the CLIs auto-load) can never break capture.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

# The seven ActWise CLI console scripts.
CLIS: list[str] = [
    "docenter", "actone", "actone-data", "actone-utils", "ndc",
    "actimize-installer", "actone-local",
]

OUT = Path(__file__).resolve().parent.parent / "content" / "cli" / "full-reference.md"

# Deterministic, colour-free, wide-enough help output.
ENV = {**os.environ, "COLUMNS": "100", "NO_COLOR": "1", "TERM": "dumb"}
# A directory with no `.env`, so the CLIs' dotenv auto-load finds nothing to parse.
CLEAN_CWD = tempfile.mkdtemp(prefix="actwise-cli-help-")

MAX_DEPTH = 4          # cli -> group -> sub-group -> leaf (docenter auth sharepoint login)
BOX_CHARS = "\u2502|"  # Rich vertical border: unicode or ASCII


def help_text(args: list[str]) -> str:
    try:
        res = subprocess.run(
            args, capture_output=True, timeout=60, env=ENV, cwd=CLEAN_CWD,
        )
        raw = res.stdout or res.stderr or b""
        return raw.decode("utf-8", errors="replace").rstrip()
    except Exception as exc:  # noqa: BLE001
        return f"(could not capture help: {exc})"


def subcommands(text: str) -> list[str]:
    """Extract sub-command names from a Rich ``Commands`` panel (uni/ASCII)."""
    names: list[str] = []
    in_panel = False
    for line in text.splitlines():
        stripped = line.strip()
        if not in_panel:
            # Panel header, e.g. "\u250c\u2500 Commands \u2500\u2510" or "+- Commands --+".
            if "Commands" in line and stripped[:1] in "\u250c+":
                in_panel = True
            continue
        # Inside the Commands panel.
        if not stripped:
            continue
        if stripped[0] in BOX_CHARS:
            content = stripped[1:].rstrip(BOX_CHARS).rstrip()
            body = content.lstrip()
            indent = len(content) - len(body)
            # Command rows are indented 1 space; wrapped description lines are
            # indented to the description column (many spaces).
            if indent <= 2 and body:
                name = body.split()[0]
                if re.fullmatch(r"[a-zA-Z][\w-]*", name):
                    names.append(name)
            continue
        # A border/blank that is not a content row ends the panel.
        break
    return names


def walk(prefix: list[str], out: list[str], depth: int) -> None:
    text = help_text(prefix + ["--help"])
    heading = "#" * min(depth + 1, 6)
    out += [f"{heading} `{' '.join(prefix)}`", "", "```text", text, "```", ""]
    if depth >= MAX_DEPTH:
        return
    for cmd in subcommands(text):
        walk(prefix + [cmd], out, depth + 1)


def main() -> None:
    lines: list[str] = [
        "# CLI full reference",
        "",
        "> Auto-generated from each CLI's live `--help`, recursively covering every "
        "sub-command, argument, and option. Do not edit by hand \u2014 run "
        "`python components/wiki/scripts/gen_cli_reference.py` to refresh. For "
        "narrative and worked examples, see the individual CLI pages.",
        "",
    ]
    for cli in CLIS:
        if shutil.which(cli) is None:
            lines += [
                f"## `{cli}`", "",
                "!!! warning",
                f"    `{cli}` is not on PATH \u2014 install the ActWise distribution.", "",
            ]
            continue
        walk([cli], lines, depth=1)
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    shutil.rmtree(CLEAN_CWD, ignore_errors=True)
    print(f"wrote {OUT} ({len(CLIS)} CLIs, recursive)")


if __name__ == "__main__":
    main()
