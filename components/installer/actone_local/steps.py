"""Phase implementations for the ActOne local-setup utility.

Every phase is **idempotent** (safe to re-run) and returns a ``Step`` result so
the CLI can print a consistent report. Heavy phases (``build``) are guarded by a
disk-space check because ActOne images are large and Windows needs headroom.
"""
from __future__ import annotations

import shutil
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .config import Config


@dataclass
class Step:
    ok: bool
    name: str
    detail: str = ""

    def line(self) -> str:
        mark = "[green]OK[/green]" if self.ok else "[red]XX[/red]"
        return f"  {mark}  [bold]{self.name}[/bold] — {self.detail}"


# ── low-level helpers ──────────────────────────────────────────────────────
def free_gb(path: Path) -> float:
    return shutil.disk_usage(path.anchor or path).free / 1e9


def sh(cmd: list[str], capture: bool = True, check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=capture, text=True, check=check)


def docker_ok() -> tuple[bool, str]:
    exe = shutil.which("docker")
    if not exe:
        return False, "docker not found on PATH"
    r = sh(["docker", "info", "--format", "{{.ServerVersion}}"])
    if r.returncode != 0:
        return False, "docker daemon not responding (is Docker Desktop running?)"
    return True, f"docker engine {r.stdout.strip()}"


def _container_state(name: str) -> str:
    r = sh(["docker", "ps", "-a", "--filter", f"name=^{name}$", "--format", "{{.State}}"])
    return (r.stdout or "").strip()


def _ensure_network(name: str) -> None:
    r = sh(["docker", "network", "ls", "--filter", f"name=^{name}$", "--format", "{{.Name}}"])
    if name not in (r.stdout or ""):
        sh(["docker", "network", "create", name])


def _image_exists(tag: str) -> bool:
    r = sh(["docker", "images", "-q", tag])
    return bool((r.stdout or "").strip())


# ── phases ─────────────────────────────────────────────────────────────────
def doctor(cfg: Config) -> list[Step]:
    steps: list[Step] = []
    ok, msg = docker_ok()
    steps.append(Step(ok, "docker", msg))

    fg = free_gb(cfg.work_dir_path.parent if cfg.work_dir_path.parent.exists() else Path.cwd())
    disk_ok = fg >= cfg.build_min_free_gb
    warn = "" if fg >= cfg.warn_free_gb else f"  [yellow](below {cfg.warn_free_gb} GB comfort line)[/yellow]"
    steps.append(Step(disk_ok, "disk", f"{fg:.1f} GB free (build needs >= {cfg.build_min_free_gb} GB){warn}"))

    steps.append(Step(cfg.package_zip_path.exists(), "package",
                      f"{cfg.package_zip} {'present' if cfg.package_zip_path.exists() else 'MISSING'}"))
    steps.append(Step(cfg.war_path.exists(), "RCM.war (extracted)",
                      "present" if cfg.war_path.exists() else "not yet — run `extract`"))
    steps.append(Step(cfg.license_path.exists(), "license.lic",
                      "present" if cfg.license_path.exists() else "MISSING — required to start the container"))
    steps.append(Step(_image_exists(cfg.image_tag), "image",
                      f"{cfg.image_tag} {'built' if _image_exists(cfg.image_tag) else 'not built — run `build`'}"))
    return steps


def extract(cfg: Config) -> Step:
    """Extract ONLY the lean build inputs: RCM/RCM.war + Docker/ build tree."""
    if cfg.war_path.exists() and cfg.build_ctx_path.exists():
        return Step(True, "extract", f"already present in {cfg.work_dir} (skipped)")
    if not cfg.package_zip_path.exists():
        return Step(False, "extract", f"payload zip missing: {cfg.package_zip}")
    cfg.work_dir_path.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(cfg.package_zip_path) as z:
        names = z.namelist()
        # RCM.war -> work_dir/RCM.war
        war = next((n for n in names if n.replace("\\", "/").endswith("RCM/RCM.war")), None)
        if not war:
            return Step(False, "extract", "RCM/RCM.war not found in payload")
        with z.open(war) as src, open(cfg.war_path, "wb") as dst:
            shutil.copyfileobj(src, dst, length=8 * 1024 * 1024)
        # Docker build tree -> work_dir/Docker/...
        for n in names:
            nn = n.replace("\\", "/")
            if nn.startswith("Docker/") and not nn.endswith("/"):
                target = cfg.work_dir_path / nn
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(n) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
    return Step(True, "extract", f"RCM.war ({cfg.war_path.stat().st_size/1e6:.0f} MB) + Docker/ -> {cfg.work_dir}")


