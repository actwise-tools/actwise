#!/usr/bin/env python
"""
fetch_spec.py — Given an ActOne base URL + credentials, log in, detect the running
version, and download the live OpenAPI/Swagger spec, falling back to the bundled
spec only when the instance exposes no api-docs.

Discovery order:
  1. /api/swagger-resources (springfox) -> advertises the real spec url(s)
  2. /api/api-docs (springfox / Swagger 2.0) and /v3/api-docs* (springdoc / OAS3)
A downloaded Swagger 2.0 spec is auto-converted to OpenAPI 3.0 via swagger2openapi
(npx) so the rest of the pipeline (generate_collection / portman) is uniform.

Usage:
  python fetch_spec.py --url http://HOST:8080/RCM --user admin --password password
  (credentials also read from postman/.env: ACTONE_USER / ACTONE_PASSWORD, or
   default to admin/password)

Outputs a versioned spec under postman/specs/ and prints a JSON summary on the
last line (consumed by the orchestrator): {"version", "spec", "source"}.
"""
import argparse, json, re, sys, subprocess, shutil, urllib.request, urllib.error, http.cookiejar
from pathlib import Path

from actone.paths import PKG, BUNDLED, workdir
WORKDIR = workdir()
SPECS = WORKDIR / "specs"


def convert_swagger2_to_oas3(in_path, version):
    """Swagger 2.0 -> OpenAPI 3.0 via swagger2openapi (npx). Returns OAS3 path or None."""
    npx = shutil.which("npx") or shutil.which("npx.cmd")
    if not npx:
        print("[convert] npx not found; leaving Swagger 2.0 spec as-is", file=sys.stderr)
        return None
    out = SPECS / ("ActOne_%s.oas3.json" % version)
    try:
        subprocess.run([npx, "swagger2openapi", "--patch", "--warnOnly",
                        str(in_path), "-o", str(out)],
                       cwd=str(WORKDIR), check=True, capture_output=True, timeout=180)
        if out.exists():
            print("[convert] Swagger 2.0 -> OpenAPI 3.0 (%s)" % out.name, file=sys.stderr)
            return out
    except Exception as e:
        print("[convert] swagger2openapi failed: %s" % e, file=sys.stderr)
    return None

# JSON endpoints first (work on envs where springdoc is enabled), then YAML.
# Springfox (Swagger 2.0) instances expose /api/api-docs (discoverable via
# /api/swagger-resources); springdoc (OAS3) instances expose /v3/api-docs.
SPEC_CANDIDATES = [
    "/api/api-docs", "/api/api-docs.json",
    "/v3/api-docs", "/v3/api-docs.json", "/api-docs", "/api-docs.json",
    "/v3/api-docs/Extend", "/v3/api-docs/public", "/v2/api-docs",
    "/v3/api-docs.yaml", "/api-docs.yaml",
]
# Discovery endpoints that advertise the real spec url(s).
RESOURCE_ENDPOINTS = ["/api/swagger-resources", "/swagger-resources"]


def load_env():
    env = {}
    f = WORKDIR / ".env"
    if f.exists():
        for line in f.read_text().splitlines():
            if line.strip().startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def make_opener():
    cj = http.cookiejar.CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj)), cj


def discover_spec_paths(opener, base, auth_headers):
    """Ask springfox/springdoc resource endpoints for the real api-docs url(s)."""
    found = []
    for ep in RESOURCE_ENDPOINTS:
        try:
            r = opener.open(urllib.request.Request(base + ep,
                                                   headers={**auth_headers, "Accept": "application/json"}), timeout=30)
            arr = json.loads(r.read().decode("utf-8", "replace"))
            for item in arr if isinstance(arr, list) else []:
                u = item.get("url") if isinstance(item, dict) else None
                if u and u not in found:
                    found.append(u)
            if found:
                print("[discover] %s advertised: %s" % (ep, ", ".join(found)), file=sys.stderr)
                break
        except urllib.error.HTTPError as e:
            print("[discover] %s -> HTTP %s" % (ep, e.code), file=sys.stderr)
        except Exception as e:
            print("[discover] %s -> %s" % (ep, e), file=sys.stderr)
    return found


