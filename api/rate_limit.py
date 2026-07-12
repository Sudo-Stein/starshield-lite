"""Configurable per-IP rate limiting middleware for FastAPI.

Uses an in-memory sliding window (good enough for single-process demos).
Disable with ``STARSHIELD_API_RATE_LIMIT=0``.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Callable, Deque, Dict, Optional, Tuple

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from config import (
    API_RATE_LIMIT_DEFAULT,
    API_RATE_LIMIT_ENABLED,
    API_RATE_LIMIT_HEAVY,
    API_RATE_LIMIT_PUBLIC,
)


def parse_limit(spec: str) -> Tuple[int, float]:
    """Parse '60/minute' or '20/minute' → (max_requests, window_seconds)."""
    spec = (spec or "60/minute").strip().lower()
    try:
        count_s, unit = spec.split("/", 1)
        count = int(count_s)
    except ValueError:
        return 60, 60.0
    unit = unit.strip()
    if unit.startswith("second"):
        window = 1.0
    elif unit.startswith("minute"):
        window = 60.0
    elif unit.startswith("hour"):
        window = 3600.0
    elif unit.startswith("day"):
        window = 86400.0
    else:
        window = 60.0
    return max(1, count), window


def _client_ip(request: Request) -> str:
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        return xff.split(",")[0].strip()
    if request.client:
        return request.client.host or "unknown"
    return "unknown"


def _path_bucket(path: str) -> str:
    """Classify path → public | default | heavy."""
    path = path.rstrip("/") or "/"
    if path in ("/", "/health", "/docs", "/openapi.json", "/redoc"):
        return "public"
    if path.startswith("/objects"):
        return "public"
    # Debris read endpoints are public; fetch/scan are heavy
    if path in ("/debris/groups", "/debris/status") or path.startswith("/debris/search"):
        return "public"
    if path.startswith("/debris"):
        return "heavy"
    # Heavy compute routes first (scan can be nested: /watchlist/{id}/scan)
    if path.startswith("/passes") or path.startswith("/export"):
        return "heavy"
    if path.endswith("/scan") or path == "/watchlist/scan":
        return "heavy"
    if path == "/watchlist" or path.startswith("/watchlist/"):
        return "public"
    if path.startswith("/history"):
        return "default"
    return "default"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Simple sliding-window rate limiter."""

    def __init__(self, app, enabled: Optional[bool] = None):
        super().__init__(app)
        self.enabled = API_RATE_LIMIT_ENABLED if enabled is None else enabled
        self.limits = {
            "public": parse_limit(API_RATE_LIMIT_PUBLIC),
            "default": parse_limit(API_RATE_LIMIT_DEFAULT),
            "heavy": parse_limit(API_RATE_LIMIT_HEAVY),
        }
        # key → deque of request timestamps
        self._hits: Dict[str, Deque[float]] = defaultdict(deque)

    def _allow(self, key: str, max_req: int, window: float) -> Tuple[bool, int, int]:
        now = time.time()
        q = self._hits[key]
        cutoff = now - window
        while q and q[0] < cutoff:
            q.popleft()
        if len(q) >= max_req:
            retry = int(max(1, window - (now - q[0]))) if q else int(window)
            return False, 0, retry
        q.append(now)
        remaining = max(0, max_req - len(q))
        return True, remaining, int(window)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if not self.enabled:
            return await call_next(request)

        # Never rate-limit OPTIONS
        if request.method == "OPTIONS":
            return await call_next(request)

        bucket = _path_bucket(request.url.path)
        max_req, window = self.limits[bucket]
        ip = _client_ip(request)
        key = f"{ip}:{bucket}"
        ok, remaining, retry_after = self._allow(key, max_req, window)
        if not ok:
            return JSONResponse(
                status_code=429,
                content={
                    "detail": (
                        f"Rate limit exceeded ({max_req} requests per "
                        f"{int(window)}s for '{bucket}' routes). "
                        f"Retry after {retry_after}s."
                    ),
                    "code": "rate_limit_exceeded",
                    "retry_after": retry_after,
                },
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(max_req),
                    "X-RateLimit-Remaining": "0",
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(max_req)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response


def rate_limit_status() -> dict:
    return {
        "enabled": bool(API_RATE_LIMIT_ENABLED),
        "public": API_RATE_LIMIT_PUBLIC,
        "default": API_RATE_LIMIT_DEFAULT,
        "heavy": API_RATE_LIMIT_HEAVY,
    }
