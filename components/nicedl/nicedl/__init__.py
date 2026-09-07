"""nicedl — CLI for the NICE Download Center (Flexera SubscribeNet).

Search, list, and download NICE Actimize product **installation packages**
(the artifacts consumed by the Actimize Installer). Complements the `docenter`
CLI (documentation) by covering the install-package gap in the ActWise ecosystem.
"""
from .cli import app

__all__ = ["app"]
