"""History / SQLite query endpoints."""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, Query

from api.dependencies import ensure_database
from api.schemas.history import (
    ConjunctionEventOut,
    HistorySummaryOut,
    PaginatedConjunctions,
    PaginatedPasses,
    PassHistoryOut,
    WatchlistRunOut,
)
from api.security import require_api_key
from services.database import (
    query_conjunctions,
    query_recent_passes,
    query_watchlist_runs,
    summary_stats,
)

router = APIRouter(
    prefix="/history",
    tags=["history"],
    dependencies=[Depends(require_api_key)],
)


@router.get("/summary", response_model=HistorySummaryOut)
def history_summary(
    days: int = Query(7, ge=1, le=365),
    _db: str = Depends(ensure_database),
):
    """Aggregate stats for the last N days."""
    s = summary_stats(days=days)
    return HistorySummaryOut(**s)


@router.get("/passes", response_model=PaginatedPasses)
def history_passes(
    days: Optional[int] = Query(30, ge=1, le=365),
    object: Optional[str] = Query(None, description="Filter by object name substring"),
    observer: Optional[str] = Query(None, description="Filter by observer profile name"),
    min_score: Optional[int] = Query(None, ge=0, le=100),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _db: str = Depends(ensure_database),
):
    """Recent high-quality passes (simple offset pagination)."""
    # Fetch limit+offset then slice (SQLite layer has limit only; keep simple)
    rows = query_recent_passes(
        limit=limit + offset,
        observer_name=observer,
        object_name=object,
        min_score=min_score,
        days=days,
    )
    page = rows[offset : offset + limit]
    items = [
        PassHistoryOut(
            id=r["id"],
            logged_at=r.get("logged_at"),
            object_name=r.get("object_name"),
            norad=r.get("norad"),
            observer_name=r.get("observer_name"),
            rise_utc=r.get("rise_utc"),
            culm_utc=r.get("culm_utc"),
            set_utc=r.get("set_utc"),
            max_elevation=r.get("max_elevation"),
            duration_s=r.get("duration_s"),
            quality_score=r.get("quality_score"),
            quality_grade=r.get("quality_grade"),
            source=r.get("source"),
        )
        for r in page
    ]
    return PaginatedPasses(count=len(items), limit=limit, offset=offset, items=items)


@router.get("/conjunctions", response_model=PaginatedConjunctions)
def history_conjunctions(
    days: Optional[int] = Query(30, ge=1, le=365),
    object: Optional[str] = Query(None, description="Filter sat1/sat2 substring"),
    risk: Optional[str] = Query(None, description="HIGH | MEDIUM | LOW"),
    watchlist_id: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _db: str = Depends(ensure_database),
):
    """Historical conjunction events."""
    rows = query_conjunctions(
        object_name=object,
        risk=risk,
        days=days,
        limit=limit + offset,
        watchlist_id=watchlist_id,
    )
    page = rows[offset : offset + limit]
    items = [
        ConjunctionEventOut(
            id=r["id"],
            logged_at=r.get("logged_at"),
            watchlist_id=r.get("watchlist_id"),
            sat1=r.get("sat1"),
            sat2=r.get("sat2"),
            norad1=r.get("norad1"),
            norad2=r.get("norad2"),
            tca_utc=r.get("tca_utc"),
            min_dist_km=r.get("min_dist_km"),
            rel_velocity_kms=r.get("rel_velocity_kms"),
            risk=r.get("risk"),
            source=r.get("source"),
        )
        for r in page
    ]
    return PaginatedConjunctions(
        count=len(items), limit=limit, offset=offset, items=items
    )


@router.get("/watchlist-runs", response_model=List[WatchlistRunOut])
def history_watchlist_runs(
    watchlist_id: Optional[str] = None,
    limit: int = Query(20, ge=1, le=100),
    _db: str = Depends(ensure_database),
):
    rows = query_watchlist_runs(watchlist_id=watchlist_id, limit=limit)
    return [
        WatchlistRunOut(
            id=r["id"],
            started_at=r.get("started_at"),
            finished_at=r.get("finished_at"),
            watchlist_id=r.get("watchlist_id"),
            pairs_scanned=r.get("pairs_scanned"),
            n_results=r.get("n_results"),
            n_high=r.get("n_high"),
            n_medium=r.get("n_medium"),
            n_low=r.get("n_low"),
            closest_km=r.get("closest_km"),
            closest_pair=r.get("closest_pair"),
        )
        for r in rows
    ]
