"""Download and cache TLE data from CelesTrak (with polite retries)."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

import requests

from config import DATA_DIR, TLE_URLS, __version__

# CelesTrak rate-limits aggressive / empty UAs — be a good citizen.
USER_AGENT = (
    f"StarShieldLite/{__version__} "
    "(+https://github.com/Sudo-Stein/starshield-lite; research)"
)
DEFAULT_TIMEOUT = 60
MAX_RETRIES = 3
BACKOFF_SECONDS = (1.5, 4.0, 10.0)


def fetch_tles(
    group: str = "active",
    *,
    force: bool = False,
    use_cache_on_error: bool = True,
) -> Path:
    """Download TLE data for a CelesTrak group and cache it under data/.

    On HTTP 403/429 (rate limit) retries with exponential backoff. If the
    network still fails and a previous cache exists, returns the cache when
    ``use_cache_on_error`` is True (with a warning printed).
    """
    url = TLE_URLS.get(group, TLE_URLS["active"])
    filepath = DATA_DIR / f"{group}_tles.txt"

    if filepath.exists() and not force:
        # Always allow re-fetch when explicitly called; callers that only need
        # data should use ensure_tles(). Here we always attempt network first.
        pass

    print(f"Fetching TLEs from {url}...")
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/plain, text/*, */*",
    }
    last_err: Optional[Exception] = None

    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(url, headers=headers, timeout=DEFAULT_TIMEOUT)
            if resp.status_code in (403, 429):
                wait = BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)]
                print(
                    f"  CelesTrak {resp.status_code} (rate limit?) — "
                    f"retry in {wait:g}s [{attempt + 1}/{MAX_RETRIES}]"
                )
                time.sleep(wait)
                last_err = requests.HTTPError(
                    f"{resp.status_code} for {url}", response=resp
                )
                continue
            resp.raise_for_status()
            text = resp.text
            if not text.strip():
                raise ValueError("Empty TLE response from CelesTrak")

            with open(filepath, "w", encoding="utf-8") as f:
                f.write(text)

            n_objects = len(text.strip().splitlines()) // 3
            print(f"Saved {n_objects} objects → {filepath}")
            return filepath
        except (requests.RequestException, ValueError) as exc:
            last_err = exc
            wait = BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)]
            if attempt + 1 < MAX_RETRIES:
                print(f"  Fetch error: {exc} — retry in {wait:g}s")
                time.sleep(wait)

    if use_cache_on_error and filepath.exists():
        print(
            f"  ⚠ Network fetch failed ({last_err}); "
            f"using cached {filepath.name}"
        )
        return filepath

    raise RuntimeError(
        f"Failed to fetch TLEs for '{group}' after {MAX_RETRIES} attempts: {last_err}"
    )


def ensure_tles(group: str = "active", *, refresh: bool = False) -> Path:
    """Return path to cached TLEs, fetching only if missing or ``refresh``."""
    filepath = DATA_DIR / f"{group}_tles.txt"
    if filepath.exists() and not refresh:
        return filepath
    return fetch_tles(group, force=refresh, use_cache_on_error=True)