def db_up(cfg: Config) -> Step:
    ok, msg = docker_ok()
    if not ok:
        return Step(False, "db-up", msg)
    _ensure_network(cfg.network)
    state = _container_state(cfg.db.container)
    if state == "running":
        return Step(True, "db-up", f"{cfg.db.container} already running (skipped)")
    if state:  # exists but stopped
        sh(["docker", "start", cfg.db.container])
        return Step(True, "db-up", f"started existing {cfg.db.container}")
    r = sh([
        "docker", "run", "-d", "--name", cfg.db.container, "--network", cfg.network,
        "-e", f"POSTGRES_DB={cfg.db.name}", "-e", f"POSTGRES_USER={cfg.db.user}",
        "-e", f"POSTGRES_PASSWORD={cfg.db.password}",
        "-p", f"{cfg.db.port}:5432", "-v", f"{cfg.db.volume}:/var/lib/postgresql/data",
        cfg.db.image,
    ])
    if r.returncode != 0:
        return Step(False, "db-up", (r.stderr or r.stdout).strip()[:300])
    return Step(True, "db-up", f"{cfg.db.image} up as {cfg.db.container} on :{cfg.db.port}")


def db_init(cfg: Config) -> Step:
    """Create the ActOne schema + search_path (db/user come from the image env)."""
    if _container_state(cfg.db.container) != "running":
        return Step(False, "db-init", f"{cfg.db.container} not running — run `db-up` first")
    # wait for readiness
    for _ in range(20):
        r = sh(["docker", "exec", cfg.db.container, "pg_isready", "-U", cfg.db.user])
        if r.returncode == 0:
            break
        time.sleep(1)
    sql = (
        f"CREATE SCHEMA IF NOT EXISTS {cfg.db.schema} AUTHORIZATION {cfg.db.user}; "
        f"ALTER ROLE {cfg.db.user} SET search_path = {cfg.db.schema};"
    )
    r = sh(["docker", "exec", "-e", f"PGPASSWORD={cfg.db.password}", cfg.db.container,
            "psql", "-U", cfg.db.user, "-d", cfg.db.name, "-c", sql])
    if r.returncode != 0:
        return Step(False, "db-init", (r.stderr or r.stdout).strip()[:300])
    return Step(True, "db-init", f"schema '{cfg.db.schema}' ready (lower-case), search_path set")


def _postgresql_env_text(cfg: Config) -> str:
    """Fill the RCM DB-installer .env with our single-user local values."""
    return "\n".join([
        "#PostgreSQL - filled by actone-local (db/schema/user all = the DB config)",
        f"rcm_db_name={cfg.db.name}",
        f"rcm_dbo_username={cfg.db.user}",
        f"rcm_schema_user={cfg.db.user}",
        f"rcm_schema_name={cfg.db.schema}",
        "^rcm_schema_password=",
        "rcm_app_user_name=",
        "^rcm_app_user_password=",
        "rcm_app_user_role=",
        "rcm_app_read_role=",
        "user_and_roles_script_logfilename=/db/users_and_roles.log",
        "degree_of_parallelism=8",
        "dblogOff=false",
        "multi_rows_operations_batch_size=4000",
    ]) + "\n"


