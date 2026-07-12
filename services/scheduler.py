"""Background watchlist scheduler (APScheduler).

Default job: scan ``iss-starlink`` every 12 hours.
Config: data/schedules.json (auto-seeded) or SCHEDULE_JOBS in config.
"""

from __future__ import annotations

import json
import signal
import sys
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import (
    CONJ_HIGH_RISK_KM,
    CONJ_THRESHOLD_KM,
    DATA_DIR,
    SCHEDULE_ENABLED,
    SCHEDULE_FILE,
    SCHEDULE_JOBS_DEFAULT,
    WATCHLIST_DEFAULT_ID,
)
from services.database import log_watchlist_scan
from services.object_index import get_index, invalidate_index
from services.watchlist import get_watchlist, scan_watchlist
from utils.immutable_log import ImmutableLog

try:
    from services.notifications import notify_conjunction_events
except Exception:  # pragma: no cover - optional at import time
    notify_conjunction_events = None  # type: ignore

log = ImmutableLog()

_DEFAULT_STORE = {
    "version": 1,
    "enabled": True,
    "jobs": deepcopy(SCHEDULE_JOBS_DEFAULT),
}


def _ensure_store(path: Path = SCHEDULE_FILE) -> dict:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(json.dumps(_DEFAULT_STORE, indent=2), encoding="utf-8")
        return deepcopy(_DEFAULT_STORE)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        data = deepcopy(_DEFAULT_STORE)
    data.setdefault("version", 1)
    data.setdefault("enabled", True)
    data.setdefault("jobs", deepcopy(SCHEDULE_JOBS_DEFAULT))
    # Merge missing default job ids without overwriting user edits
    existing_ids = {j.get("id") for j in data["jobs"]}
    for j in SCHEDULE_JOBS_DEFAULT:
        if j.get("id") not in existing_ids:
            data["jobs"].append(deepcopy(j))
    return data


def save_store(data: dict, path: Path = SCHEDULE_FILE) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def list_jobs(path: Path = SCHEDULE_FILE) -> List[dict]:
    return list(_ensure_store(path).get("jobs") or [])


def set_job_enabled(job_id: str, enabled: bool, path: Path = SCHEDULE_FILE) -> bool:
    data = _ensure_store(path)
    for j in data["jobs"]:
        if j.get("id") == job_id:
            j["enabled"] = bool(enabled)
            save_store(data, path)
            return True
    return False


def run_watchlist_job(job: dict) -> Dict[str, Any]:
    """Execute one scheduled watchlist scan and persist results."""
    wl_id = job.get("watchlist_id") or WATCHLIST_DEFAULT_ID
    hours = float(job.get("hours") or 48)
    sample = job.get("sample")
    threshold = float(job.get("threshold_km") or CONJ_THRESHOLD_KM)
    only_below = bool(job.get("only_below", False))
    refresh_tles = bool(job.get("refresh_tles", False))

    started = datetime.now(timezone.utc).isoformat()
    print(f"[scheduler] {started} starting job={job.get('id')} watchlist={wl_id}")

    if refresh_tles:
        try:
            from core.tle_fetcher import fetch_tles

            for g in job.get("refresh_groups") or ["stations", "starlink"]:
                try:
                    fetch_tles(g, force=True)
                except Exception as exc:
                    print(f"[scheduler] TLE fetch {g} failed: {exc}")
            invalidate_index()
        except Exception as exc:
            print(f"[scheduler] refresh skipped: {exc}")

    w = get_watchlist(wl_id)
    if w is None:
        msg = f"watchlist '{wl_id}' not found"
        print(f"[scheduler] ERROR: {msg}")
        log.append({"action": "schedule_error", "job": job.get("id"), "error": msg})
        return {"ok": False, "error": msg}

    if sample is not None:
        w.sample = int(sample)

    try:
        idx = get_index(force=True)
        report = scan_watchlist(
            w,
            hours=hours,
            threshold_km=threshold,
            high_risk_km=CONJ_HIGH_RISK_KM,
            only_below=only_below,
            adaptive=True,
            steps=160,
            progress_every=0,
            index=idx,
        )
        db_info = log_watchlist_scan(report, source="scheduler")
        notify_info: Dict[str, Any] = {"skipped": True}
        if notify_conjunction_events is not None:
            try:
                notify_info = notify_conjunction_events(
                    report, source="scheduler"
                )
            except Exception as exc:
                notify_info = {"ok": False, "error": str(exc)}
                print(f"[scheduler] notify skipped: {exc}")
        summary = report.get("summary") or {}
        result = {
            "ok": True,
            "job_id": job.get("id"),
            "watchlist_id": wl_id,
            "pairs_scanned": report.get("pairs_scanned"),
            "n_results": summary.get("n_results"),
            "HIGH": summary.get("HIGH"),
            "MEDIUM": summary.get("MEDIUM"),
            "LOW": summary.get("LOW"),
            "closest_km": summary.get("closest_km"),
            "closest_pair": summary.get("closest_pair"),
            "db_run_id": db_info.get("run_id"),
            "db_events": db_info.get("events_logged"),
            "notify": {
                "n": notify_info.get("n"),
                "skipped": notify_info.get("skipped"),
                "reason": notify_info.get("reason"),
            },
        }
        print(
            f"[scheduler] done job={job.get('id')} pairs={result['pairs_scanned']} "
            f"H/M/L={result['HIGH']}/{result['MEDIUM']}/{result['LOW']} "
            f"closest={result['closest_km']} km db_run={result['db_run_id']}"
        )
        if notify_info.get("n"):
            print(
                f"[scheduler] notify: {notify_info.get('notified', notify_info.get('n'))} "
                f"conjunction event(s) queued"
            )
        log.append({"action": "schedule_run", **result})
        # Update last_run in store
        try:
            data = _ensure_store()
            for j in data["jobs"]:
                if j.get("id") == job.get("id"):
                    j["last_run"] = datetime.now(timezone.utc).isoformat()
                    j["last_result"] = {
                        "closest_km": result["closest_km"],
                        "HIGH": result["HIGH"],
                        "MEDIUM": result["MEDIUM"],
                    }
            save_store(data)
        except Exception:
            pass
        return result
    except Exception as exc:
        print(f"[scheduler] ERROR job={job.get('id')}: {exc}")
        log.append(
            {
                "action": "schedule_error",
                "job": job.get("id"),
                "error": str(exc),
            }
        )
        return {"ok": False, "error": str(exc)}


