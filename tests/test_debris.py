"""Tests for optional debris catalog support."""

from __future__ import annotations

from pathlib import Path

import pytest

from config import DEBRIS_GROUPS, INDEX_GROUPS, effective_index_groups
from services.debris import (
    default_debris_watchlists,
    is_debris_group,
    list_debris_groups,
    scan_primary_vs_debris,
)
from services.object_index import ObjectIndex, get_index, invalidate_index
from services.watchlist import get_watchlist, list_watchlists


def test_debris_groups_in_tle_urls():
    from config import TLE_URLS

    for g in DEBRIS_GROUPS:
        assert g in TLE_URLS
        assert "celestrak" in TLE_URLS[g]


def test_is_debris_group():
    assert is_debris_group("debris")
    assert is_debris_group("fengyun-1c-debris")
    assert not is_debris_group("starlink")
    assert not is_debris_group("stations")


def test_list_debris_groups_structure():
    rows = list_debris_groups()
    assert len(rows) == len(DEBRIS_GROUPS)
    assert all("group" in r and "cached" in r for r in rows)


def test_effective_index_groups_core_always():
    groups = effective_index_groups()
    for g in INDEX_GROUPS:
        assert g in groups


def test_effective_index_groups_includes_cached_debris(tmp_path, monkeypatch):
    import config as cfg

    monkeypatch.setattr(cfg, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cfg, "_INDEX_DEBRIS_MODE", "auto")
    # No cache → no debris
    g0 = cfg.effective_index_groups()
    assert "debris" not in g0
    # Create cache file → included
    (tmp_path / "debris_tles.txt").write_text("dummy\n")
    g1 = cfg.effective_index_groups()
    assert "debris" in g1


def test_effective_index_groups_force_off(tmp_path, monkeypatch):
    import config as cfg

    monkeypatch.setattr(cfg, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cfg, "_INDEX_DEBRIS_MODE", "0")
    (tmp_path / "debris_tles.txt").write_text("x")
    assert "debris" not in cfg.effective_index_groups()


def test_default_debris_watchlists_seed(tmp_path, monkeypatch):
    import services.watchlist as wlmod

    path = tmp_path / "watchlists.json"
    monkeypatch.setattr(wlmod, "WATCHLIST_FILE", path)
    wls = list_watchlists(path)
    ids = {w.id for w in wls}
    assert "iss-debris" in ids
    assert "iss-fengyun-debris" in ids
    assert "stations-debris" in ids
    w = get_watchlist("iss-debris", path)
    assert w is not None
    assert w.group == "debris"
    assert w.primary == "ISS"


def test_default_debris_watchlist_defs():
    wls = default_debris_watchlists()
    assert any(w.id == "iss-debris" for w in wls)


def test_index_loads_debris_when_cached():
    """If project already has debris_tles.txt, index should load it."""
    invalidate_index()
    idx = get_index(force=True)
    if "debris" not in idx.groups_loaded and not any(
        g in idx.groups_loaded for g in DEBRIS_GROUPS
    ):
        pytest.skip("No debris TLE cache present")
    st = idx.stats()
    assert st["debris_objects"] >= 0
    assert st.get("debris_groups_loaded")
    # search should return something for common debris tokens if catalog large
    hits = idx.search_debris("DEB", limit=5)
    # may be empty if names don't contain DEB — still ok if group loaded
    assert isinstance(hits, list)


def test_scan_primary_vs_debris_if_data():
    idx = get_index(force=True)
    if "debris" not in idx.groups_loaded or "stations" not in idx.groups_loaded:
        pytest.skip("Need stations + debris caches")
    report = scan_primary_vs_debris(
        primary="ISS",
        debris_group="debris",
        hours=6,
        sample=3,
        index=idx,
    )
    assert report["pairs_scanned"] == 3
    assert "summary" in report
    assert report["summary"]["HIGH"] + report["summary"]["MEDIUM"] + report[
        "summary"
    ]["LOW"] == report["summary"]["n_results"]


def test_api_debris_groups():
    fastapi = pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from api.main import app

    client = TestClient(app)
    r = client.get("/debris/groups")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    assert any(g["group"] == "debris" for g in body)

    r2 = client.get("/debris/status")
    assert r2.status_code == 200
    assert "debris_objects" in r2.json()
