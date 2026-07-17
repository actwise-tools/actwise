"""ActWise Data eval harness — the standing regression net for the engine.

Each eval case pairs a natural-language ``question`` with the **reference SQL** a
well-grounded model should produce, plus assertions. The runner drives the *same*
guardrail + execute path as ``run_query`` (``db.run_query`` — which re-validates
internally) and scores each case on:

* **guardrail outcome** — ``expect: ok`` runs and returns rows; ``expect: reject``
  must be blocked by the pipeline (``reject_contains`` matches the reason);
* **view steering** — ``expected_views`` must equal ``views_used`` (asserts the
  item-preference: the reference SQL hits ``v_acm_item*`` not legacy ``v_acm_alert*``);
* **SQL content** — ``must_contain`` / ``must_not_contain`` substrings in ``sql_used``;
* **result shape** — ``shape.columns`` (exact, ordered) and ``shape.min_rows``.

This scores on result-shape + view-allowlist assertions, **not** brittle string
equality, so it tolerates the fresh-vs-seeded DB difference (``allow_variation``).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from actone_data import db
from actone_data.guardrails import GuardrailError

EVALS_DIR = Path(__file__).parent / "data" / "evals"


@dataclass
class CaseResult:
    file: str
    id: str
    expect: str
    passed: bool
    fails: list[str] = field(default_factory=list)
    detail: str = ""


def load_sets(path: Path | None = None) -> list[dict]:
    """Load one eval-set file, or every ``*.yaml`` under ``data/evals/``."""
    files = [Path(path)] if path else sorted(EVALS_DIR.glob("*.yaml"))
    if not files:
        raise FileNotFoundError(f"no eval sets found in {EVALS_DIR}")
    sets = []
    for f in files:
        data = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        data["_file"] = f.name
        sets.append(data)
    return sets


def _check_ok(case: dict, res: dict) -> list[str]:
    fails: list[str] = []
    ev = case.get("expected_views")
    if ev is not None:
        want = sorted(v.lower() for v in ev)
        if res["views_used"] != want:
            fails.append(f"views {res['views_used']} != expected {want}")
    sql = (res["sql_used"] or "").lower()
    for s in case.get("must_contain", []):
        if s.lower() not in sql:
            fails.append(f"missing {s!r} in sql_used")
    for s in case.get("must_not_contain", []):
        if s.lower() in sql:
            fails.append(f"forbidden {s!r} present in sql_used")
    shape = case.get("shape") or {}
    cols = shape.get("columns")
    if cols is not None:
        got = [c.lower() for c in res["columns"]]
        want_cols = [c.lower() for c in cols]
        if got != want_cols:
            fails.append(f"columns {got} != {want_cols}")
    mr = shape.get("min_rows")
    if mr is not None and res["row_count"] < mr:
        fails.append(f"row_count {res['row_count']} < min_rows {mr}")
    return fails


def run_case(cfg, case: dict) -> CaseResult:
    expect = case.get("expect", "ok")
    cid = case.get("id", "?")
    file = case.get("_file", "")
    try:
        res = db.run_query(cfg, case["sql"], max_rows=case.get("max_rows", 100))
    except GuardrailError as ge:
        if expect == "reject":
            reason = "; ".join(ge.errors)
            rc = case.get("reject_contains")
            if rc and rc.lower() not in reason.lower():
                return CaseResult(file, cid, expect, False,
                                  [f"reject reason {reason!r} lacks {rc!r}"])
            return CaseResult(file, cid, expect, True, detail="rejected as expected")
        return CaseResult(file, cid, expect, False,
                          [f"unexpected reject: {'; '.join(ge.errors)}"])
    except Exception as e:  # connection / execution error
        return CaseResult(file, cid, expect, False, [f"execution error: {e}"])

    if expect == "reject":
        return CaseResult(file, cid, expect, False, ["expected reject but query ran"])
    fails = _check_ok(case, res)
    detail = f"{res['row_count']} rows; views={res['views_used']}"
    return CaseResult(file, cid, expect, not fails, fails, detail)


def run(cfg, path: Path | None = None) -> list[CaseResult]:
    """Run every case across the loaded eval set(s) and return per-case results."""
    out: list[CaseResult] = []
    for st in load_sets(path):
        for case in st.get("cases", []):
            case = {**case, "_file": st["_file"]}
            out.append(run_case(cfg, case))
    return out
