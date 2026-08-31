"""DOCenter login broker — packaged inside the actwise distribution.

Turns the MCP's Phase-3 ``SessionRequired`` into a real per-user login: mint a
one-time login link, drive a hosted interactive browser to the real DOCenter
login, capture the user's own ``_SESSION`` (the exact success signal used by
``docenter.cli._browser_login``), and write it to the Phase-3 per-user store.
"""
