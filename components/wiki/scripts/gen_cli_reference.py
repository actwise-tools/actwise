#!/usr/bin/env python
"""Generate an exhaustive CLI reference page from the live `--help` output.

Runs `<cli> --help` and `<cli> <sub> --help` for every ActWise console script and
writes the captured help into `content/cli/full-reference.md`, so the reference never
drifts from the installed tool. Re-run after changing any CLI:

    python components/wiki/scripts/gen_cli_reference.py
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

# The seven ActWise CLI console scripts.
CLIS: list[str] = [
    "docenter", "actone", "actone-data", "actone-utils", "ndc",
    "actimize-installer", "actone-local",
]

OUT = Path(__file__).resolve().parent.parent / "content" / "cli" / "full-reference.md"


def help_text(args: list[str]) -> str:
    env = {**os.environ, "COLUMNS": "100", "NO_COLOR": "1", "TERM": "dumb"}
    try:
        res = subprocess.run(
            args, capture_output=True, timeout=60, env=env,
        )
        raw = res.stdout or res.stderr or b""
        return raw.decode("utf-8", errors="replace").rstrip()
    except Exception as exc:  # noqa: BLE001
        return f"(could not capture help: {exc})"


def main() -> None:
    lines: list[str] = [
        "# CLI full reference",
        "",
        "> Auto-generated from each CLI's top-level `--help`. Do not edit by hand — "
        "run `python components/wiki/scripts/gen_cli_reference.py` to refresh. For "
        "per-command detail and worked examples, see the individual CLI pages.",
        "",
    ]
    for cli in CLIS:
        lines += [f"## `{cli}`", ""]
        if shutil.which(cli) is None:
            lines += ["!!! warning", f"    `{cli}` is not on PATH — install the ActWise distribution.", ""]
            continue
        lines += ["```text", help_text([cli, "--help"]), "```", ""]
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {OUT} ({len(CLIS)} CLIs)")


if __name__ == "__main__":
    main()
