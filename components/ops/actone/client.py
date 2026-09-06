#!/usr/bin/env python
"""
client.py — a small, typed ActOne REST client shared by the CLI ops group and the
MCP discovery server.

Encapsulates the ActOne-specific auth + quirks proven in fetch_spec.py /
review_config.py / generate_collection.py:
  - login via POST /api/public/v1/auth/login -> CSRFTOKEN response header + JSESSIONID cookie
  - version detect via GET /api/v1/system/diagnostics
  - request execution carrying the cookie jar + CSRFTOKEN header
  - Tomcat pre-encode quirk for raw { } [ ] " in query values
  - 415 -> retry as multipart/form-data quirk

Stdlib only (urllib), matching the rest of the package. Importable: no top-level work.
"""
import json
import os
import re
import urllib.request
import urllib.error
import urllib.parse
import http.cookiejar

from actone.paths import workdir

# Characters Tomcat rejects raw in a query string; pre-percent-encode them.
_TOMCAT_BAD = '{}[]"'


def load_env():
    """Read KEY=VALUE pairs from <workdir>/.env (gitignored)."""
    env = {}
    f = workdir() / ".env"
    if f.exists():
        for line in f.read_text().splitlines():
            if line.strip().startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def pre_encode(value):
    """Percent-encode the bytes Tomcat rejects raw, plus space/control chars that
    make an invalid URL (e.g. a note query param with spaces); rest stays readable."""
    return "".join(
        ("%%%02X" % ord(c)) if (c in _TOMCAT_BAD or ord(c) <= 0x20 or ord(c) == 0x7F) else c
        for c in value
    )


class ActOneError(Exception):
    pass


