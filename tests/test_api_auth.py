"""API key authentication tests."""

import os

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient


@pytest.fixture
def auth_client(tmp_path, monkeypatch):
    """App client with auth enabled and a known key."""
    monkeypatch.setenv("STARSHIELD_API_KEY_REQUIRED", "1")
    monkeypatch.setenv("STARSHIELD_API_KEYS", "test-secret-key-abc")
    # Reload config + security modules that read env at import time
    import importlib
    import config

    importlib.reload(config)
    import api.security as security

    importlib.reload(security)
    import api.main as api_main

    importlib.reload(api_main)
    # Ensure keys visible
    assert "test-secret-key-abc" in security.get_valid_keys()
    assert security.auth_enabled() is True
    return TestClient(api_main.app)


@pytest.fixture
def open_client(monkeypatch):
    """Auth disabled."""
    monkeypatch.setenv("STARSHIELD_API_KEY_REQUIRED", "0")
    monkeypatch.delenv("STARSHIELD_API_KEYS", raising=False)
    import importlib
    import config

    importlib.reload(config)
    import api.security as security

    importlib.reload(security)
    import api.main as api_main

    importlib.reload(api_main)
    return TestClient(api_main.app)


def test_public_health_without_key(auth_client):
    r = auth_client.get("/health")
    assert r.status_code == 200
    assert r.json()["api_key_required"] is True


def test_public_objects_search_without_key(auth_client):
    r = auth_client.get("/objects/search", params={"q": "ISS", "limit": 3})
    assert r.status_code == 200


def test_passes_requires_key(auth_client):
    r = auth_client.get(
        "/passes",
        params={"object": "ISS", "hours": 6, "persist": False, "stargazer": False},
    )
    assert r.status_code == 401
    assert "API key" in r.json()["detail"] or "key" in r.json()["detail"].lower()


def test_passes_rejects_bad_key(auth_client):
    r = auth_client.get(
        "/passes",
        params={"object": "ISS", "hours": 6, "persist": False},
        headers={"X-API-Key": "wrong-key"},
    )
    assert r.status_code == 401


def test_passes_accepts_valid_key(auth_client):
    r = auth_client.get(
        "/passes",
        params={
            "object": "ISS",
            "hours": 12,
            "persist": False,
            "stargazer": False,
            "limit": 2,
        },
        headers={"X-API-Key": "test-secret-key-abc"},
    )
    # 200 if ISS in index, 404 if not
    assert r.status_code in (200, 404)


def test_history_requires_key(auth_client):
    r = auth_client.get("/history/summary")
    assert r.status_code == 401


def test_history_with_key(auth_client):
    r = auth_client.get(
        "/history/summary",
        headers={"X-API-Key": "test-secret-key-abc"},
    )
    assert r.status_code == 200


def test_watchlist_scan_requires_key(auth_client):
    r = auth_client.post(
        "/watchlist/scan",
        json={"watchlist_id": "iss-starlink", "hours": 6, "sample": 2, "persist": False},
    )
    assert r.status_code == 401


def test_watchlist_list_public(auth_client):
    r = auth_client.get("/watchlist")
    assert r.status_code == 200


def test_auth_disabled_passes_open(open_client):
    r = open_client.get(
        "/passes",
        params={"object": "ISS", "hours": 6, "persist": False, "stargazer": False},
    )
    assert r.status_code in (200, 404)


def test_generate_api_key(tmp_path, monkeypatch):
    keys_file = tmp_path / "api_keys.txt"
    monkeypatch.setattr("config.API_KEYS_FILE", keys_file)
    import importlib
    import api.security as security

    importlib.reload(security)
    # patch path after reload
    security.API_KEYS_FILE = keys_file  # type: ignore
    key = security.generate_api_key(persist=True, label="test")
    assert len(key) > 20
    assert keys_file.exists()
    assert key in keys_file.read_text()
