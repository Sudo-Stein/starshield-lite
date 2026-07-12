"""Tests for schedule config store (no long-running APScheduler loop)."""

from services.scheduler import (
    _interval_seconds,
    list_jobs,
    set_job_enabled,
)


def test_default_jobs_seed(tmp_path, monkeypatch):
    import services.scheduler as sched

    path = tmp_path / "schedules.json"
    monkeypatch.setattr(sched, "SCHEDULE_FILE", path)
    jobs = list_jobs(path)
    assert any(j["id"] == "iss-starlink-12h" for j in jobs)
    assert path.exists()


def test_interval_seconds():
    assert _interval_seconds({"interval_hours": 12}) == 12 * 3600
    assert _interval_seconds({"interval_seconds": 120}) == 120
    assert _interval_seconds({}) >= 60


def test_enable_disable(tmp_path, monkeypatch):
    import services.scheduler as sched

    path = tmp_path / "schedules.json"
    monkeypatch.setattr(sched, "SCHEDULE_FILE", path)
    list_jobs(path)  # seed
    assert set_job_enabled("iss-starlink-12h", False, path)
    jobs = list_jobs(path)
    j = next(x for x in jobs if x["id"] == "iss-starlink-12h")
    assert j["enabled"] is False
    assert set_job_enabled("iss-starlink-12h", True, path)
