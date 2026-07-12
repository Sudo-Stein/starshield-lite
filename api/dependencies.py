"""FastAPI dependencies — thin wrappers around the service layer."""

from __future__ import annotations

from typing import Optional

from fastapi import HTTPException, Query

from config import DB_LOG_ENABLED, DEFAULT_OBSERVER
from services.database import ensure_db
from services.object_index import ObjectIndex, get_index
from services.observers import resolve_observer


def get_object_index() -> ObjectIndex:
    """Return the multi-catalog object index (rebuilt when TLE files change)."""
    # fingerprint is internal to get_index; force=False uses cache
    return get_index()


def ensure_database() -> str:
    """Ensure SQLite schema exists; return path string."""
    return str(ensure_db())


def resolve_location(
    profile: Optional[str] = Query(
        None, description="Observer profile name (e.g. 'Kingsland, GA')"
    ),
    lat: Optional[float] = Query(None, ge=-90, le=90),
    lon: Optional[float] = Query(None, ge=-180, le=180),
    elevation: Optional[float] = Query(None, description="Elevation meters"),
) -> dict:
    """Build an observer location from query params (stateless)."""
    if lat is not None and lon is None:
        raise HTTPException(status_code=400, detail="lon required when lat is set")
    if lon is not None and lat is None:
        raise HTTPException(status_code=400, detail="lat required when lon is set")
    return resolve_observer(
        profile=profile or (None if lat is not None else DEFAULT_OBSERVER),
        lat=lat,
        lon=lon,
        elevation=elevation,
    )


def db_logging_enabled() -> bool:
    return bool(DB_LOG_ENABLED)
