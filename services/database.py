"""SQLite persistence for StarShield Lite.

Stores high-quality passes, conjunction events, and watchlist run metadata.
Designed for trends / replay / future scheduled jobs — not a full SSA archive.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Union

from config import (
    DB_LOG_CONJ_RISKS,
    DB_LOG_ENABLED,
    DB_LOG_PASS_MIN_SCORE,
    DB_PATH,
)

SCHEMA_VERSION = 1

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS passes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    logged_at       TEXT NOT NULL,
    object_name     TEXT NOT NULL,
    norad           INTEGER,
    observer_name   TEXT,
    observer_lat    REAL,
    observer_lon    REAL,
    observer_elev_m REAL,
    rise_utc        TEXT,
    culm_utc        TEXT,
    set_utc         TEXT,
    max_elevation   REAL,
    duration_s      REAL,
    quality_score   INTEGER,
    quality_grade   TEXT,
    sunlit_fraction REAL,
    sun_alt         REAL,
    visible         INTEGER,
    stargazer       INTEGER,
    sky_label       TEXT,
    source          TEXT,
    extra_json      TEXT
);

CREATE INDEX IF NOT EXISTS idx_passes_logged ON passes(logged_at);
CREATE INDEX IF NOT EXISTS idx_passes_object ON passes(object_name);
CREATE INDEX IF NOT EXISTS idx_passes_norad ON passes(norad);
CREATE INDEX IF NOT EXISTS idx_passes_observer ON passes(observer_name);
CREATE INDEX IF NOT EXISTS idx_passes_score ON passes(quality_score);

CREATE TABLE IF NOT EXISTS watchlist_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    watchlist_id    TEXT NOT NULL,
    watchlist_name  TEXT,
    hours           REAL,
    threshold_km    REAL,
    pairs_scanned   INTEGER,
    n_results       INTEGER,
    n_high          INTEGER,
    n_medium        INTEGER,
    n_low           INTEGER,
    closest_km      REAL,
    closest_pair    TEXT,
    source          TEXT,
    extra_json      TEXT
);

CREATE INDEX IF NOT EXISTS idx_wl_runs_started ON watchlist_runs(started_at);
CREATE INDEX IF NOT EXISTS idx_wl_runs_id ON watchlist_runs(watchlist_id);

CREATE TABLE IF NOT EXISTS conjunction_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    logged_at       TEXT NOT NULL,
    run_id          INTEGER,
    watchlist_id    TEXT,
    sat1            TEXT NOT NULL,
    sat2            TEXT NOT NULL,
    norad1          INTEGER,
    norad2          INTEGER,
    tca_utc         TEXT,
    min_dist_km     REAL,
    rel_velocity_kms REAL,
    risk            TEXT,
    hours_window    REAL,
    source          TEXT,
    extra_json      TEXT,
    FOREIGN KEY (run_id) REFERENCES watchlist_runs(id)
);

CREATE INDEX IF NOT EXISTS idx_conj_tca ON conjunction_events(tca_utc);
CREATE INDEX IF NOT EXISTS idx_conj_risk ON conjunction_events(risk);
CREATE INDEX IF NOT EXISTS idx_conj_sat1 ON conjunction_events(sat1);
CREATE INDEX IF NOT EXISTS idx_conj_sat2 ON conjunction_events(sat2);
CREATE INDEX IF NOT EXISTS idx_conj_run ON conjunction_events(run_id);
"""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_iso(dt) -> Optional[str]:
    if dt is None:
        return None
    if isinstance(dt, str):
        return dt
    if getattr(dt, "tzinfo", None) is None:
        try:
            dt = dt.replace(tzinfo=timezone.utc)
        except Exception:
            return str(dt)
    try:
        return dt.isoformat()
    except Exception:
        return str(dt)


