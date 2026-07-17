#!/usr/bin/env python
"""
review_config.py — Point at an ActOne instance and get a key-configuration summary
by calling a curated set of SAFE, read-only GET endpoints. This seeds the ActWise
vision: "give a URL, the agent extracts key info and reviews configuration".

Usage:
  python review_config.py --url http://HOST:8080/RCM --user admin --password password

Writes a Markdown report to postman/reports/ActOne_{version}_config_review.md and
prints it to stdout. NO writes/changes are made to the ActOne instance.
"""
import argparse, json, re, sys, urllib.request, urllib.error, http.cookiejar
from pathlib import Path
from actone.paths import workdir

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

WORKDIR = workdir()
REPORTS = WORKDIR / "reports"

# Safe, read-only endpoints to sample (no DELETE/POST/PUT).
PROBES = [
    ("Heartbeat", "/api/public/v1/heartbeat"),
    ("Diagnostics", "/api/v1/system/diagnostics"),
    ("Additional modules", "/api/v1/system/diagnostics/additional-modules"),
    ("Licenses", "/api/v1/licenses"),
    ("Work item types", "/api/v1/md/work-item-types"),
    ("Caller permissions", "/api/v1/users/permissions"),
    ("Tenants", "/api/v1/tenants"),
]


def load_env():
    env = {}
    f = WORKDIR / ".env"
    if f.exists():
        for line in f.read_text().splitlines():
            if not line.strip().startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def get_json(opener, url, headers):
    try:
        r = opener.open(urllib.request.Request(url, headers=headers), timeout=30)
        raw = r.read().decode("utf-8", "replace")
        return json.loads(raw), None
    except urllib.error.HTTPError as e:
        return None, "HTTP %s" % e.code
    except Exception as e:
        return None, str(e)[:80]


def main():
    env = load_env()
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=env.get("ACTONE_URL", "http://10.233.194.40:8080/RCM"))
    ap.add_argument("--user", default=env.get("ACTONE_USER", "admin"))
    ap.add_argument("--password", default=env.get("ACTONE_PASSWORD", "password"))
    args = ap.parse_args()
    base = args.url.rstrip("/")

    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

    body = json.dumps({"username": args.user, "password": args.password}).encode()
    req = urllib.request.Request(base + "/api/public/v1/auth/login", data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        resp = opener.open(req, timeout=30)
        csrf = resp.headers.get("CSRFTOKEN")
    except urllib.error.HTTPError as e:
        sys.exit("Login failed: HTTP %s" % e.code)
    H = {"CSRFTOKEN": csrf} if csrf else {}

    data = {}
    for name, path in PROBES:
        if path.startswith("/api/public/"):
            # public endpoint: use a throwaway opener so it can't clobber the auth session cookie
            try:
                r = urllib.request.urlopen(base + path, timeout=20)
                data[name] = (json.loads(r.read().decode("utf-8", "replace")), None)
            except Exception as e:
                data[name] = (None, str(e)[:80])
            continue
        obj, err = get_json(opener, base + path, H)
        data[name] = (obj, err)

    # --- extract highlights from diagnostics ---
    diag = (data.get("Diagnostics", (None,))[0] or {}).get("content", {}) if data.get("Diagnostics", (None,))[0] else {}
    ver = diag.get("acmVersion") or diag.get("rcmVersion") or "unknown"
    m = re.search(r'servicePackVersion["\s:=]+(\d+)', json.dumps(diag))
    sp = m.group(1) if m else None
    version = ver + (("_SP" + sp) if sp else "")

    L = []
    L.append("# ActOne configuration review")
    L.append("")
    L.append("- **Instance:** %s" % base)
    L.append("- **Version:** %s%s" % (ver, (" SP%s" % sp) if sp else ""))
    L.append("- **DB version:** %s" % diag.get("dbVersion", "?"))
    L.append("- **ACM mode:** %s" % diag.get("acmMode", "?"))
    L.append("- **Processors:** %s" % diag.get("availableProcessors", "?"))
    cm = diag.get("clusterMembers") or []
    if isinstance(cm, list):
        L.append("- **Cluster members:** %d (%s)" % (len(cm), ", ".join(
            "%s/%s" % (c.get("appVersion", "?"), c.get("status", "?")) for c in cm if isinstance(c, dict)) or "n/a"))
    plugins = diag.get("plugins") or []
    if isinstance(plugins, list) and plugins:
        ids = [p.get("id") for p in plugins if isinstance(p, dict) and p.get("id")]
        L.append("- **Plugins (%d):** %s" % (len(ids), ", ".join(ids[:12]) + (" ..." if len(ids) > 12 else "")))

    # work item types
    wit = data.get("Work item types", (None,))[0]
    if isinstance(wit, list):
        names = [w.get("identifier") or w.get("name") for w in wit if isinstance(w, dict)]
        L.append("- **Work item types (%d):** %s" % (len(names), ", ".join(filter(None, names[:15])) + (" ..." if len(names) > 15 else "")))

    # licenses
    lic = data.get("Licenses", (None,))[0]
    if isinstance(lic, (list, dict)):
        n = len(lic) if isinstance(lic, list) else len(lic.keys())
        L.append("- **Licenses:** %d entr%s" % (n, "ies" if n != 1 else "y"))

    L.append("")
    L.append("## Endpoint probe results")
    L.append("")
    L.append("| Area | Endpoint | Result |")
    L.append("|------|----------|--------|")
    for name, path in PROBES:
        obj, err = data[name]
        if err:
            res = "\u274c " + err
        elif isinstance(obj, list):
            res = "\u2705 %d items" % len(obj)
        elif isinstance(obj, dict):
            res = "\u2705 object (%d keys)" % len(obj)
        else:
            res = "\u2705 ok"
        L.append("| %s | `%s` | %s |" % (name, path, res))

    report = "\n".join(L) + "\n"
    REPORTS.mkdir(exist_ok=True)
    out = REPORTS / ("ActOne_%s_config_review.md" % version)
    out.write_text(report, encoding="utf-8")
    sys.stderr.write("Wrote %s\n" % out)
    print(report)


if __name__ == "__main__":
    main()
