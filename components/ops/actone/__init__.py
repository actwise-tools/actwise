__all__ = ["app"]


def __getattr__(name):
    # Lazy re-export so importing a submodule (e.g. actone.registry from the MCP
    # server) doesn't eagerly import the typer-based CLI and its heavier deps.
    if name == "app":
        from .cli import app

        return app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

