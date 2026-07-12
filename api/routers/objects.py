"""Object index search endpoints."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from api.dependencies import get_object_index
from api.schemas.objects import ObjectRecordOut, ObjectSearchResponse
from services.object_index import ObjectIndex

router = APIRouter(prefix="/objects", tags=["objects"])


def _record_out(rec) -> ObjectRecordOut:
    return ObjectRecordOut(
        norad=rec.norad,
        name=rec.name,
        groups=sorted(rec.groups),
        aliases=list(rec.aliases),
        epoch=rec.epoch.isoformat() if rec.epoch else None,
        primary_group=rec.primary_group,
    )


@router.get("/search", response_model=ObjectSearchResponse)
def search_objects(
    q: str = Query(..., min_length=1, description="Name, partial name, alias, or NORAD"),
    limit: int = Query(25, ge=1, le=100),
    index: ObjectIndex = Depends(get_object_index),
):
    """Search the multi-catalog object index."""
    hits = index.search(q.strip(), limit=limit)
    return ObjectSearchResponse(
        query=q.strip(),
        count=len(hits),
        results=[_record_out(h) for h in hits],
    )


@router.get("/{norad}", response_model=ObjectRecordOut)
def get_object(
    norad: int,
    index: ObjectIndex = Depends(get_object_index),
):
    """Lookup a single object by NORAD catalog number."""
    rec = index.get(norad)
    if rec is None:
        raise HTTPException(status_code=404, detail=f"NORAD {norad} not found in index")
    return _record_out(rec)
