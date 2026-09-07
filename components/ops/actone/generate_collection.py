#!/usr/bin/env python
"""
generate_collection.py — Build a Postman v2.1 collection for ALL ActOne Extend
REST API operations from the OpenAPI spec, organized into logical domain folders.

Reusable generator (see README "Generalizing into a reusable Actimize API suite"):
  spec + recipe(quirks) -> Postman collection.

Output: generated/ActOne.Full.postman_collection.json
"""
import yaml, json, re
from pathlib import Path
import argparse
from actone.paths import BUNDLED, workdir

WORKDIR = workdir()
DEFAULT_SPEC = BUNDLED

# --- recipe: logical domains (ordered) mapping OpenAPI tags -> top-level folders ---
DOMAINS = [
    ("00 \u00b7 Auth & Access Control", ["Access Control"]),
    ("01 \u00b7 Work Items (Core)", ["Work Items", "Forms", "Alert Details REST API", "Notifications REST API"]),
    ("02 \u00b7 Metadata & Workflow Config", ["Work Items Metadata", "Workflow Restrictions Templates REST API"]),
    ("03 \u00b7 Policy Manager", ["Policy Manager"]),
    ("04 \u00b7 Network Analytics", ["Network Analytics"]),
    ("05 \u00b7 Entity Insights", ["Entity Insights"]),
    ("06 \u00b7 Data Querying", ["Data Querying", "Search Repository"]),
    ("07 \u00b7 Administration", ["Administration", "User API"]),
    ("08 \u00b7 System & Config Management", ["System Configuration", "Configuration Management REST API", "Platform Lists"]),
    ("09 \u00b7 Diagnostics & Monitoring", ["Diagnostics", "Audit Events"]),
    ("10 \u00b7 Migration, Automation & Misc", ["Migration", "Automation", "Plugins", "Miscellaneous",
                                               "Easy Ingest", "Virtual File System", "Mini-Widget REST API"]),
]
TAG_TO_DOMAIN = {tag: dom for dom, tags in DOMAINS for tag in tags}
MISC_DOMAIN = DOMAINS[-1][0]

DESTRUCTIVE_RE = re.compile(r"\b(delete|remove|deploy|cancel|clear|reset|restore|import|backup|purge|drop)\b", re.I)

_ap = argparse.ArgumentParser()
_ap.add_argument("--spec", default=str(DEFAULT_SPEC), help="OpenAPI spec (yaml or json)")
_ap.add_argument("--version", default="", help="ActOne version label, e.g. 10.0.0.69_SP15")
_ap.add_argument("--name", default="", help="Collection name (overrides default)")
_ap.add_argument("--out", default="", help="Output collection path")
ARGS = _ap.parse_args()

SPEC = Path(ARGS.spec)
if SPEC.suffix.lower() == ".json":
    spec = json.load(open(SPEC, encoding="utf-8"))
else:
    spec = yaml.safe_load(open(SPEC, encoding="utf-8"))
SCHEMAS = spec.get("components", {}).get("schemas", {})
all_params = set()


def example(schema, depth=0, seen=None):
    seen = seen or frozenset()
    if depth > 4 or not isinstance(schema, dict):
        return {}
    if "$ref" in schema:
        name = schema["$ref"].split("/")[-1]
        if name in seen:
            return {}
        return example(SCHEMAS.get(name, {}), depth, seen | {name})
    if "allOf" in schema:
        out = {}
        for s in schema["allOf"]:
            v = example(s, depth, seen)
            if isinstance(v, dict):
                out.update(v)
        return out
    t = schema.get("type")
    if t == "object" or "properties" in schema:
        return {k: example(v, depth + 1, seen) for k, v in schema.get("properties", {}).items()}
    if t == "array":
        return [example(schema.get("items", {}), depth + 1, seen)]
    if schema.get("enum"):
        return schema["enum"][0]
    return {"string": "", "integer": 0, "number": 0, "boolean": False}.get(t)


