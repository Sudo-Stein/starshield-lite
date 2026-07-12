"""Tests for SQLite persistence layer."""

from datetime import datetime, timezone

from services.database import (
    ensure_db,
    log_conjunction_event,
    log_pass,
    log_passes_batch,
    log_watchlist_scan,
    query_conjunctions,
    query_recent_passes,
    summary_stats,
)


def _sample_scored_pass(score=85, grade="A", name="ISS (ZARYA)"):
    return {
        "object_name": name,
        "max_elevation": 55.0,
        "duration_s": 360.0,
        "sunlit_fraction": 0.9,
        "sun_alt": -12.0,
        "visible": True,
        "quality_score": score,
        "quality_grade": grade,
        "quality": {
            "score": score,
            "grade": grade,
            "breakdown": {"elevation": 60},
            "sunlit_fraction": 0.9,
            "max_elevation": 55.0,
        },
        "rise": {"time": datetime(2026, 7, 20, 1, 0, tzinfo=timezone.utc)},
        "culmination": {
            "time": datetime(2026, 7, 20, 1, 3, tzinfo=timezone.utc),
            "az": 180.0,
        },
        "set": {"time": datetime(2026, 7, 20, 1, 6, tzinfo=timezone.utc)},
    }


def test_init_and_log_pass(tmp_path):
    db = tmp_path / "test.db"
    ensure_db(db)
    rid = log_pass(
        _sample_scored_pass(90, "A"),
        object_name="ISS (ZARYA)",
        norad=25544,
        location={"name": "Kingsland, GA", "lat": 30.8, "lon": -81.65, "elevation": 5},
        stargazer=True,
        source="test",
        force=True,
        db_path=db,
    )
    assert rid is not None
    rows = query_recent_passes(limit=5, db_path=db)
    assert len(rows) == 1
    assert rows[0]["object_name"] == "ISS (ZARYA)"
    assert rows[0]["quality_score"] == 90


def test_skip_low_quality_pass(tmp_path, monkeypatch):
    import services.database as dbmod

    monkeypatch.setattr(dbmod, "DB_LOG_ENABLED", True)
    monkeypatch.setattr(dbmod, "DB_LOG_PASS_MIN_SCORE", 70)
    db = tmp_path / "test2.db"
    rid = log_pass(
        _sample_scored_pass(40, "D"),
        force=False,
        db_path=db,
    )
    assert rid is None
    assert query_recent_passes(db_path=db) == []


def test_log_conjunction_and_summary(tmp_path, monkeypatch):
    import services.database as dbmod

    monkeypatch.setattr(dbmod, "DB_LOG_ENABLED", True)
    db = tmp_path / "test3.db"
    ensure_db(db)
    rid = log_conjunction_event(
        {
            "sat1": "ISS (ZARYA)",
            "sat2": "STARLINK-1008",
            "norad1": 25544,
            "norad2": 44713,
            "tca": datetime(2026, 7, 12, 12, 0, tzinfo=timezone.utc),
            "min_dist_km": 8.5,
            "rel_velocity_kms": 10.2,
            "risk": "HIGH",
            "hours": 24,
        },
        watchlist_id="iss-starlink",
        source="test",
        force=True,
        db_path=db,
    )
    assert rid is not None
    rows = query_conjunctions(object_name="ISS", days=30, db_path=db)
    assert len(rows) >= 1
    assert rows[0]["risk"] == "HIGH"
    stats = summary_stats(days=30, db_path=db)
    assert stats["conjunctions_logged"] >= 1
    assert stats["high_risk"] >= 1


def test_watchlist_scan_persist(tmp_path, monkeypatch):
    import services.database as dbmod

    monkeypatch.setattr(dbmod, "DB_LOG_ENABLED", True)
    db = tmp_path / "test4.db"
    report = {
        "watchlist_id": "iss-starlink",
        "watchlist_name": "ISS vs Starlink",
        "hours": 12,
        "threshold_km": 50,
        "pairs_scanned": 2,
        "summary": {
            "n_results": 2,
            "HIGH": 0,
            "MEDIUM": 1,
            "LOW": 1,
            "closest_km": 25.0,
            "closest_pair": "ISS / STARLINK-1",
        },
        "results": [
            {
                "sat1": "ISS (ZARYA)",
                "sat2": "STARLINK-1",
                "norad1": 25544,
                "norad2": 1,
                "tca": datetime(2026, 7, 12, 15, 0, tzinfo=timezone.utc),
                "min_dist_km": 25.0,
                "rel_velocity_kms": 9.0,
                "risk": "MEDIUM",
                "hours": 12,
            },
            {
                "sat1": "ISS (ZARYA)",
                "sat2": "STARLINK-2",
                "norad1": 25544,
                "norad2": 2,
                "tca": datetime(2026, 7, 12, 16, 0, tzinfo=timezone.utc),
                "min_dist_km": 200.0,
                "rel_velocity_kms": 8.0,
                "risk": "LOW",
                "hours": 12,
            },
        ],
    }
    info = log_watchlist_scan(report, source="test", db_path=db)
    assert info["run_id"] is not None
    # Only MEDIUM logged by default
    assert info["events_logged"] == 1
    conj = query_conjunctions(days=30, db_path=db)
    assert len(conj) == 1
    assert conj[0]["risk"] == "MEDIUM"


def test_batch_log(tmp_path, monkeypatch):
    import services.database as dbmod

    monkeypatch.setattr(dbmod, "DB_LOG_ENABLED", True)
    db = tmp_path / "test5.db"
    n = log_passes_batch(
        [
            _sample_scored_pass(80, "B"),
            _sample_scored_pass(50, "C"),
            _sample_scored_pass(95, "A"),
        ],
        object_name="ISS (ZARYA)",
        source="test",
        db_path=db,
    )
    assert n == 2  # only B and A (>=70)
