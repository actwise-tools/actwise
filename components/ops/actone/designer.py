#!/usr/bin/env python
"""
designer.py — a catalog-driven, generic SOAP engine for the ActOne **Designer**
config surface (the "ActOne Designer as MCP" capability).

Where soap.py exposes a small *curated* allowlist of Axis operations, this module
turns the whole Designer repository surface into generic, schema-driven operations:

    get_object_info_list / get_object_list / get_object   (read)
    add_object / create_object / update_object / remove_object / clone_object  (write)
    validate_object / get_remove_constraints / order_objects
    call_operation                                         (generic escape hatch)

It is driven by the SOAP catalog (soap_catalog.SoapCatalog): object types carry a
``createPath`` (generic ``designerRepositoryService.addObject`` or a dedicated op)
and a payload ``bean``; the bean's ``flattenedFields`` are serialized into the
RPC/encoded envelope. This is a Python port of rcm-designer-mcp's DesignerService +
GeneratedTools serializer, reusing ActWise Ops' authenticated session, write gate,
and session self-heal.

Transport reuses SoapClient.invoke_raw (soap.py) so there is one authenticated
session and one 401/403 self-heal path. Responses (Axis 1.x multiRef graphs) are
inlined and rendered to plain JSON-friendly dicts.

The DDQ (Drill Down Query) create is a first vertical slice: ``create_object(
"DrillDownQuery", {...})`` builds a DrillDownQuery bean and adds it.

defusedxml for parsing (XXE-safe), matching the rest of the package.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape as _xml_escape

from defusedxml.ElementTree import fromstring as _xml_fromstring
from defusedxml.common import DefusedXmlException

from actone.client import ActOneClient
from actone.soap import SoapClient, SoapError, _local, _is_session_fault
from actone.soap_catalog import SoapCatalog, load_catalog

DESIGNER_SERVICE = "designerRepositoryService"


class DesignerError(SoapError):
    """A Designer SOAP operation failed (transport, fault, or ACMResult status=false)."""


# --------------------------------------------------------------------------- #
# type mapping (ported from rcm-designer-mcp GeneratedTools)
# --------------------------------------------------------------------------- #
def _base_type(java_type: str) -> str:
    return java_type[:-2] if java_type.endswith("[]") else java_type


def _arg_name(field_name: str) -> str:
    # CaseType is the one bean whose fields carry a Java ``m_`` member prefix; the
    # Axis wire element (and our arg key) drops it, matching every other bean.
    if field_name.startswith("m_"):
        return field_name[2:]
    return field_name[1:] if field_name.startswith("_") else field_name


def _xsd_type(java_type: str) -> str | None:
    """xsd:* local name for a scalar Java type; None = complex (nested bean)."""
    m = {
        "String": "string",
        "int": "int", "Integer": "int",
        "long": "long", "Long": "long",
        "short": "short", "Short": "short",
        "boolean": "boolean", "Boolean": "boolean",
        "double": "double", "Double": "double",
        "float": "float", "Float": "float",
    }
    if java_type in m:
        return m[java_type]
    return "string" if java_type.endswith("Enum") else None


def _scalar_json_type(java_type: str) -> str | None:
    m = {
        "String": "string",
        "int": "integer", "long": "integer", "Integer": "integer", "Long": "integer",
        "short": "integer", "Short": "integer",
        "boolean": "boolean", "Boolean": "boolean",
        "double": "number", "float": "number", "Double": "number", "Float": "number",
    }
    if java_type in m:
        return m[java_type]
    return "string" if java_type.endswith("Enum") else None


def _esc(s) -> str:
    return _xml_escape("" if s is None else str(s), {'"': "&quot;"})


def _wire(value, xsd: str) -> str:
    """Render a Python value to its XSD lexical form (bool -> true/false)."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return _esc(value)


def _has_object_info(bean: dict) -> bool:
    for f in bean.get("flattenedFields", []) or []:
        if f.get("name") in ("_objectInfo", "objectInfo"):
            return True
    return False


