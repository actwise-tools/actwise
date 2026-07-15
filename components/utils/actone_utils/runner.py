"""Assemble + run ActOne utilities (C-U).

Ties the three pieces together: take a catalog :class:`Utility` and user-supplied
values, validate/normalise them, assemble the *target* argv (script path + args),
enforce the state-changing gate, and hand the argv to the selected backend.

Safety
------
Reads / dry-runs always proceed. A **state-changing** utility only executes for
real when the caller explicitly opts in (``assume_yes`` from the CLI ``--yes``
flag, or ``ACTONE_UTILS_ALLOW_RUN`` for the MCP server). ``dry_run`` assembles and
returns the exact command without executing — always review it first.
"""
from __future__ import annotations

import os
from typing import Optional

from .backends import ExecutionBackend, ExecResult, make_backend
from .catalog import Utility, get, search
from .config import UtilsConfig


class UtilityError(Exception):
    """Unknown utility or invalid parameters."""


class RunGate(Exception):
    """A state-changing run was requested without explicit opt-in."""


def build_argv(cfg: UtilsConfig, util: Utility, values: dict,
               raw_args: Optional[list] = None) -> list:
    """Validate ``values`` against the utility's params and build the target argv.

    Any ``raw_args`` are appended verbatim after the typed args — an escape hatch
    for utility options not yet modelled in the catalog.
    """
    values = dict(values or {})
    unknown = set(values) - {p.name for p in util.params}
    if unknown:
        raise UtilityError(f"unknown parameter(s) for {util.name}: {', '.join(sorted(unknown))}")

    script = cfg.utilities_path + cfg._sep + util.tool + cfg.script_ext
    argv = [script]
    positionals, flags = [], []
    for p in util.params:
        try:
            v = p.coerce(values.get(p.name))
        except ValueError as e:
            raise UtilityError(str(e))
        if v is None:
            continue
        if p.type == "flag":
            if v:                        # bare presence switch, e.g. "-countinprogress"
                flags.append(p.flag)
            continue
        if p.positional:
            positionals.append(str(v))
        else:                            # ActOne "-name=value" convention
            flags.append(f"{p.flag}={v}")
    return argv + positionals + flags + [str(a) for a in (raw_args or [])]


def writes_enabled() -> bool:
    """MCP-side opt-in: ACTONE_UTILS_ALLOW_RUN truthy lets real state-changing runs proceed."""
    return os.environ.get("ACTONE_UTILS_ALLOW_RUN", "").strip().lower() in {"1", "true", "yes", "on"}


def run_utility(cfg: UtilsConfig, util_name: str, values: Optional[dict] = None,
                *, dry_run: bool = True, assume_yes: bool = False,
                backend: Optional[ExecutionBackend] = None,
                raw_args: Optional[list] = None,
                timeout: Optional[int] = None) -> dict:
    """Run one utility. Returns an ExecResult dict enriched with utility/backend meta."""
    util = get(util_name)
    if not util:
        raise UtilityError(f"unknown utility '{util_name}'; try: "
                           + ", ".join(b["name"] for b in search(util_name, 5)))

    argv = build_argv(cfg, util, values or {}, raw_args)

    if util.state_changing and not dry_run and not assume_yes:
        raise RunGate(
            f"'{util.name}' is state-changing. Re-run with --yes to execute, "
            f"or --dry-run to preview. Assembled command:\n  {' '.join(argv)}"
        )

    backend = backend or make_backend(cfg)
    result: ExecResult = backend.run(
        argv, cwd=cfg.utilities_path, env={}, dry_run=dry_run,
        timeout=timeout or cfg.default_timeout,
    )
    out = result.to_dict()
    out.update({"utility": util.name, "tool": util.tool,
                "access": "write" if util.state_changing else "read"})
    return out