def _interval_seconds(job: dict) -> int:
    """Parse interval from job config.

    Supports:
      hours: 12
      interval_hours: 12
      interval_seconds: 3600
    """
    if job.get("interval_seconds"):
        return max(60, int(job["interval_seconds"]))
    hours = job.get("interval_hours") or job.get("every_hours") or 12
    return max(60, int(float(hours) * 3600))


def start_scheduler(
    *,
    foreground: bool = True,
    run_immediately: bool = True,
    path: Path = SCHEDULE_FILE,
) -> None:
    """Start APScheduler and block (foreground) until interrupted."""
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.interval import IntervalTrigger
    except ImportError as exc:
        raise SystemExit(
            "APScheduler is required. Install with: pip install apscheduler"
        ) from exc

    if not SCHEDULE_ENABLED and not foreground:
        print("[scheduler] SCHEDULE_ENABLED is off — set STARSHIELD_SCHEDULE_ENABLED=1")

    data = _ensure_store(path)
    jobs = [j for j in data.get("jobs") or [] if j.get("enabled", True)]
    if not jobs:
        print("[scheduler] No enabled jobs in", path)
        if foreground:
            print("[scheduler] Idle (no jobs). Ctrl+C to exit.")
            _idle_forever()
        return

    scheduler = BackgroundScheduler(timezone="UTC")
    for job in jobs:
        jid = job.get("id") or f"job-{id(job)}"
        secs = _interval_seconds(job)
        scheduler.add_job(
            run_watchlist_job,
            trigger=IntervalTrigger(seconds=secs),
            args=[job],
            id=jid,
            name=job.get("name") or jid,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        print(
            f"[scheduler] registered {jid}: watchlist={job.get('watchlist_id')} "
            f"every {secs / 3600:.1f}h"
        )

    scheduler.start()
    print(
        f"[scheduler] running {len(jobs)} job(s) · config={path} · Ctrl+C to stop"
    )

    if run_immediately:
        for job in jobs:
            try:
                run_watchlist_job(job)
            except Exception as exc:
                print(f"[scheduler] immediate run failed: {exc}")

    if not foreground:
        return scheduler

    def _shutdown(signum=None, frame=None):
        print("\n[scheduler] shutting down…")
        scheduler.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)
    _idle_forever()


def _idle_forever():
    while True:
        time.sleep(3600)


def run_job_once(job_id: str, path: Path = SCHEDULE_FILE) -> Dict[str, Any]:
    """Run a single job by id immediately (for CLI testing)."""
    for job in list_jobs(path):
        if job.get("id") == job_id:
            return run_watchlist_job(job)
    return {"ok": False, "error": f"job '{job_id}' not found"}