@contextmanager
def connect(db_path: Optional[Union[str, Path]] = None):
    """Context-managed SQLite connection with row factory + WAL."""
    path = Path(db_path or DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Optional[Union[str, Path]] = None) -> Path:
    """Create tables if missing and stamp schema version."""
    path = Path(db_path or DB_PATH)
    with connect(path) as conn:
        conn.executescript(_SCHEMA_SQL)
        row = conn.execute(
            "SELECT value FROM schema_meta WHERE key = 'schema_version'"
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO schema_meta(key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            conn.execute(
                "INSERT OR REPLACE INTO schema_meta(key, value) VALUES ('created_at', ?)",
                (_utc_now_iso(),),
            )
        # Future: bump SCHEMA_VERSION and run migrations here
    return path


def ensure_db(db_path: Optional[Union[str, Path]] = None) -> Path:
    """Idempotent init — call before any write/query."""
    return init_db(db_path)


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def log_pass(
    pass_data: dict,
    *,
    object_name: str = "",
    norad: Optional[int] = None,
    location: Optional[dict] = None,
    stargazer: Optional[bool] = None,
    source: str = "cli",
    min_score: Optional[int] = None,
    force: bool = False,
    db_path: Optional[Union[str, Path]] = None,
) -> Optional[int]:
    """Insert a pass row if it meets quality threshold.

    Returns row id or None if skipped.
    """
    if not force and not DB_LOG_ENABLED:
        return None

    q = pass_data.get("quality") or {}
    score = pass_data.get("quality_score")
    if score is None:
        score = q.get("score")
    grade = pass_data.get("quality_grade") or q.get("grade")
    threshold = DB_LOG_PASS_MIN_SCORE if min_score is None else min_score

    if not force:
        if score is None or int(score) < int(threshold):
            return None

    loc = location or {}
    name = (
        object_name
        or pass_data.get("object_name")
        or pass_data.get("name")
        or q.get("object_name")
        or "unknown"
    )
    rise = pass_data.get("rise") or {}
    culm = pass_data.get("culmination") or {}
    set_ = pass_data.get("set") or {}

    ensure_db(db_path)
    with connect(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO passes (
                logged_at, object_name, norad,
                observer_name, observer_lat, observer_lon, observer_elev_m,
                rise_utc, culm_utc, set_utc,
                max_elevation, duration_s,
                quality_score, quality_grade,
                sunlit_fraction, sun_alt, visible, stargazer, sky_label,
                source, extra_json
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                _utc_now_iso(),
                name,
                norad,
                loc.get("name"),
                loc.get("lat"),
                loc.get("lon"),
                loc.get("elevation"),
                _as_iso(rise.get("time")),
                _as_iso(culm.get("time")),
                _as_iso(set_.get("time")),
                pass_data.get("max_elevation") or q.get("max_elevation"),
                pass_data.get("duration_s"),
                int(score) if score is not None else None,
                grade,
                pass_data.get("sunlit_fraction") or q.get("sunlit_fraction"),
                pass_data.get("sun_alt") or q.get("sun_alt"),
                1 if pass_data.get("visible") else 0 if pass_data.get("visible") is False else None,
                1 if stargazer else 0 if stargazer is False else None,
                None,
                source,
                json.dumps(
                    {
                        "breakdown": q.get("breakdown"),
                        "az": (culm or rise).get("az") if isinstance(culm or rise, dict) else None,
                    },
                    default=str,
                ),
            ),
        )
        return int(cur.lastrowid)


def log_passes_batch(
    passes: Sequence[dict],
    *,
    object_name: str = "",
    norad: Optional[int] = None,
    location: Optional[dict] = None,
    stargazer: Optional[bool] = None,
    source: str = "cli",
    min_score: Optional[int] = None,
    force: bool = False,
    db_path: Optional[Union[str, Path]] = None,
) -> int:
    """Log multiple passes; returns count inserted."""
    n = 0
    for p in passes:
        rid = log_pass(
            p,
            object_name=object_name,
            norad=norad,
            location=location,
            stargazer=stargazer,
            source=source,
            min_score=min_score,
            force=force,
            db_path=db_path,
        )
        if rid is not None:
            n += 1
    return n


def start_watchlist_run(
    *,
    watchlist_id: str,
    watchlist_name: str = "",
    hours: Optional[float] = None,
    threshold_km: Optional[float] = None,
    source: str = "cli",
    db_path: Optional[Union[str, Path]] = None,
) -> Optional[int]:
    """Create a watchlist_runs row; return run id."""
    if not DB_LOG_ENABLED:
        return None
    ensure_db(db_path)
    with connect(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO watchlist_runs (
                started_at, watchlist_id, watchlist_name,
                hours, threshold_km, source
            ) VALUES (?,?,?,?,?,?)
            """,
            (
                _utc_now_iso(),
                watchlist_id,
                watchlist_name,
                hours,
                threshold_km,
                source,
            ),
        )
        return int(cur.lastrowid)


def finish_watchlist_run(
    run_id: Optional[int],
    summary: dict,
    *,
    db_path: Optional[Union[str, Path]] = None,
) -> None:
    if run_id is None or not DB_LOG_ENABLED:
        return
    ensure_db(db_path)
    with connect(db_path) as conn:
        conn.execute(
            """
            UPDATE watchlist_runs SET
                finished_at = ?,
                pairs_scanned = ?,
                n_results = ?,
                n_high = ?,
                n_medium = ?,
                n_low = ?,
                closest_km = ?,
                closest_pair = ?,
                extra_json = ?
            WHERE id = ?
            """,
            (
                _utc_now_iso(),
                summary.get("pairs_scanned"),
                summary.get("n_results"),
                summary.get("HIGH") or summary.get("n_high"),
                summary.get("MEDIUM") or summary.get("n_medium"),
                summary.get("LOW") or summary.get("n_low"),
                summary.get("closest_km"),
                summary.get("closest_pair"),
                json.dumps(summary, default=str),
                run_id,
            ),
        )


def log_conjunction_event(
    event: dict,
    *,
    run_id: Optional[int] = None,
    watchlist_id: Optional[str] = None,
    hours_window: Optional[float] = None,
    source: str = "cli",
    min_risks: Optional[Sequence[str]] = None,
    force: bool = False,
    db_path: Optional[Union[str, Path]] = None,
) -> Optional[int]:
    """Log one close approach if risk is in configured set."""
    if not force and not DB_LOG_ENABLED:
        return None
    risk = (event.get("risk") or "").upper()
    allowed = tuple(min_risks) if min_risks is not None else DB_LOG_CONJ_RISKS
    if not force and risk not in allowed:
        return None

    ensure_db(db_path)
    with connect(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO conjunction_events (
                logged_at, run_id, watchlist_id,
                sat1, sat2, norad1, norad2,
                tca_utc, min_dist_km, rel_velocity_kms, risk,
                hours_window, source, extra_json
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                _utc_now_iso(),
                run_id,
                watchlist_id or event.get("watchlist"),
                event.get("sat1"),
                event.get("sat2"),
                event.get("norad1"),
                event.get("norad2"),
                _as_iso(event.get("tca")),
                event.get("min_dist_km"),
                event.get("rel_velocity_kms"),
                risk,
                hours_window or event.get("hours"),
                source,
                json.dumps(
                    {
                        "threshold_km": event.get("threshold_km"),
                        "refined": event.get("refined"),
                    },
                    default=str,
                ),
            ),
        )
        return int(cur.lastrowid)


def log_watchlist_scan(
    report: dict,
    *,
    source: str = "cli",
    log_all_risks: bool = False,
    db_path: Optional[Union[str, Path]] = None,
) -> Dict[str, Any]:
    """Persist a full watchlist scan: run row + qualifying conjunction events.

    By default only MEDIUM/HIGH events are stored (``DB_LOG_CONJ_RISKS``).
    Returns ``{run_id, events_logged}``.
    """
    if not DB_LOG_ENABLED:
        return {"run_id": None, "events_logged": 0}

    run_id = start_watchlist_run(
        watchlist_id=report.get("watchlist_id", "unknown"),
        watchlist_name=report.get("watchlist_name", ""),
        hours=report.get("hours"),
        threshold_km=report.get("threshold_km"),
        source=source,
        db_path=db_path,
    )
    summary = dict(report.get("summary") or {})
    summary["pairs_scanned"] = report.get("pairs_scanned")
    finish_watchlist_run(run_id, summary, db_path=db_path)

    n = 0
    for ev in report.get("results") or []:
        rid = log_conjunction_event(
            ev,
            run_id=run_id,
            watchlist_id=report.get("watchlist_id"),
            hours_window=report.get("hours"),
            source=source,
            min_risks=None if log_all_risks else DB_LOG_CONJ_RISKS,
            force=log_all_risks,
            db_path=db_path,
        )
        if rid is not None:
            n += 1
    return {"run_id": run_id, "events_logged": n}


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------


def _rows_to_dicts(rows: Iterable[sqlite3.Row]) -> List[dict]:
    return [dict(r) for r in rows]


def query_recent_passes(
    *,
    limit: int = 50,
    observer_name: Optional[str] = None,
    object_name: Optional[str] = None,
    min_score: Optional[int] = None,
    days: Optional[int] = None,
    db_path: Optional[Union[str, Path]] = None,
) -> List[dict]:
    ensure_db(db_path)
    clauses = []
    params: List[Any] = []
    if observer_name:
        clauses.append("observer_name = ?")
        params.append(observer_name)
    if object_name:
        clauses.append("object_name LIKE ?")
        params.append(f"%{object_name}%")
    if min_score is not None:
        clauses.append("quality_score >= ?")
        params.append(min_score)
    if days is not None:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        clauses.append("logged_at >= ?")
        params.append(since)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = f"""
        SELECT * FROM passes
        {where}
        ORDER BY logged_at DESC
        LIMIT ?
    """
    params.append(limit)
    with connect(db_path) as conn:
        rows = conn.execute(sql, params).fetchall()
    return _rows_to_dicts(rows)


def query_conjunctions(
    *,
    object_name: Optional[str] = None,
    risk: Optional[str] = None,
    days: Optional[int] = 7,
    limit: int = 50,
    watchlist_id: Optional[str] = None,
    db_path: Optional[Union[str, Path]] = None,
) -> List[dict]:
    """Historical conjunction events (optionally for one object / risk)."""
    ensure_db(db_path)
    clauses = []
    params: List[Any] = []
    if object_name:
        clauses.append("(sat1 LIKE ? OR sat2 LIKE ?)")
        params.extend([f"%{object_name}%", f"%{object_name}%"])
    if risk:
        clauses.append("risk = ?")
        params.append(risk.upper())
    if watchlist_id:
        clauses.append("watchlist_id = ?")
        params.append(watchlist_id)
    if days is not None:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        clauses.append("logged_at >= ?")
        params.append(since)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = f"""
        SELECT * FROM conjunction_events
        {where}
        ORDER BY COALESCE(tca_utc, logged_at) DESC
        LIMIT ?
    """
    params.append(limit)
    with connect(db_path) as conn:
        rows = conn.execute(sql, params).fetchall()
    return _rows_to_dicts(rows)


def query_watchlist_runs(
    *,
    watchlist_id: Optional[str] = None,
    limit: int = 20,
    db_path: Optional[Union[str, Path]] = None,
) -> List[dict]:
    ensure_db(db_path)
    if watchlist_id:
        sql = """
            SELECT * FROM watchlist_runs
            WHERE watchlist_id = ?
            ORDER BY started_at DESC LIMIT ?
        """
        params: tuple = (watchlist_id, limit)
    else:
        sql = "SELECT * FROM watchlist_runs ORDER BY started_at DESC LIMIT ?"
        params = (limit,)
    with connect(db_path) as conn:
        rows = conn.execute(sql, params).fetchall()
    return _rows_to_dicts(rows)


def summary_stats(
    *,
    days: int = 7,
    db_path: Optional[Union[str, Path]] = None,
) -> Dict[str, Any]:
    """Aggregate counts for the last N days."""
    ensure_db(db_path)
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with connect(db_path) as conn:
        n_passes = conn.execute(
            "SELECT COUNT(*) AS c FROM passes WHERE logged_at >= ?", (since,)
        ).fetchone()["c"]
        n_conj = conn.execute(
            "SELECT COUNT(*) AS c FROM conjunction_events WHERE logged_at >= ?",
            (since,),
        ).fetchone()["c"]
        n_high = conn.execute(
            "SELECT COUNT(*) AS c FROM conjunction_events WHERE logged_at >= ? AND risk = 'HIGH'",
            (since,),
        ).fetchone()["c"]
        n_med = conn.execute(
            "SELECT COUNT(*) AS c FROM conjunction_events WHERE logged_at >= ? AND risk = 'MEDIUM'",
            (since,),
        ).fetchone()["c"]
        n_runs = conn.execute(
            "SELECT COUNT(*) AS c FROM watchlist_runs WHERE started_at >= ?",
            (since,),
        ).fetchone()["c"]
        avg_score = conn.execute(
            "SELECT AVG(quality_score) AS a FROM passes WHERE logged_at >= ? AND quality_score IS NOT NULL",
            (since,),
        ).fetchone()["a"]
        closest = conn.execute(
            """
            SELECT min_dist_km, sat1, sat2, tca_utc FROM conjunction_events
            WHERE logged_at >= ? AND min_dist_km IS NOT NULL
            ORDER BY min_dist_km ASC LIMIT 1
            """,
            (since,),
        ).fetchone()
    return {
        "days": days,
        "passes_logged": n_passes,
        "conjunctions_logged": n_conj,
        "high_risk": n_high,
        "medium_risk": n_med,
        "watchlist_runs": n_runs,
        "avg_pass_score": round(avg_score, 1) if avg_score is not None else None,
        "closest_approach_km": closest["min_dist_km"] if closest else None,
        "closest_pair": (
            f"{closest['sat1']} / {closest['sat2']}" if closest else None
        ),
        "db_path": str(db_path or DB_PATH),
    }
