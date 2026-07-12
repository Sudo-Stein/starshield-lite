"""Pass quality scoring — rank which passes are worth going outside for.

Score 0–100 with letter grade, built from:
  Max elevation (30%), duration (20%), sky darkness (25%),
  sunlit fraction (15%), magnitude proxy / ISS bonus (10%).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from skyfield.api import EarthSatellite, load

from config import LOCATION
from core.predictor import (
    is_satellite_sunlit,
    make_observer,
    sun_altitude_at_observer,
    _ephemeris,
    _to_skyfield_time,
)


# ---------------------------------------------------------------------------
# Grades
# ---------------------------------------------------------------------------

def get_grade(score: float) -> str:
    if score >= 85:
        return "A"
    if score >= 70:
        return "B"
    if score >= 55:
        return "C"
    if score >= 40:
        return "D"
    return "F"


def grade_style(grade: str) -> str:
    """Rich / CSS-ish color hint for UIs."""
    return {
        "A": "green",
        "B": "green",
        "C": "yellow",
        "D": "red",
        "F": "red",
    }.get(grade, "white")


# ---------------------------------------------------------------------------
# Component scores
# ---------------------------------------------------------------------------

def _duration_minutes(pass_data: dict) -> float:
    if pass_data.get("duration_minutes") is not None:
        return float(pass_data["duration_minutes"])
    dur_s = pass_data.get("duration_s")
    if dur_s is not None:
        return float(dur_s) / 60.0
    return 0.0


def _peak_time(pass_data: dict) -> Optional[datetime]:
    for key in ("culmination", "rise", "set"):
        ev = pass_data.get(key)
        if isinstance(ev, dict) and ev.get("time") is not None:
            t = ev["time"]
            if getattr(t, "tzinfo", None) is None:
                t = t.replace(tzinfo=timezone.utc)
            return t
    t = pass_data.get("culmination_time")
    if t is not None and getattr(t, "tzinfo", None) is None:
        t = t.replace(tzinfo=timezone.utc)
    return t


def _max_elevation(pass_data: dict) -> float:
    if pass_data.get("max_elevation") is not None:
        return float(pass_data["max_elevation"])
    culm = pass_data.get("culmination") or {}
    if isinstance(culm, dict) and culm.get("alt") is not None:
        return float(culm["alt"])
    return 0.0


def darkness_score_from_sun_alt(sun_alt: Optional[float]) -> float:
    """Map solar altitude (°) at observer → darkness score 0–100.

    Astronomical night (sun ≤ −18°) → 100
    Nautical (−18..−12) → ~85
    Civil (−12..−6) → ~60
    Civil twilight / dusk (−6..0) → ~35
    Daylight → low
    """
    if sun_alt is None:
        return 40.0  # unknown
    if sun_alt <= -18:
        return 100.0
    if sun_alt <= -12:
        # -18 → 100, -12 → 85
        return 85.0 + (-12 - sun_alt) / 6.0 * 15.0
    if sun_alt <= -6:
        return 60.0 + (-6 - sun_alt) / 6.0 * 25.0
    if sun_alt <= 0:
        return 35.0 + (0 - sun_alt) / 6.0 * 25.0
    if sun_alt <= 6:
        return max(5.0, 20.0 - sun_alt * 2.5)
    return 0.0


def estimate_sunlit_fraction(
    sat: EarthSatellite,
    pass_data: dict,
    location: Optional[dict] = None,
    samples: int = 7,
) -> float:
    """Fraction of the pass (rise→set) when the satellite is sunlit."""
    rise = pass_data.get("rise") or {}
    set_ = pass_data.get("set") or {}
    t0 = rise.get("time")
    t1 = set_.get("time")
    if t0 is None or t1 is None:
        # fall back to single peak flag
        if pass_data.get("sunlit") is True:
            return 1.0
        if pass_data.get("sunlit") is False:
            return 0.0
        return 0.5

    if getattr(t0, "tzinfo", None) is None:
        t0 = t0.replace(tzinfo=timezone.utc)
    if getattr(t1, "tzinfo", None) is None:
        t1 = t1.replace(tzinfo=timezone.utc)

    ts = load.timescale()
    eph = _ephemeris()
    span = (t1 - t0).total_seconds()
    if span <= 0:
        return 1.0 if pass_data.get("sunlit") else 0.0

    lit = 0
    n = max(2, samples)
    for i in range(n):
        frac = i / (n - 1)
        ti = _to_skyfield_time(ts, t0 + (t1 - t0) * frac)
        try:
            if is_satellite_sunlit(sat, ti, eph=eph):
                lit += 1
        except Exception:
            pass
    return lit / n


def magnitude_proxy_score(
    pass_data: dict,
    object_name: str = "",
) -> float:
    """Rough 0–100 'brightness potential' proxy (not a real mag model).

    Higher max elevation → shorter range → brighter.
    ISS / large stations get a strong bonus.
    """
    elev = _max_elevation(pass_data)
    # elevation proxy: 10°→30, 40°→70, 80°→95
    base = min(100.0, max(0.0, (elev - 5.0) / 75.0 * 100.0))
    name = (object_name or pass_data.get("object_name") or "").upper()
    if "ISS" in name and "DEB" not in name:
        base = min(100.0, base + 25.0)
    elif any(tok in name for tok in ("HST", "HUBBLE", "CSS", "TIANGONG", "TIANHE")):
        base = min(100.0, base + 12.0)
    elif "STARLINK" in name:
        base = min(100.0, base + 5.0)  # trains can be fun but dim alone
    return base


# ---------------------------------------------------------------------------
# Main API
# ---------------------------------------------------------------------------

def calculate_pass_quality(
    pass_data: dict,
    location: Optional[dict] = None,
    *,
    sat: Optional[EarthSatellite] = None,
    object_name: str = "",
) -> Dict[str, Any]:
    """Compute quality score 0–100 + letter grade + component breakdown.

    ``pass_data`` may be a raw predictor pass dict (rise/culmination/set,
    max_elevation, duration_s, sun_alt, sunlit) or a flat summary dict.
    """
    loc = location or LOCATION
    name = object_name or pass_data.get("object_name") or pass_data.get("name") or ""

    elev = _max_elevation(pass_data)
    elev_score = min(elev / 90.0 * 100.0, 100.0)

    dur_min = _duration_minutes(pass_data)
    dur_score = min(dur_min / 10.0 * 100.0, 100.0)

    # Darkness: prefer measured sun altitude at peak
    sun_alt = pass_data.get("sun_alt")
    if sun_alt is None and sat is not None:
        peak = _peak_time(pass_data)
        if peak is not None:
            try:
                ts = load.timescale()
                observer = make_observer(loc)
                ti = _to_skyfield_time(ts, peak)
                sun_alt = sun_altitude_at_observer(observer, ti)
            except Exception:
                sun_alt = None
    dark_score = darkness_score_from_sun_alt(
        float(sun_alt) if sun_alt is not None else None
    )

    # Sunlit fraction
    if "sunlit_fraction" in pass_data and pass_data["sunlit_fraction"] is not None:
        sunlit_frac = float(pass_data["sunlit_fraction"])
    elif sat is not None:
        sunlit_frac = estimate_sunlit_fraction(sat, pass_data, location=loc)
    elif pass_data.get("sunlit") is True:
        sunlit_frac = 1.0
    elif pass_data.get("sunlit") is False:
        sunlit_frac = 0.0
    else:
        sunlit_frac = 0.5
    sunlit_score = max(0.0, min(1.0, sunlit_frac)) * 100.0

    mag_score = magnitude_proxy_score(pass_data, name)

    # Weighted sum (weights sum to 1.0)
    final = (
        elev_score * 0.30
        + dur_score * 0.20
        + dark_score * 0.25
        + sunlit_score * 0.15
        + mag_score * 0.10
    )
    # Classic naked-eye combo bonus: dark sky + sunlit + decent elev
    if (
        sunlit_frac >= 0.5
        and sun_alt is not None
        and sun_alt <= -6
        and elev >= 20
    ):
        final = min(100.0, final + 5.0)

    # Hard reality: if the satellite is almost never sunlit, you won't see it
    # (Earth shadow) — cap the "go outside" score.
    if sunlit_frac < 0.15:
        final = min(final, 45.0)
    elif sunlit_frac < 0.4:
        final = min(final, 70.0)
    # Daylight: bright sky kills contrast even if sat is sunlit
    if sun_alt is not None and sun_alt > 0:
        final = min(final, 55.0)

    final_score = int(max(0, min(100, round(final))))
    grade = get_grade(final_score)

    return {
        "score": final_score,
        "grade": grade,
        "breakdown": {
            "elevation": round(elev_score, 1),
            "duration": round(dur_score, 1),
            "darkness": round(dark_score, 1),
            "sunlit": round(sunlit_score, 1),
            "magnitude_proxy": round(mag_score, 1),
        },
        "sunlit_fraction": round(sunlit_frac, 3),
        "sun_alt": round(float(sun_alt), 2) if sun_alt is not None else None,
        "duration_minutes": round(dur_min, 2),
        "max_elevation": round(elev, 2),
        "object_name": name,
    }


def score_passes(
    passes: Sequence[dict],
    location: Optional[dict] = None,
    *,
    sat: Optional[EarthSatellite] = None,
    object_name: str = "",
    min_score: float = 0,
    sort: bool = True,
) -> List[dict]:
    """Attach ``quality`` to each pass and optionally filter/sort by score.

    Returns **new** list of pass dicts (shallow copy + quality key).
    """
    scored: List[dict] = []
    for p in passes:
        q = calculate_pass_quality(
            p, location=location, sat=sat, object_name=object_name
        )
        item = dict(p)
        item["quality"] = q
        item["quality_score"] = q["score"]
        item["quality_grade"] = q["grade"]
        if q["score"] >= min_score:
            scored.append(item)
    if sort:
        scored.sort(key=lambda x: (-x["quality_score"], -(_max_elevation(x))))
    return scored


def format_quality_cell(q: Optional[dict]) -> str:
    """Compact table cell: ``B 78``."""
    if not q:
        return "—"
    return f"{q.get('grade', '?')} {q.get('score', 0)}"


def format_quality_breakdown(q: dict) -> str:
    """One-line breakdown for detail views."""
    b = q.get("breakdown") or {}
    return (
        f"el {b.get('elevation', '—')} · "
        f"dur {b.get('duration', '—')} · "
        f"dark {b.get('darkness', '—')} · "
        f"sun {b.get('sunlit', '—')} · "
        f"mag {b.get('magnitude_proxy', '—')}"
    )