def _extract_dbscripts(cfg: Config) -> None:
    """Extract the RCM DB-install engine (DB_Scripts/Infrastructure) + write the .env."""
    jar = cfg.dbscripts_dir / "scripts" / "RCM" / "db_scripts.jar"
    if not jar.exists():
        marker = "/DB_Scripts/Infrastructure/"
        with zipfile.ZipFile(cfg.package_zip_path) as z:
            base = None
            for n in z.namelist():
                nn = n.replace("\\", "/")
                if nn.startswith("Installer/image/RCM ") and marker in nn:
                    base = nn[: nn.index(marker) + len(marker)]
                    break
            if not base:
                raise FileNotFoundError("RCM DB_Scripts/Infrastructure not found in payload")
            for info in z.infolist():
                nn = info.filename.replace("\\", "/")
                if info.is_dir() or not nn.startswith(base):
                    continue
                dest = cfg.dbscripts_dir / nn[len(base):]
                dest.parent.mkdir(parents=True, exist_ok=True)
                with z.open(info) as src, open(dest, "wb") as out:
                    shutil.copyfileobj(src, out)
    (cfg.dbscripts_dir / "postgresql.env.filled").write_text(
        _postgresql_env_text(cfg), encoding="utf-8")


def _schema_populated(cfg: Config) -> bool:
    r = sh(["docker", "exec", "-e", f"PGPASSWORD={cfg.db.password}", cfg.db.container,
            "psql", "-U", cfg.db.user, "-d", cfg.db.name, "-tAc",
            f"SELECT to_regclass('{cfg.db.schema}.acm_md_config_params')"])
    return "acm_md_config_params" in (r.stdout or "")


def db_schema(cfg: Config) -> Step:
    """Populate the ActOne DDL + seed data into the schema (dbupgrade -exec -new)."""
    ok, msg = docker_ok()
    if not ok:
        return Step(False, "db-schema", msg)
    if not cfg.package_zip_path.exists():
        return Step(False, "db-schema", f"package not found: {cfg.package_zip}")
    if _container_state(cfg.db.container) != "running":
        return Step(False, "db-schema", f"{cfg.db.container} not running — run `db-up` first")
    if _schema_populated(cfg):
        return Step(True, "db-schema", f"schema '{cfg.db.schema}' already populated (skipped)")
    try:
        _extract_dbscripts(cfg)
    except Exception as e:
        return Step(False, "db-schema", f"failed to extract DB scripts: {e}")

    db_dir = str(cfg.dbscripts_dir.resolve())
    inner = (
        "cd /db && java -Dorg.xml.sax.driver=org.apache.xerces.parsers.SAXParser "
        "-cp 'scripts/RCM/db_scripts.jar:lib/*' com.actimize.util.dbupgrade.Main "
        f"-exec -new -dbtype=postgresql -db='{_jdbc_url(cfg)}' "
        f"-user={cfg.db.user} -password={cfg.db.password} -env=postgresql.env.filled"
    )
    # This runs the full ActOne DDL (600+ tables) — can take several minutes.
    r = sh(["docker", "run", "--rm", "--network", cfg.network, "-v", f"{db_dir}:/db",
            cfg.base_image, "sh", "-c", inner])
    if not _schema_populated(cfg):
        tail = ((r.stdout or "")[-300:] + (r.stderr or "")[-300:]).strip()
        return Step(False, "db-schema", f"dbupgrade did not populate the schema. {tail[:400]}")
    cnt = sh(["docker", "exec", "-e", f"PGPASSWORD={cfg.db.password}", cfg.db.container,
              "psql", "-U", cfg.db.user, "-d", cfg.db.name, "-tAc",
              f"SELECT count(*) FROM information_schema.tables WHERE table_schema='{cfg.db.schema}'"])
    n = (cnt.stdout or "").strip() or "?"
    return Step(True, "db-schema", f"populated '{cfg.db.schema}' with {n} tables (ActOne 10.2 DDL)")


def _jdbc_url(cfg: Config) -> str:
    return (f"jdbc:postgresql://{cfg.db.container}:5432/{cfg.db.name}"
            f"?currentSchema={cfg.db.schema}")


