"""Watchlist endpoints."""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException

from api.dependencies import get_object_index
from api.schemas.watchlist import (
    ConjunctionResultOut,
    WatchlistInfo,
    WatchlistScanRequest,
    WatchlistScanResponse,
)
from api.security import require_api_key
from config import DB_LOG_ENABLED
from services.database import log_watchlist_scan
from services.object_index import ObjectIndex
from services.watchlist import get_watchlist, list_watchlists, scan_watchlist

router = APIRouter(prefix="/watchlist", tags=["watchlist"])


@router.get("", response_model=List[WatchlistInfo])
def list_all_watchlists():
    """List configured conjunction watchlists."""
    return [
        WatchlistInfo(
            id=w.id,
            name=w.name,
            description=w.description,
            mode=w.mode,
            primary=w.primary,
            group=w.group or w.group2,
            sample=w.sample,
        )
        for w in list_watchlists()
    ]


@router.get("/{watchlist_id}", response_model=WatchlistInfo)
def get_one_watchlist(watchlist_id: str):
    w = get_watchlist(watchlist_id)
    if w is None:
        raise HTTPException(status_code=404, detail=f"Watchlist '{watchlist_id}' not found")
    return WatchlistInfo(
        id=w.id,
        name=w.name,
        description=w.description,
        mode=w.mode,
        primary=w.primary,
        group=w.group or w.group2,
        sample=w.sample,
    )


@router.post(
    "/scan",
    response_model=WatchlistScanResponse,
    dependencies=[Depends(require_api_key)],
)
def run_watchlist_scan(
    body: WatchlistScanRequest,
    index: ObjectIndex = Depends(get_object_index),
):
    """Scan a watchlist over a time window; optionally persist MEDIUM/HIGH hits.

    **Requires API key** when ``STARSHIELD_API_KEY_REQUIRED=1``.
    """
    w = get_watchlist(body.watchlist_id)
    if w is None:
        raise HTTPException(
            status_code=404, detail=f"Watchlist '{body.watchlist_id}' not found"
        )
    if body.sample is not None:
        w.sample = int(body.sample)

    report = scan_watchlist(
        w,
        hours=body.hours,
        threshold_km=body.threshold_km,
        high_risk_km=body.high_risk_km,
        only_below=body.only_below,
        adaptive=body.adaptive,
        steps=180,
        progress_every=0,
        index=index,
    )

    db_run_id = None
    db_events = 0
    if body.persist and DB_LOG_ENABLED:
        try:
            info = log_watchlist_scan(report, source="api")
            db_run_id = info.get("run_id")
            db_events = int(info.get("events_logged") or 0)
        except Exception:
            pass

    try:
        from services.notifications import notify_conjunction_events

        notify_conjunction_events(report, source="api")
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
        watchlist_id=report.get("watchlist_id") or w.id,
        watchlist_name=report.get("watchlist_name") or w.name,
        hours=float(report.get("hours") or body.hours),
        pairs_scanned=int(report.get("pairs_scanned") or 0),
        count=len(out_results),
        summary=report.get("summary") or {},
        results=out_results,
        db_run_id=db_run_id,
        db_events_logged=db_events,
    )
