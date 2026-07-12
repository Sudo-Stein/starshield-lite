"""Basic smoke tests for StarShield Lite."""

from config import BASE_DIR, DATA_DIR, TLE_URLS, LOCATION, STARGAZER_SUN_ALT_MAX
from core.predictor import (
    az_to_direction,
    find_satellite_by_name,
    format_pass_row,
)


def test_config_paths():
    assert BASE_DIR.exists()
    assert DATA_DIR.exists()
    assert DATA_DIR == BASE_DIR / "data"


def test_tle_urls_defined():
    assert "active" in TLE_URLS
    assert "starlink" in TLE_URLS
    assert "stations" in TLE_URLS
    for url in TLE_URLS.values():
        assert url.startswith("https://")


def test_location_keys():
    assert {"lat", "lon", "elevation"} <= set(LOCATION.keys())


def test_immutable_log_append(tmp_path, monkeypatch):
    from utils.immutable_log import ImmutableLog
    import utils.immutable_log as imlog

    monkeypatch.setattr(imlog, "DATA_DIR", tmp_path)
    log = ImmutableLog("test.log")
    h1 = log.append({"action": "test", "n": 1})
    h2 = log.append({"action": "test", "n": 2})
    assert h1 != h2
    assert (tmp_path / "test.log").exists()
    text = (tmp_path / "test.log").read_text(encoding="utf-8")
    assert "test" in text


def test_az_to_direction():
    assert az_to_direction(0) == "N"
    assert az_to_direction(90) == "E"
    assert az_to_direction(180) == "S"
    assert az_to_direction(270) == "W"


class _FakeSat:
    def __init__(self, name):
        self.name = name


def test_find_satellite_by_name():
    sats = [
        _FakeSat("STARLINK-1234"),
        _FakeSat("ISS (ZARYA)"),
        _FakeSat("ISS DEB"),
    ]
    assert find_satellite_by_name(sats, "ISS").name == "ISS (ZARYA)"
    assert find_satellite_by_name(sats, "starlink-1234").name == "STARLINK-1234"
    assert find_satellite_by_name(sats, "nope") is None


def test_format_pass_row_emptyish():
    from datetime import datetime, timezone

    row = format_pass_row(
        {
            "rise": None,
            "culmination": {
                "time": datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
                "alt": 45.0,
                "az": 180.0,
                "direction": "S",
            },
            "set": None,
            "max_elevation": 45.0,
            "duration_s": None,
            "sun_alt": -12.0,
            "sunlit": True,
            "dark_sky": True,
            "visible": True,
        }
    )
    assert row["max_el"] == "45.0°"
    assert "S" in row["az_max"]
    assert row["rise"] == "—"
    assert "★" in row["sky"]

    local_row = format_pass_row(
        {
            "rise": None,
            "culmination": {
                "time": datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
                "alt": 45.0,
                "az": 180.0,
                "direction": "S",
            },
            "set": None,
            "max_elevation": 45.0,
            "duration_s": None,
            "sun_alt": -12.0,
            "sunlit": True,
            "dark_sky": True,
            "visible": True,
        },
        local=True,
    )
    # Local string should include a timezone abbrev or offset-ish token
    assert local_row["culmination"] != "—"


def test_format_pass_row_daylight():
    row = format_pass_row(
        {
            "rise": None,
            "culmination": None,
            "set": None,
            "max_elevation": 20.0,
            "duration_s": 120,
            "sun_alt": 30.0,
            "sunlit": True,
            "dark_sky": False,
            "visible": False,
        }
    )
    assert row["sky"] == "daylight"


def test_stargazer_threshold_config():
    assert STARGAZER_SUN_ALT_MAX <= 0


def test_risk_level_and_html_report(tmp_path, monkeypatch):
    from core import simulator as sim
    import core.simulator as sim_mod

    monkeypatch.setattr(sim_mod, "DATA_DIR", tmp_path)

    assert sim._risk_level(5) == "HIGH"
    assert sim._risk_level(25) == "MEDIUM"
    assert sim._risk_level(100) == "LOW"

    sample = {
        "sat1": "ISS (ZARYA)",
        "sat2": "STARLINK-TEST",
        "tca": __import__("datetime").datetime(2026, 7, 12, 12, 0, 0),
        "min_dist_km": 42.5,
        "risk": "MEDIUM",
        "threshold_km": 50,
        "high_risk_km": 10,
        "hours": 24,
        "times": [],
        "distances": [],
        "below_threshold": True,
    }
    path = sim.generate_html_report(sample, open_browser=False)
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "ISS" in text
    assert "42.5" in text