class ActOneClient:
    """Authenticated client for one ActOne instance."""

    def __init__(self, base_url, user, password, timeout=30, context_root=None):
        self.base = base_url.rstrip("/")
        # Context root (e.g. "/RCM") for the client-constructed auth + diagnostics
        # endpoints. Operation paths come from the spec and already carry their own
        # prefix, so the context root is applied only to login/detect_version.
        # Resolves from the ACTONE_CONTEXT_ROOT env var (or <workdir>/.env) when not
        # passed explicitly; defaults to empty for instances served at the root.
        if context_root is None:
            context_root = os.environ.get("ACTONE_CONTEXT_ROOT") or \
                load_env().get("ACTONE_CONTEXT_ROOT", "")
        ctx = (context_root or "").strip().strip("/")
        self.ctx = ("/" + ctx) if ctx else ""
        self.user = user
        self.password = password
        self.timeout = timeout
        self.csrf = None
        self.version = "unknown"
        self._cj = http.cookiejar.CookieJar()
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self._cj)
        )
        self._logged_in = False

    # --- auth ---------------------------------------------------------------
    def login(self):
        body = json.dumps({"username": self.user, "password": self.password}).encode()
        req = urllib.request.Request(
            self.base + self.ctx + "/api/public/v1/auth/login", data=body,
            headers={"Content-Type": "application/json"},
        )
        try:
            resp = self._opener.open(req, timeout=self.timeout)
        except urllib.error.HTTPError as e:
            raise ActOneError("login failed: HTTP %s" % e.code)
        except Exception as e:
            raise ActOneError("login failed: %s" % e)
        self.csrf = resp.headers.get("CSRFTOKEN")
        self._logged_in = True
        return self

    def ensure_login(self):
        if not self._logged_in:
            self.login()
        return self

    def relogin(self):
        """Force a fresh login, e.g. after a server-side session timeout on a
        long-lived cached client. Replaces the expired JSESSIONID + CSRF token."""
        self._logged_in = False
        self.csrf = None
        return self.login()

    def detect_version(self):
        """GET /api/v1/system/diagnostics -> 'acmVersion[_SP<n>]'. Best-effort."""
        self.ensure_login()
        try:
            obj = self._raw("GET", self.ctx + "/api/v1/system/diagnostics")
            content = (obj or {}).get("content", {}) if isinstance(obj, dict) else {}
            ver = content.get("acmVersion") or content.get("rcmVersion") or "unknown"
            m = re.search(r'servicePackVersion["\s:=]+(\d+)', json.dumps(content))
            self.version = ver + (("_SP" + m.group(1)) if m else "")
        except Exception:
            self.version = "unknown"
        return self.version

    # --- requests -----------------------------------------------------------
    def _auth_headers(self, extra=None):
        h = {"CSRFTOKEN": self.csrf} if self.csrf else {}
        if extra:
            h.update(extra)
        return h

    def _raw(self, method, path, headers=None):
        """Minimal GET/raw helper returning parsed JSON (or text)."""
        url = self.base + path if path.startswith("/") else self.base + "/" + path
        req = urllib.request.Request(url, headers=self._auth_headers(headers), method=method)
        r = self._opener.open(req, timeout=self.timeout)
        raw = r.read().decode("utf-8", "replace")
        try:
            return json.loads(raw)
        except ValueError:
            return raw

    def request(self, method, path, query=None, body=None, headers=None):
        """Execute an arbitrary ActOne request.

        Returns dict: {status, ok, content_type, body (parsed JSON or text), url}.
        Applies the Tomcat pre-encode quirk to query values and retries a 415 as
        multipart/form-data.
        """
        self.ensure_login()
        method = method.upper()

        qs = ""
        if query:
            parts = []
            for k, v in query.items():
                if v is None:
                    continue
                v = v if isinstance(v, str) else json.dumps(v)
                parts.append("%s=%s" % (urllib.parse.quote(str(k)), pre_encode(v)))
            if parts:
                qs = "?" + "&".join(parts)

        url = (self.base + path if path.startswith("/") else self.base + "/" + path) + qs

        def _attempt():
            data = None
            hdrs = self._auth_headers(headers)
            if body is not None:
                data = json.dumps(body).encode()
                hdrs.setdefault("Content-Type", "application/json")
            return self._do(method, url, data, hdrs)

        try:
            return _attempt()
        except urllib.error.HTTPError as e:
            if e.code == 415:
                # quirk: some ActOne POSTs (e.g. save-step) require multipart/form-data
                # even with no JSON body — retry as multipart (empty body -> {}).
                return self._do_multipart(method, url, body or {}, self._auth_headers(headers))
            if e.code in (401, 403):
                # A long-lived cached client's ActOne session may have timed out;
                # re-login once (fresh JSESSIONID + CSRF) and retry before giving up.
                self.relogin()
                try:
                    return _attempt()
                except urllib.error.HTTPError as e2:
                    return self._err_result(method, url, e2)
            return self._err_result(method, url, e)

    def _do(self, method, url, data, hdrs):
        req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
        r = self._opener.open(req, timeout=self.timeout)
        return self._ok_result(method, url, r)

    def _do_multipart(self, method, url, body, hdrs):
        boundary = "----actone%s" % id(body)
        fields = dict(body or {})
        if not fields:
            # ActOne rejects an empty multipart body; a placeholder part keeps it valid
            # (mirrors the Postman recipe's empty "_" field for e.g. save-step).
            fields["_"] = ""
        lines = []
        for k, v in fields.items():
            v = v if isinstance(v, str) else json.dumps(v)
            lines += ["--" + boundary,
                      'Content-Disposition: form-data; name="%s"' % k, "", v]
        lines += ["--" + boundary + "--", ""]
        data = "\r\n".join(lines).encode()
        hdrs["Content-Type"] = "multipart/form-data; boundary=%s" % boundary
        req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
        try:
            r = self._opener.open(req, timeout=self.timeout)
            return self._ok_result(method, url, r)
        except urllib.error.HTTPError as e:
            return self._err_result(method, url, e)

    @staticmethod
    def _parse(raw, ctype):
        if "json" in (ctype or "").lower() or raw.lstrip().startswith(("{", "[")):
            try:
                return json.loads(raw)
            except ValueError:
                pass
        return raw

    def _ok_result(self, method, url, r):
        raw = r.read().decode("utf-8", "replace")
        ctype = r.headers.get("Content-Type", "")
        return {"status": r.status, "ok": True, "content_type": ctype,
                "body": self._parse(raw, ctype), "url": url, "method": method}

    def _err_result(self, method, url, e):
        try:
            raw = e.read().decode("utf-8", "replace")
        except Exception:
            raw = ""
        ctype = e.headers.get("Content-Type", "") if e.headers else ""
        return {"status": e.code, "ok": False, "content_type": ctype,
                "body": self._parse(raw, ctype) if raw else None,
                "url": url, "method": method, "error": "HTTP %s" % e.code}