def to_url(base, path):
    """Join a discovered/candidate path to the base, avoiding a duplicated context."""
    if path.startswith("http"):
        return path
    host = re.match(r"^(https?://[^/]+)", base).group(1)
    ctx = base[len(host):]                      # e.g. /RCM
    if ctx and path.startswith(ctx + "/"):
        return host + path                      # already context-qualified
    return base + (path if path.startswith("/") else "/" + path)


def main():
    env = load_env()
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=env.get("ACTONE_URL", "http://10.233.194.40:8080/RCM"))
    ap.add_argument("--user", default=env.get("ACTONE_USER", "admin"))
    ap.add_argument("--password", default=env.get("ACTONE_PASSWORD", "password"))
    args = ap.parse_args()
    base = args.url.rstrip("/")
    opener, _ = make_opener()

    # --- 1. login ---
    body = json.dumps({"username": args.user, "password": args.password}).encode()
    req = urllib.request.Request(base + "/api/public/v1/auth/login", data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        resp = opener.open(req, timeout=30)
        csrf = resp.headers.get("CSRFTOKEN")
        print("[login] OK, CSRF captured" if csrf else "[login] OK (no CSRF header)", file=sys.stderr)
    except urllib.error.HTTPError as e:
        print("[login] FAILED: HTTP %s" % e.code, file=sys.stderr)
        sys.exit(2)

    auth_headers = {"CSRFTOKEN": csrf} if csrf else {}

    # --- 2. detect version from /system/diagnostics ---
    version = "unknown"
    try:
        d = opener.open(urllib.request.Request(base + "/api/v1/system/diagnostics",
                                               headers=auth_headers), timeout=30)
        content = json.loads(d.read().decode("utf-8", "replace")).get("content", {})
        ver = content.get("acmVersion") or content.get("rcmVersion") or "unknown"
        m = re.search(r'servicePackVersion["\s:=]+(\d+)', json.dumps(content))
        version = ver + (("_SP" + m.group(1)) if m else "")
        print("[version] detected %s" % version, file=sys.stderr)
    except Exception as e:
        print("[version] could not detect: %s" % e, file=sys.stderr)

    # --- 3. try to download the live spec (discovery first, then JSON candidates) ---
    SPECS.mkdir(exist_ok=True)
    discovered = discover_spec_paths(opener, base, auth_headers)
    candidates = discovered + [c for c in SPEC_CANDIDATES if c not in discovered]
    for path in candidates:
        url = to_url(base, path)
        try:
            r = opener.open(urllib.request.Request(url,
                                                   headers={**auth_headers, "Accept": "application/json"}), timeout=30)
            raw = r.read().decode("utf-8", "replace")
            ctype = r.headers.get("Content-Type", "")
            if "html" in ctype.lower():
                continue
            looks_json = raw.lstrip().startswith("{")
            if looks_json:
                obj = json.loads(raw)
                if "openapi" in obj or "swagger" in obj:
                    out = SPECS / ("ActOne_%s.json" % version)
                    out.write_text(json.dumps(obj, indent=2), encoding="utf-8")
                    source = "live:" + path
                    if str(obj.get("swagger", "")).startswith("2"):
                        conv = convert_swagger2_to_oas3(out, version)
                        if conv:
                            out, source = conv, source + " (converted to OAS3)"
                    print(json.dumps({"version": version, "spec": str(out), "source": source}))
                    return
            elif "openapi:" in raw[:200] or "swagger:" in raw[:200]:
                out = SPECS / ("ActOne_%s.yaml" % version)
                out.write_text(raw, encoding="utf-8")
                print(json.dumps({"version": version, "spec": str(out), "source": "live:" + path}))
                return
        except urllib.error.HTTPError as e:
            print("[spec] %s -> HTTP %s" % (path, e.code), file=sys.stderr)
        except Exception as e:
            print("[spec] %s -> %s" % (path, e), file=sys.stderr)

    # --- 4. fallback to bundled spec ---
    print("[spec] live api-docs not accessible on this instance; using bundled spec", file=sys.stderr)
    print(json.dumps({"version": version, "spec": str(BUNDLED), "source": "bundled"}))


if __name__ == "__main__":
    main()
