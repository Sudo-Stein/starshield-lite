"""Tests for linked starmap / ground-track visualization helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from services.visualization import (
    advance_scrub,
    apply_focus_to_session_state,
    event_near_scrub,
    focus_quality_label,
    format_scrub_clock,
    hours_to_minutes,
    minutes_to_hours,
    pass_to_starmap_focus,
    _is_focus,
)


def test_pass_to_starmap_focus_window():
    now = datetime(2026, 7, 12, 12, 0, tzinfo=timezone.utc)
    p = {
        "rise": {"time": now + timedelta(hours=3)},
        "culmination": {"time": now + timedelta(hours=3, minutes=6)},
        "set": {"time": now + timedelta(hours=3, minutes=12)},
        "max_elevation": 62.0,
        "quality_grade": "B",
        "quality_score": 74,
    }
    focus = pass_to_starmap_focus(p, object_name="ISS (ZARYA)", norad=25544, now=now)
    assert focus["object"] == "ISS (ZARYA)"
    assert abs(focus["scrub_hours"] - (3 + 6 / 60)) < 0.02
    assert focus["window_hours"] >= focus["scrub_hours"]
    assert focus["quality_grade"] == "B"
    assert focus["focus_mode"] is True
    assert focus["rise_hours"] is not None
    assert focus["set_hours"] is not None


def test_focus_quality_label():
    assert focus_quality_label({"quality_grade": "A", "quality_score": 90}) == "A 90"
    assert focus_quality_label(None) == ""


def test_scrub_clock_and_units():
    assert hours_to_minutes(1.5) == 90.0
    assert minutes_to_hours(90) == 1.5
    clock = format_scrub_clock(
        2.5, now=datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    )
    assert "UTC" in clock["utc"]
    assert clock["offset"]


def test_advance_scrub():
    m, end = advance_scrub(58, step_minutes=5, max_minutes=60)
    assert m == 60 and end is True
    m2, end2 = advance_scrub(10, step_minutes=2, max_minutes=60)
    assert m2 == 12 and end2 is False


def test_apply_focus_to_session_state():
    state = {}
    focus = pass_to_starmap_focus(
        {
            "culmination": {
                "time": datetime.now(timezone.utc) + timedelta(hours=1)
            },
            "quality_grade": "A",
            "quality_score": 91,
            "max_elevation": 40,
        },
        object_name="ISS",
    )
    apply_focus_to_session_state(state, focus)
    assert state["sky_objects"] == ["ISS"]
    assert "sky_scrub_minutes" in state
    assert state["sky_focus_mode"] is True
    assert state["sky_jump_nonce"] == 1
    apply_focus_to_session_state(state, focus)
    assert state["sky_jump_nonce"] == 2


def test_is_focus_alias():
    assert _is_focus("ISS (ZARYA)", "ISS")
    assert _is_focus("ISS", "ISS (ZARYA)")
    assert not _is_focus("STARLINK-1", "ISS")


def test_event_near_scrub():
    now = datetime(2026, 7, 12, 12, 0, tzinfo=timezone.utc)
    track = {
        "name": "ISS",
        "start": now,
        "hours": 2,
        "times": [now + timedelta(minutes=i) for i in range(0, 120, 5)],
        "events": [
            {
                "type": "culmination",
                "time": now + timedelta(minutes=30),
                "alt": 50,
                "az": 180,
            }
        ],
    }
    near = event_near_scrub([track], scrub_hours=0.5, window_minutes=10)
    assert len(near) == 1
    assert near[0]["type"] == "culmination"
