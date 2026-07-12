"""Pass prediction endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from api.dependencies import get_object_index, resolve_location
from api.schemas.common import ObserverOut
from api.schemas.passes import EventSampleOut, PassOut, PassesResponse, QualityOut
from api.security import require_api_key
from config import DB_LOG_ENABLED, PASS_MIN_ELEVATION
from core.predictor import predict_passes
from services.database import log_passes_batch
from services.object_index import ObjectIndex
from services.pass_quality import score_passes

router = APIRouter(
    prefix="/passes",
    tags=["passes"],
    dependencies=[Depends(require_api_key)],
)


def _event_out(ev) -> Optional[EventSampleOut]:
    if not ev or not isinstance(ev, dict):
        return None
    t = ev.get("time")
    return EventSampleOut(
        time=t.isoformat() if hasattr(t, "isoformat") else (str(t) if t else None),
        alt=ev.get("alt"),
        az=ev.get("az"),
        direction=ev.get("direction"),
    )


def _pass_out(p: dict, object_name: str, norad: Optional[int]) -> PassOut:
    q = p.get("quality")
    quality = None
    if q:
        quality = QualityOut(
            score=int(q.get("score", 0)),
            grade=str(q.get("grade", "?")),
            breakdown=q.get("breakdown") or {},
            sunlit_fraction=q.get("sunlit_fraction"),
            sun_alt=q.get("sun_alt"),
            duration_minutes=q.get("duration_minutes"),
            max_elevation=q.get("max_elevation"),
        )
    return PassOut(
        object_name=object_name,
        norad=norad,
        rise=_event_out(p.get("rise")),
        culmination=_event_out(p.get("culmination")),
        set=_event_out(p.get("set")),
        max_elevation=p.get("max_elevation"),
        duration_s=p.get("duration_s"),
        sunlit=p.get("sunlit"),
        dark_sky=p.get("dark_sky"),
        visible=p.get("visible"),
        sun_alt=p.get("sun_alt"),
        quality=quality,
        quality_score=p.get("quality_score"),
        quality_grade=p.get("quality_grade"),
    )


@router.get("", response_model=PassesResponse)
def get_passes(
    object: str = Query(..., description="Name, alias, or NORAD (e.g. ISS, 25544)"),
    hours: float = Query(48, gt=0, le=336),
    min_elevation: float = Query(PASS_MIN_ELEVATION, ge=0, le=90),
    stargazer: bool = Query(True),
    sort: str = Query("quality", pattern="^(quality|time|score|best)$"),
    min_score: float = Query(0, ge=0, le=100),
    limit: int = Query(20, ge=1, le=100),
    persist: bool = Query(True, description="Log Grade B+ passes to SQLite"),
    location: dict = Depends(resolve_location),
    index: ObjectIndex = Depends(get_object_index),
):
    """Predict and score passes for an object from a given observer location."""
    rec = index.resolve(object)
    sat = index.get_satellite(rec) if rec else None
    if sat is None:
        raise HTTPException(
            status_code=404,
            detail=f"Object '{object}' not found in index. Fetch TLEs or try another name.",
        )

    raw = predict_passes(
        sat,
        location=location,
        hours_ahead=hours,
        min_elevation=min_elevation,
        max_passes=max(limit * 3, 30),
        stargazer=stargazer,
    )
    sort_quality = sort.lower() in ("quality", "score", "best")
    scored = score_passes(
        raw,
        location=location,
        sat=sat,
        object_name=sat.name,
        min_score=min_score,
        sort=sort_quality,
    )
    if not sort_quality:
        scored.sort(
            key=lambda p: (
                p.get("culmination") or p.get("rise") or p.get("set") or {}
            ).get("time")
            or datetime.min
        )
    scored = scored[:limit]

    if persist and DB_LOG_ENABLED and scored:
        try:
            log_passes_batch(
                scored,
                object_name=sat.name,
                norad=rec.norad if rec else None,
                location=location,
                stargazer=stargazer,
                source="api",
            )
        except Exception:
            pass

    if scored:
        try:
            from services.notifications import notify_high_quality_passes

            notify_high_quality_passes(
                scored,
                object_name=sat.name,
                location=location,
                source="api",
            )
        except Exception:
            pass

    return PassesResponse(
        object_name=sat.name.strip(),
        norad=rec.norad if rec else None,
        observer=ObserverOut(
            name=location.get("name"),
            lat=float(location["lat"]),
            lon=float(location["lon"]),
            elevation=float(location.get("elevation") or 0),
            note=location.get("note"),
        ),
        hours=hours,
        min_elevation=min_elevation,
        stargazer=stargazer,
        sort=sort,
        min_score=min_score,
        geometric_count=getattr(raw, "geometric_count", None),
        visible_count=getattr(raw, "visible_count", None),
        count=len(scored),
        passes=[_pass_out(p, sat.name.strip(), rec.norad if rec else None) for p in scored],
    )
