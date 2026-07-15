"""Build and (optionally) execute Actimize installer commands, with guardrails.

Installs mutate an environment, so this runner is **dry-run by default**. It
builds the exact command line from a detected package and only executes when
explicitly told to (``execute=True``), after pre-flight checks. Every real run
is captured to a timestamped log under ``installer-runs/``.
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from .detect import DetectedInstaller, InstallerKind
from actwise.paths import repo_root

# Repo-root default for run logs (gitignored).
REPO_ROOT = repo_root() or Path(__file__).resolve().parent.parent
RUNS_DIR = Path(os.environ.get("ACTINSTALLER_RUNS", str(REPO_ROOT / "installer-runs")))

# Words in a conf/target path that suggest a production environment.
_PROD_HINTS = ("prod", "production")


@dataclass
class InstallPlan:
    """A fully-resolved command line plus the pre-flight findings."""
    kind: InstallerKind
    argv: list[str]
    cwd: Path
    log_dir: Optional[Path]
    warnings: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)

    @property
    def command_str(self) -> str:
        return " ".join(_quote(a) for a in self.argv)

    def to_dict(self) -> dict:
        return {
            "kind": self.kind.value,
            "argv": self.argv,
            "command": self.command_str,
            "cwd": str(self.cwd),
            "log_dir": str(self.log_dir) if self.log_dir else None,
            "warnings": self.warnings,
            "blockers": self.blockers,
        }


def _quote(a: str) -> str:
    return f'"{a}"' if (" " in a or "\t" in a) else a


def build_plan(
    det: DetectedInstaller,
    *,
    command: str = "install",
    mode: Optional[str] = None,
    include: Optional[list[str]] = None,
    exclude: Optional[list[str]] = None,
    force: bool = False,
    from_version: Optional[str] = None,
    to_version: Optional[str] = None,
    conf: Optional[Path] = None,
    work: Optional[Path] = None,
    log: Optional[Path] = None,
    # AIS setup.exe knobs
    features: Optional[str] = None,
    target_path: Optional[str] = None,
    upgrade_from: Optional[str] = None,
    allow_prod: bool = False,
) -> InstallPlan:
    """Resolve a command line for the detected installer.

    ``mode`` (full|sp|patch) is a friendly alias that picks the native command
    when ``command`` isn't given explicitly: full -> install, sp/patch -> upgrade.
    """
    warnings: list[str] = []
    blockers: list[str] = []

    if not det.found or det.bin is None:
        blockers.append("No installer executable detected in the package.")
        return InstallPlan(det.kind, [], det.package_root, None, warnings, blockers)

    # mode -> native command (explicit `command` still wins if caller set it).
    if mode:
        m = mode.lower()
        if m == "full":
            command = "install"
        elif m in ("sp", "patch"):
            command = "upgrade"
        else:
            warnings.append(f"Unknown --mode '{mode}'; ignoring.")

    if det.kind is InstallerKind.AIS_MODELER:
        return _build_modeler_plan(
            det, mode=mode, features=features, target_path=target_path,
            upgrade_from=upgrade_from, warnings=warnings, blockers=blockers,
        )

    # ── ActOne / Generic (rcm-installer | Actimize-installer) ──────────────
    argv: list[str] = [str(det.bin), command]

    if command == "upgrade" and det.kind is InstallerKind.ACTONE:
        blockers.append(
            "The ActOne (rcm-installer) does NOT support the `upgrade` command. "
            "Use `install`, or use the Patch Installer for patches."
        )
    if (from_version or to_version) and command != "upgrade":
        warnings.append("--from/--to only apply to the `upgrade` command; ignoring.")

    for t in include or []:
        argv += ["-i", t]
    for t in exclude or []:
        argv += ["-x", t]
    if force:
        argv.append("-f")
    if command == "upgrade":
        if from_version:
            argv += ["-F", from_version]
        if to_version:
            argv += ["-T", to_version]
    if conf:
        argv += ["-c", str(conf)]
    if work:
        argv += ["-w", str(work)]
    if log:
        argv += ["-l", str(log)]

    # Pre-flight: CONF files must exist/be populated for a task/step engine.
    conf_dir = conf or det.conf_dir
    if command in ("install", "upgrade"):
        if conf_dir is None or not Path(conf_dir).is_dir():
            warnings.append(
                "No CONF directory found — the installer needs populated CONF "
                "files (Installer/conf). Verify before executing."
            )
        else:
            _check_conf_prod(Path(conf_dir), allow_prod, warnings, blockers)

    cwd = det.bin.parent  # installers expect to run from Installer/bin
    return InstallPlan(det.kind, argv, cwd, det.logs_dir, warnings, blockers)


def _build_modeler_plan(det, *, mode, features, target_path, upgrade_from,
                        warnings, blockers) -> InstallPlan:
    """setup.exe silent -<mode> [-f features] [-p path] [-v version] /hide_progress"""
    m = (mode or "new").lower()
    valid = {"full": "new", "new": "new", "upgrade": "upgrade",
             "modify": "modify", "repair": "repair", "uninst": "uninst",
             "patch": "upgrade", "sp": "upgrade"}
    smode = valid.get(m)
    if smode is None:
        blockers.append(f"Unsupported setup.exe mode '{mode}'. "
                        "Use new|upgrade|modify|repair|uninst.")
        smode = "new"
    argv = [str(det.bin), "silent", f"-{smode}"]
    if features:
        argv += ["-f", features]
    if target_path:
        argv += ["-p", target_path]
    if smode == "upgrade" and upgrade_from:
        argv += ["-v", upgrade_from]
    argv.append("/hide_progress")
    warnings.append(
        "On Windows, prefix with `start /wait` to block until the setup "
        "completes (prevents parallel installs)."
    )
    return InstallPlan(det.kind, argv, det.bin.parent, None, warnings, blockers)


def _check_conf_prod(conf_dir: Path, allow_prod: bool,
                     warnings: list[str], blockers: list[str]) -> None:
    """Cheap production guard: scan CONF text for prod hostnames/markers."""
    hits: list[str] = []
    for p in conf_dir.rglob("*"):
        if not p.is_file():
            continue
        low = p.name.lower()
        if any(h in low for h in _PROD_HINTS):
            hits.append(p.name)
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore").lower()
        except Exception:
            continue
        if any(h in text for h in _PROD_HINTS):
            hits.append(p.name)
    if hits:
        msg = (f"CONF references a production environment ({', '.join(sorted(set(hits)))}). "
               "Refusing without --allow-prod." if not allow_prod
               else f"CONF references production ({', '.join(sorted(set(hits)))}); "
                    "proceeding because --allow-prod was set.")
        (blockers if not allow_prod else warnings).append(msg)


def execute(plan: InstallPlan, *, runs_dir: Path = RUNS_DIR) -> tuple[int, Path]:
    """Run the plan, tee-ing combined output to a timestamped run log.

    Returns (exit_code, log_path). Caller is responsible for the confirmation
    gate — this function assumes consent has already been obtained.
    """
    runs_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_path = runs_dir / f"{stamp}-{plan.kind.value}.log"

    header = (f"# actimize-installer run {stamp}\n"
              f"# kind: {plan.kind.value}\n"
              f"# cwd:  {plan.cwd}\n"
              f"# cmd:  {plan.command_str}\n\n")
    with log_path.open("w", encoding="utf-8") as logf:
        logf.write(header)
        logf.flush()
        proc = subprocess.Popen(
            plan.argv, cwd=str(plan.cwd),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            print(line, end="")
            logf.write(line)
            logf.flush()
        proc.wait()
    return proc.returncode, log_path
