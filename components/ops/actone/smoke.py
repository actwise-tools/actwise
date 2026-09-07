"""smoke.py — read-only smoke harness across the whole ops MCP surface.

Drives the *actual* MCP tool functions (``actone_mcp.server``) rather than the
engine directly, so a pass proves an operation works **from the MCP** — the exact
surface we ship to other team members — not merely from the CLI/engine one layer
down. (The CLI and MCP share the same engine, so this also covers the CLI.)

Three invocable surfaces are exercised:

* **REST** — every read (GET/HEAD) op via ``invoke_op``. No-required-param ops run
  directly; ops needing a path/query value run only if a fixture supplies it.
* **Curated SOAP** — ``invoke_soap_operation`` read ops (``bu.list`` / ``bu.get``).
* **Full SOAP catalog** — every read-classified op with no required input via
  ``designer_call_operation`` (the escape hatch over all 335 catalog ops).

Reads only by default (safe to run anywhere). Two opt-in extensions widen coverage
toward "everything we ship" without ever blind-firing a destructive op:

* ``write=True`` — exercises the shipped *write-authoring* paths end-to-end as
  create → verify persisted → remove, each cleaned up in a ``finally`` so a partial
  failure leaves no residue: **typed** (AlertType, DDQ), **curated SOAP**
  (BusinessUnit), and the **generic engine** (clone → verify → remove). This proves
  the create/clone/remove mechanisms we author, not merely that the engine compiles.
* ``gating=True`` with a read-only ``ro_env`` — the *safe* way to validate every
  *other* write op we expose (REST writes, curated-SOAP writes, and the whole SOAP
  write catalog, ~240 ops). Rather than executing them, it asserts each is **refused
  at the write gate** when the target env forbids writes. The gate fires offline
  (``precheck`` / ``_designer_write_guard`` return before any login), so this touches
  no server state yet proves the MCP correctly protects — and correctly classifies —
  every write op before we ship it.

Read coverage is widened by ``_autofixtures``: it discovers real ids from the live
env via safe reads (work-item types, business units, policy types, connections) and
feeds them back so id-dependent reads run instead of skipping. Pure reads.
"""
from __future__ import annotations

import time
from typing import Optional


# --------------------------------------------------------------------------- #
# result interpretation
# --------------------------------------------------------------------------- #
def _verdict(res: dict) -> tuple[str, str]:
    """Map an MCP response dict to ``(status, detail)``.

    ``status`` is ``"pass"``, ``"fail"``, or ``"error"``. A response is a pass when
    the call reached the server and the server did not report an error: REST
    ``ok`` is truthy (HTTP < 400), SOAP/designer has no ``error`` and ``ok`` is not
    ``False``."""
    if not isinstance(res, dict):
        return "fail", "non-dict response: %r" % (res,)
    if res.get("error"):
        return "error", str(res["error"])[:200]
    if "status" in res:  # REST shape
        code = res.get("status")
        if res.get("ok") or (isinstance(code, int) and code < 400):
            return "pass", "HTTP %s" % code
        return "fail", "HTTP %s: %s" % (code, str(res.get("body"))[:150])
    if res.get("ok") is False:  # SOAP/designer explicit failure
        return "fail", str(res.get("messages") or res)[:200]
    return "pass", "ok"


def _record(bucket: dict, op_id: str, status: str, detail: str) -> None:
    bucket["results"].append({"op": op_id, "status": status, "detail": detail})
    bucket[status] = bucket.get(status, 0) + 1


def _new_bucket() -> dict:
    return {"results": [], "pass": 0, "fail": 0, "error": 0, "skip": 0}


# --------------------------------------------------------------------------- #
# auto-fixtures: discover real ids from safe reads so id-dependent reads run
# --------------------------------------------------------------------------- #
def _body_list(res: dict) -> list:
    """Return the list body of an MCP REST response, else []."""
    if isinstance(res, dict):
        b = res.get("body")
        if isinstance(b, list):
            return b
        if isinstance(b, dict):
            for v in b.values():  # some payloads wrap the list under one key
                if isinstance(v, list):
                    return v
    return []