def _acm_ini_text(cfg: Config, password: str, iv: str | None = None) -> str:
    url = _jdbc_url(cfg)
    lines = [
        "# Generated by actone-local - PostgreSQL repository connection",
        f"actimize.repository.url = {url}",
        "actimize.repository.type = postgresql",
        f"actimize.repository.defaultCatalog = {cfg.db.name}",
        f"actimize.repository.username = {cfg.db.user}",
    ]
    if iv:
        lines.append(f"actimize.bootstrap.encryption.iv = {iv}")
    else:
        lines += [
            "# WARNING: ActOne ALWAYS decrypts this value (PasswordManager.decryptArray).",
            "# A plaintext password makes RCM fail to start. Run `encrypt-config` to replace",
            "# it with an AES-encrypted value + actimize.bootstrap.encryption.iv.",
        ]
    lines.append(f"actimize.repository.password = {password}")
    return "\n".join(lines) + "\n"


def render_config(cfg: Config) -> Step:
    """Write acm.ini (PostgreSQL, PLAINTEXT password) into the work dir. Idempotent."""
    cfg.acm_ini_path.parent.mkdir(parents=True, exist_ok=True)
    cfg.acm_ini_path.write_text(_acm_ini_text(cfg, cfg.db.password), encoding="utf-8")
    return Step(True, "render-config",
                f"wrote {cfg.acm_ini} (password PLAINTEXT — run `encrypt-config` before `run`)")


def _extract_encryptor(cfg: Config) -> None:
    """Extract the bundled RCM Encryption Tool classpath (Utilities/{bin,etc,lib})."""
    lib = cfg.encryptor_dir / "lib"
    if lib.exists() and any(lib.glob("*.jar")):
        return
    with zipfile.ZipFile(cfg.package_zip_path) as z:
        for info in z.infolist():
            name = info.filename
            if info.is_dir():
                continue
            if not (name.startswith("Utilities/lib/") or name.startswith("Utilities/etc/")
                    or name.startswith("Utilities/bin/")):
                continue
            rel = name[len("Utilities/"):]
            dest = cfg.encryptor_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out)


def encrypt_config(cfg: Config) -> Step:
    """Encrypt the DB password with the bundled tool and write acm.ini with the IV."""
    ok, msg = docker_ok()
    if not ok:
        return Step(False, "encrypt-config", msg)
    if not cfg.package_zip_path.exists():
        return Step(False, "encrypt-config", f"package not found: {cfg.package_zip}")
    try:
        _extract_encryptor(cfg)
    except Exception as e:
        return Step(False, "encrypt-config", f"failed to extract encryptor: {e}")

    enc = str(cfg.encryptor_dir.resolve())
    java = (
        "cd /enc && java "
        "--add-opens=java.base/java.lang=ALL-UNNAMED "
        "--add-opens=java.base/java.util=ALL-UNNAMED "
        "--add-opens=java.base/java.lang.reflect=ALL-UNNAMED "
        "-cp 'etc:lib/*' com.actimize.encriptor.Encryptor "
        f"-encrypt={cfg.db.password} -iv={cfg.encrypt_iv}"
    )
    r = sh(["docker", "run", "--rm", "-v", f"{enc}:/enc:ro", cfg.base_image, "sh", "-c", java])
    if r.returncode != 0:
        return Step(False, "encrypt-config", (r.stderr or r.stdout).strip()[:300])
    # The encrypted token is the last non-empty stdout line.
    token = ""
    for ln in (r.stdout or "").splitlines():
        if ln.strip():
            token = ln.strip()
    if not token:
        return Step(False, "encrypt-config", "encryptor produced no output")
    cfg.acm_ini_path.parent.mkdir(parents=True, exist_ok=True)
    cfg.acm_ini_path.write_text(_acm_ini_text(cfg, token, iv=cfg.encrypt_iv), encoding="utf-8")
    return Step(True, "encrypt-config",
                f"wrote {cfg.acm_ini} with AES-encrypted password (iv={cfg.encrypt_iv})")




