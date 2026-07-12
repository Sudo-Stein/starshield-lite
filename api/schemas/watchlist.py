"""Watchlist schemas."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class WatchlistInfo(BaseModel):
    id: str
    name: str
    description: str = ""
    mode: str
    primary: str = ""
    group: str = ""
    sample: int = 40


class WatchlistScanRequest(BaseModel):
    watchlist_id: str = Field("iss-starlink", description="Watchlist id")
    hours: float = Field(48, gt=0, le=336)
    threshold_km: float = Field(50, gt=0)
    high_risk_km: float = Field(10, gt=0)
    only_below: bool = False
    sample: Optional[int] = Field(
        None, description="Override sample size for group scans"
    )
    max_results: int = Field(50, ge=1, le=500)
    persist: bool = Field(True, description="Write MEDIUM/HIGH events to SQLite")
    adaptive: bool = True


class ConjunctionResultOut(BaseModel):
    sat1: str
    sat2: str
    norad1: Optional[int] = None
    norad2: Optional[int] = None
    tca: Optional[str] = None
    min_dist_km: float
    rel_velocity_kms: Optional[float] = None
    risk: str
    below_threshold: bool = False


class WatchlistScanResponse(BaseModel):
    watchlist_id: str
    watchlist_name: str
    hours: float
    pairs_scanned: int
    count: int
    summary: Dict[str, Any]
    results: List[ConjunctionResultOut]
    db_run_id: Optional[int] = None
    db_events_logged: int = 0
