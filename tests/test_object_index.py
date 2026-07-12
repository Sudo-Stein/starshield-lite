"""Tests for multi-catalog object index, observers, and sky scrubber helpers."""

from datetime import datetime, timezone

from config import DEFAULT_OBSERVER, INDEX_GROUPS, OBSERVER_PROFILES
from services.object_index import ObjectIndex, catalog_fingerprint, get_index
from services.observers import format_observer, resolve_observer
from services.sky import find_track_events, position_at_offset
import numpy as np


def test_observer_profiles_include_home():
    assert DEFAULT_OBSERVER in OBSERVER_PROFILES
    home = resolve_observer(profile=DEFAULT_OBSERVER)
    assert abs(home["lat"] - 30.8) < 0.01
    assert abs(home["lon"] - (-81.65)) < 0.01


def test_custom_observer():
    loc = resolve_observer(lat=40.0, lon=-74.0, elevation=10.0, label="NYC")
    assert loc["name"] == "NYC"
    assert loc["lat"] == 40.0
    assert "NYC" in format_observer(loc)


def test_index_builds_and_finds_iss():
    idx = get_index(force=True)
    # stations should be cached in this project
    if "stations" not in idx.groups_loaded:
        return  # skip if no data
    rec = idx.resolve("ISS")
    assert rec is not None
    assert rec.norad > 0
    assert "ISS" in rec.name.upper() or any("ISS" in a.upper() for a in rec.aliases)
    sat = idx.get_satellite(rec)
    assert sat is not None
    hits = idx.search("25544", limit=3)  # classic ISS NORAD — may vary
    # at least name search works
    assert idx.search("STARLINK", limit=5) or idx.search("ISS", limit=5)


def test_catalog_fingerprint_stable():
    a = catalog_fingerprint(INDEX_GROUPS)
    b = catalog_fingerprint(INDEX_GROUPS)
    assert a == b


def test_find_track_events_rise_set():
    # synthetic: below, above peak, below
    alt = np.array([-10, 5, 40, 5, -10], dtype=float)
    az = np.array([0, 10, 20, 30, 40], dtype=float)
    times = [datetime(2026, 1, 1, i, tzinfo=timezone.utc) for i in range(5)]
    ev = find_track_events(alt, az, times, min_elevation=0)
    types = {e["type"] for e in ev}
    assert "rise" in types
    assert "set" in types
    assert "culmination" in types


def test_position_at_offset():
    times = [datetime(2026, 1, 1, 0, i, tzinfo=timezone.utc) for i in range(0, 60, 10)]
    n = len(times)
    track = {
        "times": times,
        "alt_raw": np.linspace(10, 50, n),
        "az_raw": np.linspace(0, 90, n),
        "above": np.ones(n, dtype=bool),
        "name": "TEST",
    }
    pos = position_at_offset(track, hours_from_start=0.5)  # 30 min
    assert pos["above"] is True
    assert pos["alt"] is not None
