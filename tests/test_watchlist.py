"""Tests for watchlists and adaptive conjunction checks."""

from pathlib import Path

from core.simulator import _risk_level, check_conjunction
from services.object_index import get_index
from services.watchlist import (
    DEFAULT_WATCHLISTS,
    get_watchlist,
    list_watchlists,
    resolve_watchlist_pairs,
    results_to_rows,
    scan_watchlist,
)


def test_risk_bands():
    assert _risk_level(5) == "HIGH"
    assert _risk_level(25) == "MEDIUM"
    assert _risk_level(100) == "LOW"


def test_default_watchlists_seed(tmp_path, monkeypatch):
    import services.watchlist as wlmod

    path = tmp_path / "watchlists.json"
    monkeypatch.setattr(wlmod, "WATCHLIST_FILE", path)
    wls = list_watchlists(path)
    ids = {w.id for w in wls}
    assert "iss-starlink" in ids
    assert path.exists()


def test_resolve_iss_starlink_pairs():
    idx = get_index(force=True)
    if "starlink" not in idx.groups_loaded or "stations" not in idx.groups_loaded:
        return
    w = get_watchlist("iss-starlink")
    assert w is not None
    w.sample = 5
    pairs, meta = resolve_watchlist_pairs(w, idx)
    assert len(pairs) == 5
    assert meta.get("primary")


def test_check_conjunction_adaptive_fields():
    idx = get_index(force=True)
    if "stations" not in idx.groups_loaded:
        return
    iss = idx.get_satellite(idx.resolve("ISS"))
    # second station object if any
    stations = idx.satellites_in_group("stations")
    other = next((s for s in stations if s is not iss), None)
    if iss is None or other is None:
        return
    r = check_conjunction(iss, other, hours=6, steps=80, adaptive=True)
    assert "min_dist_km" in r
    assert "rel_velocity_kms" in r
    assert r["risk"] in ("HIGH", "MEDIUM", "LOW")
    assert r.get("adaptive") is True


def test_scan_watchlist_small():
    idx = get_index(force=True)
    if "starlink" not in idx.groups_loaded:
        return
    w = get_watchlist("iss-starlink")
    w.sample = 3
    report = scan_watchlist(
        w, hours=6, steps=60, adaptive=True, progress_every=0, index=idx
    )
    assert report["pairs_scanned"] == 3
    assert "summary" in report
    rows = results_to_rows(report["results"])
    assert isinstance(rows, list)
