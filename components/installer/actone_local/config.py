"""Configuration for the ActOne local-setup utility.

A single dataclass captures every knob needed to stand up ActOne core locally
(Docker + PostgreSQL). Defaults target a **low-resource laptop** (alpine
Postgres, a trimmed JVM heap, no SSL). Values can be overridden from a YAML file
(``actone-local.yaml`` in the repo root) so the same tooling generalises to
other solutions later by shipping a different config.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, field
from pathlib import Path

import yaml

from actwise.paths import find_config, repo_root

REPO_ROOT = repo_root() or Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = find_config("actone-local.yaml")


@dataclass
class DbConfig:
    image: str = "postgres:16-alpine"   # lightweight Postgres (~250 MB vs ~430 MB)
    name: str = "actone"                # all lower case — ActOne is case-sensitive-unfriendly on PG
    user: str = "actone"
    password: str = "actone"            # dev only; encrypted into acm.ini for the container
    schema: str = "actone"
    port: int = 5432
    container: str = "actone-db"
    volume: str = "actone-pgdata"


@dataclass
class Config:
    # Source package (NDC element 7955981 -> the 10.2 Full wrapper zip)
    package_zip: str = "packages/ActOne-10.2.0-inner.zip"
    ndc_element: str = "7955981"
    ndc_plne: str = "792217"

    # Where lean build inputs land (only RCM.war + Docker/ build dir -- not the full 2.49 GB)
    work_dir: str = "packages/actone-local"

    # Docker image / runtime
    base_image: str = "amazoncorretto:21-al2023"   # public base (replaces artifactory default)
    tomcat_version: str = "10.1.44"                 # RCM.war is Jakarta EE 10 -> needs Tomcat 10.1.x (NOT the Dockerfile's stale 9.0.104 default)
    tomcat_url: str = ""                            # blank -> derived from tomcat_version below
    image_tag: str = "actone:10.2"
    container: str = "actone"
    network: str = "actone-net"
    http_port: int = 8082          # host -> container 8080
    heap: str = "-Xmx2048m"        # trim the 8 GB default for a laptop
    use_ssl: bool = False

    # Runtime config files (host paths mounted into the container)
    acm_ini: str = "packages/actone-local/acm.ini"
    license: str = "packages/actone-local/license.lic"

    # DB-password encryption (ActOne always decrypts repository.password).
    # IV: 1-16 letters/digits, no special chars. Encrypted with the bundled
    # cipher-encryptor (com.actimize.encriptor.Encryptor) run in the base image.
    encrypt_iv: str = "ActoneLocalIV01"

    # Disk safety (GB). `build` refuses below build_min_free_gb unless --force.
    build_min_free_gb: float = 6.0
    warn_free_gb: float = 8.0

    db: DbConfig = field(default_factory=DbConfig)

    # -- paths (absolute, repo-relative) -------------------------------------
    def p(self, rel: str) -> Path:
        rp = Path(rel)
        return rp if rp.is_absolute() else (REPO_ROOT / rp)

    @property
    def package_zip_path(self) -> Path: return self.p(self.package_zip)

    @property
    def work_dir_path(self) -> Path: return self.p(self.work_dir)

    @property
    def war_path(self) -> Path: return self.work_dir_path / "RCM.war"

    @property
    def build_ctx_path(self) -> Path: return self.work_dir_path / "Docker" / "Dockerfile" / "build"

    @property
    def encryptor_dir(self) -> Path: return self.work_dir_path / "encryptor"

    @property
    def dbscripts_dir(self) -> Path: return self.work_dir_path / "dbscripts"

    @property
    def acm_ini_path(self) -> Path: return self.p(self.acm_ini)

    @property
    def license_path(self) -> Path: return self.p(self.license)

    @property
    def tomcat_download_url(self) -> str:
        if self.tomcat_url:
            return self.tomcat_url
        major = self.tomcat_version.split(".", 1)[0]
        return (f"https://archive.apache.org/dist/tomcat/tomcat-{major}/"
                f"v{self.tomcat_version}/bin/apache-tomcat-{self.tomcat_version}.tar.gz")

    # -- load / save ---------------------------------------------------------
    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        path = path or DEFAULT_CONFIG_PATH
        if not path.exists():
            return cls()
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        db = DbConfig(**{**asdict(DbConfig()), **(raw.pop("db", {}) or {})})
        fields = {k: v for k, v in raw.items() if k in cls.__dataclass_fields__}
        return cls(**fields, db=db)

    def dump(self) -> str:
        return yaml.safe_dump(asdict(self), sort_keys=False)
