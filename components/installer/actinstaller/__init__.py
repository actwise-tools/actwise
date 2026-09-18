"""actimize-installer — gated runner that installs packages fetched by `ndc`.

Detects the Actimize installer inside a downloaded NICE Download Center package
(ActOne rcm-installer, generic/patch Actimize-installer, or AIS setup.exe),
builds the exact command line, and runs it behind a confirmation gate with
captured logs. Dry-run by default. Completes the ActWise chain:
docs (docenter) -> package (ndc) -> install (actimize-installer).
"""
from .cli import app

__all__ = ["app"]
