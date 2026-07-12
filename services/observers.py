"""Named observer profiles and custom location resolution."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Optional

from config import DEFAULT_OBSERVER, LOCATION, OBSERVER_PROFILES


def list_observer_names() -> List[str]:
    """Return profile names in display order (default first)."""
    names = list(OBSERVER_PROFILES.keys())
    if DEFAULT_OBSERVER in names:
        names.remove(DEFAULT_OBSERVER)
        names.insert(0, DEFAULT_OBSERVER)
    return names


def get_observer(name: Optional[str] = None) -> Dict[str, Any]:
    """Return a location dict for a named profile (copy).

    Falls back to config LOCATION / DEFAULT_OBSERVER.
    """
    key = name or DEFAULT_OBSERVER
    if key in OBSERVER_PROFILES:
        return deepcopy(OBSERVER_PROFILES[key])
    # Unknown name → home default
    return deepcopy(OBSERVER_PROFILES.get(DEFAULT_OBSERVER, LOCATION))


def resolve_observer(
    *,
    profile: Optional[str] = None,
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    elevation: Optional[float] = None,
    label: Optional[str] = None,
) -> Dict[str, Any]:
    """Build an observer location from profile and/or custom overrides.

    If lat and lon are both provided, custom coordinates win (elevation
    defaults to profile/home elevation when omitted).
    """
    base = get_observer(profile)
    if lat is not None and lon is not None:
        return {
            "name": label or "Custom",
            "lat": float(lat),
            "lon": float(lon),
            "elevation": float(
                elevation if elevation is not None else base.get("elevation", 0.0)
            ),
            "note": "user-defined",
        }
    if elevation is not None:
        base["elevation"] = float(elevation)
    return base


def format_observer(loc: Dict[str, Any]) -> str:
    """Short human label for UI captions."""
    name = loc.get("name", "Observer")
    lat = loc.get("lat", 0.0)
    lon = loc.get("lon", 0.0)
    ns = "N" if lat >= 0 else "S"
    ew = "E" if lon >= 0 else "W"
    elev = loc.get("elevation", 0.0)
    return f"{name} ({abs(lat):g}°{ns}, {abs(lon):g}°{ew}, {elev:g} m)"
