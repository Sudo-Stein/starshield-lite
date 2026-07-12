"""Tests for PDF and ICS export helpers."""

from datetime import datetime, timezone

import pytest

from services.export import (
    ExportError,
    passes_to_ics,
    passes_to_pdf,
    watchlist_to_pdf,
    write_ics,
    write_pdf,
)


def _sample_passes():
    t0 = datetime(2026, 7, 20, 2, 0, tzinfo=timezone.utc)
    from datetime import timedelta

    return [
        {
            "max_elevation": 55.0,
            "duration_s": 360.0,
            "sunlit": True,
            "dark_sky": True,
            "visible": True,
            "quality_score": 82,
            "quality_grade": "B",
            "quality": {
                "score": 82,
                "grade": "B",
                "breakdown": {"elevation": 70, "duration": 60},
            },
            "rise": {
                "time": t0,
                "alt": 10.0,
                "az": 200.0,
                "direction": "SSW",
            },
            "culmination": {
                "time": t0 + timedelta(minutes=3),
                "alt": 55.0,
                "az": 180.0,
                "direction": "S",
            },
            "set": {
                "time": t0 + timedelta(minutes=6),
                "alt": 10.0,
                "az": 160.0,
                "direction": "SSE",
            },
        }
    ]


def test_passes_to_ics_contains_vevent():
    ics = passes_to_ics(
        _sample_passes(),
        object_name="ISS (ZARYA)",
        location={"name": "Kingsland, GA", "lat": 30.8, "lon": -81.65},
    )
    assert "BEGIN:VCALENDAR" in ics
    assert "BEGIN:VEVENT" in ics
    assert "ISS" in ics
    assert "DTSTART:" in ics
    assert ics.endswith("\r\n") or ics.endswith("\n")


def test_write_ics(tmp_path):
    ics = passes_to_ics(_sample_passes(), object_name="ISS")
    path = write_ics(ics, tmp_path / "t.ics")
    assert path.exists()
    assert "VEVENT" in path.read_text()


def test_passes_to_pdf_bytes():
    fpdf = pytest.importorskip("fpdf")
    data = passes_to_pdf(
        _sample_passes(),
        object_name="ISS (ZARYA)",
        location={"name": "Kingsland, GA", "lat": 30.8, "lon": -81.65},
        hours=72,
        stargazer=False,
    )
    assert isinstance(data, (bytes, bytearray))
    assert data[:4] == b"%PDF"


def test_watchlist_to_pdf():
    pytest.importorskip("fpdf")
    report = {
        "watchlist_id": "iss-starlink",
        "watchlist_name": "ISS vs Starlink",
        "hours": 24,
        "threshold_km": 50,
        "pairs_scanned": 2,
        "summary": {
            "n_results": 1,
            "HIGH": 0,
            "MEDIUM": 1,
            "LOW": 0,
            "closest_km": 25.0,
            "closest_pair": "ISS / STARLINK-1",
        },
        "results": [
            {
                "sat1": "ISS (ZARYA)",
                "sat2": "STARLINK-1",
                "tca": datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc),
                "min_dist_km": 25.0,
                "rel_velocity_kms": 10.0,
                "risk": "MEDIUM",
            }
        ],
    }
    data = watchlist_to_pdf(report)
    assert data[:4] == b"%PDF"
    path = write_pdf(data, __import__("pathlib").Path("data") / "_test_export.pdf")
    assert path.exists()
    path.unlink(missing_ok=True)
