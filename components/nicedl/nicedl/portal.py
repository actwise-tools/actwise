"""Portal client for the NICE Download Center (Flexera SubscribeNet).

Server-rendered JSP portal — no JSON API — so this scrapes HTML with an
authenticated ``requests`` session. Corporate TLS interception is handled via
``truststore`` (falls back gracefully if unavailable).
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

try:  # Use the OS trust store so corporate TLS-inspection CAs are trusted.
    import truststore  # type: ignore
    truststore.inject_into_ssl()
except Exception:  # pragma: no cover - best effort
    pass

import requests
from bs4 import BeautifulSoup

# ── Paths / config ──────────────────────────────────────────────────────────────
from actwise.paths import repo_root

PKG_DIR = Path(__file__).resolve().parent
REPO_ROOT = repo_root() or PKG_DIR.parent

# Load .env (cwd first, then repo root) so NDC_* vars are available.
for _envf in (Path.cwd() / ".env", REPO_ROOT / ".env"):
    if _envf.exists():
        try:
            from dotenv import load_dotenv
            load_dotenv(_envf, override=False)
        except ImportError:
            pass
        break

BASE = os.environ.get("NDC_PORTAL_URL", "https://nice.subscribenet.com/").rstrip("/")
CONTROL = f"{BASE}/control/nice"
EMAIL = os.environ.get("NDC_EMAIL", "")
PASSWORD = os.environ.get("NDC_PASSWORD", "")

USER_DIR = Path(os.environ.get("NDC_HOME", str(Path.home() / ".nicedl")))
_repo_cookie = REPO_ROOT / "browser-profile" / "ndc-cookies.json"
COOKIES_FILE = _repo_cookie if _repo_cookie.parent.exists() else (USER_DIR / "ndc-cookies.json")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36 nicedl")

FLEXNET_HOST = "download.flexnetoperations.com"


class AuthError(Exception):
    """Raised when the portal session is missing or expired."""


@dataclass
class Release:
    title: str
    version: str
    variant: str          # Full | SP | Patch | ""
    element: str
    plne: str
    cert_num: str
    href: str


@dataclass
class DownloadFile:
    filename: str
    url: str              # signed flexnetoperations URL (time-limited)
    size: str
    md5: str
    dkey: str


def _variant(title: str) -> str:
    for v in ("Full", "Patch", "SP"):
        if re.search(rf"\b{v}\b", title):
            return v
    return ""


def _version(title: str) -> str:
    m = re.search(r"\b(\d+(?:\.\d+){0,3})\b", title)
    return m.group(1) if m else ""


class Portal:
    def __init__(self):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept": "text/html,application/xhtml+xml"})
        self._load_cookies()

    # ── cookie persistence ──────────────────────────────────────────────────────
    def _load_cookies(self):
        if COOKIES_FILE.exists():
            try:
                data = json.loads(COOKIES_FILE.read_text(encoding="utf-8"))
                for c in data.get("cookies", []):
                    self.s.cookies.set(c["name"], c["value"], domain=c.get("domain"),
                                       path=c.get("path", "/"))
            except Exception:
                pass

    def _save_cookies(self):
        COOKIES_FILE.parent.mkdir(parents=True, exist_ok=True)
        cookies = [{"name": c.name, "value": c.value, "domain": c.domain, "path": c.path}
                   for c in self.s.cookies]
        COOKIES_FILE.write_text(json.dumps({"cookies": cookies}, indent=2), encoding="utf-8")

    def logout(self):
        try:
            self.s.get(f"{CONTROL}/logout", timeout=15)
        except Exception:
            pass
        self.s.cookies.clear()
        if COOKIES_FILE.exists():
            COOKIES_FILE.unlink()

    # ── auth ─────────────────────────────────────────────────────────────────────
    @staticmethod
    def _is_login_page(html: str) -> bool:
        h = html.lower()
        return (
            ('name="password"' in h and 'value="authenticate"' in h)
            or "forgot your login" in h
            or ": login</title>" in h
        )

    def login(self, email: str = "", password: str = "") -> bool:
        email = email or EMAIL
        password = password or PASSWORD
        if not email or not password:
            raise AuthError("NDC_EMAIL / NDC_PASSWORD not set (add them to .env).")
        r = self.s.post(f"{CONTROL}/login", timeout=30, allow_redirects=True, data={
            "nextURL": "/control/nice/index",
            "action": "authenticate",
            "username": email,
            "password": password,
            "persistCookie": "true",
        })
        ok = r.status_code == 200 and not self._is_login_page(r.text) and "logout" in r.text.lower()
        if ok:
            self._save_cookies()
        return ok

    def is_authed(self) -> bool:
        try:
            r = self.s.get(f"{CONTROL}/index", timeout=20)
        except Exception:
            return False
        return r.status_code == 200 and not self._is_login_page(r.text)

    def _get(self, path: str, **params) -> str:
        url = path if path.startswith("http") else f"{CONTROL}/{path.lstrip('/')}"
        r = self.s.get(url, params=params or None, timeout=45)
        if self._is_login_page(r.text):
            raise AuthError("Session expired. Run: ndc auth login")
        r.raise_for_status()
        return r.text

    # ── discovery ────────────────────────────────────────────────────────────────
    def product_lines(self) -> list[dict]:
        html = self._get("index")
        soup = BeautifulSoup(html, "html.parser")
        out, seen = [], set()
        for a in soup.select("a[href*='manu=']"):
            href = a.get("href", "")
            m = re.search(r"manu=([^&]+)", href)
            name = a.get_text(" ", strip=True)
            if m and name and m.group(1) not in seen and m.group(1) != "productupdates":
                seen.add(m.group(1))
                out.append({"name": name, "manu": m.group(1)})
        return out

    def _parse_releases(self, html: str) -> list[Release]:
        soup = BeautifulSoup(html, "html.parser")
        out, seen = [], set()
        for a in soup.select("a[href*='download?']"):
            href = a.get("href", "")
            if "element=" not in href:
                continue
            title = a.get_text(" ", strip=True)
            if not title:
                continue
            q = dict(re.findall(r"([a-zA-Z_]+)=([^&]+)", href))
            element = q.get("element", "")
            key = (element, title)
            if not element or key in seen:
                continue
            seen.add(key)
            out.append(Release(
                title=title, version=_version(title), variant=_variant(title),
                element=element, plne=q.get("plne", ""), cert_num=q.get("cert_num", ""),
                href=href,
            ))
        return out

    def search(self, query: str) -> list[Release]:
        html = self._get("search", query=query, action="search")
        return self._parse_releases(html)

    def recent(self) -> list[Release]:
        return self._parse_releases(self._get("viewRecentProductReleases"))

    def list_files(self, element: str, plne: str = "", cert_num: str = "") -> list[DownloadFile]:
        html = self._get("download", element=element, dkey="NULL",
                          plne=plne or None, cert_num=cert_num or None)
        soup = BeautifulSoup(html, "html.parser")
        files: list[DownloadFile] = []
        for a in soup.select(f"a[href*='{FLEXNET_HOST}']"):
            url = a.get("href", "")
            filename = a.get_text(" ", strip=True) or url.split("/")[-1].split("?")[0]
            m = re.search(r"/(\d+)/[^/]+\?", url)  # dkey embedded in path
            dkey = m.group(1) if m else ""
            # size + md5: size/date live in the file row; MD5 is in the
            # following collapsible "Compressed File Contents" sibling rows.
            row = a.find_parent("tr")
            block = row.get_text(" ", strip=True) if row else ""
            size_m = re.search(r"([\d.]+\s?(?:KB|MB|GB|bytes))", block)
            md5_scope = block
            sib = row
            for _ in range(3):
                sib = sib.find_next_sibling("tr") if sib else None
                if sib is None:
                    break
                sib_txt = sib.get_text(" ", strip=True)
                if sib.find("a", href=re.compile(FLEXNET_HOST)):
                    break  # reached the next file's row — stop
                md5_scope += " " + sib_txt
            md5_m = re.search(r"\b([a-f0-9]{32})\b", md5_scope)
            files.append(DownloadFile(
                filename=filename, url=url,
                size=size_m.group(1) if size_m else "",
                md5=md5_m.group(1) if md5_m else "",
                dkey=dkey,
            ))
        return files

    def download_file(self, f: DownloadFile, dest: Path) -> Path:
        dest.mkdir(parents=True, exist_ok=True)
        target = dest / f.filename
        with self.s.get(f.url, stream=True, timeout=120) as r:
            r.raise_for_status()
            with open(target, "wb") as fh:
                for chunk in r.iter_content(chunk_size=1 << 16):
                    fh.write(chunk)
        return target


def release_dict(r: Release) -> dict:
    return asdict(r)


def file_dict(f: DownloadFile) -> dict:
    return asdict(f)
