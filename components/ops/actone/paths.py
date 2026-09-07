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
# Designer/SOAP catalog (22 services / 335 ops, 275 object types, 282 beans) that
# drives the generalized SOAP "designer" engine. Ships in the wheel; override the
# path with ACTONE_CATALOG for a version-specific regenerated catalog.
CATALOG = DATA / "actone-catalog.json"


def workdir() -> Path:
    return Path(os.environ.get("ACTONE_WORKDIR") or Path.cwd())