def _autofixtures(S, env: Optional[str]) -> dict:
    """Discover real identifiers from side-effect-free reads.

    Each probe is best-effort (an empty table or missing feature just yields no
    fixture); the returned map is keyed by the *param names* the id-dependent
    reads expect, so ``smoke_rest`` can run them instead of skipping. Pure reads —
    nothing is created or mutated."""
    fx: dict = {}

    def _first_id(op, *keys):
        for rec in _body_list(_safe(lambda: S.invoke_op(op, env=env))):
            if isinstance(rec, dict):
                for k in keys:
                    if rec.get(k):
                        return rec[k]
        return None

    wit = _first_id("getWorkItemTypes", "identifier")
    if wit:
        fx.setdefault("workItemTypeIdentifier", wit)
        fx.setdefault("alertTypeIdentifier", wit)
    pt = _first_id("getPolicyTypes", "identifier")
    if pt:
        fx.setdefault("policyTypeIdentifier", pt)
    conn = _first_id("getConnectionsList", "name", "identifier") or \
        _first_id("getConnections", "name", "identifier")
    if conn:
        fx.setdefault("connectionName", conn)
        fx.setdefault("connectionIdentifier", conn)
    # a user identifier from the permissions read (dict-wrapped under userInfoList)
    perms = _safe(lambda: S.invoke_op("getUsersPermissionsForAllUsers", env=env)) or {}
    body = perms.get("body") if isinstance(perms, dict) else None
    uinfo = body.get("userInfoList") if isinstance(body, dict) else None
    if isinstance(uinfo, list) and uinfo and isinstance(uinfo[0], dict):
        uid = uinfo[0].get("UserIdentifier") or uinfo[0].get("userIdentifier")
        if uid:
            fx.setdefault("userIdentifier", uid)
    # business unit id via curated SOAP
    lst = _safe(lambda: S.invoke_soap_operation("bu.list", env=env)) or {}
    recs = lst.get("records") if isinstance(lst, dict) else None
    if recs:
        bu = recs[0]
        if bu.get("identifier"):
            fx.setdefault("businessUnitIdentifier", bu["identifier"])
    return fx


def _safe(fn):
    """Run ``fn`` and swallow any exception (discovery must never abort a run)."""
    try:
        return fn()
    except Exception:  # noqa: BLE001
        return None


# --------------------------------------------------------------------------- #
# write-gate verdict: a WRITE op is "pass" when it is correctly REFUSED
# --------------------------------------------------------------------------- #
def _gate_verdict(res: dict) -> tuple[str, str]:
    """Interpret a write op invoked against a writes-forbidden env.

    A ``pass`` means the MCP refused it at the gate (the desired protection). A
    ``fail`` means the call was NOT refused — a gate leak or misclassification we
    must catch before shipping."""
    if isinstance(res, dict):
        err = str(res.get("error") or "")
        if "writes are disabled" in err.lower() or (
                "write" in err.lower() and "disabl" in err.lower()):
            return "pass", "refused at gate"
        if res.get("error"):
            return "error", err[:180]
    return "fail", "NOT refused: %s" % (str(res)[:180])


# --------------------------------------------------------------------------- #
# REST
# --------------------------------------------------------------------------- #
def smoke_rest(S, env: Optional[str], fixtures: dict, limit: Optional[int]) -> dict:
    """Invoke every REST read op reachable without side effects."""
    bucket = _new_bucket()
    reg = S._reg()
    reads = sorted((o for o in reg.ops.values() if o["read"]),
                   key=lambda o: o["operationId"])
    n = 0
    for op in reads:
        if limit and n >= limit:
            break
        op_id = op["operationId"]
        req = [p for p in op["params"] if p.get("required")]
        missing = [p["name"] for p in req if p["name"] not in fixtures]
        if (op.get("requestBody") or {}).get("required"):
            _record(bucket, op_id, "skip", "needs request body")
            continue
        if missing:
            _record(bucket, op_id, "skip", "needs param(s): %s" % ", ".join(missing))
            continue
        params = {p["name"]: fixtures[p["name"]] for p in req}
        n += 1
        try:
            res = S.invoke_op(op_id, params=params or None, env=env)
        except Exception as e:  # noqa: BLE001 — harness must never abort mid-run
            _record(bucket, op_id, "error", "exception: %s" % e)
            continue
        _record(bucket, op_id, *_verdict(res))
    return bucket