def _object_info_type(catalog: SoapCatalog, type_value: str, bean: dict) -> str:
    """Wire type for objectInfo: an explicit override on the type entry, else the
    declared objectInfo field type, else ACMObjectInfo (mirrors GeneratedTools)."""
    t = catalog.find_type(type_value)
    if t and t.get("objectInfoBean"):
        return t["objectInfoBean"]
    for f in bean.get("flattenedFields", []) or []:
        if f.get("name") in ("_objectInfo", "objectInfo") and f.get("type"):
            return f["type"]
    return "ACMObjectInfo"


# --------------------------------------------------------------------------- #
# bean serialization (ported from GeneratedTools.serializeFields/executeCreate)
# --------------------------------------------------------------------------- #
def _serialize_fields(catalog: SoapCatalog, bean: dict, args: dict, root: bool) -> str:
    """Serialize a bean's flattenedFields from ``args`` into RPC/encoded SOAP XML."""
    root_identity = root and _has_object_info(bean)
    parts: list[str] = []
    for f in bean.get("flattenedFields", []) or []:
        field = _arg_name(f.get("name", ""))
        jtype = f.get("type", "")
        is_array = jtype.endswith("[]")
        base = _base_type(jtype)

        if root_identity and field in ("identifier", "name", "description", "objectInfo"):
            continue  # emitted in the objectInfo block

        xsd = _xsd_type(base)
        value = args.get(field)

        # scalar
        if xsd is not None and not is_array:
            is_enum = base.endswith("Enum")
            if value is None or str(value) == "":
                if field == "id" and base in ("int", "long"):
                    parts.append('<id xsi:type="xsd:%s">-1</id>' % base)
                if base == "UpdatableEnum":
                    parts.append('<%s xsi:type="urn:UpdatableEnum">Updatable</%s>' % (field, field))
                continue
            xsi = ("urn:%s" % base) if is_enum else ("xsd:%s" % xsd)
            parts.append('<%s xsi:type="%s">%s</%s>' % (field, xsi, _wire(value, xsd), field))
            continue

        # array of scalars
        if xsd is not None and is_array:
            if isinstance(value, list) and value:
                parts.append('<%s soapenc:arrayType="xsd:%s[%d]" xsi:type="soapenc:Array">'
                             % (field, xsd, len(value)))
                for it in value:
                    parts.append('<item xsi:type="xsd:%s">%s</item>' % (xsd, _wire(it, xsd)))
                parts.append("</%s>" % field)
            else:
                _append_raw_fallback(parts, args, field)
            continue

        # complex (nested bean or array of beans)
        nested = catalog.find_bean(base)
        if nested is not None and value is not None:
            if is_array and isinstance(value, list):
                parts.append('<%s soapenc:arrayType="urn:%s[%d]" xsi:type="soapenc:Array">'
                             % (field, base, len(value)))
                for it in value:
                    if not isinstance(it, dict):
                        raise DesignerError(
                            "each element of %r must be an object (%s)" % (field, base))
                    parts.append('<item xsi:type="urn:%s">' % base)
                    parts.append(_serialize_fields(catalog, nested, it, False))
                    parts.append("</item>")
                parts.append("</%s>" % field)
            elif not is_array and isinstance(value, dict):
                parts.append('<%s xsi:type="urn:%s">' % (field, base))
                parts.append(_serialize_fields(catalog, nested, value, False))
                parts.append("</%s>" % field)
            else:
                _append_raw_fallback(parts, args, field)
        else:
            _append_raw_fallback(parts, args, field)
    return "".join(parts)


def _append_raw_fallback(parts: list[str], args: dict, field: str) -> None:
    raw = args.get(field + "_xml")
    if raw is not None and str(raw).strip():
        parts.append(str(raw))


def _dedicated_create_path(type_entry: dict) -> dict | None:
    """First dedicated (non-generic) create path with a payload bean, or None."""
    for p in type_entry.get("createPaths", []) or []:
        if p.get("via") == "dedicated" and p.get("bean"):
            return p
    return None


