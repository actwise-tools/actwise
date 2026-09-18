"""Browser backends for the login broker — where the hosted interactive browser runs.

Two backends behind one interface (the R5 decision point):
  * SelfHostedBackend  — Playwright Chromium on this host / in the noVNC Docker
    image; the user drives it via noVNC (self-host on the corp network is the
    Conditional-Access fallback).
  * BrowserbaseBackend — a Browserbase cloud session; the user drives it via the
    Browserbase live-view URL (a datacenter browser — the CA risk R5 tests).

A backend only opens a browser the user can drive and exposes an ``interactive_url``.
Success detection + the store write live in ``capture.poll_capture`` (one path).
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable

from .capture import PORTAL_LOGIN_URL


@dataclass
class BrowserHandle:
    """An opened browser the user can drive plus how to reach and close it."""

    context: object                 # a Playwright BrowserContext
    interactive_url: str            # URL the user opens to drive the login
    close: Callable[[], None]


class BrowserBackend(ABC):
    name: str

    @abstractmethod
    def open(self) -> BrowserHandle:
        """Open a browser session navigated to the DOCenter login page."""


class SelfHostedBackend(BrowserBackend):
    """Playwright Chromium on this host (headed under noVNC, or headless for tests).

    Two knobs matter for real employee SSO behind Entra Conditional Access (R5):
      * ``BROKER_BROWSER_CHANNEL`` — launch a branded browser channel instead of
        the bundled Chromium (``msedge`` gives Windows device-compliance SSO, which
        vanilla Chromium lacks → CA error 53000). Also ``chrome``, ``msedge-beta``.
      * ``BROKER_USER_DATA_DIR`` — drive a *persistent* profile (the user's own
        managed, device-joined browser profile) via ``launch_persistent_context``,
        so the device-compliance signal Conditional Access requires is present.
    """

    name = "self-hosted"

    def __init__(self, headless: bool | None = None, novnc_url: str | None = None,
                 channel: str | None = None, user_data_dir: str | None = None):
        # Headed by default so a user can drive it via noVNC; tests pass headless=True.
        self.headless = (
            headless if headless is not None
            else os.environ.get("BROKER_HEADLESS", "").lower() in ("1", "true", "yes")
        )
        # Where the user reaches the headed browser (the noVNC web endpoint).
        self.novnc_url = novnc_url or os.environ.get("BROKER_NOVNC_URL", "http://localhost:6080/vnc.html")
        # Branded channel (e.g. "msedge") — needed to pass Entra device-compliance CA.
        self.channel = channel if channel is not None else (os.environ.get("BROKER_BROWSER_CHANNEL") or None)
        # A persistent profile dir carries the managed-device SSO state.
        self.user_data_dir = user_data_dir if user_data_dir is not None else (os.environ.get("BROKER_USER_DATA_DIR") or None)

    def open(self) -> BrowserHandle:
        from playwright.sync_api import sync_playwright

        pw = sync_playwright().start()
        launch_kwargs = {"headless": self.headless}
        if self.channel:
            launch_kwargs["channel"] = self.channel

        if self.user_data_dir:
            # Persistent context: one object is both browser and context.
            context = pw.chromium.launch_persistent_context(self.user_data_dir, **launch_kwargs)
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(PORTAL_LOGIN_URL, timeout=30000)

            def _close():
                try:
                    context.close()
                finally:
                    pw.stop()

            return BrowserHandle(context=context, interactive_url=self.novnc_url, close=_close)

        browser = pw.chromium.launch(**launch_kwargs)
        context = browser.new_context()
        page = context.new_page()
        page.goto(PORTAL_LOGIN_URL, timeout=30000)

        def _close():
            try:
                context.close()
                browser.close()
            finally:
                pw.stop()

        return BrowserHandle(context=context, interactive_url=self.novnc_url, close=_close)


class BrowserbaseBackend(BrowserBackend):
    """A Browserbase cloud browser session (USER-gated: needs a Browserbase account).

    Guarded — raises a clear error when BROWSERBASE_API_KEY / PROJECT_ID are unset,
    so the broker runs on the self-hosted backend without a Browserbase signup."""

    name = "browserbase"

    def __init__(self, api_key: str | None = None, project_id: str | None = None):
        self.api_key = api_key or os.environ.get("BROWSERBASE_API_KEY", "")
        self.project_id = project_id or os.environ.get("BROWSERBASE_PROJECT_ID", "")

    def open(self) -> BrowserHandle:
        if not (self.api_key and self.project_id):
            raise RuntimeError(
                "BrowserbaseBackend needs BROWSERBASE_API_KEY and BROWSERBASE_PROJECT_ID "
                "(USER-gated: sign up for the Browserbase trial). Use the self-hosted "
                "backend for local testing."
            )
        import httpx
        from playwright.sync_api import sync_playwright

        # Create a cloud browser session; get the CDP connect URL + the live-view URL.
        resp = httpx.post(
            "https://api.browserbase.com/v1/sessions",
            headers={"X-BB-API-Key": self.api_key, "Content-Type": "application/json"},
            json={"projectId": self.project_id},
            timeout=30,
        )
        resp.raise_for_status()
        session = resp.json()
        connect_url = session["connectUrl"]
        live_url = session.get("liveViewUrl") or session.get("seleniumRemoteUrl") or connect_url

        pw = sync_playwright().start()
        browser = pw.chromium.connect_over_cdp(connect_url)
        context = browser.contexts[0] if browser.contexts else browser.new_context()
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(PORTAL_LOGIN_URL, timeout=30000)

        def _close():
            try:
                browser.close()
            finally:
                pw.stop()

        return BrowserHandle(context=context, interactive_url=live_url, close=_close)


def get_backend(name: str | None = None) -> BrowserBackend:
    """Resolve the configured backend (``BROKER_BACKEND`` env; default self-hosted)."""
    name = (name or os.environ.get("BROKER_BACKEND", "self-hosted")).lower()
    if name in ("self-hosted", "selfhosted", "local", "novnc"):
        return SelfHostedBackend()
    if name in ("browserbase", "bb"):
        return BrowserbaseBackend()
    raise ValueError(f"unknown BROKER_BACKEND: {name}")
