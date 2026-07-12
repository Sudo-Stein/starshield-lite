"""FastAPI endpoint smoke tests (TestClient)."""

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from api.main import app


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "index_objects" in body


def test_root(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "docs" in r.json()


def test_objects_search(client):
    r = client.get("/objects/search", params={"q": "ISS", "limit": 5})
    assert r.status_code == 200
    body = r.json()
    assert body["query"] == "ISS"
    assert "results" in body
    # index may be empty in CI without TLEs
    if body["count"] > 0:
        assert "norad" in body["results"][0]
        assert "name" in body["results"][0]


def test_passes_missing_object(client):
    r = client.get(
        "/passes",
        params={"object": "ZZZ_NOT_A_REAL_SAT_99999", "hours": 6, "persist": False},
    )
    assert r.status_code == 404


def test_passes_iss_if_available(client):
    # First check index has ISS
    s = client.get("/objects/search", params={"q": "ISS", "limit": 1})
    if s.json().get("count", 0) == 0:
        pytest.skip("No TLEs in index")
    r = client.get(
        "/passes",
        params={
            "object": "ISS",
            "hours": 24,
            "stargazer": False,
            "sort": "quality",
            "limit": 3,
            "persist": False,
            "profile": "Kingsland, GA",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["object_name"]
    assert "passes" in body
    assert body["observer"]["lat"]


def test_watchlist_list(client):
    r = client.get("/watchlist")
    assert r.status_code == 200
    assert isinstance(r.json(), list)
    assert any(w["id"] == "iss-starlink" for w in r.json())


def test_watchlist_scan_small(client):
    r = client.post(
        "/watchlist/scan",
        json={
            "watchlist_id": "iss-starlink",
            "hours": 6,
            "sample": 2,
            "persist": False,
            "max_results": 5,
        },
    )
    # 404 if no starlink/stations TLEs; 200 otherwise
    if r.status_code == 404:
        pytest.skip("watchlist not resolvable")
    assert r.status_code == 200
    body = r.json()
    assert body["watchlist_id"] == "iss-starlink"
    assert "results" in body
    assert "summary" in body


def test_history_summary(client):
    r = client.get("/history/summary", params={"days": 7})
    assert r.status_code == 200
    body = r.json()
    assert "passes_logged" in body
    assert "conjunctions_logged" in body


def test_history_passes_pagination(client):
    r = client.get("/history/passes", params={"limit": 5, "offset": 0, "days": 30})
    assert r.status_code == 200
    body = r.json()
    assert body["limit"] == 5
    assert "items" in body


def test_history_conjunctions(client):
    r = client.get(
        "/history/conjunctions",
        params={"object": "ISS", "days": 30, "limit": 10},
    )
    assert r.status_code == 200
    assert "items" in r.json()