# --------------------------------------------------------------------------- #
# curated SOAP (bu.*)
# --------------------------------------------------------------------------- #
def smoke_soap_curated(S, env: Optional[str], fixtures: dict) -> dict:
    """Invoke the curated SOAP read ops via ``invoke_soap_operation``."""
    from actone.soap import SOAP_OPS
    bucket = _new_bucket()
    for op_id, spec in sorted(SOAP_OPS.items()):
        if spec.get("access") != "read":
            _record(bucket, op_id, "skip", "write op")
            continue
        # params is a {name: {type, required?}} map; treat each as needed input
        pnames = list((spec.get("params") or {}).keys())
        missing = [n for n in pnames if n not in fixtures]
        # bu.get needs an identifier — borrow the first from bu.list if absent
        if missing and op_id == "bu.get":
            try:
                lst = S.invoke_soap_operation("bu.list", env=env)
                recs = lst.get("records") or []
                ident = recs[0].get("identifier") if recs else None
                if ident:
                    fixtures = {**fixtures, **{n: ident for n in missing}}
                    missing = []
            except Exception:  # noqa: BLE001
                pass
        if missing:
            _record(bucket, op_id, "skip", "needs param(s): %s" % ", ".join(missing))
            continue
        params = {n: fixtures[n] for n in pnames}
        try:
            res = S.invoke_soap_operation(op_id, params=params or None, env=env)
        except Exception as e:  # noqa: BLE001
            _record(bucket, op_id, "error", "exception: %s" % e)
            continue
        _record(bucket, op_id, *_verdict(res))
    return bucket


# --------------------------------------------------------------------------- #
# full SOAP catalog (via designer_call_operation)
# --------------------------------------------------------------------------- #
def smoke_soap_catalog(S, env: Optional[str], limit: Optional[int]) -> dict:
    """Invoke every read-classified catalog op that needs no input parameter."""
    from actone.soap_catalog import load_catalog, operation_access
    bucket = _new_bucket()
    cat = load_catalog()
    n = 0
    for svc in cat.services:
        service = svc.get("name")
        ops = svc.get("operations", [])
        items = ops if isinstance(ops, list) else [dict(v, name=k) for k, v in ops.items()]
        for op in sorted(items, key=lambda o: o.get("name") or ""):
            name = op.get("name") or ""
            op_id = "%s.%s" % (service, name)
            if operation_access(name) != "read":
                _record(bucket, op_id, "skip", "write/unclassified verb")
                continue
            params = op.get("parameters") or []
            ins = [p for p in params if p.get("mode") == "in"]
            if ins:
                _record(bucket, op_id, "skip",
                        "needs input: %s" % ", ".join(p.get("name", "?") for p in ins))
                continue
            if limit and n >= limit:
                _record(bucket, op_id, "skip", "over --limit")
                continue
            out_param = next((p.get("name") for p in params if p.get("mode") == "out"), None)
            n += 1
            try:
                res = S.designer_call_operation(service, name, out_param=out_param, env=env)
            except Exception as e:  # noqa: BLE001
                _record(bucket, op_id, "error", "exception: %s" % e)
                continue
            _record(bucket, op_id, *_verdict(res))
    return bucket