def build(cfg: Config, force: bool = False) -> Step:
    ok, msg = docker_ok()
    if not ok:
        return Step(False, "build", msg)
    if not cfg.war_path.exists() or not cfg.build_ctx_path.exists():
        return Step(False, "build", "missing build inputs — run `extract` first")
    fg = free_gb(cfg.work_dir_path)
    if fg < cfg.build_min_free_gb and not force:
        return Step(False, "build",
                    f"only {fg:.1f} GB free (need >= {cfg.build_min_free_gb} GB). "
                    f"Free disk or pass --force to override.")
    if _image_exists(cfg.image_tag):
        return Step(True, "build", f"{cfg.image_tag} already built (skipped; use `docker rmi` to rebuild)")

    # Cache the Tomcat tarball on the host and serve it locally over plain HTTP.
    # This avoids relying on the container's CA trust for archive.apache.org
    # (which proved flaky) and makes rebuilds reproducible/offline.
    tomcat_tar = cfg.work_dir_path / f"apache-tomcat-{cfg.tomcat_version}.tar.gz"
    if not tomcat_tar.exists():
        try:
            _download(cfg.tomcat_download_url, tomcat_tar)
        except Exception as e:
            return Step(False, "build", f"failed to fetch Tomcat {cfg.tomcat_version}: {e}")

    # Serve the work dir (RCM.war + Tomcat tarball) so the Dockerfile can fetch both locally.
    port = _free_port()
    httpd = _serve_dir(cfg.work_dir_path, port)
    try:
        war_url = f"http://host.docker.internal:{port}/RCM.war"
        tomcat_url = f"http://host.docker.internal:{port}/{tomcat_tar.name}"
        cmd = [
            "docker", "build",
            "--build-arg", f"FROM_IMAGE={cfg.base_image}",
            "--build-arg", f"RCM_HTTP_URL={war_url}",
            "--build-arg", f"TOMCAT_VERSION={cfg.tomcat_version}",
            "--build-arg", f"TOMCAT_URL={tomcat_url}",
            "--add-host", "host.docker.internal:host-gateway",
            "-t", cfg.image_tag, ".",
        ]
        r = subprocess.run(cmd, cwd=str(cfg.build_ctx_path), text=True)
    finally:
        httpd.shutdown()
    if r.returncode != 0:
        return Step(False, "build", "docker build failed (see output above)")
    return Step(True, "build", f"image {cfg.image_tag} built")


def run_container(cfg: Config) -> Step:
    ok, msg = docker_ok()
    if not ok:
        return Step(False, "run", msg)
    if not _image_exists(cfg.image_tag):
        return Step(False, "run", f"{cfg.image_tag} not built — run `build` first")
    if not cfg.acm_ini_path.exists():
        return Step(False, "run", "acm.ini missing — run `render-config` first")
    if not cfg.license_path.exists():
        return Step(False, "run", f"license.lic missing at {cfg.license} — obtain from NICE")
    _ensure_network(cfg.network)
    if _container_state(cfg.container) == "running":
        return Step(True, "run", f"{cfg.container} already running (skipped)")
    if _container_state(cfg.container):
        sh(["docker", "rm", "-f", cfg.container])
    cmd = [
        "docker", "run", "-d", "--name", cfg.container, "--network", cfg.network,
        "-e", "repo_config_mode=mount", "-e", f"use_ssl={'true' if cfg.use_ssl else 'false'}",
        "-e", f"CATALINA_OPTS={cfg.heap} -Duser.timezone=UTC",
        "-v", f"{cfg.acm_ini_path}:/usr/local/tomcat/bin/acm.ini:ro",
        "-v", f"{cfg.license_path}:/usr/local/tomcat/bin/acm/license/license.lic:ro",
        "-p", f"{cfg.http_port}:8080", cfg.image_tag,
    ]
    r = sh(cmd)
    if r.returncode != 0:
        return Step(False, "run", (r.stderr or r.stdout).strip()[:300])
    return Step(True, "run", f"{cfg.container} up — http://localhost:{cfg.http_port}/")


