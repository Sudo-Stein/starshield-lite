"""Health and meta endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from api.dependencies import db_logging_enabled, ensure_database, get_object_index
from api.schemas.common import HealthResponse
from api.security import auth_enabled
from config import DB_PATH, __version__
from services.object_index import ObjectIndex

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health(
    index: ObjectIndex = Depends(get_object_index),
    _db: str = Depends(ensure_database),
    logging_on: bool = Depends(db_logging_enabled),
):
    """Liveness + light readiness (index size, DB path exists). Public."""
    stats = index.stats()
    return HealthResponse(
        status="ok",
        version=__version__,
        db_logging=logging_on,
        index_objects=stats.get("objects"),
        api_key_required=auth_enabled(),
    )


@router.get("/")
def root():
    return {
        "service": "starshield-lite",
        "version": __version__,
        "docs": "/docs",
        "health": "/health",
        "db": str(DB_PATH),
        "api_key_required": auth_enabled(),
        "auth_header": "X-API-Key" if auth_enabled() else None,
    }
