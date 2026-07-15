#!/usr/bin/env python
"""
soap.py — a small, curated SOAP client for the ActOne legacy Axis web services.

Complements the Extend REST client (client.py): the REST API is the runtime
integration surface, while the SOAP services at ``/RCM/services`` cover the
**admin / design-time** surface the REST API does not — notably creating a
**Business Unit** (there is no create-BU REST op), which is the gate to seeding
work items on a fresh instance.

Key fact that makes this cheap: the **REST login's ``JSESSIONID`` cookie already
unlocks the SOAP services**. So this module reuses an authenticated
``ActOneClient`` (its cookie jar + opener + CSRF) rather than doing a separate
SOAP login. Envelopes are RPC/encoded (the style ActOne's Axis services use).

Scope is deliberately **curated**, not a full WSDL-driven registry: only a small
allowlist of verified operations is exposed (see ``SOAP_OPS``), each classified
read/write so it inherits the same write-gate as the REST ops. A full
WSDL-introspecting SOAP registry for all 21 deployed services is a documented
future item (see docs/components/ops/2026-07-10-actone-soap-services.md).

Stdlib only (urllib + xml.etree), matching the rest of the package.
"""
from __future__ import annotations

import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

from actone.client import ActOneClient


class SoapError(Exception):
    pass


# ── curated operation allowlist ──────────────────────────────────────────────
# Each op: service + operation (Axis local name) + access (read|write) + a param
# spec (name -> {type, required}) and, for struct-bodied ops, a `struct` wrapper.
# Verified live against a 10.2 instance's businessUnitService.
SOAP_OPS: dict[str, dict] = {
    "bu.list": {
        "service": "businessUnitService",
        "operation": "getAllBusinessUnits",
        "access": "read",
        "summary": "List all business units.",
        "params": {},
    },
    "bu.get": {
        "service": "businessUnitService",
        "operation": "getBusinessUnitByIdentifier",
        "access": "read",
        "summary": "Get one business unit by its identifier.",
        "params": {
            "businessUnitIdentifier": {"type": "xsd:string", "required": True},
        },
    },
    "bu.create": {
        "service": "businessUnitService",
        "operation": "addBusinessUnit",
        "access": "write",
        "summary": "Create a business unit (returns the new numeric id). "
                   "Unblocks seeding work items via the REST addWorkItem op.",
        "struct": {
            "part": "businessUnit",
            "type": "BusinessUnit",
            "fields": {
                "id": {"type": "xsd:int", "required": False, "default": "0"},
                "identifier": {"type": "xsd:string", "required": True},
                "name": {"type": "xsd:string", "required": True},
                "description": {"type": "xsd:string", "required": False},
            },
        },
        "params": {
            "identifier": {"type": "xsd:string", "required": True},
            "name": {"type": "xsd:string", "required": True},
            "description": {"type": "xsd:string", "required": False},
        },
    },
    "bu.remove": {
        "service": "businessUnitService",
        "operation": "removeBusinessUnit",
        "access": "write",
        "summary": "Remove a business unit by its numeric id (see bu.list to find the id).",
        "params": {
            "businessUnitId": {"type": "xsd:int", "required": True},
        },
    },
}


def list_operations() -> list[dict]:
    """Curated SOAP ops (offline) — id, service, operation, access, summary, params."""
    out = []
    for op_id, spec in SOAP_OPS.items():
        out.append({
            "operationId": op_id,
            "service": spec["service"],
            "operation": spec["operation"],
            "access": spec["access"],
            "summary": spec["summary"],
            "params": {k: v for k, v in spec.get("params", {}).items()},
        })
    return out


def describe_operation(op_id: str) -> dict | None:
    spec = SOAP_OPS.get(op_id)
    if not spec:
        return None
    return {
        "operationId": op_id,
        "service": spec["service"],
        "operation": spec["operation"],
        "access": spec["access"],
        "summary": spec["summary"],
        "params": spec.get("params", {}),
    }


