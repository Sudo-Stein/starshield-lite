"""Optional HTTP client helpers for Streamlit (or other UIs).

When ``STARSHIELD_USE_API=1`` and the API is reachable, Streamlit can call
these instead of importing services directly.

Sends ``X-API-Key`` when ``STARSHIELD_API_KEY`` (or first configured key) is set.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import httpx

from config import API_BASE_URL, API_KEY_REQUIRED
from api.security import API_KEY_HEADER_NAME, get_valid_keys
import os


def _resolve_client_api_key(explicit: Optional[str] = None) -> Optional[str]:
    if explicit:
        return explicit
    env_key = os.getenv("STARSHIELD_API_KEY", "").strip()
    if env_key:
        return env_key
    # Fall back to first configured server key (dev convenience only)
    if API_KEY_REQUIRED:
        keys = sorted(get_valid_keys())
        if keys:
            return keys[0]
    return None


class StarShieldAPI:
    def __init__(
        self,
        base_url: str = API_BASE_URL,
        timeout: float = 120.0,
        api_key: Optional[str] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.api_key = _resolve_client_api_key(api_key)

    def _headers(self) -> Dict[str, str]:
        h: Dict[str, str] = {}
        if self.api_key:
            h[API_KEY_HEADER_NAME] = self.api_key
        return h

    def _get(self, path: str, **params) -> Any:
        with httpx.Client(
            base_url=self.base_url,
            timeout=self.timeout,
            headers=self._headers(),
        ) as c:
            r = c.get(path, params={k: v for k, v in params.items() if v is not None})
            r.raise_for_status()
            return r.json()

    def _post(self, path: str, json: dict) -> Any:
        with httpx.Client(
            base_url=self.base_url,
            timeout=self.timeout,
            headers=self._headers(),
        ) as c:
            r = c.post(path, json=json)
            r.raise_for_status()
            return r.json()

    def health(self) -> dict:
        return self._get("/health")

    def search_objects(self, q: str, limit: int = 25) -> dict:
        return self._get("/objects/search", q=q, limit=limit)

    def get_passes(
        self,
        object: str,
        *,
        hours: float = 48,
        profile: Optional[str] = None,
        lat: Optional[float] = None,
        lon: Optional[float] = None,
        stargazer: bool = True,
        sort: str = "quality",
        min_score: float = 0,
        limit: int = 20,
    ) -> dict:
        return self._get(
            "/passes",
            object=object,
            hours=hours,
            profile=profile,
            lat=lat,
            lon=lon,
            stargazer=stargazer,
            sort=sort,
            min_score=min_score,
            limit=limit,
        )

    def scan_watchlist(self, watchlist_id: str = "iss-starlink", **kwargs) -> dict:
        body = {"watchlist_id": watchlist_id, **kwargs}
        return self._post("/watchlist/scan", json=body)

    def history_summary(self, days: int = 7) -> dict:
        return self._get("/history/summary", days=days)

    def history_passes(self, **params) -> dict:
        return self._get("/history/passes", **params)

    def history_conjunctions(self, **params) -> dict:
        return self._get("/history/conjunctions", **params)


def api_reachable(base_url: str = API_BASE_URL, timeout: float = 2.0) -> bool:
    try:
        with httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout) as c:
            r = c.get("/health")
            return r.status_code == 200
    except Exception:
        return False