def normalize_ddq_fields(fields: dict) -> dict:
    """Fill the DrillDownQuery result-display fields the server dereferences at
    runtime but that no caller reliably sets.

    ``rowFormat`` (Integer) and ``sortable`` (Boolean) are dereferenced by the
    server's ``DrillDownQueryData`` ctor and make ``runDDQ`` NPE if null;
    ``columnWidths`` must have the same element count as ``columnNames`` or Designer
    marks the object Invalid ("Display columns width is not specified"). These are
    the "Result Display" tab a human always fills. Applied centrally so every
    caller (CLI, MCP, generic create) is safe; explicit values pass through
    untouched. Returns the same dict (mutated) for convenience."""
    fields.setdefault("rowFormat", 0)
    fields.setdefault("sortable", False)
    cols = [c for c in str(fields.get("columnNames", "")).split(",") if c.strip()]
    if cols and not str(fields.get("columnWidths", "")).strip():
        fields["columnWidths"] = ",".join(["100"] * len(cols))
    return fields


def build_object_xml(catalog: SoapCatalog, type_value: str, args: dict,
                     param_name: str = "newObject", path: dict | None = None) -> str:
    """Build the RPC/encoded ``<newObject xsi:type="urn:Bean">`` payload for a
    Designer-creatable object type from a flat ``args`` dict (bean fields; nested
    beans as dict/list; identifier/name/description surface objectInfo).

    ``path`` overrides the create path (else the generic addObject path is used);
    pass a dedicated create path for beans the generic handler can't accept."""
    t = catalog.find_type(type_value)
    if not t:
        raise DesignerError("unknown object type %r (see search_object_types)" % type_value)
    if path is None:
        path = catalog.pick_create_path(t)
    if not path:
        raise DesignerError("object type %r has no usable create path/bean" % type_value)
    bean = catalog.find_bean(path.get("bean"))
    if not bean:
        raise DesignerError("create bean %r for %r not found in catalog"
                            % (path.get("bean"), type_value))
    wire_bean = path.get("wireBean") or bean["name"]
    service = path.get("op", DESIGNER_SERVICE + ".addObject").split(".")[0]

    xml = [
        '<%s xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'
        ' xmlns:xsd="http://www.w3.org/2001/XMLSchema"'
        ' xmlns:soapenc="http://schemas.xmlsoap.org/soap/encoding/"'
        ' xmlns:urn="urn:%s" xsi:type="urn:%s">' % (param_name, service, wire_bean)
    ]

    if _has_object_info(bean):
        identifier = args.get("identifier")
        if identifier is not None and str(identifier).strip():
            name = args.get("name", identifier)
            info_type = _object_info_type(catalog, type_value, bean)
            xml.append('<objectInfo xsi:type="urn:%s">' % info_type)
            xml.append('<identifier xsi:type="xsd:string">%s</identifier>' % _esc(identifier))
            xml.append('<name xsi:type="xsd:string">%s</name>' % _esc(name))
            xml.append('<description xsi:type="xsd:string">%s</description>'
                       % _esc(args.get("description", "")))
            # -1 sentinel: some handlers dereference objectInfo.id even on create
            xml.append('<id xsi:type="xsd:long">-1</id>')
            xml.append('<type xsi:type="xsd:string">%s</type>' % _esc(type_value))
            _append_info_subtype_fields(catalog, xml, info_type, args, name)
            xml.append("</objectInfo>")

    xml.append(_serialize_fields(catalog, bean, args, root=True))
    xml.append("</%s>" % param_name)
    return "".join(xml)