def build_request(method, path, op):
    op_id = op.get("operationId", "")
    summary = (op.get("summary") or op_id or path).strip()
    is_login = op_id == "login"
    is_save_step = op_id == "saveStepChanges"
    destructive = method == "DELETE" or bool(DESTRUCTIVE_RE.search(summary)) or bool(DESTRUCTIVE_RE.search(op_id))

    name = ("\u26a0 " if destructive else "") + summary

    # --- url ---
    path_no_rcm = path[4:] if path.startswith("/RCM") else path  # {{rcm}} already ends with /RCM
    pm_path = re.sub(r"\{([^}]+)\}", r":\1", path_no_rcm)
    segs = [s for s in pm_path.strip("/").split("/") if s]
    url_vars = []
    for p in op.get("parameters", []):
        if p.get("in") == "path":
            all_params.add(p["name"])
            url_vars.append({"key": p["name"], "value": "{{%s}}" % p["name"],
                             "description": (p.get("description") or "").strip()})

    query = []
    for p in op.get("parameters", []):
        if p.get("in") != "query":
            continue
        all_params.add(p["name"])
        required = p.get("required", False)
        entry = {"key": p["name"], "value": "{{%s}}" % p["name"],
                 "description": (p.get("description") or "").strip()}
        if not required:
            entry["disabled"] = True
        query.append(entry)

    # save-step quirk: pre-encoded JSON params (Tomcat rejects raw { } [ ] ")
    if is_save_step:
        query = [
            {"key": "workItemIdentifiers", "value": "{{wi_q}}", "description": "JSON array, percent-encoded by pre-request."},
            {"key": "statusIdentifier", "value": "{{status_identifier}}", "description": "Target step IDENTIFIER (case-sensitive)."},
            {"key": "note", "value": "{{note_q}}", "description": "JSON object {\"note\":\"...\"}, percent-encoded by pre-request."},
            {"key": "forceStatus", "value": "{{force_status}}", "description": "ActOne 10.1.0 SP5+; ignored on older servers."},
        ]

    raw = "{{rcm}}/" + "/".join(segs)
    enabled_q = [q for q in query if not q.get("disabled")]
    if enabled_q:
        raw += "?" + "&".join("%s=%s" % (q["key"], q["value"]) for q in enabled_q)
    url = {"raw": raw, "host": ["{{rcm}}"], "path": segs}
    if query:
        url["query"] = query
    if url_vars:
        url["variable"] = url_vars

    # --- headers ---
    headers = []
    if not is_login:
        headers.append({"key": "CSRFTOKEN", "value": "{{CSRFTOKEN}}"})

    # --- body ---
    body = None
    rb = op.get("requestBody")
    if is_save_step:
        body = {"mode": "formdata", "formdata": [
            {"key": "_", "value": "", "type": "text",
             "description": "Placeholder so Postman sends valid multipart/form-data (save-step requires it; otherwise 415)."}]}
    elif is_login:
        headers.append({"key": "Content-Type", "value": "application/json"})
        body = {"mode": "raw", "raw": json.dumps({"username": "{{username}}", "password": "{{password}}"}, indent=2),
                "options": {"raw": {"language": "json"}}}
    elif rb and "application/json" in rb.get("content", {}):
        headers.append({"key": "Content-Type", "value": "application/json"})
        sch = rb["content"]["application/json"].get("schema", {})
        body = {"mode": "raw", "raw": json.dumps(example(sch), indent=2),
                "options": {"raw": {"language": "json"}}}

    request = {"method": method, "header": headers, "url": url}
    if body:
        request["body"] = body
    desc = (op.get("description") or "").strip()
    if destructive:
        desc = "\u26a0 DESTRUCTIVE / ADMIN operation \u2014 review before running.\n\n" + desc
    if desc:
        request["description"] = desc

    item = {"name": name, "request": request}

    # --- scripts ---
    events = []
    if is_login:
        events.append({"listen": "test", "script": {"type": "text/javascript", "exec": [
            'var t = pm.response.headers.get("CSRFTOKEN");',
            'if (t) { pm.environment.set("CSRFTOKEN", t); }',
            'pm.test("Login 200", function () { pm.response.to.have.status(200); });',
            'pm.test("CSRF token exists", function () { pm.expect(t).to.not.be.null; });']}})
    if is_save_step:
        events.append({"listen": "prerequest", "script": {"type": "text/javascript", "exec": [
            "// Tomcat rejects raw { } [ ] \" in the URL. Pre-encode JSON-valued query params.",
            "var wid = pm.environment.get('work_item_id') || pm.variables.get('work_item_id');",
            "var note = pm.environment.get('note') || pm.variables.get('note') || '';",
            "pm.variables.set('wi_q', encodeURIComponent(JSON.stringify([wid])));",
            "pm.variables.set('note_q', encodeURIComponent(JSON.stringify({ note: note })));"]}})
    if events:
        item["event"] = events
    return item, is_login, destructive


