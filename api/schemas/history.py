"""History / SQLite schemas."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class PassHistoryOut(BaseModel):
    id: int
    logged_at: Optional[str] = None
    object_name: Optional[str] = None
    norad: Optional[int] = None
    observer_name: Optional[str] = None
    rise_utc: Optional[str] = None
    culm_utc: Optional[str] = None
    set_utc: Optional[str] = None
    max_elevation: Optional[float] = None
    duration_s: Optional[float] = None
    quality_score: Optional[int] = None
    quality_grade: Optional[str] = None
    source: Optional[str] = None


class ConjunctionEventOut(BaseModel):
    id: int
    logged_at: Optional[str] = None
    watchlist_id: Optional[str] = None
    sat1: Optional[str] = None
    sat2: Optional[str] = None
    norad1: Optional[int] = None
    norad2: Optional[int] = None
    tca_utc: Optional[str] = None
    min_dist_km: Optional[float] = None
    rel_velocity_kms: Optional[float] = None
    risk: Optional[str] = None
    source: Optional[str] = None


class WatchlistRunOut(BaseModel):
    id: int
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    watchlist_id: Optional[str] = None
    pairs_scanned: Optional[int] = None
    n_results: Optional[int] = None
    n_high: Optional[int] = None
    n_medium: Optional[int] = None
    n_low: Optional[int] = None
    closest_km: Optional[float] = None
    closest_pair: Optional[str] = None


class HistorySummaryOut(BaseModel):
    days: int
    passes_logged: int
    conjunctions_logged: int
    high_risk: int
    medium_risk: int
    watchlist_runs: int
    avg_pass_score: Optional[float] = None
    closest_approach_km: Optional[float] = None
    closest_pair: Optional[str] = None
    db_path: str


class PaginatedPasses(BaseModel):
    count: int
    limit: int
    offset: int
    items: List[PassHistoryOut]


class PaginatedConjunctions(BaseModel):
    count: int
    limit: int
    offset: int
    items: List[ConjunctionEventOut]
