"""Shared schema pieces."""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = "ok"
    service: str = "starshield-lite"
    version: str = "0.2.0"
    db_logging: bool = True
    index_objects: Optional[int] = None
    api_key_required: bool = False


class ErrorResponse(BaseModel):
    detail: str
    code: Optional[str] = None


class LocationParams(BaseModel):
    """Observer location — profile name and/or explicit lat/lon."""

    profile: Optional[str] = Field(
        None, description="Named profile, e.g. 'Kingsland, GA'"
    )
    lat: Optional[float] = Field(None, ge=-90, le=90)
    lon: Optional[float] = Field(None, ge=-180, le=180)
    elevation: Optional[float] = Field(None, description="Meters above WGS84")
    label: Optional[str] = Field(None, description="Custom location name")

    def to_observer_dict(self) -> Dict[str, Any]:
        from services.observers import resolve_observer

        return resolve_observer(
            profile=self.profile,
            lat=self.lat,
            lon=self.lon,
            elevation=self.elevation,
            label=self.label,
        )


class ObserverOut(BaseModel):
    name: Optional[str] = None
    lat: float
    lon: float
    elevation: float = 0.0
    note: Optional[str] = None