# --- group operations: domain -> tag -> [items] ---
tree = {dom: {} for dom, _ in DOMAINS}
login_item = None
for path, item in spec.get("paths", {}).items():
    for method, op in item.items():
        if method.lower() not in ("get", "post", "put", "delete", "patch"):
            continue
        tag = (op.get("tags") or ["Miscellaneous"])[0]
        domain = TAG_TO_DOMAIN.get(tag, MISC_DOMAIN)
        pm_item, is_login, _ = build_request(method.upper(), path, op)
        tree[domain].setdefault(tag, []).append((pm_item, is_login))

# --- assemble folders, login first in its tag ---
def folderize(name, items):
    return {"name": name, "item": items}

root_items = []
for dom, tags in DOMAINS:
    tag_map = tree[dom]
    if not tag_map:
        continue
    single = len(tags) == 1
    dom_children = []
    for tag in tags:
        entries = tag_map.get(tag)
        if not entries:
            continue
        entries.sort(key=lambda e: (not e[1], e[0]["name"]))  # login first
        reqs = [e[0] for e in entries]
        if single:
            dom_children.extend(reqs)
        else:
            dom_children.append(folderize(tag, reqs))
    root_items.append(folderize(dom, dom_children))

# --- collection variables (all path/query params + core) ---
core = ["rcm", "username", "password", "CSRFTOKEN", "work_item_id", "status_identifier", "note", "force_status"]
variables = [{"key": k, "value": ""} for k in core]
for p in sorted(all_params):
    if p not in core:
        variables.append({"key": p, "value": ""})

spec_ver = spec.get("info", {}).get("version", "?")
ver_label = ARGS.version or spec_ver
col_name = ARGS.name or ("ActOne Extend REST APIs \u2014 Full (v%s)" % ver_label)
total_ops = sum(len(v) for tm in tree.values() for v in tm.values())

collection = {
    "info": {
        "name": col_name,
        "description": ("Auto-generated by generate_collection.py from spec '%s' (spec v%s; target instance v%s). "
                        "All %d operations across logical domains. Run **00 \u00b7 Auth \u2192 Login** first to "
                        "capture CSRFTOKEN. Requests prefixed \u26a0 are destructive/admin \u2014 review before running."
                        % (SPEC.name, spec_ver, ver_label, total_ops)),
        "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"
    },
    "item": root_items,
    "variable": variables,
}

OUT = Path(ARGS.out) if ARGS.out else (WORKDIR / "generated" / ("ActOne.Full.%s.postman_collection.json" % ver_label))
OUT.parent.mkdir(exist_ok=True)
OUT.write_text(json.dumps(collection, indent=2), encoding="utf-8")
total = total_ops
print("Wrote %s" % OUT)
print("Collection: %s" % col_name)
print("Domains: %d | Operations: %d | Variables: %d" % (len(root_items), total, len(variables)))
for dom, _ in DOMAINS:
    n = sum(len(v) for v in tree[dom].values())
    if n:
        print("  %-38s %d" % (dom, n))
