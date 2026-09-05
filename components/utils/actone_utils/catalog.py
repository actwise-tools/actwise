"""Declarative catalog of ActOne maintenance utilities (C-U).

Each entry describes *one* ActOne ``.bat/.sh`` utility: its script base-name, its
typed parameters, whether it changes state, and the source doc. The runner turns a
catalog entry + user-supplied values into a target argv; the backend runs it.

Discovery mirrors actone-ops:  ``search / list -> describe -> run``.

GROUNDING: every entry and its parameters are verified against the **ActOne 10.2
Implementer Guide** (RCM Utilities / RCM Blotters pages — see each ``doc_url``).
ActOne utilities use the ``-name=value`` flag convention (single dash, ``=``); the
runner renders params accordingly. Shared *Authentication* and *SSL-Related Options*
parameters (documented once and referenced by every utility page) are attached via
the ``_auth()`` / ``_ssl()`` helpers. Unmodelled options can always be passed with
``--arg``. Always review the ``--dry-run`` command before a real run.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

# supported parameter value types.
#   bool -> rendered as ``-name=true`` / ``-name=false`` (e.g. -encrypted=true)
#   flag -> bare presence switch ``-name`` when truthy (e.g. -countinprogress)
PARAM_TYPES = ("str", "int", "date", "enum", "bool", "flag")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TRUE = {"1", "true", "yes", "on"}


@dataclass
class Param:
    name: str
    type: str = "str"
    required: bool = False
    default: Optional[str] = None
    choices: list = field(default_factory=list)   # for type == "enum"
    description: str = ""
    arg: str = ""            # explicit flag; blank -> "--{name-with-dashes}"
    positional: bool = False  # emit value only (ordered), no flag

    @property
    def flag(self) -> str:
        """ActOne convention: single dash + verbatim name (``-acm_nodes``)."""
        return self.arg or ("-" + self.name)

    def coerce(self, value):
        """Validate + normalise a supplied value; raise ValueError on bad input."""
        if self.type == "flag":
            # bare presence switch; absent -> None (omitted), present -> bool
            if value is None:
                return None if self.default is None else (str(self.default).lower() in _TRUE)
            if isinstance(value, bool):
                return value
            return str(value).strip().lower() in _TRUE
        if value is None:
            if self.required and self.default is None:
                raise ValueError(f"missing required parameter '{self.name}'")
            value = self.default
        if value is None:
            return None
        if self.type == "int":
            try:
                return int(value)
            except (TypeError, ValueError):
                raise ValueError(f"parameter '{self.name}' must be an integer, got {value!r}")
        if self.type == "date":
            if not _DATE_RE.match(str(value)):
                raise ValueError(f"parameter '{self.name}' must be YYYY-MM-DD, got {value!r}")
            return str(value)
        if self.type == "bool":
            if isinstance(value, bool):
                return "true" if value else "false"
            return "true" if str(value).strip().lower() in _TRUE else "false"
        if self.type == "enum":
            if str(value) not in self.choices:
                raise ValueError(f"parameter '{self.name}' must be one of "
                                 f"{self.choices}, got {value!r}")
            return str(value)
        return str(value)

    def to_dict(self) -> dict:
        return {"name": self.name, "type": self.type, "required": self.required,
                "default": self.default, "choices": self.choices,
                "description": self.description, "flag": None if self.positional else self.flag,
                "positional": self.positional}


@dataclass
class Utility:
    name: str                 # slug, e.g. "dart-runner"
    title: str
    tool: str                 # script base-name (no extension), e.g. "query_asynch_execution_tool"
    summary: str
    params: list              # list[Param]
    tags: list = field(default_factory=list)
    state_changing: bool = True
    doc_url: str = ""
    notes: str = ""

    def param(self, name: str) -> Optional[Param]:
        return next((p for p in self.params if p.name == name), None)

    def brief(self) -> dict:
        return {"name": self.name, "title": self.title, "tool": self.tool,
                "tags": self.tags, "access": "write" if self.state_changing else "read"}

    def describe(self) -> dict:
        return {"name": self.name, "title": self.title, "tool": self.tool,
                "summary": self.summary, "tags": self.tags,
                "access": "write" if self.state_changing else "read",
                "doc_url": self.doc_url, "notes": self.notes,
                "parameters": [p.to_dict() for p in self.params]}


# --------------------------------------------------------------------------- #
# Seed catalog — parameters verified against the ActOne 10.2 Implementer Guide.
# --------------------------------------------------------------------------- #
_IMPL = "https://docs.niceactimize.com/bundle/Actimize_ActOne_10.2_Implementer_Guide/page/Content/Platform/RCM/"
_UTIL = _IMPL + "RCM_Utilities/"   # RCM Utilities section; per-tool ground truth = shipped <tool>_readme.txt


def _acm(nodes: bool) -> list:
    """The ActOne connection URL parameter (single ``acm`` vs. clustered ``acm_nodes``)."""
    if nodes:
        return [Param("acm_nodes", required=True,
                      description="ActOne application URL; semicolon-separate several nodes for a "
                                  "cluster/load-balanced run (http://n1:8080/acm;http://n2:8080/acm).")]
    return [Param("acm", required=True,
                  description="URL to the ActOne location (e.g. http://host:8080/actimize).")]


def _auth(ntlm: bool = True) -> list:
    """Shared 'Authentication for Utilities' parameters.

    ``ntlm=False`` for utilities that explicitly do not support NTLM (e.g. the
    Historical External Entities Extraction Tool).
    """
    params = [
        Param("user", required=True,
              description="ActOne user name (Execute Web Services permission may be required)."),
        Param("password", required=True,
              description="User password. For an encrypted value also pass -encrypted=true."),
    ]
    if ntlm:
        params += [
            Param("auth_mode", type="enum", choices=["internal", "ntlm_cl", "ntlm_full"],
                  description="Authentication mode: internal (default), ntlm_cl (NTLM via CLI "
                              "params, needs ntlm_domain), or ntlm_full (uses machine credentials)."),
            Param("ntlm_domain",
                  description="Windows/NTLM domain (required with auth_mode=ntlm_cl)."),
        ]
    params.append(Param("encrypted", type="bool",
                        description="Set true when the supplied password value is encrypted."))
    return params


def _ssl() -> list:
    """Shared 'SSL-Related Options' parameters (only needed for https ActOne URLs)."""
    return [
        Param("ts", description="[https] Path to the truststore file containing server certificates."),
        Param("tspassword", description="[https] Truststore password."),
        Param("ks", description="[https] Path to the client keystore file (two-way / client SSL auth)."),
        Param("kspassword", description="[https] Keystore password (two-way / client SSL auth)."),
        Param("kstype", description="[https] Keystore type (default JKS)."),
        Param("tstype", description="[https] Truststore type (default JKS)."),
    ]


def _ddq(returns: str, id_name: str = "acmQueryIdentifier",
         params_name: str = "acmQueryParameters", required: bool = True) -> list:
    """Shared drill-down-query selector (identifier + escaped parameter list)."""
    return [
        Param(id_name, required=required,
              description=f"Drill-down query (DDQ) identifier; the query should return {returns}."),
        Param(params_name,
              description="Comma-separated DDQ parameters. Escape a literal comma as '\\,', a literal "
                          "backslash as '\\\\', and a literal percent as '%%'. Date values use "
                          "'YYYY-MM-DD hh:mm:ss'."),
    ]


def _file_output(default_ext: str = ".pdf") -> list:
    """Shared output-file options for the archive/render family."""
    return [
        Param("prefix", description="Filename prefix for the generated output files."),
        Param("suffix", description="Filename suffix (before the extension) for the output files."),
        Param("extension", description=f"Output file extension (default '{default_ext}')."),
        Param("overwrite", type="bool",
              description="Overwrite pre-existing output files on a name clash (true/false)."),
        Param("zip", type="bool",
              description="Bundle all generated files into a single zip archive (default false)."),
        Param("objectdir", type="bool",
              description="Write each object's files under a new 'prefix_id_suffix' directory "
                          "(default false); such filenames omit prefix/suffix."),
    ]


_CATALOG: dict = {}


def _add(u: Utility) -> None:
    _CATALOG[u.name] = u


_add(Utility(
    name="blotter-maintenance",
    title="Blotter Maintenance (Materialization Asynch Execution) Tool",
    tool="materialization_asynch_execution_tool",
    summary=("Run the blotter materialization process: materialize signed-off blotters to HTML, "
             "archive them to PDF on the file system, and purge transaction instances from the "
             "repository (governed by the actimize.blotters.* configuration parameters)."),
    params=(_acm(nodes=True) + _auth(ntlm=True) + [
        Param("timeout", type="int",
              description="Maximum number of seconds the maintenance process may run."),
        Param("pool_size", type="int",
              description="Concurrent threads per ActOne server "
                          "(default: actimize.blottersMaterialization.poolSize)."),
    ] + _ssl()),
    tags=["rcm", "blotter", "maintenance"],
    state_changing=True,
    doc_url=_IMPL + "RCM_Blotters/Run_the_Blotter_Maintenance.htm",
    notes="Driven by utilities.env (JDK path). Long-running; materializes/archives/purges blotters.",
))

_add(Utility(
    name="dart-runner",
    title="DART Scheduling (Query Asynch Execution) Tool",
    tool="query_asynch_execution_tool",
    summary=("Run the DART query-scheduling maintenance process: execute, stop, or abort the "
             "scheduled queries for an External Data Source and reference date, distributing them "
             "asynchronously across the ActOne node(s)."),
    params=([
        Param("action", type="enum", required=True, choices=["execute", "stop", "abort"],
              description="execute the scheduled queries, stop them (running tasks finish), "
                          "or abort them (only completed tasks are spared)."),
        Param("eds_identifier", required=True,
              description="External Data Source (EDS) identifier the scheduled queries target."),
        Param("reference_date", type="date", required=True,
              description="Reference date (YYYY-MM-DD) substituted into DART query date conditions "
                          "that are relative to the current day."),
        Param("pool_size", type="int",
              description="Concurrent threads per ActOne server "
                          "(default: actimize.dartScheduling.poolSize)."),
        Param("force_execution", type="bool",
              description="With action=execute, re-run a process that already completed for the "
                          "reference date (default false)."),
        Param("timeout", type="int",
              description="Maximum number of seconds the maintenance process may run."),
    ] + _acm(nodes=True) + _auth(ntlm=True) + _ssl()),
    tags=["rcm", "dart", "scheduling", "ddq"],
    state_changing=True,
    doc_url=_IMPL + "RCM_Utilities/query_asynch_execution_t.htm",
    notes="Driven by utilities.env (JDK path). Long-running; executes/stops/aborts DART schedules.",
))

_add(Utility(
    name="workflow-async",
    title="Workflow Asynch Execution Tool",
    tool="workflow_asynch_execution_tool",
    summary=("Run the workflow escalation process: for each work item/case whose current-step "
             "deadline has passed, email the owner and advance the step per the workflow template. "
             "(The ActOne Scheduler's workflow-escalation job can be used instead.)"),
    params=(_acm(nodes=True) + _auth(ntlm=True) + _ssl()),
    tags=["rcm", "workflow", "escalation", "maintenance"],
    state_changing=True,
    doc_url=_IMPL + "RCM_Utilities/Workflow_Asynch_Execution.htm",
    notes="Sends deadline emails and advances workflow steps; requires SMTP config for email. "
          "State-changing.",
))

_add(Utility(
    name="efile",
    title="eFiling Tool",
    tool="efiling_tool",
    summary=("Bundle Outgoing forms marked 'Ready for report' into regulator-formatted e-file "
             "batches, and/or process acknowledgement files returned by the regulator."),
    params=(_acm(nodes=False) + _auth(ntlm=True) + [
        Param("formTypeIdentifiers",
              description="Semicolon-separated list of form type identifiers "
                          "(e.g. RCM_SAR_Form;RCM_CTR_Form). Default: all form types."),
        Param("task", type="enum", choices=["all", "efile", "ack"],
              description="all (default; both), efile (create e-files from ready forms), or "
                          "ack (process regulator acknowledgement files)."),
    ] + _ssl()),
    tags=["efile", "regulatory", "forms", "export"],
    state_changing=True,
    doc_url=_IMPL + "RCM_Utilities/efiling_tool.htm",
    notes="Output/acknowledge folders are set via admin.jsp Config Parameters. State-changing.",
))

_add(Utility(
    name="historical-entities",
    title="Historical External Entities Extraction Tool",
    tool="historical_external_entities_extraction",
    summary=("Queue previously-unextracted work items for external-entity extraction (or, with "
             "-countinprogress, just report the queue depth). Best run when no users are active."),
    params=(_acm(nodes=False) + _auth(ntlm=False) + [
        Param("acmqueryidentifier",
              description="Drill-down query (DDQ) identifier returning items to extract "
                          "(item_id, item_type_id, fl_deleted, fl_extracted). "
                          "Required unless -countinprogress is used."),
        Param("acmqueryparameters",
              description="Comma-separated DDQ parameters (escape a literal comma as \\, )."),
        Param("countinprogress", type="flag",
              description="Display the number of items waiting in the extraction queue. "
                          "Required unless acmqueryidentifier is provided."),
    ] + _ssl()),
    tags=["extraction", "entities", "batch"],
    state_changing=True,
    doc_url=_IMPL + "RCM_Utilities/Historical_External_Entities_Extraction_Tool.htm",
    notes="Does NOT support NTLM authentication. Requires the entity-extraction plugin. "
          "Queueing is state-changing; -countinprogress alone is read-only.",
))

_add(Utility(
    name="get-form-pdf",
    title="Get Form As PDF Tool",
    tool="get_form_as_pdf",
    summary=("Render ActOne forms as PDF files (for regulator reports), saved to the file system "
             "and/or the Case Manager database. Select forms by identifier list or a drill-down query."),
    params=(_acm(nodes=False) + _auth(ntlm=True) + [
        Param("save_to_path", required=True,
              description="Full path to the folder in which to save the generated PDF files."),
        Param("save_pdf_in_db", type="bool",
              description="Also store the generated PDF in the database (default false)."),
        Param("form_identifiers",
              description="Comma-delimited form identifiers to render "
                          "(supply this or ddq_identifer)."),
        Param("ddq_identifer",
              description="Drill-down query identifier returning the forms to render "
                          "(doc spelling: 'ddq_identifer'; supply this or form_identifiers)."),
    ] + _ssl()),
    tags=["form", "pdf", "report", "export"],
    state_changing=False,
    doc_url=_IMPL + "RCM_Utilities/Get_Form_As_PDF_Tool.htm",
    notes="Read-oriented export. Note: -save_pdf_in_db=true persists the PDF to the database.",
))


# --------------------------------------------------------------------------- #
# Full installer Utilities package (Utilities/bin). Params verified against each
# shipped <tool>_readme.txt (ActOne 10.2). Same -name=value convention.
# --------------------------------------------------------------------------- #

# --- Import / export (data, packages, lists, resource strings) ------------- #
_add(Utility(
    name="import-data",
    title="Import Data Tool",
    tool="import_data",
    summary=("Import alerts, case items and cases (with their external/internal dependencies) into "
             "ActOne from one or more XML files produced by the Export Data tool."),
    params=(_acm(nodes=False) + _auth(ntlm=True) + [
        Param("source", required=True,
              description="Path to the XML file to import, or a folder (all XML files in it are imported)."),
        Param("batchsize", type="int", default="500",
              description="Minimum objects imported per transaction (default 500)."),
        Param("validate", type="bool",
              description="Validate the XML source before importing (true/false)."),
        Param("schemalocation",
              description="Full path to the schema XML file (used only when validate=true)."),
    ] + _ssl()),
    tags=["import", "data", "alerts", "cases", "migration"],
    state_changing=True,
    doc_url=_UTIL,
    notes="Counterpart of export-data. Source of truth: Utilities/bin/import_data_readme.txt.",
))

_add(Utility(
    name="export-data",
    title="Export Data Tool",
    tool="export_data",
    summary=("Export alerts or cases (common/custom fields, notes, attachments, audits, step trail, "
             "related cases) selected by a drill-down query to an XML file consumable by Import Data."),
    params=(_acm(nodes=False) + _auth(ntlm=True) + [
        Param("module", type="enum", required=True, choices=["alerts", "cases"],
              description="Object type to export: 'alerts' or 'cases'."),
        Param("drillDownQueryIdentifier", required=True,
              description="DDQ identifier returning the identifiers of the alerts/cases to export."),
        Param("drillDownQueryParameters",
              description="Comma-separated DDQ parameters (escape comma as '\\,', backslash as '\\\\', "
                          "percent as '%%')."),
        Param("out", required=True,
              description="Full path of the XML file to write the exported alerts/cases to."),
    ] + _ssl()),
    tags=["export", "data", "alerts", "cases"],
    state_changing=False,
    doc_url=_UTIL,
    notes="Read/export; output feeds import-data. Source of truth: Utilities/bin/export_data_readme.txt.",
))

_add(Utility(
    name="import-package",
    title="Import Utility (APF Package)",
    tool="import",
    summary="Import an acmObjectPackage (.apf) into the ActOne repository using an import policy.",
    params=(_acm(nodes=False) + _auth(ntlm=True) + [
        Param("filename", required=True, description="Full path to the .apf package file to import."),
        Param("importPolicy", required=True,
              description="ActOne import policy (e.g. Selective, Overwrite)."),
        Param("brokenlinkpolicy", required=True,
              description="ActOne broken-link policy (e.g. Permissive)."),
        Param("processId", description="Optional import process id."),
    ] + _ssl()),
    tags=["import", "apf", "deployment", "package"],
    state_changing=True,
    doc_url=_UTIL,
    notes="Imports a Designer APF package. Source of truth: Utilities/bin/import_readme.txt.",
))

_add(Utility(
    name="export-to-apf",
    title="Export to APF Utility",
    tool="export_to_apf",
    summary="Merge AHO files and export the merged selection into a single .apf package file.",
    params=(_acm(nodes=False) + _auth(ntlm=True) + [
        Param("source", required=True,
              description="Pattern/path of the AHO files to merge (at least one, e.g. C:\\in\\*.aho)."),
        Param("out", required=True, description="Full path of the output .apf file (must end with '.apf')."),
        Param("includeDependencies", type="flag",
              description="Include object dependencies in the package (excluded by default)."),
    ] + _ssl()),
    tags=["export", "apf", "deployment", "package"],
    state_changing=False,
    doc_url=_UTIL,
    notes="Produces a deployable .apf. Source of truth: Utilities/bin/export_to_apf_readme.txt.",
))

_add(Utility(
    name="import-attachment",
    title="Import Attachment Tool",
    tool="import_attachment",
    summary=("Import a file as an attachment on a case or work item (optionally with a description and "
             "note), mirroring the ActOne UI 'add attachment' capability."),
    params=(_acm(nodes=False) + _auth(ntlm=True) + [
        Param("file", required=True, description="File (relative or full path) to import as an attachment."),
        Param("module", type="enum", required=True, choices=["item", "case"],
              description="Attach to a work 'item' or a 'case'."),
        Param("identifier", required=True,
              description="Identifier of the item or case to import the attachment into."),
        Param("description", description="Optional description for the attachment."),
        Param("note", description="Optional note to add alongside the attachment."),
    ] + _ssl()),
    tags=["import", "attachment", "cases", "items"],
    state_changing=True,
    doc_url=_UTIL,
    notes="Source of truth: Utilities/bin/import_attachment_readme.txt.",
))

_add(Utility(
    name="import-virtualfs",
    title="Import Virtual File System Tool",
    tool="import_virtualfs",
    summary=("Import a .zip or .war archive into the ActOne virtual file system from outside the "
             "Designer (e.g. app_gui_items or external_items)."),
    params=([
        Param("rcm", required=True,
              description="URL to the ActOne/RCM location (e.g. http://host:8080/actimize)."),
    ] + _auth(ntlm=True) + [
        Param("filename", required=True, description="Path to the .zip or .war archive to import."),
        Param("virtual_path", type="enum", choices=["app_gui_items", "external_items"],
              default="app_gui_items",
              description="Target virtual path (default app_gui_items)."),
    ] + _ssl()),
    tags=["import", "virtualfs", "deployment"],
    state_changing=True,
    doc_url=_UTIL,
    notes="Supports only .zip/.war; URL flag is '-rcm' (not '-acm'). "
          "Source of truth: Utilities/bin/import_virtualfs_readme.txt.",
))

_add(Utility(
    name="import-platform-list",
    title="Import Platform List Utility",
    tool="import_platform_list",
    summary="Import platform list items into a list from a file (optionally only when the list is empty).",
    params=(_acm(nodes=False) + _auth(ntlm=True) + [
        Param("identifier", required=True, description="Platform list identifier to import into."),
        Param("fileName", required=True, description="Full path of the file to import."),
        Param("log", description="Output file path for error messages (data-related errors)."),
        Param("onlyIfEmpty", type="flag",
              description="Import items only if the target list is currently empty."),
    ] + _ssl()),
    tags=["import", "platform-list", "lists"],
    state_changing=True,
    doc_url=_UTIL,
    notes="Source of truth: Utilities/bin/import_platform_list_readme.txt.",
))

_add(Utility(
    name="export-platform-list",
    title="Export Platform List Utility",
    tool="export_platform_list",
    summary="Export a platform list's items to a CSV file.",
    params=(_acm(nodes=False) + _auth(ntlm=True) + [
        Param("identifier", required=True, description="Platform list identifier to export."),
        Param("out", required=True, description="Full path of the CSV file to write."),
    ] + _ssl()),
    tags=["export", "platform-list", "lists"],
    state_changing=False,
    doc_url=_UTIL,
    notes="Read/export. Source of truth: Utilities/bin/export_platform_list_readme.txt.",
))

_add(Utility(
    name="import-resource-strings",
    title="Import Resource Strings Utility",
    tool="import_resource_strings",
    summary="Import resource strings from a CSV file into the ActOne repository.",
    params=(_acm(nodes=False) + _auth(ntlm=True) + [
        Param("filename", required=True, description="Full path to the CSV file to import."),
        Param("importPolicy", type="enum", required=True, choices=["Overwrite", "Selective"],
              description="ActOne import policy: Overwrite or Selective."),
    ] + _ssl()),
    tags=["import", "resource-strings", "localization"],
    state_changing=True,
    doc_url=_UTIL,
    notes="Source of truth: Utilities/bin/import_resource_strings_readme.txt.",
))

_add(Utility(
    name="import-resource-strings-by-value",
    title="Import Resource Strings By Value Utility",
    tool="import_resource_strings_by_value",
    summary="Import base values as new resource strings from a CSV file, created under a given module.",
    params=(_acm(nodes=False) + _auth(ntlm=True) + [
        Param("filename", required=True, description="Full path to the CSV file to import."),
        Param("module", required=True,
              description="Module name all new resource strings are created under."),
    ] + _ssl()),
    tags=["import", "resource-strings", "localization"],
    state_changing=True,
    doc_url=_UTIL,
    notes="Source of truth: Utilities/bin/import_resource_strings_by_value_readme.txt.",
))

_add(Utility(
    name="export-resource-strings",
    title="Export Resource Strings Utility",
    tool="export_resource_strings",
    summary="Export resource strings from the ActOne repository to a zipped CSV file.",
    params=(_acm(nodes=False) + _auth(ntlm=True) + [
        Param("last_update_date",
              description="Export only strings updated on/after this date ('YYYY-MM-DD hh:mm:ss')."),
        Param("identifiers", description="Comma-delimited list of resource string identifiers."),
        Param("modules", description="Comma-delimited list of resource string modules."),
        Param("out", description="Output file path (default Utilities/bin/English-Base.csv)."),
    ] + _ssl()),
    tags=["export", "resource-strings", "localization"],
    state_changing=False,
    doc_url=_UTIL,
    notes="Date format 'YYYY-MM-DD hh:mm:ss'. "
          "Source of truth: Utilities/bin/export_resource_strings_readme.txt.",
))

# --- Alert / case lifecycle (archive, delete, render, migrate) ------------- #
_add(Utility(
    name="archive-alerts",
    title="Alerts Archiving Tool",
    tool="archive_alerts",
    summary=("Transform selected work items (incl. case items) to PDF/zip archive files and mark them "
             "'archived' in the repository. Selection is by drill-down query."),
    params=(_acm(nodes=False) + _auth(ntlm=True)
            + _ddq("the alert_join_id of the work items to archive")
            + [Param("type", description="Output file format (first release supports pdf).")]
            + _file_output()
            + [Param("generateFile", type="bool", default="true",
                     description="Generate files and archive (default true); when false, items are still "
                                 "marked archived but no files are produced.")]
            + _ssl()),
    tags=["archive", "alerts", "items", "lifecycle"],
    state_changing=True,
    doc_url=_UTIL,
    notes="Marks work items as archived (state-changing). "
          "Source of truth: Utilities/bin/archive_alerts_readme.txt.",
))

_add(Utility(
    name="archive-cases",
    title="Objects Archiving Tool",
    tool="archive_cases",
    summary=("Transform selected ACM objects (cases) to PDF/zip archive files and mark them 'archived' "
             "in the repository. Selection is by drill-down query."),
    params=(_acm(nodes=False) + _auth(ntlm=True)
            + _ddq("the case_join_id of the objects to archive")
            + _file_output()
            + [Param("generateFile", type="bool", default="true",
                     description="Generate files and archive (default true); when false, cases are still "
                                 "marked archived but no files are produced.")]
            + _ssl()),
    tags=["archive", "cases", "lifecycle"],
    state_changing=True,
    doc_url=_UTIL,
    notes="Marks cases as archived (state-changing). "
          "Source of truth: Utilities/bin/archive_cases_readme.txt.",
))

_add(Utility(
    name="delete-alerts",
    title="Delete Alerts Tool",
    tool="delete_alerts",
    summary=("Delete work items (incl. case items) selected by a drill-down query, handling external and "
             "internal dependencies. Supports physical vs. logical delete."),
    params=(_acm(nodes=False) + _auth(ntlm=True)
            + _ddq("the alert_id of the work items to delete")
            + [
        Param("physicalDelete", type="bool", default="false",
              description="Physically delete from the DB (true) or logical/marked delete (false, default)."),
        Param("requiresAudit", type="bool", default="false",
              description="Add audits to deleted alerts and related objects (default false)."),
        Param("forceDependency", type="bool", default="false",
              description="Delete alerts even if they have external dependencies (default false)."),
        Param("continueOnError", type="bool", default="false",
              description="Keep deleting remaining alerts if one fails (default false = all-or-nothing)."),
    ] + _ssl()),
    tags=["delete", "alerts", "items", "lifecycle"],
    state_changing=True,
    doc_url=_UTIL,
    notes="Destructive; physicalDelete=true is irreversible. "
          "Source of truth: Utilities/bin/delete_alerts_readme.txt.",
))

_add(Utility(
    name="delete-cases",
    title="Delete Cases Tool",
    tool="delete_cases",
    summary=("Delete cases selected by a drill-down query, handling external/internal dependencies. "
             "For case work items use delete-alerts instead."),
    params=(_acm(nodes=False) + _auth(ntlm=True)
            + _ddq("the case identifiers to delete")
            + [Param("forceDependency", type="bool", default="true",
                     description="Delete cases even if they have external dependencies (default true).")]
            + _ssl()),
    tags=["delete", "cases", "lifecycle"],
    state_changing=True,
    doc_url=_UTIL,
    notes="Destructive. Source of truth: Utilities/bin/delete_cases_readme.txt.",
))

_add(Utility(
    name="render-alerts",
    title="Alerts Rendering Tool",
    tool="render_alerts",
    summary=("Render selected alerts to PDF (and attachment files) without marking them archived. "
             "Selection is by drill-down query."),
    params=(_acm(nodes=False) + _auth(ntlm=True)
            + _ddq("the alert_join_id of the alerts to render")
            + [Param("type", required=True,
                     description="Output file format (first release supports pdf).")]
            + _file_output()
            + _ssl()),
    tags=["render", "alerts", "pdf", "report"],
    state_changing=False,
    doc_url=_UTIL,
    notes="Read/export (does not mark archived). "
          "Source of truth: Utilities/bin/render_alerts_readme.txt.",
))

_add(Utility(
    name="case-migration",
    title="Case Migration Tool",
    tool="case_migration",
    summary=("Migrate legacy case data (notes, attachments, related work items) to case items via an XML "
             "mapping file and a DDQ, then delete the legacy cases. Migration cannot be reverted."),
    params=(_acm(nodes=False) + _auth(ntlm=True)
            + _ddq("the case identifiers to migrate")
            + [
        Param("mappingfile",
              description="Full path to the XML mapping file (legacy case types/fields/steps -> case item)."),
        Param("numOfThreads", type="int", default="4",
              description="Migration threads (default 4; min 1, max 16)."),
    ] + _ssl()),
    tags=["migration", "cases", "case-items", "lifecycle"],
    state_changing=True,
    doc_url=_UTIL,
    notes="Irreversible: migrated cases cannot be reverted; new metadata must exist in Designer first. "
          "Source of truth: Utilities/bin/case_migration_readme.txt.",
))

# --- Config / deployment / admin ------------------------------------------- #
_add(Utility(
    name="policy-type-deployment",
    title="Policy Type Deployment Tool",
    tool="policy_type_deployment",
    summary=("Deploy (activate) rules queued for activation for the given policy types — the CLI "
             "equivalent of clicking 'Activate Policy' in Policy Manager."),
    params=(_acm(nodes=False) + _auth(ntlm=True) + [
        Param("policy_type_identifiers", required=True,
              description="Comma-delimited identifiers of the policy types to deploy."),
    ] + _ssl()),
    tags=["policy", "deployment", "policy-manager", "rules"],
    state_changing=True,
    doc_url=_UTIL,
    notes="Activates pending rules. Source of truth: Utilities/bin/policy_type_deployment_readme.txt.",
))

_add(Utility(
    name="manage-product-info",
    title="Manage Product Info Utility",
    tool="manage_product_info",
    summary=("Add, get or delete products information (version, patches, 3rd-party info) stored in the "
             "virtual file system."),
    params=(_acm(nodes=False) + _auth(ntlm=True) + [
        Param("action", type="enum", required=True, choices=["add", "get", "delete"],
              description="Action to perform."),
        Param("productName", required=True, description="Product name."),
        Param("infoType", type="enum", required=True, choices=["version", "third_party", "all"],
              description="Product info type."),
        Param("filePath", description="[add] Path to the file to upload."),
        Param("overwrite", type="flag", description="[add] Overwrite an existing file (default false)."),
        Param("out", description="[get] Path to the output zip file to write."),
        Param("files", description="[delete] Name(s) of the file(s) to delete (supports regex; "
                                   "ignored when infoType=all)."),
    ] + _ssl()),
    tags=["product-info", "virtualfs", "admin"],
    state_changing=True,
    doc_url=_UTIL,
    notes="action=get is read-only; add/delete change the virtual file system. "
          "Source of truth: Utilities/bin/manage_product_info_readme.txt.",
))

_add(Utility(
    name="manage-virtual-plugin",
    title="Manage Virtual Plugin Utility",
    tool="manage_virtual_plugin",
    summary="Manage plugins in the virtual file system (currently: upload a zipped plugin).",
    params=(_acm(nodes=False) + _auth(ntlm=True) + [
        Param("pluginId", required=True,
              description="Plugin id; stored as <pluginId>.zip (must be a valid file name)."),
        Param("action", type="enum", required=True, choices=["upload"],
              description="Action to perform (only 'upload' is currently available)."),
        Param("zipFile", description="Full path to the zipped plugin file."),
    ] + _ssl()),
    tags=["plugin", "virtualfs", "admin"],
    state_changing=True,
    doc_url=_UTIL,
    notes="Source of truth: Utilities/bin/manage_virtual_plugin_readme.txt.",
))

_add(Utility(
    name="manage-failover",
    title="Manage Failover Utility",
    tool="manage_failover",
    summary="Set an ActOne/RCM cluster's mode (active or standby) for failover management.",
    params=(_acm(nodes=False) + _auth(ntlm=True) + [
        Param("mode", type="enum", required=True, choices=["active", "standby"],
              description="Cluster mode to set."),
    ] + _ssl()),
    tags=["failover", "cluster", "infrastructure", "admin"],
    state_changing=True,
    doc_url=_UTIL,
    notes="Changes cluster mode. Source of truth: Utilities/bin/manage_failover_readme.txt.",
))

_add(Utility(
    name="form-filing",
    title="Form Status Change Utility",
    tool="formFilingTool",
    summary="Update the status and/or reference of one or more forms.",
    params=(_acm(nodes=False) + _auth(ntlm=True) + [
        Param("forms", required=True,
              description="Semicolon/comma-separated list of form identifiers."),
        Param("newStatusIdentifier",
              description="Form status to set (one value for all forms, or one per form in order); "
                          "e.g. 'Ready for report', 'Reported - success'."),
        Param("reference",
              description="Reference per form (semicolon-separated; a space keeps it empty). "
                          "Omit to leave references unchanged."),
    ] + _ssl()),
    tags=["forms", "status", "regulatory"],
    state_changing=True,
    doc_url=_UTIL,
    notes="Source of truth: Utilities/bin/formFilingTool_readme.txt.",
))

_add(Utility(
    name="vla-graphs",
    title="VLA Utility (Visual Link Analysis Graphs)",
    tool="vla_tool",
    summary=("Add or delete Visual Link Analysis graphs in ActOne, optionally associating an added graph "
             "with an alert."),
    params=(_acm(nodes=False) + _auth(ntlm=True) + [
        Param("task", type="enum", required=True, choices=["add", "delete"],
              description="add a graph or delete a graph."),
        Param("graphFile",
              description="[add] Path to the file containing the graph XML (mandatory for add)."),
        Param("alertIdentifier",
              description="[add] Alert identifier to associate the graph with "
                          "(optional; unassociated if omitted)."),
        Param("graphIdentifer",
              description="[delete] Identifier of the graph to delete "
                          "(mandatory for delete; note the doc spelling 'graphIdentifer')."),
    ] + _ssl()),
    tags=["vla", "graphs", "link-analysis"],
    state_changing=True,
    doc_url=_UTIL,
    notes="Not documented in the online Implementer Guide. "
          "Source of truth: Utilities/bin/vla_tool_readme.txt.",
))

# --- Local / no-connection helpers ----------------------------------------- #
_add(Utility(
    name="merge-aho-files",
    title="Merge AHO Files Utility",
    tool="merge_aho_files",
    summary="Merge multiple AHO files into a single .aho file (local operation; no ActOne connection).",
    params=[
        Param("source", required=True,
              description="Pattern/path of the AHO files to merge (at least one, e.g. C:\\in\\*.aho)."),
        Param("out", required=True,
              description="Full path of the merged output file (must end with '.aho')."),
    ],
    tags=["aho", "merge", "package", "local"],
    state_changing=False,
    doc_url=_UTIL,
    notes="No authentication; local file merge. "
          "Source of truth: Utilities/bin/merge_aho_files_readme.txt.",
))

_add(Utility(
    name="run-encryptor",
    title="Encryption Tool",
    tool="run_encryptor",
    summary=("Encrypt passwords/strings using AES (ActOne 6.6.0 SP2+). Run with no parameters to open "
             "the wizard, or use flags for command-line encryption."),
    params=[
        Param("encrypt", description="String value to encrypt."),
        Param("iv", description="User-defined initialization vector (1-16 letters/digits)."),
        Param("iv_gen", type="flag", description="Generate a new initialization vector (IV)."),
        Param("DES", type="flag",
              description="Encrypt a string for use by the utilities (utilities-format encryption)."),
    ],
    tags=["encryption", "password", "security", "local"],
    state_changing=False,
    doc_url=_UTIL,
    notes="No ActOne connection; run with no args to open the GUI wizard. "
          "Source of truth: Utilities/bin/run_encryptor_readme.txt.",
))

# --- Database script generators (DB creds, not ACM auth) ------------------- #
_add(Utility(
    name="dbupgrade",
    title="RCM DB Script Generator (dbupgrade)",
    tool="dbupgrade",
    summary=("Generate (or, with -exec, execute) the SQL script that creates a new ActOne/RCM database "
             "or upgrades an existing one. Runs against the DB, not the ACM URL."),
    params=[
        Param("dbtype", type="enum", required=True,
              choices=["oracle", "mssql", "nmssql", "postgresql"],
              description="Target DB type (nmssql = MSSQL with nvarchar string columns)."),
        Param("db", description="JDBC URL to the RCM repository (required for upgrade / -exec)."),
        Param("user", description="DB user name."),
        Param("password", description="DB user password."),
        Param("catalog", description="DB catalog (MSSQL), if required."),
        Param("new", type="flag", description="Generate a script for a new/empty database."),
        Param("exec", type="flag",
              description="Execute the SQL against the DB instead of only emitting SQL."),
        Param("out", description="File to redirect the generated SQL to (default: console)."),
        Param("env",
              description="Environment key=value file (mandatory for oracle/mssql/postgresql; "
                          "e.g. oracle.env, mssql.env, postgresql.env)."),
        Param("summary",
              description="File to redirect run summary values (e.g. current DB version) to."),
        Param("help", type="flag", description="Show the usage screen."),
    ],
    tags=["database", "upgrade", "install", "dba"],
    state_changing=True,
    doc_url=_UTIL,
    notes="Uses DB credentials (not ACM auth). Without -exec it only emits SQL; with -exec it modifies "
          "the database. Source of truth: Utilities/bin/dbupgrade_readme.txt.",
))

_add(Utility(
    name="rcm-users-and-roles",
    title="RCM DB Users and Roles Script Generator",
    tool="RCM_UsersAndRoles",
    summary=("Generate a SQL script that creates a DB user with the privileges needed to run dbupgrade "
             "(MSSQL/Oracle/PostgreSQL)."),
    params=[
        Param("dbtype", type="enum", required=True, choices=["mssql", "oracle", "postgresql"],
              description="Target DB type."),
        Param("env", required=True,
              description="Env file with the DB configuration (e.g. mssql.env, oracle.env, postgresql.env)."),
        Param("out", required=True, description="File to redirect the generated SQL to."),
    ],
    tags=["database", "users", "roles", "install", "dba"],
    state_changing=False,
    doc_url=_UTIL,
    notes="Generates a SQL script (does not modify the DB); edit the .env first. "
          "Source of truth: Utilities/bin/RCM_UsersAndRoles_readme.txt.",
))



# --------------------------------------------------------------------------- #
# discovery API
# --------------------------------------------------------------------------- #
def all_utils() -> list:
    return list(_CATALOG.values())


def get(name: str) -> Optional[Utility]:
    return _CATALOG.get(name)


def list_briefs() -> list:
    return [u.brief() for u in sorted(_CATALOG.values(), key=lambda u: u.name)]


def search(query: str, limit: int = 25) -> list:
    q = (query or "").lower().strip()
    terms = [t for t in re.split(r"\s+", q) if t]
    scored = []
    for u in _CATALOG.values():
        hay = " ".join([u.name, u.title, u.tool, u.summary, " ".join(u.tags)]).lower()
        score = sum(3 if t in u.name.lower() else (2 if t in " ".join(u.tags).lower()
                    else (1 if t in hay else 0)) for t in terms)
        if not terms:
            score = 1
        if score:
            scored.append((score, u))
    scored.sort(key=lambda x: (-x[0], x[1].name))
    return [u.brief() for _, u in scored[:limit]]


def tags() -> dict:
    seen: dict = {}
    for u in _CATALOG.values():
        for t in u.tags:
            seen[t] = seen.get(t, 0) + 1
    return dict(sorted(seen.items()))