def _append_info_subtype_fields(catalog: SoapCatalog, xml: list[str], info_type: str,
                                args: dict, name) -> None:
    info_bean = catalog.find_bean(info_type)
    if not info_bean:
        return
    base_fields = {"id", "identifier", "type", "name", "description"}
    for f in info_bean.get("flattenedFields", []) or []:
        field = _arg_name(f.get("name", ""))
        ftype = f.get("type", "")
        if field in base_fields or ftype.endswith("[]"):
            continue
        xsd = _xsd_type(ftype)
        if xsd is None:
            continue
        value = args.get(field)
        if value is None and field == "shortName":
            value = name
        if value is None or str(value) == "":
            continue
        xsi = ("urn:%s" % ftype) if ftype.endswith("Enum") else ("xsd:%s" % xsd)
        xml.append('<%s xsi:type="%s">%s</%s>' % (field, xsi, _wire(value, xsd), field))


# --------------------------------------------------------------------------- #
# response parsing (Axis multiRef graph -> plain dict)
# --------------------------------------------------------------------------- #
_XSI_TYPE = "{http://www.w3.org/2001/XMLSchema-instance}type"
_XSI_NIL = "{http://www.w3.org/2001/XMLSchema-instance}nil"


def _href(el: ET.Element) -> str | None:
    for k, v in el.attrib.items():
        if _local(k) == "href" and v.startswith("#"):
            return v[1:]
    return None


def _collect_event_messages(el: ET.Element, pool: dict,
                            seen: frozenset = frozenset()) -> list[str]:
    """Collect ``eventMessage`` texts under an element, following Axis multiRef
    hrefs into the pool (LogMessage entries are usually referenced, not inline)."""
    ref = _href(el)
    if ref is not None:
        if ref in seen or ref not in pool:
            return []
        return _collect_event_messages(pool[ref], pool, seen | {ref})
    if _local(el.tag) == "eventMessage":
        txt = "".join(el.itertext()).strip()
        return [txt] if txt else []
    out: list[str] = []
    for c in el:
        if isinstance(c.tag, str):
            out.extend(_collect_event_messages(c, pool, seen))
    return out


def _to_obj(el: ET.Element, pool: dict, seen: frozenset = frozenset()):
    """Render an element (resolving Axis multiRef hrefs) into a JSON-friendly value."""
    ref = _href(el)
    if ref is not None:
        if ref in seen or ref not in pool:
            return {"@ref": ref}
        return _to_obj(pool[ref], pool, seen | {ref})

    children = [c for c in el if isinstance(c.tag, str)]
    if not children:
        if el.get(_XSI_NIL) in ("true", "1"):
            return None
        return (el.text or "").strip()

    # Axis encodes arrays as a container whose children are all <item> — render
    # those as a JSON list.
    if all(_local(c.tag) == "item" for c in children):
        return [_to_obj(c, pool, seen) for c in children]

    # group by local name to detect repeats (collections without item wrappers)
    groups: dict[str, list[ET.Element]] = {}
    order: list[str] = []
    for c in children:
        name = _local(c.tag)
        if name not in groups:
            groups[name] = []
            order.append(name)
        groups[name].append(c)

    obj: dict = {}
    xtype = el.get(_XSI_TYPE)
    if xtype:
        lt = _local(xtype)
        if not lt.startswith(("xsd", "soapenc")) and lt not in ("string", "int", "long", "boolean"):
            obj["@type"] = lt
    for name in order:
        items = groups[name]
        if len(items) == 1:
            obj[name] = _to_obj(items[0], pool, seen)
        else:
            obj[name] = [_to_obj(it, pool, seen) for it in items]
    return obj


