#!/usr/bin/env python
"""
provision_from_url.py — One command, end to end: point at an ActOne instance and
get a version-stamped Postman collection (+ environment) in your workspace.

Pipeline:  fetch_spec.py  ->  generate_collection.py  ->  push to Postman

Usage:
  python provision_from_url.py --url http://HOST:8080/RCM --user admin --password password [--push]

Reads POSTMAN_API_KEY / POSTMAN_WORKSPACE_ID from postman/.env for --push.
"""
import argparse, json, subprocess, sys, urllib.request, urllib.error
from pathlib import Path
from actone.paths import workdir

WORKDIR = workdir()
PY = sys.executable


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


def run(cmd):
    print("  $ " + " ".join(Path(c).name if c.endswith(".py") else c for c in cmd), file=sys.stderr)
    p = subprocess.run(cmd, capture_output=True, text=True)
    sys.stderr.write(p.stderr)
    if p.returncode != 0:
        print("  FAILED (%s)" % p.returncode, file=sys.stderr)
        sys.exit(p.returncode)
    return p.stdout


def post_json(url, api_key, body):
    data = body.encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"X-API-Key": api_key, "Content-Type": "application/json"})
    try:
        return json.loads(urllib.request.urlopen(req, timeout=60).read().decode())
    except urllib.error.HTTPError as e:
        raise SystemExit("Postman API error: " + e.read().decode())


def main():
    env = load_env()
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=env.get("ACTONE_URL", "http://10.233.194.40:8080/RCM"))
    ap.add_argument("--user", default=env.get("ACTONE_USER", "admin"))
    ap.add_argument("--password", default=env.get("ACTONE_PASSWORD", "password"))
    ap.add_argument("--push", action="store_true")
    args = ap.parse_args()

    # 1. fetch spec + version
    print("[1/3] Detecting version and fetching spec ...", file=sys.stderr)
    out = run([PY, "-m", "actone.fetch_spec", "--url", args.url, "--user", args.user, "--password", args.password])
    info = json.loads(out.strip().splitlines()[-1])
    version, spec, source = info["version"], info["spec"], info["source"]
    print("      version=%s  source=%s" % (version, source), file=sys.stderr)

    # 2. generate collection
    print("[2/3] Generating collection ...", file=sys.stderr)
    out = run([PY, "-m", "actone.generate_collection", "--spec", spec, "--version", version])
    coll_path = next((l.split("Wrote ", 1)[1].strip() for l in out.splitlines() if l.startswith("Wrote ")), None)
    coll_name = next((l.split("Collection: ", 1)[1].strip() for l in out.splitlines() if l.startswith("Collection: ")), "ActOne")

    result = {"version": version, "spec": spec, "source": source, "collection_file": coll_path, "collection_name": coll_name}

    # 3. push (optional)
    if args.push:
        api_key = env.get("POSTMAN_API_KEY")
        ws = env.get("POSTMAN_WORKSPACE_ID")
        if not api_key:
            raise SystemExit("POSTMAN_API_KEY missing in postman/.env")
        print("[3/3] Pushing to Postman workspace %s ..." % ws, file=sys.stderr)
        coll_raw = Path(coll_path).read_text(encoding="utf-8")
        r = post_json("https://api.getpostman.com/collections?workspace=%s" % ws, api_key, '{"collection":' + coll_raw + '}')
        result["collection_uid"] = r["collection"]["uid"]
        # environment pointed at this instance
        envdoc = {"name": "ActOne - %s" % version, "values": [
            {"key": "rcm", "value": args.url, "enabled": True},
            {"key": "username", "value": args.user, "enabled": True},
            {"key": "password", "value": args.password, "type": "secret", "enabled": True},
            {"key": "CSRFTOKEN", "value": "", "type": "secret", "enabled": True},
        ], "_postman_variable_scope": "environment"}
        e = post_json("https://api.getpostman.com/environments?workspace=%s" % ws, api_key, json.dumps({"environment": envdoc}))
        result["environment_uid"] = e["environment"]["uid"]
    else:
        print("[3/3] Skipped push (use --push). Collection saved locally.", file=sys.stderr)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
