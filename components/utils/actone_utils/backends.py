"""Execution backends for the ActOne utilities runner (C-U).

A utility invocation is assembled once (by ``runner.py`` / ``catalog.py``) into a
*target* argv — ``[script_path, arg, arg, ...]`` — plus a working directory and a
small set of environment exports (``JAVA_HOME``). *Where* that argv actually runs
is the backend's job:

    local  — subprocess on this host (dev / actone_local container host)
    ssh    — piped through the system OpenSSH client to a remote ActOne host
    winrm  — Windows Remote Management to a Windows ActOne host (optional pywinrm)

Every backend implements the same ``run(...)`` contract and supports ``dry_run``,
which assembles and returns the exact command *without executing it* — the primary
safety valve for state-changing utilities.

Stdlib only for local/ssh; ``pywinrm`` is imported lazily and only for real winrm
runs (dry-run never needs it).
"""
from __future__ import annotations

import os
import shlex
import subprocess
from dataclasses import dataclass, field
from typing import Optional

from .config import UtilsConfig


@dataclass
class ExecResult:
    backend: str
    target: str                 # human description of where it ran ("local", "user@host")
    dry_run: bool
    command: str                # display string of what was (or would be) executed
    remote_command: str = ""    # the command as it runs on the target (ssh/winrm)
    argv: list = field(default_factory=list)   # the argv this process actually spawned
    returncode: Optional[int] = None
    stdout: str = ""
    stderr: str = ""

    @property
    def ok(self) -> bool:
        return self.dry_run or self.returncode == 0

    def to_dict(self) -> dict:
        return {
            "backend": self.backend,
            "target": self.target,
            "dry_run": self.dry_run,
            "ok": self.ok,
            "command": self.command,
            "remote_command": self.remote_command,
            "returncode": self.returncode,
            "stdout": self.stdout,
            "stderr": self.stderr,
        }


class ExecutionBackend:
    """Abstract backend. Subclasses run a target argv and return an ExecResult."""

    name = "abstract"

    def __init__(self, cfg: UtilsConfig):
        self.cfg = cfg

    def describe(self) -> dict:
        return {"backend": self.name}

    def run(self, argv: list, cwd: str = "", env: Optional[dict] = None,
            dry_run: bool = True, timeout: Optional[int] = None) -> ExecResult:
        raise NotImplementedError

    # shared helper: JAVA_HOME + any tool env, as an ordered (k, v) list
    def _env_pairs(self, env: Optional[dict]) -> list:
        pairs = []
        if self.cfg.jdk_home:
            pairs.append(("JAVA_HOME", self.cfg.jdk_home))
        for k, v in (env or {}).items():
            pairs.append((k, str(v)))
        return pairs


class LocalBackend(ExecutionBackend):
    name = "local"

    def describe(self) -> dict:
        return {"backend": self.name, "host": "localhost", "os": os.name}

    def run(self, argv, cwd="", env=None, dry_run=True, timeout=None):
        full_env = dict(os.environ)
        for k, v in self._env_pairs(env):
            full_env[k] = v
        command = _display(argv)
        if dry_run:
            return ExecResult(self.name, "local", True, command, argv=list(argv))
        cp = subprocess.run(
            argv, cwd=cwd or None, env=full_env,
            capture_output=True, text=True,
            timeout=timeout or self.cfg.default_timeout,
        )
        return ExecResult(self.name, "local", False, command, argv=list(argv),
                          returncode=cp.returncode, stdout=cp.stdout, stderr=cp.stderr)


class SshBackend(ExecutionBackend):
    name = "ssh"

    def _target(self) -> str:
        s = self.cfg.ssh
        return f"{s.user}@{s.host}" if s.user else s.host

    def _ssh_argv(self, remote_cmd: str) -> list:
        s = self.cfg.ssh
        argv = ["ssh"]
        if s.port and s.port != 22:
            argv += ["-p", str(s.port)]
        if s.key:
            argv += ["-i", s.key]
        if s.options:
            argv += shlex.split(s.options)
        argv += [self._target(), remote_cmd]
        return argv

    def _remote_cmd(self, argv, cwd, env) -> str:
        parts = []
        if cwd:
            parts.append(f"cd {shlex.quote(cwd)}")
        for k, v in self._env_pairs(env):
            parts.append(f"export {k}={shlex.quote(v)}")
        parts.append(shlex.join(argv))
        return " && ".join(parts)

    def describe(self) -> dict:
        s = self.cfg.ssh
        return {"backend": self.name, "host": s.host, "user": s.user, "port": s.port,
                "key": s.key or "(agent/default)"}

    def run(self, argv, cwd="", env=None, dry_run=True, timeout=None):
        if not self.cfg.ssh.host:
            raise RuntimeError("ssh backend selected but ssh.host is not configured "
                               "(set ACTONE_UTILS_SSH_HOST or actone-utils.yaml).")
        remote_cmd = self._remote_cmd(argv, cwd, env)
        ssh_argv = self._ssh_argv(remote_cmd)
        command = _display(ssh_argv)
        if dry_run:
            return ExecResult(self.name, self._target(), True, command,
                              remote_command=remote_cmd, argv=ssh_argv)
        cp = subprocess.run(
            ssh_argv, capture_output=True, text=True,
            timeout=timeout or self.cfg.default_timeout,
        )
        return ExecResult(self.name, self._target(), False, command,
                          remote_command=remote_cmd, argv=ssh_argv,
                          returncode=cp.returncode, stdout=cp.stdout, stderr=cp.stderr)