# --------------------------------------------------------------------------- #
# Designer write lifecycle (opt-in; auto-cleanup)
# --------------------------------------------------------------------------- #
def smoke_designer_write(S, env: Optional[str], workflow: str) -> dict:
    """create → verify persisted → remove for the shipped write-authoring paths.

    Covers the mechanisms we actually author — **typed** (AlertType, DDQ),
    **curated SOAP** (BusinessUnit), and the **generic engine** (clone). Every
    created object is removed in a ``finally`` so a partial failure leaves no
    residue. Requires the target env to permit writes."""
    bucket = _new_bucket()
    ts = int(time.time())
    at_id = "AW_SMOKE_AT_%d" % ts
    ddq_id = "AW_SMOKE_DDQ_%d" % ts
    bu_id = "AW_SMOKE_BU_%d" % ts
    clone_id = "AW_SMOKE_CLONE_%d" % ts

    # -- AlertType: create -> present in getWorkItemTypes -> remove -----------
    try:
        res = S.create_alert_type(at_id, name=at_id, description="smoke",
                                  using_alert_status_workflow=True,
                                  alert_status_workflow_definition_identifier=workflow,
                                  env=env)
        st, detail = _verdict(res)
        if st == "pass":
            wit = S.invoke_op("getWorkItemTypes", env=env)
            body = str(wit.get("body"))
            st = "pass" if at_id in body else "fail"
            detail = "in getWorkItemTypes" if at_id in body else "created but not listed"
        _record(bucket, "AlertType.lifecycle", st, detail)
    except Exception as e:  # noqa: BLE001
        _record(bucket, "AlertType.lifecycle", "error", "exception: %s" % e)
    finally:
        try:
            S.designer_remove_object("AlertType", at_id, env=env)
        except Exception:  # noqa: BLE001
            pass

    # -- DrillDownQuery: create -> runDDQ -> remove ---------------------------
    try:
        res = S.create_drill_down_query(
            ddq_id, "select 1 as one", name=ddq_id, connection_id=-1,
            column_names="one", web_accessible=True, env=env)
        st, detail = _verdict(res)
        if st == "pass":
            run = S.invoke_op("runDDQ", params={"ddqIdentifier": ddq_id,
                                                "maxNumOfRows": 5, "startIndex": 0,
                                                "timeoutInSeconds": 30}, env=env)
            st, detail = _verdict(run)
        _record(bucket, "DrillDownQuery.lifecycle", st, detail)
    except Exception as e:  # noqa: BLE001
        _record(bucket, "DrillDownQuery.lifecycle", "error", "exception: %s" % e)
    finally:
        try:
            S.designer_remove_object("DrillDownQuery", ddq_id, env=env)
        except Exception:  # noqa: BLE001
            pass

    # -- BusinessUnit (curated SOAP): create -> get -> remove ----------------
    # RCMBusinessUnitService: addBusinessUnit -> getBusinessUnitByIdentifier ->
    # removeBusinessUnit (grounded: Implementer Guide "Web Services for Business
    # Unit Management"). bu.remove keys on the numeric id, so read it from bu.get.
    bu_numeric = None
    try:
        res = S.invoke_soap_operation("bu.create", params={
            "identifier": bu_id, "name": bu_id, "description": "smoke"}, env=env)
        st, detail = _verdict(res)
        if st == "pass":
            got = S.invoke_soap_operation("bu.get",
                                          params={"businessUnitIdentifier": bu_id}, env=env)
            rec = (got.get("records") or [None])[0] if isinstance(got, dict) else None
            if isinstance(rec, dict) and rec.get("identifier") == bu_id:
                bu_numeric = rec.get("id")
                st, detail = "pass", "created + fetched (id=%s)" % bu_numeric
            else:
                st, detail = "fail", "created but not returned by bu.get"
        _record(bucket, "BusinessUnit.lifecycle", st, detail)
    except Exception as e:  # noqa: BLE001
        _record(bucket, "BusinessUnit.lifecycle", "error", "exception: %s" % e)
    finally:
        try:
            S.invoke_soap_operation("bu.remove",
                                    params={"businessUnitId": bu_numeric or bu_id}, env=env)
        except Exception:  # noqa: BLE001
            pass

    # -- Generic engine (clone): create a DDQ -> clone it -> verify -> remove -
    # Exercises the generic create_object path (designer_clone_object fetches the
    # source and re-creates it under a new id) — the verb behind 100+ types.
    src_id = "AW_SMOKE_SRC_%d" % ts
    try:
        seed = S.create_drill_down_query(
            src_id, "select 1 as one", name=src_id, connection_id=-1,
            column_names="one", web_accessible=True, env=env)
        st, detail = _verdict(seed)
        if st == "pass":
            cl = S.designer_clone_object("DrillDownQuery", src_id, clone_id, env=env)
            st, detail = _verdict(cl)
            if st == "pass":
                got = S.designer_get_object("DrillDownQuery", clone_id, env=env)
                ok = isinstance(got, dict) and not got.get("error") and \
                    clone_id in str(got)
                st = "pass" if ok else "fail"
                detail = "clone fetched" if ok else "cloned but not retrievable"
        _record(bucket, "DrillDownQuery.clone.lifecycle", st, detail)
    except Exception as e:  # noqa: BLE001
        _record(bucket, "DrillDownQuery.clone.lifecycle", "error", "exception: %s" % e)
    finally:
        for ident in (clone_id, src_id):
            try:
                S.designer_remove_object("DrillDownQuery", ident, env=env)
            except Exception:  # noqa: BLE001
                pass
    return bucket