class SoapClient:
    """Curated SOAP caller bound to an authenticated ``ActOneClient``.

    Reuses the REST client's cookie jar / opener / CSRF (the JSESSIONID from the
    REST login authorizes the Axis services), so callers just do
    ``ActOneClient(...).login()`` then wrap it here.
    """

    def __init__(self, client: ActOneClient):
        self._c = client

    # -- endpoint / namespace helpers ---------------------------------------
    def _endpoint(self, service: str) -> str:
        return "%s%s/services/%s" % (self._c.base, self._c.ctx, service)

    def _op_ns(self, service: str) -> str:
        # RPC/encoded operation namespace == the per-host WSDL targetNamespace,
        # i.e. the service endpoint URL. Deriving it from the live base URL keeps
        # this correct across environments (each host generates its own WSDL).
        return self._endpoint(service)

    @staticmethod
    def _type_ns(service: str) -> str:
        return "urn:%s" % service

    # -- envelope build ------------------------------------------------------
    @staticmethod
    def _leaf(name: str, value, xtype: str) -> str:
        return '<%s xsi:type="%s">%s</%s>' % (name, xtype, escape(str(value)), name)

    def _build_body(self, spec: dict, args: dict) -> str:
        service = spec["service"]
        op = spec["operation"]
        op_ns = self._op_ns(service)
        type_ns = self._type_ns(service)

        inner = ""
        if "struct" in spec:
            st = spec["struct"]
            fields_xml = ""
            for fname, fspec in st["fields"].items():
                if fname in args and args[fname] is not None:
                    val = args[fname]
                elif "default" in fspec:
                    val = fspec["default"]
                elif fspec.get("required"):
                    raise SoapError("missing required field %r for %s" % (fname, op))
                else:
                    continue
                fields_xml += self._leaf(fname, val, fspec["type"])
            inner = '<%s xsi:type="urn:%s">%s</%s>' % (
                st["part"], st["type"], fields_xml, st["part"])
        else:
            for pname, pspec in spec.get("params", {}).items():
                if pname in args and args[pname] is not None:
                    inner += self._leaf(pname, args[pname], pspec["type"])
                elif pspec.get("required"):
                    raise SoapError("missing required param %r for %s" % (pname, op))

        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"'
            ' xmlns:xsd="http://www.w3.org/2001/XMLSchema"'
            ' xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'
            ' xmlns:api="%s" xmlns:urn="%s">'
            '<soapenv:Body soapenv:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
            '<api:%s>%s</api:%s>'
            '</soapenv:Body></soapenv:Envelope>'
        ) % (op_ns, type_ns, op, inner, op)

    # -- transport -----------------------------------------------------------
    def _post(self, service: str, envelope: str, _retry: bool = True) -> str:
        url = self._endpoint(service)
        req = urllib.request.Request(
            url, data=envelope.encode("utf-8"),
            headers={
                "Content-Type": "text/xml; charset=utf-8",
                "SOAPAction": '""',
                "CSRFTOKEN": self._c.csrf or "",
            },
            method="POST",
        )
        try:
            r = self._c._opener.open(req, timeout=self._c.timeout)
            return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            if _retry and e.code in (401, 403):
                # A long-lived cached client's ActOne session may have timed out
                # ("No Session or a session timeout"); re-login once and retry.
                self._c.relogin()
                return self._post(service, envelope, _retry=False)
            raise SoapError("SOAP HTTP %s: %s" % (e.code, _strip(body)[:400]))
        except Exception as e:  # noqa: BLE001
            raise SoapError("SOAP transport error: %s" % e)

    # -- public --------------------------------------------------------------
    def call(self, op_id: str, args: dict | None = None) -> dict:
        """Invoke a curated SOAP op. Returns a normalized result dict."""
        spec = SOAP_OPS.get(op_id)
        if not spec:
            raise SoapError("unknown SOAP op %r (see list_operations)" % op_id)
        self._c.ensure_login()
        envelope = self._build_body(spec, dict(args or {}))
        raw = self._post(spec["service"], envelope)
        result = _parse_response(op_id, spec["operation"], raw)
        # Some session timeouts surface as an HTTP 200/500 SOAP fault rather than a
        # 401/403; re-login once and retry when the fault names a session timeout.
        if result.get("ok") is False and _is_session_fault(result.get("messages")):
            self._c.relogin()
            raw = self._post(spec["service"], envelope)
            result = _parse_response(op_id, spec["operation"], raw)
        return result


# ── response parsing (RPC/encoded, multiRef) ─────────────────────────────────
def _local(tag: str) -> str:
    """Local name from an ElementTree tag (Clark ``{uri}local``) or a QName
    (``prefix:local`` — the form ``xsi:type`` attribute values use)."""
    if "}" in tag:
        tag = tag.rsplit("}", 1)[-1]
    if ":" in tag:
        tag = tag.rsplit(":", 1)[-1]
    return tag


def _strip(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", html)


def _is_session_fault(messages) -> bool:
    """True when a SOAP fault message indicates an expired/absent session
    (so the caller can re-login once and retry)."""
    blob = " ".join(messages or []).lower()
    return "no session" in blob or "session timeout" in blob \
        or "session has timed out" in blob or "session timed out" in blob


_RECORD_SKIP = {"ACMResult"}  # status wrapper, surfaced separately


def _elem_to_dict(el: ET.Element) -> dict:
    out = {}
    for child in el:
        name = _local(child.tag)
        if list(child):
            out[name] = _elem_to_dict(child)
        else:
            out[name] = (child.text or "").strip()
    return out


def _parse_response(op_id: str, operation: str, raw: str) -> dict:
    result = {
        "operationId": op_id, "operation": operation,
        "ok": None, "status": None, "messages": [], "records": [],
        "result_scalar": None,
    }
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        result["ok"] = False
        result["messages"].append("unparseable SOAP response")
        result["raw"] = raw[:800]
        return result

    # SOAP fault?
    for el in root.iter():
        if _local(el.tag) == "Fault":
            fs = el.find(".//faultstring")
            result["ok"] = False
            result["messages"].append((fs.text if fs is not None else "SOAP Fault") or "SOAP Fault")
            result["raw"] = raw[:800]
            return result

    for el in root.iter():
        name = _local(el.tag)
        xtype = _local(el.get("{http://www.w3.org/2001/XMLSchema-instance}type", "") or "")
        # ACMResult carries status + messageList
        if xtype == "ACMResult":
            for child in el:
                cn = _local(child.tag)
                if cn == "status":
                    result["status"] = (child.text or "").strip().lower() == "true"
                elif cn == "messageList":
                    for m in child:
                        txt = "".join(m.itertext()).strip()
                        if txt:
                            result["messages"].append(txt)
        # record multiRefs (e.g. BusinessUnit)
        elif name == "multiRef" and xtype and xtype not in _RECORD_SKIP:
            rec = _elem_to_dict(el)
            if rec:
                result["records"].append(rec)
        # scalar <result> (e.g. addBusinessUnit returns the new int id)
        elif name == "result" and not list(el) and (el.text or "").strip():
            result["result_scalar"] = el.text.strip()

    # ok: prefer explicit status, else assume true when we got a well-formed body
    result["ok"] = result["status"] if result["status"] is not None else True
    return result
