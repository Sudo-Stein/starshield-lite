"""Pass prediction schemas."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from api.schemas.common import ObserverOut


class QualityOut(BaseModel):
    score: int
    grade: str
    breakdown: Dict[str, Any] = Field(default_factory=dict)
    sunlit_fraction: Optional[float] = None
    sun_alt: Optional[float] = None
    duration_minutes: Optional[float] = None
    max_elevation: Optional[float] = None


class EventSampleOut(BaseModel):
    time: Optional[str] = None
    alt: Optional[float] = None
    az: Optional[float] = None
    direction: Optional[str] = None


class PassOut(BaseModel):
    object_name: str
    norad: Optional[int] = None
    rise: Optional[EventSampleOut] = None
    culmination: Optional[EventSampleOut] = None
    set: Optional[EventSampleOut] = None
    max_elevation: Optional[float] = None
    duration_s: Optional[float] = None
    sunlit: Optional[bool] = None
    dark_sky: Optional[bool] = None
    visible: Optional[bool] = None
    sun_alt: Optional[float] = None
    quality: Optional[QualityOut] = None
    quality_score: Optional[int] = None
    quality_grade: Optional[str] = None


class PassesResponse(BaseModel):
    object_name: str
    norad: Optional[int] = None
    observer: ObserverOut
    hours: float
    min_elevation: float
    stargazer: bool
    sort: str
    min_score: float
    geometric_count: Optional[int] = None
    visible_count: Optional[int] = None
    count: int
    passes: List[PassOut]
