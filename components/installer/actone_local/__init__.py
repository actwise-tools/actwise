"""actone-local — repeatable local ActOne core setup (Docker + PostgreSQL).

Idempotent, disk-aware, laptop-friendly runner for the ActOne 10.2 local install
plan. Completes the ActWise chain:
docs (docenter) -> package (ndc) -> install (actimize-installer) -> **run local (actone-local)**.
"""
from .cli import app

__all__ = ["app"]
