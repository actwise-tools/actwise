"""POC auth proxy: expose the `docenter` live-portal search as a small HTTPS API
that a Microsoft Copilot Studio agent can call as a custom connector / HTTP action
(the "Option D — live API grounding" architecture).

Why this exists
---------------
Copilot Studio grounds answers by calling a retrieval endpoint and mapping the
results into ``System.SearchResults`` (Title / Content / ContentLocation). Instead
of ingesting the ~62K-page corpus, we point Copilot at the documentation portal
*live*, reusing the hybrid product/version/guide filtering already built in
``docenter``. The portal session cookie stays server-side; callers authenticate
with a static API key.

POC scope
---------
* Auth: a single ``X-API-Key`` shared secret (env ``DOCENTER_PROXY_API_KEY``).
* Identity: the proxy runs under the developer's own portal login — the
  ``_SESSION`` cookie loaded by ``docenter.cli.load_session`` (re-login ~monthly;
  MFA blocks fully-automated refresh). Swap the cookie for a real service
  credential later with **zero** change to the Copilot side.
* Transport: run behind a dev tunnel (HTTPS) for the POC; Azure Container App /
  Function + APIM for production.

The OpenAPI document at ``/openapi.json`` can be imported directly when creating
the Copilot Studio custom connector.
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import List, Optional

from fastapi import FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field

from docenter.cli import portal_search_core, load_session, _map_portal_item

API_KEY_ENV = "DOCENTER_PROXY_API_KEY"

app = FastAPI(
    title="docenter Copilot grounding proxy",
    version="0.1.0",
    description="Live NICE Actimize documentation search for Copilot Studio grounding (Option D).",
)


class SearchResultItem(BaseModel):
    """One result, shaped for Copilot Studio's ``System.SearchResults`` table.

    The property names match the Copilot schema exactly so the custom connector
    can auto-map them in ``OnKnowledgeRequested``."""

    Title: str = Field(..., description="Result title (becomes the citation title).")
    ContentLocation: str = Field(..., description="Canonical portal URL — the citation Copilot surfaces.")
    Content: str = Field(..., description="Snippet/body the model reads to ground its answer.")


class SearchResponse(BaseModel):
    """Envelope returned to the Copilot custom connector."""

    value: List[SearchResultItem] = Field(default_factory=list, description="Search results.")
    originalQuery: str = Field(..., description="The query as received.")
    correctedQuery: Optional[str] = Field(None, description="Spelling/synonym correction the portal applied, if any.")
    suggestions: List[str] = Field(default_factory=list, description="Alternative query suggestions when results are sparse.")


def _require_api_key(provided: Optional[str]) -> None:
    """Enforce the shared-secret API key. 503 if the proxy isn't configured."""
    import hmac
    expected = os.environ.get(API_KEY_ENV)
    if not expected:
        raise HTTPException(status_code=503, detail=f"Proxy not configured: set {API_KEY_ENV}.")
    if not provided or not hmac.compare_digest(provided.strip(), expected.strip()):
        raise HTTPException(status_code=401, detail="Invalid or missing API key.")


@lru_cache(maxsize=1)
def _session():
    """Cache the portal session for the process lifetime. Cleared on a 403 so the
    next request rebuilds it after the operator refreshes the cookie."""
    return load_session()


@app.get("/healthz", tags=["meta"])
def healthz() -> dict:
    """Unauthenticated liveness probe (for tunnels / load balancers)."""
    return {"status": "ok"}


@app.get("/search", tags=["search"], operation_id="searchDocs", response_model=SearchResponse)
def search(
    q: str = Query(..., description="The user's search query."),
    product: Optional[str] = Query(None, description="Product key/name, e.g. actone, ifm, sam."),
    doc_version: Optional[str] = Query(None, description="Doc version, e.g. 10.1, 11.2."),
    guide: Optional[str] = Query(None, description="Guide type, e.g. implementer, reference."),
    max_results: int = Query(5, ge=1, le=20, alias="max", description="Max results (Copilot token budget)."),
    page: int = Query(1, ge=1, description="Result page."),
    retry: bool = Query(True, description="Auto-retry the portal's spelling/synonym suggestion when empty."),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> SearchResponse:
    """Search the live portal and return results shaped for Copilot Studio's
    ``System.SearchResults`` table (Title / Content / ContentLocation)."""
    _require_api_key(x_api_key)

    try:
        sr = portal_search_core(
            _session(), q, max_results=max_results, page=page,
            product=product, doc_version=doc_version, guide=guide, retry=retry,
        )
    except RuntimeError as exc:
        if str(exc) == "access_denied":
            cache_clear = getattr(_session, "cache_clear", None)
            if cache_clear:
                cache_clear()
            raise HTTPException(
                status_code=502,
                detail="Portal session expired. Run `docenter auth login` on the proxy host.",
            )
        raise HTTPException(status_code=502, detail=f"Portal search failed: {exc}")
    except HTTPException:
        raise
    except Exception as exc:  # missing cookie, dependency, etc.
        raise HTTPException(status_code=503, detail=f"Portal session unavailable: {exc}")

    value = []
    for item in sr["results"]:
        m = _map_portal_item(item)
        value.append({
            "Title": m["title"],
            # ContentLocation is the canonical citation Copilot surfaces to the user.
            "ContentLocation": m["portal_url"],
            # Content is what the model reads; fall back to the title when the
            # portal returns no snippet so the model still has an anchor.
            "Content": m["snippet"] or m["title"],
        })

    return {
        "value": value,
        "originalQuery": q,
        "correctedQuery": sr["effective_query"] if sr["corrected_from"] else None,
        # Only offer alternatives when the search came up empty (the core now
        # computes suggestions on every call; this endpoint keeps its original
        # sparse-results-only contract).
        "suggestions": sr["suggestions"] if not value else [],
    }
