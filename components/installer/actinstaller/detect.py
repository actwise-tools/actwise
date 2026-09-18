"""Detect which Actimize installer lives inside a downloaded package.

The NICE Download Center ships packages that are consumed by one of a small
number of installer engines. This module inspects an *extracted* package
directory and reports the installer flavor, its executable, and the config
files it expects — the facts the runner needs to build a safe command line.

Interfaces (verified against the DOCenter Installation Guides, 2026-07-02):

- ActOne "RCM" installer  -> ``Installer/bin/rcm-installer.{bat,sh}``
  CONF-driven, task/step engine. Usage:
  ``rcm-installer [install|upgrade|show] [-i/-x TASK] [-f] [-c/-w/-l DIR]``
  (ActOne itself does NOT support the ``upgrade`` command.)

- Generic / Patch installer -> ``Installer/bin/Actimize-installer{,.bat,.sh}``
  Same grammar as rcm-installer plus ``upgrade --from/-F`` / ``--to/-T`` for
  patch ranges. Used by the Actimize Patch Installer.

- AIS Visual Modeler / Server Monitor -> ``setup.exe`` (MSI-style). Usage:
  ``setup.exe silent -<mode> [-f features] [-p path] [-v version] [/hide_progress]``
  modes: new|upgrade|modify|repair|uninst.
"""
from __future__ import annotations

import zipfile
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Optional


class InstallerKind(str, Enum):
    ACTONE = "actone"          # rcm-installer (ActOne / RCM)
    GENERIC = "generic"        # Actimize-installer (generic + patch installer)
    AIS_MODELER = "ais-modeler"  # setup.exe (Visual Modeler / Server Monitor)
    UNKNOWN = "unknown"


# Filenames we look for, in priority order. First hit wins.
_ACTONE_BINS = ("rcm-installer.bat", "rcm-installer.sh")
_GENERIC_BINS = (
    "Actimize-installer.bat", "Actimize-installer.sh",
    "actimize-installer.bat", "actimize-installer.sh",
    "Actimize-installer", "actimize-installer",
)
_MODELER_BINS = ("setup.exe",)


@dataclass
class DetectedInstaller:
    kind: InstallerKind
    package_root: Path            # dir the user pointed us at (extracted package)
    installer_dir: Optional[Path]  # the `Installer/` root, if present
    bin: Optional[Path]           # the installer executable/script
    conf_dir: Optional[Path]      # `Installer/conf` (CONF files to populate)
    conf_files: list[Path] = field(default_factory=list)
    logs_dir: Optional[Path] = None
    notes: list[str] = field(default_factory=list)

    @property
    def found(self) -> bool:
        return self.kind is not InstallerKind.UNKNOWN and self.bin is not None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["kind"] = self.kind.value
        for k in ("package_root", "installer_dir", "bin", "conf_dir", "logs_dir"):
            d[k] = str(d[k]) if d[k] is not None else None
        d["conf_files"] = [str(p) for p in self.conf_files]
        d["found"] = self.found
        return d


def _first_existing(root: Path, names: tuple[str, ...]) -> Optional[Path]:
    """Return the first matching file found anywhere under root (shallow-first)."""
    hits: list[Path] = []
    for name in names:
        hits.extend(root.rglob(name))
    if not hits:
        return None
    hits.sort(key=lambda p: (len(p.relative_to(root).parts), str(p).lower()))
    return hits[0]


def maybe_extract(package: Path, dest: Optional[Path] = None) -> Path:
    """If `package` is a .zip, extract it next to itself and return the dir.

    A directory is returned unchanged. Extraction target defaults to a sibling
    ``<name>_extracted`` folder; existing extractions are reused.
    """
    if package.is_dir():
        return package
    if package.suffix.lower() == ".zip" and package.is_file():
        target = dest or package.with_name(package.stem + "_extracted")
        if not target.exists():
            with zipfile.ZipFile(package) as zf:
                zf.extractall(target)
        return target
    raise FileNotFoundError(
        f"Package path is neither a directory nor a .zip: {package}"
    )


def detect(package: Path) -> DetectedInstaller:
    """Inspect an extracted package directory and classify its installer."""
    root = package.resolve()
    if not root.exists():
        raise FileNotFoundError(f"Package path does not exist: {root}")

    notes: list[str] = []

    # 1) ActOne / RCM (highest priority — it's the modern platform installer).
    bin_path = _first_existing(root, _ACTONE_BINS)
    kind = InstallerKind.ACTONE if bin_path else InstallerKind.UNKNOWN

    # 2) Generic / Patch installer.
    if bin_path is None:
        bin_path = _first_existing(root, _GENERIC_BINS)
        if bin_path:
            kind = InstallerKind.GENERIC

    # 3) AIS Visual Modeler / Server Monitor (setup.exe).
    if bin_path is None:
        bin_path = _first_existing(root, _MODELER_BINS)
        if bin_path:
            kind = InstallerKind.AIS_MODELER
            notes.append(
                "Detected an MSI-style setup.exe (AIS Visual Modeler / Server "
                "Monitor). Uses `setup.exe silent -<mode>` grammar, not the "
                "task/step CONF engine."
            )

    installer_dir = None
    conf_dir = None
    conf_files: list[Path] = []
    logs_dir = None
    if bin_path is not None and kind in (InstallerKind.ACTONE, InstallerKind.GENERIC):
        # bin lives at <Installer>/bin/<exe>
        installer_dir = bin_path.parent.parent
        conf_dir = installer_dir / "conf"
        if conf_dir.is_dir():
            conf_files = sorted(
                p for p in conf_dir.rglob("*")
                if p.is_file() and p.suffix.lower() in (".conf", ".ini", ".env", ".properties")
            )
        else:
            conf_dir = None
            notes.append("No Installer/conf folder found — CONF files may be elsewhere.")
        logs_dir = installer_dir / "logs"

    if bin_path is None:
        notes.append(
            "No known Actimize installer found. Looked for rcm-installer.{bat,sh}, "
            "Actimize-installer, and setup.exe. Is the package extracted?"
        )

    return DetectedInstaller(
        kind=kind,
        package_root=root,
        installer_dir=installer_dir,
        bin=bin_path,
        conf_dir=conf_dir,
        conf_files=conf_files,
        logs_dir=logs_dir,
        notes=notes,
    )
