"""Shared path resolution for the actone package.

- PKG/DATA/BUNDLED point at packaged, read-only assets (ship in the wheel).
- workdir() is where the CLI reads/writes per-run artifacts (specs/, generated/,
  reports/, .env). Defaults to the current directory; override with ACTONE_WORKDIR.
"""
import os
from pathlib import Path

PKG = Path(__file__).parent
DATA = PKG / "data"
BUNDLED = DATA / "ActOne_Extend_Rest_APIs.bundled.yaml"


def workdir() -> Path:
    return Path(os.environ.get("ACTONE_WORKDIR") or Path.cwd())
