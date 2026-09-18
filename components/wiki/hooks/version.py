"""MkDocs hook: stamp the site footer with the ActWise version + git ref.

Single-sources the version from the repo-root ``pyproject.toml`` and the current
git tag/commit, so the deployed wiki can always be tied back to a release. Fails
soft: if the version or git metadata can't be read, the footer is left untouched.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


def _repo_root() -> Path:
    # components/wiki/hooks/version.py -> repo root is three parents up.
    return Path(__file__).resolve().parents[3]


def _version() -> str:
    try:
        text = (_repo_root() / "pyproject.toml").read_text(encoding="utf-8")
    except OSError:
        return ""
    m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return m.group(1) if m else ""


def _git(*args: str) -> str:
    try:
        out = subprocess.run(
            ["git", *args],
            cwd=_repo_root(),
            capture_output=True,
            text=True,
            check=True,
        )
        return out.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def on_config(config, **kwargs):
    version = _version()
    sha = _git("rev-parse", "--short", "HEAD")
    repo = (config.get("repo_url") or "").rstrip("/")

    bits: list[str] = []
    if version:
        tag = f"v{version}"
        bits.append(f'<a href="{repo}/releases/tag/{tag}">{tag}</a>' if repo else tag)
    if sha:
        bits.append(f'<a href="{repo}/commit/{sha}">{sha}</a>' if repo else sha)

    if bits:
        config["copyright"] = "ActWise " + " · ".join(bits)
    return config