def _rcm_status(url: str) -> int | None:
    """GET url WITHOUT following redirects; return the HTTP status, or None if unreachable."""
    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):  # noqa: ANN001
            return None
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(urllib.request.Request(url, method="GET"), timeout=5) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return None


def verify(cfg: Config, timeout: int = 180) -> Step:
    """Poll the RCM webapp until it actually serves (login redirect), not just 'container started'.

    This closes the gap where `run` reports OK the instant the container starts, even though
    ActOne needs ~85 s to deploy and a valid license.lic to leave the 404 gate. Success is a
    301/302/200 from /RCM (login); a persistent 404 means RCM is still deploying OR the license
    is missing/invalid; connection-refused means the container never bound the port.
    """
    if _container_state(cfg.container) != "running":
        return Step(False, "verify", f"{cfg.container} not running — run `run` first")
    url = f"http://localhost:{cfg.http_port}/RCM"
    deadline = time.time() + timeout
    last = "no response yet"
    while time.time() < deadline:
        code = _rcm_status(url)
        if code in (200, 301, 302):
            return Step(True, "verify", f"RCM up at {url} (HTTP {code} -> login)")
        if code == 404:
            last = "HTTP 404 (RCM still deploying, or license.lic missing/invalid)"
        elif code is None:
            last = "connection refused (container port not bound yet)"
        else:
            last = f"HTTP {code}"
        time.sleep(4)
    hint = ""
    if "404" in last and not cfg.license_path.exists():
        hint = f"  license.lic MISSING at {cfg.license} — this is the usual cause of a stuck 404."
    return Step(False, "verify", f"RCM not ready after {timeout}s — last: {last}.{hint}")


def status(cfg: Config) -> str:
    r = sh(["docker", "ps", "-a", "--filter", f"name={cfg.container}",
            "--filter", f"name={cfg.db.container}",
            "--format", "table {{.Names}}\t{{.Image}}\t{{.State}}\t{{.Ports}}"])
    return (r.stdout or "").strip() or "(no actone containers)"


def down(cfg: Config, purge: bool = False) -> list[Step]:
    steps = []
    for name in (cfg.container, cfg.db.container):
        if _container_state(name):
            sh(["docker", "rm", "-f", name])
            steps.append(Step(True, "down", f"removed {name}"))
    if purge:
        sh(["docker", "volume", "rm", cfg.db.volume])
        steps.append(Step(True, "down", f"purged volume {cfg.db.volume}"))
    return steps or [Step(True, "down", "nothing running")]


# ── tiny WAR http server (for the Dockerfile curl) ──────────────────────────
def _free_port() -> int:
    s = socket.socket()
    s.bind(("", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _download(url: str, dest: Path, retries: int = 3) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    last = None
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(url, timeout=60) as resp, open(tmp, "wb") as fh:
                shutil.copyfileobj(resp, fh)
            tmp.replace(dest)
            return
        except Exception as e:  # transient network, or corporate SSL-inspection proxy
            last = e
            time.sleep(2 * attempt)
    # Fallback: curl.exe (Schannel) trusts the OS cert store; --ssl-no-revoke
    # tolerates proxies whose chain can't be revocation-checked.
    curl = shutil.which("curl") or shutil.which("curl.exe")
    if curl:
        r = subprocess.run([curl, "-fsSL", "--ssl-no-revoke", "-o", str(dest), url],
                           capture_output=True, text=True)
        if r.returncode == 0 and dest.exists() and dest.stat().st_size > 0:
            return
        last = RuntimeError((r.stderr or r.stdout or "curl failed").strip()[:200])
    if tmp.exists():
        tmp.unlink()
    raise last


def _serve_dir(directory: Path, port: int) -> ThreadingHTTPServer:
    handler = lambda *a, **k: SimpleHTTPRequestHandler(*a, directory=str(directory), **k)
    httpd = ThreadingHTTPServer(("0.0.0.0", port), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd
