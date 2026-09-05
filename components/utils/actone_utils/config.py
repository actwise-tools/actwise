"""Configuration for the ActOne utilities runner (C-U).

ActOne ships Java maintenance utilities as ``.bat`` / ``.sh`` scripts that live in
the install tree and are driven by ``utilities.env`` (JDK path + classpath) plus
per-tool CLI params. This config captures *where* those scripts run and *how* to
reach them, independent of *which* utility runs (that is the catalog's job).

Sources, lowest to highest precedence:
  1. dataclass defaults (local backend, conventional paths)
  2. YAML file ``actone-utils.yaml`` at the repo root (optional)
  3. environment variables ``ACTONE_UTILS_*`` (optional)

Stdlib + pyyaml only. Importable; no top-level work.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

import yaml

from actwise.paths import find_config

DEFAULT_CONFIG_PATH = find_config("actone-utils.yaml")

BACKENDS = ("local", "ssh", "winrm", "container")
SHELLS = ("auto", "sh", "bat")


@dataclass
class SshConfig:
    host: str = ""
    user: str = ""
    port: int = 22
    key: str = ""            # path to a private key (optional; else agent/default)
    options: str = ""        # extra raw ssh options, space-separated


@dataclass
class WinRmConfig:
    host: str = ""
    user: str = ""
    password: str = ""       # dev only; prefer ACTONE_UTILS_WINRM_PASSWORD in env
    port: int = 5985
    transport: str = "ntlm"  # ntlm | kerberos | basic
    scheme: str = "http"     # http | https


@dataclass
class ContainerConfig:
    name: str = "actone"       # target container (actone_local default is "actone")
    docker_bin: str = "docker"  # or "podman"


@dataclass
class UtilsConfig:
    # --- where the utilities live / how they are driven --------------------- #
    backend: str = "local"                 # local | ssh | winrm
    actone_home: str = ""                  # install root containing the utilities
    utilities_dir: str = "utilities"       # subdir of actone_home holding the scripts
    utilities_env: str = ""                # path to utilities.env (blank -> <utilities_dir>/utilities.env)
    jdk_home: str = ""                     # JAVA_HOME to export before running
    shell: str = "auto"                    # auto -> .bat on Windows/local, .sh elsewhere

    # --- remote backends ---------------------------------------------------- #
    ssh: SshConfig = field(default_factory=SshConfig)
    winrm: WinRmConfig = field(default_factory=WinRmConfig)
    container: ContainerConfig = field(default_factory=ContainerConfig)

    # --- safety knobs ------------------------------------------------------- #
    default_timeout: int = 900             # seconds; state-changing tools can run long

    # -- derived paths ------------------------------------------------------- #
    @property
    def _sep(self) -> str:
        return "\\" if self.effective_shell == "bat" else "/"

    @property
    def utilities_path(self) -> str:
        """Directory (on the target) holding the utility scripts."""
        if not self.actone_home:
            return self.utilities_dir
        return self.actone_home.rstrip("/\\") + self._sep + self.utilities_dir

    @property
    def utilities_env_path(self) -> str:
        if self.utilities_env:
            return self.utilities_env
        return self.utilities_path + self._sep + "utilities.env"

    @property
    def effective_shell(self) -> str:
        """Resolve ``auto`` to a concrete script flavour.

        ``bat`` only when running the *local* backend on Windows; every remote
        target (ssh/winrm typically a Linux/Unix ActOne host) and any non-Windows
        local host defaults to ``sh``.
        """
        if self.shell in ("sh", "bat"):
            return self.shell
        if self.backend == "local" and os.name == "nt":
            return "bat"
        return "sh"

    @property
    def script_ext(self) -> str:
        return ".bat" if self.effective_shell == "bat" else ".sh"

    # -- load ---------------------------------------------------------------- #
    @classmethod
    def load(cls, path: Optional[Path] = None) -> "UtilsConfig":
        path = path or DEFAULT_CONFIG_PATH
        raw: dict = {}
        if path and Path(path).exists():
            raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        ssh = SshConfig(**{**asdict(SshConfig()), **(raw.pop("ssh", {}) or {})})
        winrm = WinRmConfig(**{**asdict(WinRmConfig()), **(raw.pop("winrm", {}) or {})})
        container = ContainerConfig(**{**asdict(ContainerConfig()), **(raw.pop("container", {}) or {})})
        fields = {k: v for k, v in raw.items() if k in cls.__dataclass_fields__}
        cfg = cls(**fields, ssh=ssh, winrm=winrm, container=container)
        cfg._overlay_env()
        return cfg

    def _overlay_env(self) -> None:
        """Environment variables win over YAML/defaults."""
        g = os.environ.get
        self.backend = g("ACTONE_UTILS_BACKEND", self.backend)
        self.actone_home = g("ACTONE_UTILS_HOME", self.actone_home)
        self.utilities_dir = g("ACTONE_UTILS_DIR", self.utilities_dir)
        self.utilities_env = g("ACTONE_UTILS_ENV", self.utilities_env)
        self.jdk_home = g("ACTONE_UTILS_JDK", self.jdk_home) or g("JAVA_HOME", self.jdk_home)
        self.shell = g("ACTONE_UTILS_SHELL", self.shell)
        if g("ACTONE_UTILS_TIMEOUT"):
            self.default_timeout = int(g("ACTONE_UTILS_TIMEOUT"))
        # ssh
        self.ssh.host = g("ACTONE_UTILS_SSH_HOST", self.ssh.host)
        self.ssh.user = g("ACTONE_UTILS_SSH_USER", self.ssh.user)
        if g("ACTONE_UTILS_SSH_PORT"):
            self.ssh.port = int(g("ACTONE_UTILS_SSH_PORT"))
        self.ssh.key = g("ACTONE_UTILS_SSH_KEY", self.ssh.key)
        self.ssh.options = g("ACTONE_UTILS_SSH_OPTIONS", self.ssh.options)
        # winrm
        self.winrm.host = g("ACTONE_UTILS_WINRM_HOST", self.winrm.host)
        self.winrm.user = g("ACTONE_UTILS_WINRM_USER", self.winrm.user)
        self.winrm.password = g("ACTONE_UTILS_WINRM_PASSWORD", self.winrm.password)
        if g("ACTONE_UTILS_WINRM_PORT"):
            self.winrm.port = int(g("ACTONE_UTILS_WINRM_PORT"))
        self.winrm.transport = g("ACTONE_UTILS_WINRM_TRANSPORT", self.winrm.transport)
        self.winrm.scheme = g("ACTONE_UTILS_WINRM_SCHEME", self.winrm.scheme)
        # container
        self.container.name = g("ACTONE_UTILS_CONTAINER", self.container.name)
        self.container.docker_bin = g("ACTONE_UTILS_DOCKER_BIN", self.container.docker_bin)

    def summary(self) -> dict:
        """Redacted, human/agent-friendly view of the effective config."""
        return {
            "backend": self.backend,
            "actone_home": self.actone_home or "(unset)",
            "utilities_path": self.utilities_path,
            "utilities_env": self.utilities_env_path,
            "jdk_home": self.jdk_home or "(inherit)",
            "shell": self.effective_shell,
            "script_ext": self.script_ext,
            "timeout": self.default_timeout,
            "ssh": {"host": self.ssh.host, "user": self.ssh.user, "port": self.ssh.port,
                    "key": self.ssh.key or "(agent/default)"} if self.backend == "ssh" else None,
            "winrm": {"host": self.winrm.host, "user": self.winrm.user, "port": self.winrm.port,
                      "transport": self.winrm.transport, "password": "***" if self.winrm.password else ""}
            if self.backend == "winrm" else None,
            "container": {"name": self.container.name, "docker_bin": self.container.docker_bin}
            if self.backend == "container" else None,
        }