def _parse(raw: str, operation: str, out_param: str | None) -> dict:
    """Parse a designer SOAP response. Returns dict with ok/status/messages and,
    when ``out_param`` is given, ``out`` = that resolved out parameter."""
    result: dict = {"operation": operation, "ok": None, "status": None,
                    "messages": [], "out": None}
    try:
        root = _xml_fromstring(raw)
    except (ET.ParseError, DefusedXmlException):
        result["ok"] = False
        result["messages"].append("unparseable SOAP response")
        result["raw"] = raw[:800]
        return result

    body = None
    for el in root.iter():
        if _local(el.tag) == "Body":
            body = el
            break
    if body is None:
        result["ok"] = False
        result["messages"].append("no SOAP Body")
        result["raw"] = raw[:800]
        return result

    # Fault?
    for el in body.iter():
        if _local(el.tag) == "Fault":
            fs = el.find(".//faultstring")
            result["ok"] = False
            result["messages"].append((fs.text if fs is not None else "SOAP Fault") or "SOAP Fault")
            result["raw"] = raw[:800]
            return result

    children = [c for c in body if isinstance(c.tag, str)]
    pool = {}
    resp = None
    for c in children:
        if _local(c.tag) == "multiRef":
            for k, v in c.attrib.items():
                if _local(k) == "id":
                    pool[v] = c
        elif resp is None:
            resp = c
    if resp is None:
        result["ok"] = True
        return result

    # ACMResult status + messages. In Axis RPC/encoded responses the ACMResult
    # is usually a <multiRef> referenced by href, so scan the resp *and* the pool.
    scan = [resp, *pool.values()]
    for holder in scan:
        for el in holder.iter():
            xt = el.get(_XSI_TYPE)
            if xt and _local(xt) == "ACMResult":
                for child in el:
                    cn = _local(child.tag)
                    if cn == "status":
                        result["status"] = (child.text or "").strip().lower() == "true"
                    elif cn == "messageList":
                        for txt in _collect_event_messages(child, pool):
                            if txt not in result["messages"]:
                                result["messages"].append(txt)

    if out_param:
        for c in resp:
            if _local(c.tag) == out_param:
                result["out"] = _to_obj(c, pool)
                break

    result["ok"] = result["status"] if result["status"] is not None else True
    return result


