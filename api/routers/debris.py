"""Debris catalog endpoints (optional)."""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api.dependencies import get_object_index
from api.schemas.objects import ObjectRecordOut, ObjectSearchResponse
from api.schemas.watchlist import ConjunctionResultOut, WatchlistScanResponse
from api.security import require_api_key
from config import DB_LOG_ENABLED, DEBRIS_GROUPS, WATCHLIST_DEBRIS_SAMPLE
from services.database import log_watchlist_scan
from services.debris import (
    debris_index_stats,
    fetch_debris,
    is_debris_group,
    list_debris_groups,
    scan_primary_vs_debris,
)
from services.object_index import ObjectIndex
from services.notifications import notify_conjunction_events

router = APIRouter(prefix="/debris", tags=["debris"])


class DebrisGroupOut(BaseModel):
    group: str
    description: str = ""
    url: Optional[str] = None
    cached: bool = False
    path: Optional[str] = None
    objects_approx: int = 0
    bytes: int = 0
    in_index: bool = False


class DebrisStatusOut(BaseModel):
    index_objects: int = 0
    debris_objects: int = 0
    debris_groups_loaded: List[str] = Field(default_factory=list)
    groups_loaded: List[str] = Field(default_factory=list)
    catalogs: List[DebrisGroupOut] = Field(default_factory=list)


class DebrisFetchRequest(BaseModel):
    group: str = Field("debris", description="Debris TLE group key")
    force: bool = True


class DebrisFetchResponse(BaseModel):
    group: str
    path: str
    objects_approx: int = 0
    index_objects: int = 0
    debris_objects: int = 0


class DebrisScanRequest(BaseModel):
    primary: str = Field("ISS", description="Active object name / NORAD")
    debris_group: str = Field("debris", description="Debris catalog group")
    hours: float = Field(24, gt=0, le=168)
    sample: int = Field(WATCHLIST_DEBRIS_SAMPLE, ge=1, le=200)
    threshold_km: float = Field(50, gt=0)
    high_risk_km: float = Field(10, gt=0)
    only_below: bool = False
    max_results: int = Field(50, ge=1, le=500)
    persist: bool = True


def _record_out(rec) -> ObjectRecordOut:
    return ObjectRecordOut(
        norad=rec.norad,
        name=rec.name,
        groups=sorted(rec.groups),
        aliases=list(rec.aliases),
        epoch=rec.epoch.isoformat() if rec.epoch else None,
        primary_group=rec.primary_group,
    )


@router.get("/groups", response_model=List[DebrisGroupOut])
def get_debris_groups():
    """List known debris catalogs and local cache status."""
    return [DebrisGroupOut(**row) for row in list_debris_groups()]


@router.get("/status", response_model=DebrisStatusOut)
def get_debris_status():
    """Debris presence in the object index + per-catalog cache info."""
    st = debris_index_stats()
    return DebrisStatusOut(
        index_objects=int(st.get("index_objects") or 0),
        debris_objects=int(st.get("debris_objects") or 0),
        debris_groups_loaded=list(st.get("debris_groups_loaded") or []),
        groups_loaded=list(st.get("groups_loaded") or []),
        catalogs=[DebrisGroupOut(**c) for c in st.get("catalogs") or []],
    )


@router.get("/search", response_model=ObjectSearchResponse)
def search_debris(
    q: str = Query("", description="Optional name / NORAD filter"),
    limit: int = Query(25, ge=1, le=100),
    index: ObjectIndex = Depends(get_object_index),
):
    """Search debris-tagged objects in the index (empty q → first N debris)."""
    hits = index.search_debris(q.strip(), limit=limit)
    return ObjectSearchResponse(
        query=q.strip() or "*",
        count=len(hits),
        results=[_record_out(h) for h in hits],
    )


