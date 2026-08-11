"""Path resolution shared by all actwise components."""
import os
from pathlib import Path

def repo_root(anchor: Path | None = None) -> Path | None:
    """Dev-checkout root: walk up from this file (or anchor) to the first dir
    containing pyproject.toml AND components/. None when wheel-installed."""
    p = (anchor or Path(__file__)).resolve()
    for parent in [p, *p.parents]:
        if (parent / "pyproject.toml").is_file() and (parent / "components").is_dir():
            return parent
    return None

def find_config(filename: str) -> Path:
    """First existing of: $ACTWISE_CONFIG_DIR/<f> -> cwd/<f> -> ~/.actwise/<f> ->
    <dev repo root>/<f>. If none exist, returns ~/.actwise/<f> (a non-existing
    path, so callers' .exists() checks fall through to their built-in defaults,
    and 'config init' style writers have a sane target)."""
    candidates = []
    env_dir = os.environ.get("ACTWISE_CONFIG_DIR")
    if env_dir:
        candidates.append(Path(env_dir).expanduser() / filename)
    candidates.append(Path.cwd() / filename)
    home = Path.home() / ".actwise" / filename
    candidates.append(home)
    root = repo_root()
    if root is not None:
        candidates.append(root / filename)
    for c in candidates:
        if c.exists():
            return c
    return home
