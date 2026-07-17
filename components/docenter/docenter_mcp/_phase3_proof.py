r"""Phase 3 offline proof — MCP per-user resolution + X-DOCenter-User enforcement.

Deterministic, no network: exercises _resolve_session routing, per-user isolation,
SessionRequired for unseeded users, and the token verifier the _AuthGate uses.
Run from repo root:  py components\docenter\docenter_mcp\_phase3_proof.py
"""
from __future__ import annotations

import os
import sys
import tempfile

SECRET = "phase3-test-secret"
ALICE = "alice@example.com"
BOB = "bob@example.com"

_fail = 0


def check(label: str, cond: bool) -> None:
    global _fail
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}")
    if not cond:
        _fail += 1


def main() -> int:
    # Point the user store at a throwaway dir and turn the flag on BEFORE import.
    store = tempfile.mkdtemp(prefix="docenter-users-")
    os.environ["DOCENTER_USER_STORE_DIR"] = store
    os.environ["DOCENTER_USER_TOKEN_SECRET"] = SECRET
    os.environ["DOCENTER_PER_USER"] = "1"

    from docenter_mcp import server, user_store
    from docenter_mcp.user_token import mint_docenter_user_token, verify_docenter_user_token

    # Seed alice with a dummy cookie payload; leave bob unseeded.
    fake_cookies = {"data": {"cookies": [
        {"name": "_SESSION", "value": "alice-cookie", "domain": ".niceactimize.com"},
    ]}}
    user_store.save_user_cookie_data(ALICE, fake_cookies)

    print("flag ON — routing:")
    # flag on + user=alice (seeded) -> per-user session, user_id=alice
    server._current_user_id = lambda: ALICE
    sess_a, uid_a = server._resolve_session()
    check("alice resolves to a session with user_id=alice", uid_a == ALICE and sess_a is not None)
    check("alice session carries her own cookie",
          sess_a.cookies.get("_SESSION") == "alice-cookie")

    # flag on + user=bob (unseeded) -> SessionRequired, NEVER shared
    server._current_user_id = lambda: BOB
    raised = False
    try:
        server._resolve_session()
    except server.SessionRequired as exc:
        raised = exc.user_id == BOB
    check("bob (unseeded) raises SessionRequired, no shared fallback", raised)

    # flag on + no user header -> shared session (Copilot path)
    server._current_user_id = lambda: None
    called = {"shared": False}
    orig_shared = server._get_session
    server._get_session = lambda: (called.__setitem__("shared", True) or "SHARED")
    try:
        sess_n, uid_n = server._resolve_session()
    finally:
        server._get_session = orig_shared
    check("no user header -> shared session, user_id=None",
          uid_n is None and sess_n == "SHARED" and called["shared"])

    print("flag OFF — routing:")
    server.DOCENTER_PER_USER = False
    server._current_user_id = lambda: (_ for _ in ()).throw(AssertionError("must not be called"))
    server._get_session = lambda: "SHARED-OFF"
    sess_off, uid_off = server._resolve_session()
    check("flag off -> shared session, user id never consulted",
          uid_off is None and sess_off == "SHARED-OFF")
    server._get_session = orig_shared
    server.DOCENTER_PER_USER = True

    print("token verifier (what _AuthGate enforces):")
    good = mint_docenter_user_token(ALICE, SECRET)
    check("valid token verifies to alice", verify_docenter_user_token(good, SECRET).user_id == ALICE)

    wrong_secret = mint_docenter_user_token(ALICE, "other-secret")
    rejected = False
    try:
        verify_docenter_user_token(wrong_secret, SECRET)
    except ValueError:
        rejected = True
    check("token signed with wrong secret -> rejected", rejected)

    tampered = good[:-4] + ("AAAA" if not good.endswith("AAAA") else "BBBB")
    rejected2 = False
    try:
        verify_docenter_user_token(tampered, SECRET)
    except ValueError:
        rejected2 = True
    check("tampered signature -> rejected", rejected2)

    expired = mint_docenter_user_token(ALICE, SECRET, ttl_seconds=-3600)
    rejected3 = False
    try:
        verify_docenter_user_token(expired, SECRET)
    except ValueError:
        rejected3 = True
    check("expired token -> rejected", rejected3)

    print("isolation:")
    # The per-user store dir must be distinct from the shared cookie file path.
    from docenter.cli import COOKIES_FILE
    check("user store dir != shared cookie file",
          str(user_store.user_store_dir()) not in str(COOKIES_FILE))

    print(f"\n{'ALL PASS' if _fail == 0 else str(_fail) + ' FAILED'}")
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
