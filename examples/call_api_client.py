#!/usr/bin/env python3
"""Call the StarShield Lite HTTP API from Python (httpx).

Use this when you run the FastAPI server and want a minimal client for health
checks, object search, and pass prediction — the same pattern as external
integrations.

Prerequisites::

    pip install -e ".[dev]"          # provides httpx
    python main.py api               # other terminal (or: starshield-api)
    # if STARSHIELD_API_KEY_REQUIRED=1:
    #   export STARSHIELD_API_KEY=your-key

Usage::

    python examples/call_api_client.py
    python examples/call_api_client.py --base-url http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description="Call StarShield API from Python")
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8000",
        help="API base URL (default: http://127.0.0.1:8000)",
    )
    args = parser.parse_args()

    try:
        import httpx
    except ImportError:
        print("httpx is required: pip install httpx", file=sys.stderr)
        return 1

    base = args.base_url.rstrip("/")
    print(f"Talking to {base} …\n")

    try:
        # --- Option A: raw httpx (no StarShield imports needed) ---
        r = httpx.get(f"{base}/health", timeout=30.0)
        r.raise_for_status()
        health = r.json()
        print("Health:", health)

        r = httpx.get(
            f"{base}/objects/search",
            params={"q": "ISS", "limit": 3},
            timeout=30.0,
        )
        r.raise_for_status()
        search = r.json()
        print(f"\nSearch 'ISS': {search.get('count')} hit(s)")
        for hit in search.get("results") or []:
            print(f"  · {hit.get('name')}  NORAD {hit.get('norad')}")

        # Passes may 404 if catalogs are empty — that is OK for this example
        r = httpx.get(
            f"{base}/passes",
            params={
                "object": "ISS",
                "hours": 24,
                "stargazer": "false",
                "sort": "quality",
                "limit": 3,
                "persist": "false",
            },
            timeout=120.0,
        )
        if r.status_code == 200:
            body = r.json()
            print(f"\nPasses for {body.get('object_name')}: {body.get('count')}")
            for p in (body.get("passes") or [])[:3]:
                q = p.get("quality") or {}
                print(
                    f"  · grade {q.get('grade')} {q.get('score')}  "
                    f"max el {p.get('max_elevation')}"
                )
        else:
            print(f"\nPasses skipped (HTTP {r.status_code}): {r.text[:200]}")

        # --- Option B: built-in client helper ---
        print("\n--- Using api.client.StarShieldAPI ---")
        from api.client import StarShieldAPI

        client = StarShieldAPI(base_url=base)
        print("health()", client.health().get("status"))
        print("search_objects('HST') count:", client.search_objects("HST", limit=2).get("count"))

    except httpx.ConnectError:
        print(
            f"Could not connect to {base}.\n"
            "Start the API first:\n"
            "  python main.py api\n"
            "  # then re-run this script",
            file=sys.stderr,
        )
        return 1
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