# --------------------------------------------------------------------------- #
# engine
# --------------------------------------------------------------------------- #
class DesignerClient:
    """Generic, catalog-driven Designer SOAP client bound to an authenticated
    ``ActOneClient`` (reuses the REST login's session, like soap.SoapClient)."""

    def __init__(self, client: ActOneClient, catalog: SoapCatalog | None = None):
        self._soap = SoapClient(client)
        self.catalog = catalog or load_catalog()

    # -- transport with in-body session self-heal ---------------------------
    def _call(self, service: str, operation: str, inner_xml: str,
              out_param: str | None) -> dict:
        raw = self._soap.invoke_raw(service, operation, inner_xml)
        res = _parse(raw, operation, out_param)
        if res.get("ok") is False and _is_session_fault(res.get("messages")):
            self._soap._c.relogin()
            raw = self._soap.invoke_raw(service, operation, inner_xml)
            res = _parse(raw, operation, out_param)
        if res.get("ok") is False:
            raise DesignerError("; ".join(res.get("messages") or
                                          ["%s failed" % operation]))
        return res

    @staticmethod
    def _identification(param: str, type_value: str, identifier: str) -> str:
        return ('<%s xsi:type="urn:ACMObjectIdentification">'
                '<identifier xsi:type="xsd:string">%s</identifier>'
                '<type xsi:type="xsd:string">%s</type>'
                '</%s>' % (param, _esc(identifier), _esc(type_value), param))

    # -- reads --------------------------------------------------------------
    def get_object_info_list(self, type_value: str) -> dict:
        """Lightweight listing (identifiers + names) for a Designer object type."""
        inner = '<type xsi:type="xsd:string">%s</type>' % _esc(type_value)
        return self._call(DESIGNER_SERVICE, "getObjectInfoList", inner, "objectInfoArray")

    def get_object_list(self, type_value: str) -> dict:
        """Full object list for a Designer object type."""
        inner = '<type xsi:type="xsd:string">%s</type>' % _esc(type_value)
        return self._call(DESIGNER_SERVICE, "getObjectList", inner, "objectArray")

    def get_object(self, type_value: str, identifier: str) -> dict:
        """One object by type + identifier (resolved to a plain dict)."""
        inner = self._identification("objectIdentification", type_value, identifier)
        return self._call(DESIGNER_SERVICE, "getObject", inner, "returnObject")

    def get_remove_constraints(self, type_value: str, identifier: str) -> dict:
        """Dependencies that would block/accompany a delete."""
        inner = self._identification("objId", type_value, identifier)
        return self._call(DESIGNER_SERVICE, "getRemoveConstraints", inner, "constraintsHolder")

    # -- writes -------------------------------------------------------------
    def add_object(self, object_xml: str) -> dict:
        """Add a pre-built ``<newObject>`` payload; returns the new identification."""
        return self._call(DESIGNER_SERVICE, "addObject", object_xml, "objectIdentification")

    def create_object(self, type_value: str, fields: dict) -> dict:
        """Build a Designer-creatable object from ``fields`` and add it.

        ``fields`` are the bean's flattened fields; ``identifier``/``name``/
        ``description`` populate objectInfo. Returns the new identification dict.

        The generic ``addObject`` handler only accepts objectInfo-style beans; a
        creatable type whose generic bean has no ``objectInfo`` (e.g. CaseType) is
        routed to its dedicated create op instead."""
        if type_value == "DrillDownQuery":
            fields = normalize_ddq_fields(dict(fields))
        t = self.catalog.find_type(type_value)
        path = self.catalog.pick_create_path(t) if t else None
        if path and path.get("via") == "generic":
            bean = self.catalog.find_bean(path.get("bean"))
            if bean and not _has_object_info(bean):
                dedicated = _dedicated_create_path(t)
                if dedicated:
                    return self._create_via_op(type_value, dedicated, fields)
        xml = build_object_xml(self.catalog, type_value, fields)
        return self.add_object(xml)

    def _create_via_op(self, type_value: str, path: dict, fields: dict) -> dict:
        """Create through a dedicated add op (e.g. ``caseDesignService.addCaseType``)
        for beans the generic ``addObject`` handler can't deserialize."""
        service, operation = path["op"].split(".", 1)
        op = self.catalog.find_operation(service, operation)
        param = next((p.get("name") for p in (op or {}).get("parameters", [])
                      if p.get("mode") == "in"), "arg0")
        out_param = next((p.get("name") for p in (op or {}).get("parameters", [])
                          if p.get("mode") == "out"), None)
        xml = build_object_xml(self.catalog, type_value, fields,
                               param_name=param, path=path)
        return self._call(service, operation, xml, out_param)

    def clone_object(self, type_value: str, source_identifier: str,
                     new_identifier: str, overrides: dict | None = None) -> dict:
        """Create a copy of an existing object under a new identifier.

        Fetches the source, flattens its objectInfo identity, drops the internal
        id, applies ``overrides``, and creates the copy. Referenced objects (FKs)
        are copied by identifier, so they must already exist on the target."""
        obj = self.get_object(type_value, source_identifier).get("out")
        if not isinstance(obj, dict):
            raise DesignerError("cannot clone %r/%r: source not found"
                                % (type_value, source_identifier))
        fields = {k: v for k, v in obj.items() if k not in ("@type", "objectInfo", "id")}
        info = obj.get("objectInfo") if isinstance(obj.get("objectInfo"), dict) else {}
        fields["identifier"] = new_identifier
        # Default the copy's name to the new identifier, not the source name:
        # many types (e.g. AlertType) enforce a UNIQUE name, so copying the
        # source name verbatim would always collide. Override with --overrides.
        fields["name"] = new_identifier
        fields["description"] = info.get("description", "")
        if overrides:
            fields.update(overrides)
        return self.create_object(type_value, fields)

    def update_object(self, type_value: str, identifier: str, object_xml: str) -> dict:
        """Save a modified object payload (identification + updatedObject)."""
        inner = (self._identification("objectIdentification", type_value, identifier)
                 + _rename_root(object_xml, "updatedObject"))
        return self._call(DESIGNER_SERVICE, "updateObject", inner, None)

    def remove_object(self, type_value: str, identifier: str) -> dict:
        """Remove an object by type + identifier."""
        inner = self._identification("objectIdentification", type_value, identifier)
        return self._call(DESIGNER_SERVICE, "removeObject", inner, None)

    def validate_object(self, type_value: str, identifier: str, object_xml: str) -> dict:
        """Server-side validation without saving; ``messages`` empty = valid."""
        inner = (self._identification("objectIdentification", type_value, identifier)
                 + _rename_root(object_xml, "validatedObject"))
        res = self._call(DESIGNER_SERVICE, "validateObject", inner, None)
        return res

    def validate_fields(self, type_value: str, fields: dict) -> dict:
        """Validate the object we WOULD create from ``fields`` — builds the same
        payload as :meth:`create_object` but routes it through ``validateObject``
        (a read; nothing is saved). ``messages`` empty = valid.

        The generic ``validateObject`` handler only accepts objectInfo-style
        beans (the same shape ``addObject`` requires). A type whose generic bean
        has no ``objectInfo`` (e.g. CaseType) has no server-side validate op, so
        we raise rather than send a payload the server will reject with a
        SAXException."""
        if type_value == "DrillDownQuery":
            fields = normalize_ddq_fields(dict(fields))
        t = self.catalog.find_type(type_value)
        path = self.catalog.pick_create_path(t) if t else None
        if path and path.get("via") == "generic":
            bean = self.catalog.find_bean(path.get("bean"))
            if bean and not _has_object_info(bean) and _dedicated_create_path(t):
                raise DesignerError(
                    "server-side validation is not available for %r: it has no "
                    "generic objectInfo bean and the SOAP API exposes no dedicated "
                    "validate op. Validation happens at create time instead."
                    % type_value)
        xml = build_object_xml(self.catalog, type_value, fields)
        return self.validate_object(type_value, str(fields.get("identifier", "")), xml)

    def order_objects(self, type_value: str, identifiers: list[str]) -> dict:
        """Persist the display order of a type's objects (pass ALL identifiers)."""
        items = "".join(
            '<item xsi:type="urn:ACMObjectIdentification">'
            '<identifier xsi:type="xsd:string">%s</identifier>'
            '<type xsi:type="xsd:string">%s</type></item>'
            % (_esc(i), _esc(type_value)) for i in identifiers)
        inner = ('<objectIdentifications xsi:type="soapenc:Array"'
                 ' soapenc:arrayType="urn:ACMObjectIdentification[%d]">%s'
                 '</objectIdentifications>' % (len(identifiers), items))
        return self._call(DESIGNER_SERVICE, "orderObjects", inner, None)

    # -- generic escape hatch ----------------------------------------------
    def call_operation(self, service: str, operation: str, inner_xml: str = "",
                       out_param: str | None = None) -> dict:
        """Invoke any catalog operation on any service with a raw inner-XML param
        list. For operations not covered by the typed helpers above."""
        return self._call(service, operation, inner_xml, out_param)


def _rename_root(object_xml: str, param_name: str) -> str:
    """Re-wrap a caller-provided object element (e.g. from get_object round-trip)
    under the required RPC parameter name, preserving the root's attributes
    (xsi:type etc.) and children verbatim by renaming only the root tag."""
    import re
    m = re.match(r"\s*<([\w:.\-]+)", object_xml)
    if not m:
        raise DesignerError("object_xml is not well-formed XML (no root element)")
    old = m.group(1)
    opened = re.sub(r"^(\s*)<" + re.escape(old),
                    lambda mo: mo.group(1) + "<" + param_name, object_xml, count=1)
    close = "</" + old + ">"
    idx = opened.rfind(close)
    if idx == -1:
        # self-closing root: <old .../>
        sc = re.search(r"/>\s*$", opened)
        if sc:
            return opened
        raise DesignerError("object_xml root element %r is not closed" % old)
    return opened[:idx] + "</" + param_name + ">" + opened[idx + len(close):]
