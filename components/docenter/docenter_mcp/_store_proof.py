r"""Step-1 offline proof — pluggable per-user store (filesystem + S3), no network.

Deterministic, no AWS: exercises both backends of ``user_store`` and proves

  A. filesystem backend is byte-for-byte the pre-existing behavior (default,
     no S3 env): save→load round-trips, unseeded→None, hashed filename, drop.
  B. S3 backend (``DOCENTER_USER_STORE_S3_BUCKET`` set) via an in-memory fake
     boto3 client injected through the ``S3_CLIENT_FACTORY`` seam: save→load
     round-trips, unseeded→None (NoSuchKey), object key = <prefix>/<sha256>.json,
     ``save`` returns an ``s3://`` URI, drop deletes, and the filesystem is NEVER
     touched while S3 is active.
  C. the same public API (``load``/``save``/``drop``) drives both backends —
     consumers (MCP read, broker/password write) need no change.

Run from repo root:  py components\docenter\docenter_mcp\_store_proof.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from hashlib import sha256

ALICE = "alice@example.com"
BOB = "bob@example.com"
PAYLOAD = {"data": {"cookies": [
    {"name": "_SESSION", "value": "alice-cookie", "domain": ".niceactimize.com"},
]}}

_fail = 0


def check(label: str, cond: bool) -> None:
    global _fail
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}")
    if not cond:
        _fail += 1


class _NoSuchKey(Exception):
    pass


class _Body:
    def __init__(self, raw: bytes):
        self._raw = raw

    def read(self) -> bytes:
        return self._raw


class _FakeS3Exceptions:
    NoSuchKey = _NoSuchKey


class _FakeS3Client:
    """In-memory stand-in mirroring the boto3 S3 client surface we use."""

    def __init__(self, store: dict):
        self._store = store  # {(bucket, key): bytes}
        self.exceptions = _FakeS3Exceptions()

    def get_object(self, Bucket, Key):  # noqa: N803 (boto3 casing)
        if (Bucket, Key) not in self._store:
            raise _NoSuchKey(f"missing {Bucket}/{Key}")
        return {"Body": _Body(self._store[(Bucket, Key)])}

    def put_object(self, Bucket, Key, Body, ContentType=None):  # noqa: N803
        self._store[(Bucket, Key)] = Body

    def delete_object(self, Bucket, Key):  # noqa: N803
        self._store.pop((Bucket, Key), None)


def main() -> int:
    fs_dir = tempfile.mkdtemp(prefix="store-proof-fs-")
    os.environ["DOCENTER_USER_STORE_DIR"] = fs_dir
    os.environ.pop("DOCENTER_USER_STORE_S3_BUCKET", None)

    from docenter_mcp import user_store

    # ── A. filesystem backend (default) ──────────────────────────────────────
    print("A. filesystem backend (default, no S3 env):")
    check("unseeded user -> None", user_store.load_user_cookie_data(BOB) is None)
    loc = user_store.save_user_cookie_data(ALICE, PAYLOAD)
    check("save returns a filesystem path (not s3://)",
          isinstance(loc, str) and not loc.startswith("s3://") and loc.endswith(".json"))
    got = user_store.load_user_cookie_data(ALICE)
    check("save->load round-trips the exact payload", got == PAYLOAD)
    expected_name = sha256(ALICE.encode()).hexdigest() + ".json"
    check("on-disk filename is sha256(user_id).json (email never in path)",
          os.path.basename(loc) == expected_name and ALICE not in loc)
    user_store.drop_user_cookie_data(ALICE)
    check("drop removes the file (load -> None)", user_store.load_user_cookie_data(ALICE) is None)

    # ── B. S3 backend (fake client via the factory seam) ─────────────────────
    print("B. S3 backend (DOCENTER_USER_STORE_S3_BUCKET set, fake boto3 client):")
    s3_mem: dict = {}
    user_store.S3_CLIENT_FACTORY = lambda: _FakeS3Client(s3_mem)
    os.environ["DOCENTER_USER_STORE_S3_BUCKET"] = "actwise-docenter-users"
    os.environ["DOCENTER_USER_STORE_S3_PREFIX"] = "docenter-users"

    check("unseeded user -> None (NoSuchKey handled)", user_store.load_user_cookie_data(BOB) is None)
    uri = user_store.save_user_cookie_data(ALICE, PAYLOAD)
    check("save returns an s3:// URI", uri == "s3://actwise-docenter-users/docenter-users/"
          + sha256(ALICE.encode()).hexdigest() + ".json")
    got_s3 = user_store.load_user_cookie_data(ALICE)
    check("S3 save->load round-trips the exact payload", got_s3 == PAYLOAD)
    expected_key = "docenter-users/" + sha256(ALICE.encode()).hexdigest() + ".json"
    check("object key = <prefix>/<sha256>.json (email never in key)",
          ("actwise-docenter-users", expected_key) in s3_mem)

    # Isolation: with S3 active, the filesystem store must be untouched.
    check("filesystem NOT written while S3 active",
          user_store._fs_load(ALICE) is None)

    user_store.drop_user_cookie_data(ALICE)
    check("S3 drop deletes the object (load -> None)", user_store.load_user_cookie_data(ALICE) is None)
    check("S3 store is now empty", s3_mem == {})

    # ── C. backend switch is env-only ────────────────────────────────────────
    print("C. same API, backend chosen by env only:")
    os.environ.pop("DOCENTER_USER_STORE_S3_BUCKET", None)
    check("clearing the bucket env falls back to filesystem",
          user_store._s3_bucket() is None)
    user_store.save_user_cookie_data(ALICE, PAYLOAD)
    check("write after fallback lands on the filesystem again",
          user_store._fs_load(ALICE) == PAYLOAD and s3_mem == {})
    user_store.drop_user_cookie_data(ALICE)

    user_store.S3_CLIENT_FACTORY = None

    print()
    if _fail:
        print(f"RESULT: {_fail} check(s) FAILED")
        return 1
    print("RESULT: all checks PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