@router.post(
    "/fetch",
    response_model=DebrisFetchResponse,
    dependencies=[Depends(require_api_key)],
)
def post_fetch_debris(body: DebrisFetchRequest):
    """Download a debris TLE group from CelesTrak and refresh the index.

    **Requires API key** when ``STARSHIELD_API_KEY_REQUIRED=1``.
    """
    group = body.group.strip()
    if group not in DEBRIS_GROUPS and not is_debris_group(group):
        raise HTTPException(
            status_code=400,
            detail=f"Unknown debris group '{group}'. Valid: {', '.join(DEBRIS_GROUPS)}",
        )
    try:
        path = fetch_debris(group, force=body.force, refresh_index=True)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    st = debris_index_stats()
    n_obj = 0
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        n_obj = len([ln for ln in text.splitlines() if ln.strip()]) // 3
    except OSError:
        pass
    return DebrisFetchResponse(
        group=group,
        path=str(path),
        objects_approx=n_obj,
        index_objects=int(st.get("index_objects") or 0),
        debris_objects=int(st.get("debris_objects") or 0),
    )


@router.post(
    "/scan",
    response_model=WatchlistScanResponse,
    dependencies=[Depends(require_api_key)],
)
def post_debris_scan(
    body: DebrisScanRequest,
    index: ObjectIndex = Depends(get_object_index),
):
    """Conjunction scan: primary active object vs a debris catalog sample.

    Reuses the adaptive conjunction engine. Results feed DB logging and
    webhook notifications the same way as watchlist scans.

    **Requires API key** when ``STARSHIELD_API_KEY_REQUIRED=1``.
    """
    if body.debris_group not in DEBRIS_GROUPS and not is_debris_group(body.debris_group):
        raise HTTPException(
            status_code=400,
            detail=f"Unknown debris group. Valid: {', '.join(DEBRIS_GROUPS)}",
        )
    # Ensure group is loaded
    if not index.satellites_in_group(body.debris_group):
        raise HTTPException(
            status_code=404,
            detail=(
                f"Debris group '{body.debris_group}' not in index. "
                f"POST /debris/fetch with group={body.debris_group} first."
            ),
        )

    report = scan_primary_vs_debris(
        primary=body.primary,
        debris_group=body.debris_group,
        hours=body.hours,
        sample=body.sample,
        threshold_km=body.threshold_km,
        high_risk_km=body.high_risk_km,
        only_below=body.only_below,
        index=index,
    )

    if report.get("pairs_scanned", 0) == 0:
        skipped = (report.get("meta") or {}).get("skipped") or []
        raise HTTPException(
            status_code=404,
            detail=f"No pairs resolved (primary/debris missing?). skipped={skipped}",
        )

    db_run_id = None
    db_events = 0
    if body.persist and DB_LOG_ENABLED:
        try:
            info = log_watchlist_scan(report, source="api-debris")
            db_run_id = info.get("run_id")
            db_events = int(info.get("events_logged") or 0)
        except Exception:
            pass

    try:
        notify_conjunction_events(report, source="api-debris")
    except Exception:
        pass

    results = report.get("results") or []
    clipped = results[: body.max_results]
    out_results = []
    for r in clipped:
        tca = r.get("tca")
        out_results.append(
            ConjunctionResultOut(
                sat1=r.get("sat1") or "",
                sat2=r.get("sat2") or "",
                norad1=r.get("norad1"),
                norad2=r.get("norad2"),
                tca=tca.isoformat() if hasattr(tca, "isoformat") else str(tca) if tca else None,
                min_dist_km=float(r.get("min_dist_km") or 0),
                rel_velocity_kms=r.get("rel_velocity_kms"),
                risk=r.get("risk") or "LOW",
                below_threshold=bool(r.get("below_threshold")),
            )
        )

    return WatchlistScanResponse(
        watchlist_id=report.get("watchlist_id") or f"adhoc-{body.primary}",
        watchlist_name=report.get("watchlist_name") or f"{body.primary} vs {body.debris_group}",
        hours=float(report.get("hours") or body.hours),
        pairs_scanned=int(report.get("pairs_scanned") or 0),
        count=len(out_results),
        summary=report.get("summary") or {},
        results=out_results,
        db_run_id=db_run_id,
        db_events_logged=db_events,
    )
