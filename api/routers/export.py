"""Export download endpoints (PDF / ICS)."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from api.dependencies import get_object_index, resolve_location
from api.security import require_api_key
from core.predictor import predict_passes
from services.export import (
    ExportError,
    passes_to_ics,
    passes_to_pdf,
    watchlist_to_pdf,
)
from services.object_index import ObjectIndex
from services.pass_quality import score_passes
from services.watchlist import get_watchlist, scan_watchlist

router = APIRouter(
    prefix="/export",
    tags=["export"],
    dependencies=[Depends(require_api_key)],
)


@router.get("/passes.pdf")
def export_passes_pdf(
    object: str = Query(..., description="Object name / NORAD"),
    hours: float = Query(72, gt=0, le=336),
    stargazer: bool = Query(False),
    sort: str = Query("quality"),
    min_score: float = Query(0),
    limit: int = Query(20, ge=1, le=100),
    location: dict = Depends(resolve_location),
    index: ObjectIndex = Depends(get_object_index),
):
    """Download a PDF pass report (protected)."""
    rec = index.resolve(object)
    sat = index.get_satellite(rec) if rec else None
    if sat is None:
        raise HTTPException(404, detail=f"Object '{object}' not found")
    raw = predict_passes(
        sat,
        location=location,
        hours_ahead=hours,
        max_passes=max(limit * 2, 30),
        stargazer=stargazer,
    )
    scored = score_passes(
        raw,
        location=location,
        sat=sat,
        object_name=sat.name,
        min_score=min_score,
        sort=(sort.lower() in ("quality", "score", "best")),
    )[:limit]
    try:
        data = passes_to_pdf(
            scored,
            object_name=sat.name.strip(),
            location=location,
            stargazer=stargazer,
            hours=hours,
        )
    except ExportError as exc:
        raise HTTPException(503, detail=str(exc)) from exc
    fname = f"passes_{rec.norad if rec else 'obj'}.pdf"
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.get("/passes.ics")
def export_passes_ics(
    object: str = Query(...),
    hours: float = Query(72, gt=0, le=336),
    stargazer: bool = Query(True),
    limit: int = Query(30, ge=1, le=100),
    location: dict = Depends(resolve_location),
    index: ObjectIndex = Depends(get_object_index),
):
    """Download an ICS calendar of passes (protected)."""
    rec = index.resolve(object)
    sat = index.get_satellite(rec) if rec else None
    if sat is None:
        raise HTTPException(404, detail=f"Object '{object}' not found")
    raw = predict_passes(
        sat,
        location=location,
        hours_ahead=hours,
        max_passes=limit,
        stargazer=stargazer,
    )
    scored = score_passes(
        raw, location=location, sat=sat, object_name=sat.name, sort=True
    )[:limit]
    ics = passes_to_ics(
        scored,
        object_name=sat.name.strip(),
        location=location,
    )
    fname = f"passes_{rec.norad if rec else 'obj'}.ics"
    return Response(
        content=ics.encode("utf-8"),
        media_type="text/calendar",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.get("/watchlist.pdf")
def export_watchlist_pdf(
    watchlist_id: str = Query("iss-starlink"),
    hours: float = Query(48, gt=0, le=336),
    sample: int = Query(15, ge=1, le=80),
    only_below: bool = Query(False),
    index: ObjectIndex = Depends(get_object_index),
):
    """Run a watchlist scan and download PDF (protected)."""
    w = get_watchlist(watchlist_id)
    if w is None:
        raise HTTPException(404, detail=f"Watchlist '{watchlist_id}' not found")
    w.sample = sample
    report = scan_watchlist(
        w,
        hours=hours,
        only_below=only_below,
        adaptive=True,
        steps=120,
        progress_every=0,
        index=index,
    )
    try:
        data = watchlist_to_pdf(report)
    except ExportError as exc:
        raise HTTPException(503, detail=str(exc)) from exc
    return Response(
        content=data,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="watchlist_{watchlist_id}.pdf"'
        },
    )
