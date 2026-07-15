"""ActWise — ActOne Utilities runner (C-U).

Typed CLI + MCP wrapper over ActOne's Java maintenance utilities
(Blotter Maintenance, DART runner) with a pluggable execution backend
(local / ssh / winrm). See ``cli.py`` (``actone-utils``) and ``server.py``
(``actone-utils-mcp``).
"""
from .cli import app, main

__all__ = ["app", "main"]