# --------------------------------------------------------------------------- #
# write-gating sweep (opt-in; NO side effects — proves every write op is gated)
# --------------------------------------------------------------------------- #
def smoke_write_gating(S, ro_env: str, limit: Optional[int] = None) -> dict:
    """Assert that every write op we expose is REFUSED when the env forbids writes.

    ``ro_env`` must be a profile with ``allow_writes: false``. The gate fires
    offline (``precheck`` / ``_designer_write_guard`` return before any login), so
    this validates the protection — and the read/write classification — of every
    REST write, curated-SOAP write, and SOAP-catalog write without touching server
    state. A ``fail`` here is a gate leak or a misclassified write."""
    bucket = _new_bucket()

    # REST writes via invoke_op
    reg = S._reg()
    n = 0
    for op in sorted((o for o in reg.ops.values() if not o["read"]),
                     key=lambda o: o["operationId"]):
        if limit and n >= limit:
            break
        n += 1
        try:
            res = S.invoke_op(op["operationId"], env=ro_env)
        except Exception as e:  # noqa: BLE001
            _record(bucket, "rest:%s" % op["operationId"], "error", "exception: %s" % e)
            continue
        _record(bucket, "rest:%s" % op["operationId"], *_gate_verdict(res))

    # curated SOAP writes via invoke_soap_operation
    from actone.soap import SOAP_OPS
    for op_id, spec in sorted(SOAP_OPS.items()):
        if spec.get("access") != "write":
            continue
        try:
            res = S.invoke_soap_operation(op_id, env=ro_env)
        except Exception as e:  # noqa: BLE001
            _record(bucket, "soap:%s" % op_id, "error", "exception: %s" % e)
            continue
        _record(bucket, "soap:%s" % op_id, *_gate_verdict(res))

    # full SOAP catalog writes via designer_call_operation
    from actone.soap_catalog import load_catalog, operation_access
    cat = load_catalog()
    m = 0
    for svc in cat.services:
        service = svc.get("name")
        ops = svc.get("operations", [])
        items = ops if isinstance(ops, list) else [dict(v, name=k) for k, v in ops.items()]
        for op in sorted(items, key=lambda o: o.get("name") or ""):
            name = op.get("name") or ""
            if operation_access(name) != "write":
                continue
            if limit and m >= limit:
                break
            m += 1
            op_id = "catalog:%s.%s" % (service, name)
            try:
                res = S.designer_call_operation(service, name, env=ro_env)
            except Exception as e:  # noqa: BLE001
                _record(bucket, op_id, "error", "exception: %s" % e)
                continue
            _record(bucket, op_id, *_gate_verdict(res))
    return bucket


# --------------------------------------------------------------------------- #
# orchestrator
# --------------------------------------------------------------------------- #
def run_smoke(env: Optional[str] = None, rest: bool = True, soap: bool = True,
              catalog: bool = True, fixtures: Optional[dict] = None,
              write: bool = False, workflow: str = "workflow1",
              limit: Optional[int] = None, autofixtures: bool = True,
              gating: bool = False, ro_env: Optional[str] = None) -> dict:
    """Run the smoke suite and return a structured report.

    Drives ``actone_mcp.server`` tool functions directly. ``fixtures`` supplies
    values for path/query params (e.g. ``{"workItemTypeIdentifier": "..."}``) so
    reads that need an id can also run; when ``autofixtures`` is set they are
    merged UNDER any explicit ``fixtures`` (explicit wins) after being discovered
    from the live env. ``gating`` runs the write-refusal sweep against ``ro_env``
    (a profile with ``allow_writes: false``)."""
    from actone_mcp import server as S

    fixtures = dict(fixtures or {})
    if autofixtures:
        auto = _autofixtures(S, env)
        merged = {**auto, **fixtures}  # explicit fixtures win over discovered
        fixtures = merged
    report: dict = {"env": env or "default", "fixtures": sorted(fixtures.keys()),
                    "surfaces": {}}
    if rest:
        report["surfaces"]["rest"] = smoke_rest(S, env, fixtures, limit)
    if soap:
        report["surfaces"]["soap_curated"] = smoke_soap_curated(S, env, fixtures)
    if catalog:
        report["surfaces"]["soap_catalog"] = smoke_soap_catalog(S, env, limit)
    if write:
        report["surfaces"]["designer_write"] = smoke_designer_write(S, env, workflow)
    if gating:
        if not ro_env:
            report["surfaces"]["write_gating"] = {
                "results": [{"op": "write_gating", "status": "error",
                             "detail": "gating requires a read-only ro_env "
                                       "(a profile with allow_writes: false)"}],
                "pass": 0, "fail": 0, "error": 1, "skip": 0}
        else:
            report["surfaces"]["write_gating"] = smoke_write_gating(S, ro_env, limit)

    totals = {"pass": 0, "fail": 0, "error": 0, "skip": 0}
    for b in report["surfaces"].values():
        for k in totals:
            totals[k] += b.get(k, 0)
    report["totals"] = totals
    report["failures"] = [
        {"surface": sname, **r}
        for sname, b in report["surfaces"].items()
        for r in b["results"] if r["status"] in ("fail", "error")
    ]
    return report
