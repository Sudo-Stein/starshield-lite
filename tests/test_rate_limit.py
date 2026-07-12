"""Rate-limit middleware unit tests."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.rate_limit import RateLimitMiddleware, _path_bucket, parse_limit
from config import API_RATE_LIMIT_ENABLED


def test_parse_limit_variants():
    assert parse_limit("60/minute") == (60, 60.0)
    assert parse_limit("20/hour") == (20, 3600.0)
    assert parse_limit("5/second") == (5, 1.0)
    assert parse_limit("100/day") == (100, 86400.0)
    n, w = parse_limit("not-a-limit")
    assert n == 60 and w == 60.0


def test_path_bucket_classification():
    assert _path_bucket("/health") == "public"
    assert _path_bucket("/docs") == "public"
    assert _path_bucket("/objects/search") == "public"
    assert _path_bucket("/watchlist") == "public"
    assert _path_bucket("/passes") == "heavy"
    assert _path_bucket("/export/passes/pdf") == "heavy"
    assert _path_bucket("/history/passes") == "default"
    assert _path_bucket("/watchlist/iss-starlink/scan") == "heavy"


class _TinyLimit(RateLimitMiddleware):
    """Two requests per minute for every bucket."""

    def __init__(self, app, *, enabled: bool = True, max_req: int = 2):
        super().__init__(app, enabled=enabled)
        self.limits = {
            "public": (max_req, 60.0),
            "default": (max_req, 60.0),
            "heavy": (max_req, 60.0),
        }


def test_middleware_returns_429_when_exceeded():
    app = FastAPI()

    @app.get("/health")
    def health():
        return {"ok": True}

    app.add_middleware(_TinyLimit, enabled=True, max_req=2)
    client = TestClient(app)

    assert client.get("/health").status_code == 200
    assert client.get("/health").status_code == 200
    r3 = client.get("/health")
    assert r3.status_code == 429
    body = r3.json()
    assert body.get("code") == "rate_limit_exceeded"
    assert "Retry-After" in r3.headers
    assert r3.headers.get("X-RateLimit-Remaining") == "0"


def test_middleware_sets_limit_headers_on_success():
    app = FastAPI()

    @app.get("/health")
    def health():
        return {"ok": True}

    app.add_middleware(_TinyLimit, enabled=True, max_req=5)
    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.headers.get("X-RateLimit-Limit") == "5"
    assert int(r.headers.get("X-RateLimit-Remaining", "-1")) >= 0


def test_middleware_can_be_disabled():
    app = FastAPI()

    @app.get("/health")
    def health():
        return {"ok": True}

    app.add_middleware(_TinyLimit, enabled=False, max_req=1)
    client = TestClient(app)
    for _ in range(5):
        assert client.get("/health").status_code == 200


def test_main_app_exposes_rate_limit_headers():
    """Smoke: real app middleware adds limit headers when enabled."""
    if not API_RATE_LIMIT_ENABLED:
        pytest.skip("rate limiting disabled in env")

    from api.main import app

    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200
    assert "X-RateLimit-Limit" in r.headers
    assert "X-RateLimit-Remaining" in r.headers
