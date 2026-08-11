"""JSONL audit log — one object per query attempt, including rejections."""
from __future__ import annotations

import getpass
import json
import os
from datetime import datetime, timezone
from pathlib import Path


def _default_path() -> Path:
    env = os.getenv("ACTONE_DATA_AUDIT_LOG")
    if env:
        return Path(env)
    return Path.home() / ".actone-data" / "audit.jsonl"


def actor() -> str:
    try:
        return getpass.getuser()
    except Exception:
        return "unknown"


def record(
    *,
    transport: str,
    question: str,
    sql: str,
    ok: bool,
    sql_used: str | None = None,
    rejected_reason: str | None = None,
    rows: int | None = None,
    truncated: bool | None = None,
    duration_ms: int | None = None,
    db: str | None = None,
    env: str | None = None,
    path: Path | None = None,
) -> dict:
    """Append one attempt to the audit log and return the written record."""
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "actor": actor() if transport in ("cli", "mcp-stdio") else transport,
        "transport": transport,
        "env": env,
        "question": question or "",
        "sql": sql,
        "sql_used": sql_used,
        "ok": ok,
        "rejected_reason": rejected_reason,
        "rows": rows,
        "truncated": truncated,
        "duration_ms": duration_ms,
        "db": db,
    }
    p = path or _default_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def tail(n: int = 20, path: Path | None = None) -> list[dict]:
    """Return the last ``n`` audit records (oldest→newest)."""
    p = path or _default_path()
    if not p.exists():
        return []
    lines = [ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]
    out = []
    for ln in lines[-n:]:
        try:
            out.append(json.loads(ln))
        except json.JSONDecodeError:
            continue
    return out
