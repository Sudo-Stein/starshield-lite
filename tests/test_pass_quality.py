"""Tests for pass quality scoring."""

from datetime import datetime, timezone

from services.pass_quality import (
    calculate_pass_quality,
    darkness_score_from_sun_alt,
    get_grade,
    score_passes,
)


def _sample_pass(**kwargs):
    base = {
        "max_elevation": 60.0,
        "duration_s": 400.0,
        "sun_alt": -15.0,
        "sunlit": True,
        "object_name": "ISS (ZARYA)",
        "rise": {
            "time": datetime(2026, 7, 20, 2, 0, tzinfo=timezone.utc),
            "alt": 10.0,
            "az": 200.0,
            "direction": "SSW",
        },
        "culmination": {
            "time": datetime(2026, 7, 20, 2, 3, tzinfo=timezone.utc),
            "alt": 60.0,
            "az": 180.0,
            "direction": "S",
        },
        "set": {
            "time": datetime(2026, 7, 20, 2, 6, tzinfo=timezone.utc),
            "alt": 10.0,
            "az": 160.0,
            "direction": "SSE",
        },
    }
    base.update(kwargs)
    return base


def test_grades():
    assert get_grade(90) == "A"
    assert get_grade(75) == "B"
    assert get_grade(60) == "C"
    assert get_grade(45) == "D"
    assert get_grade(10) == "F"


def test_darkness_from_sun_alt():
    assert darkness_score_from_sun_alt(-20) == 100
    assert darkness_score_from_sun_alt(-15) > darkness_score_from_sun_alt(-8)
    assert darkness_score_from_sun_alt(30) == 0


def test_good_iss_pass_scores_high():
    q = calculate_pass_quality(_sample_pass(), location={"lat": 30.8, "lon": -81.65})
    assert q["score"] >= 70
    assert q["grade"] in ("A", "B", "C")
    assert "elevation" in q["breakdown"]
    assert q["sunlit_fraction"] >= 0.5


def test_daylight_pass_scores_lower():
    good = calculate_pass_quality(_sample_pass())
    day = calculate_pass_quality(
        _sample_pass(sun_alt=25.0, sunlit=True, object_name="ISS (ZARYA)")
    )
    assert day["score"] < good["score"]


def test_score_passes_sorts_and_filters():
    low = _sample_pass(max_elevation=12.0, sun_alt=10.0, object_name="DEB")
    high = _sample_pass(max_elevation=70.0, sun_alt=-18.0)
    out = score_passes([low, high], min_score=0, sort=True)
    assert out[0]["quality_score"] >= out[1]["quality_score"]
    filtered = score_passes([low, high], min_score=90, sort=True)
    # may be 0 or 1 depending on scores
    assert all(p["quality_score"] >= 90 for p in filtered)