class WinRmBackend(ExecutionBackend):
    name = "winrm"

    def _target(self) -> str:
        w = self.cfg.winrm
        return f"{w.user}@{w.host}" if w.user else w.host

    def _remote_cmd(self, argv, cwd, env) -> str:
        # Windows shell (cmd) chain: cd /d <cwd> & set K=V & "script" args...
        parts = []
        if cwd:
            parts.append(f'cd /d "{cwd}"')
        for k, v in self._env_pairs(env):
            parts.append(f'set "{k}={v}"')
        script = f'"{argv[0]}"'
        rest = " ".join(subprocess.list2cmdline([a]) for a in argv[1:])
        parts.append((script + " " + rest).strip())
        return " & ".join(parts)

    def describe(self) -> dict:
        w = self.cfg.winrm
        return {"backend": self.name, "host": w.host, "user": w.user, "port": w.port,
                "transport": w.transport, "scheme": w.scheme}

    def run(self, argv, cwd="", env=None, dry_run=True, timeout=None):
        w = self.cfg.winrm
        if not w.host:
            raise RuntimeError("winrm backend selected but winrm.host is not configured "
                               "(set ACTONE_UTILS_WINRM_HOST or actone-utils.yaml).")
        remote_cmd = self._remote_cmd(argv, cwd, env)
        command = f"winrm://{self._target()}:{w.port}  {remote_cmd}"
        if dry_run:
            return ExecResult(self.name, self._target(), True, command,
                              remote_command=remote_cmd, argv=list(argv))
        try:
            import winrm  # type: ignore
        except ImportError as e:
            raise RuntimeError(
                "winrm backend requires the 'pywinrm' package for real runs "
                "(pip install pywinrm). Use --dry-run to assemble the command "
                "without executing."
            ) from e
        session = winrm.Session(
            f"{w.scheme}://{w.host}:{w.port}/wsman",
            auth=(w.user, w.password), transport=w.transport,
        )
        r = session.run_cmd(remote_cmd)
        return ExecResult(self.name, self._target(), False, command,
                          remote_command=remote_cmd, argv=list(argv),
                          returncode=r.status_code,
                          stdout=r.std_out.decode("utf-8", "replace"),
                          stderr=r.std_err.decode("utf-8", "replace"))


class ContainerBackend(ExecutionBackend):
    """Run inside a running container (e.g. the actone_local ``actone`` container).

    Uses ``docker exec`` (or ``podman``) with ``-w`` for the working dir and ``-e``
    for env exports. The target is the container's Linux shell, so paths/scripts
    are always ``.sh``.
    """

    name = "container"

    def _docker_argv(self, argv, cwd, env) -> list:
        c = self.cfg.container
        out = [c.docker_bin, "exec"]
        if cwd:
            out += ["-w", cwd]
        for k, v in self._env_pairs(env):
            out += ["-e", f"{k}={v}"]
        out += [c.name]
        out += list(argv)
        return out

    def describe(self) -> dict:
        c = self.cfg.container
        return {"backend": self.name, "container": c.name, "docker_bin": c.docker_bin}

    def run(self, argv, cwd="", env=None, dry_run=True, timeout=None):
        if not self.cfg.container.name:
            raise RuntimeError("container backend selected but container.name is not "
                               "configured (set ACTONE_UTILS_CONTAINER or actone-utils.yaml).")
        docker_argv = self._docker_argv(argv, cwd, env)
        command = _display(docker_argv)
        if dry_run:
            return ExecResult(self.name, self.cfg.container.name, True, command,
                              argv=docker_argv)
        cp = subprocess.run(
            docker_argv, capture_output=True, text=True,
            timeout=timeout or self.cfg.default_timeout,
        )
        return ExecResult(self.name, self.cfg.container.name, False, command,
                          argv=docker_argv, returncode=cp.returncode,
                          stdout=cp.stdout, stderr=cp.stderr)


_BACKENDS = {"local": LocalBackend, "ssh": SshBackend, "winrm": WinRmBackend,
             "container": ContainerBackend}


def make_backend(cfg: UtilsConfig) -> ExecutionBackend:
    cls = _BACKENDS.get(cfg.backend)
    if not cls:
        raise RuntimeError(f"unknown backend {cfg.backend!r} (expected one of "
                           f"{', '.join(_BACKENDS)})")
    return cls(cfg)


def _display(argv) -> str:
    try:
        return shlex.join(argv)
    except Exception:
        return " ".join(str(a) for a in argv)
