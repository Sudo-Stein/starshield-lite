"""Pass predictions over a ground observer (default: Kingsland, GA).

Stargazer mode keeps only naked-eye-friendly passes:
  • satellite above min elevation
  • observer sky dark enough (sun below twilight threshold)
  • satellite still sunlit (not in Earth's shadow)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any, Dict, List, Optional, Sequence

from skyfield.api import EarthSatellite, load, wgs84

from config import LOCATION, STARGAZER_SUN_ALT_MAX

# Compass labels for azimuth (16-point, for readable tables)
_AZ_POINTS = [
    "N",
    "NNE",
    "NE",
    "ENE",
    "E",
    "ESE",
    "SE",
    "SSE",
    "S",
    "SSW",
    "SW",
    "WSW",
    "W",
    "WNW",
    "NW",
    "NNW",
]


def az_to_direction(az_deg: float) -> str:
    """Convert azimuth degrees (0–360) to a compass label."""
    idx = int((az_deg % 360) / 22.5 + 0.5) % 16
    return _AZ_POINTS[idx]


@lru_cache(maxsize=1)
def _ephemeris():
    """Lazy-load planetary ephemeris (downloads de421.bsp on first use)."""
    return load("de421.bsp")


def make_observer(location: Optional[dict] = None):
    """Build a WGS84 observer from LOCATION or an override dict."""
    loc = location or LOCATION
    return wgs84.latlon(
        loc["lat"],
        loc["lon"],
        elevation_m=loc.get("elevation", 0.0),
    )


def find_satellite_by_name(
    satellites: Sequence[EarthSatellite],
    name: str,
) -> Optional[EarthSatellite]:
    """Case-insensitive match on satellite name.

    Prefers exact matches, then names that start with the query, and deprioritizes
    debris / rocket-body objects so ``ISS`` resolves to ``ISS (ZARYA)`` rather
    than ``ISS DEB``.
    """
    q = name.strip().upper()
    if not q:
        return None

    exact = [s for s in satellites if s.name.strip().upper() == q]
    if exact:
        return exact[0]

    matches = [s for s in satellites if q in s.name.upper()]
    if not matches:
        return None

    def _score(s: EarthSatellite):
        n = s.name.strip().upper()
        # Lower score wins
        if n == q:
            rank = 0
        elif n.startswith(q + " ") or n.startswith(q + "(") or n.startswith(q + "-"):
            rank = 10
        elif n.startswith(q):
            rank = 20
        else:
            rank = 50
        # Debris / R/B usually not what people want for "passes"
        if any(tok in n for tok in (" DEB", "DEBRI", "R/B", " AKM")):
            rank += 100
        # Prefer the classic ISS complex designator over module-only TLEs
        if q == "ISS" and "ZARYA" in n:
            rank -= 5
        return (rank, len(n), n)

    matches.sort(key=_score)
    return matches[0]


def search_satellites(
    satellites: Sequence[EarthSatellite],
    name: str,
    limit: int = 15,
) -> List[EarthSatellite]:
    """Return up to `limit` satellites whose names contain `name`."""
    q = name.strip().upper()
    hits = [s for s in satellites if q in s.name.upper()]
    hits.sort(key=lambda s: (len(s.name), s.name))
    return hits[:limit]


def _event_sample(sat, observer, ti) -> Dict[str, Any]:
    """Altitude / azimuth at a Skyfield time for sat relative to observer."""
    topocentric = (sat - observer).at(ti)
    alt, az, _distance = topocentric.altaz()
    return {
        "time": ti.utc_datetime(),
        "alt": float(alt.degrees),
        "az": float(az.degrees),
        "direction": az_to_direction(float(az.degrees)),
    }


def sun_altitude_at_observer(observer, ti, eph=None) -> float:
    """Apparent solar altitude (degrees) at the observer."""
    eph = eph or _ephemeris()
    earth = eph["earth"]
    sun = eph["sun"]
    # GeographicPosition is already a topos relative to Earth
    astrometric = (earth + observer).at(ti).observe(sun).apparent()
    alt, _az, _dist = astrometric.altaz()
    return float(alt.degrees)


def is_satellite_sunlit(sat: EarthSatellite, ti, eph=None) -> bool:
    """True if the satellite is outside Earth's umbra at time ``ti``."""
    eph = eph or _ephemeris()
    # Skyfield Geocentric.is_sunlit handles umbra geometry
    result = sat.at(ti).is_sunlit(eph)
    # May be a numpy bool_ or array of length 1
    try:
        return bool(result)
    except TypeError:
        return bool(result.item())


def visibility_at(
    sat: EarthSatellite,
    observer,
    ti,
    *,
    sun_alt_max: float = STARGAZER_SUN_ALT_MAX,
    eph=None,
) -> Dict[str, Any]:
    """Evaluate stargazer visibility at a single epoch.

    Returns dict with sunlit, dark_sky, sun_alt, visible.
    """
    eph = eph or _ephemeris()
    sun_alt = sun_altitude_at_observer(observer, ti, eph=eph)
    sunlit = is_satellite_sunlit(sat, ti, eph=eph)
    dark_sky = sun_alt <= sun_alt_max
    return {
        "sun_alt": sun_alt,
        "sunlit": sunlit,
        "dark_sky": dark_sky,
        "visible": bool(sunlit and dark_sky),
    }


def _to_skyfield_time(ts, dt: datetime):
    """Convert a datetime to a Skyfield Time (UTC)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return ts.from_datetime(dt)


def _sample_times_for_pass(raw: Dict[str, Any], ts) -> List[Any]:
    """Epochs to evaluate stargazer visibility along a pass.

    Prefer culmination for reporting, but also check rise/set and midpoints so
    twilight-edge passes are not missed.
    """
    samples = []
    for key in ("rise", "culmination", "set"):
        ev = raw.get(key)
        if ev and ev.get("time") is not None:
            samples.append(_to_skyfield_time(ts, ev["time"]))

    rise = raw.get("rise")
    set_ = raw.get("set")
    if rise and set_ and rise.get("time") and set_.get("time"):
        t0 = rise["time"]
        t1 = set_["time"]
        if t0.tzinfo is None:
            t0 = t0.replace(tzinfo=timezone.utc)
        if t1.tzinfo is None:
            t1 = t1.replace(tzinfo=timezone.utc)
        span = (t1 - t0).total_seconds()
        if span > 60:
            for frac in (0.25, 0.5, 0.75):
                samples.append(
                    _to_skyfield_time(ts, t0 + timedelta(seconds=span * frac))
                )
    return samples


def _evaluate_pass_visibility(
    sat: EarthSatellite,
    observer,
    raw: Dict[str, Any],
    ts,
    *,
    sun_alt_max: float,
    eph,
) -> Dict[str, Any]:
    """Return best visibility metadata along the pass (prefer visible epochs)."""
    times = _sample_times_for_pass(raw, ts)
    if not times:
        return {
            "sun_alt": None,
            "sunlit": None,
            "dark_sky": None,
            "visible": None,
        }

    best = None
    for ti in times:
        try:
            vis = visibility_at(
                sat, observer, ti, sun_alt_max=sun_alt_max, eph=eph
            )
        except Exception:
            continue
        if best is None:
            best = vis
        elif vis["visible"] and not best["visible"]:
            best = vis
        elif vis["visible"] == best["visible"]:
            # Prefer darker sky among equals
            if (vis.get("sun_alt") is not None) and (
                best.get("sun_alt") is None
                or vis["sun_alt"] < best["sun_alt"]
            ):
                best = vis
    return best or {
        "sun_alt": None,
        "sunlit": None,
        "dark_sky": None,
        "visible": None,
    }


def predict_passes(
    sat: EarthSatellite,
    location: Optional[dict] = None,
    hours_ahead: float = 24,
    min_elevation: float = 10.0,
    max_passes: int = 10,
    stargazer: bool = True,
    sun_alt_max: float = STARGAZER_SUN_ALT_MAX,
) -> List[Dict[str, Any]]:
    """Find upcoming passes of ``sat`` above ``min_elevation``.

    Each pass dict includes:
      rise, culmination, set  — event samples (time, alt, az, direction)
      max_elevation, duration_s
      sunlit, dark_sky, sun_alt, visible  — stargazer flags at peak

    When ``stargazer=True`` (default), only naked-eye-friendly passes are
    returned (dark sky + sunlit satellite at culmination).
    """
    ts = load.timescale()
    observer = make_observer(location)
    eph = _ephemeris() if stargazer else None

    t0 = ts.now()
    t1 = ts.utc(t0.utc_datetime() + timedelta(hours=hours_ahead))

    times, events = sat.find_events(
        observer, t0, t1, altitude_degrees=min_elevation
    )

    raw_passes: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None

    for ti, event in zip(times, events):
        sample = _event_sample(sat, observer, ti)

        if event == 0:  # rise
            if current and (current.get("rise") or current.get("culmination")):
                raw_passes.append(current)
            current = {"rise": sample, "culmination": None, "set": None}

        elif event == 1:  # culmination
            if current is None:
                current = {"rise": None, "culmination": sample, "set": None}
            else:
                current["culmination"] = sample

        elif event == 2:  # set
            if current is None:
                current = {"rise": None, "culmination": None, "set": sample}
            else:
                current["set"] = sample
            raw_passes.append(current)
            current = None

    if current is not None:
        raw_passes.append(current)

    eph = eph or _ephemeris()
    all_finalized: List[Dict[str, Any]] = []
    for raw in raw_passes:
        finalized = _finalize_pass(raw)
        vis = _evaluate_pass_visibility(
            sat,
            observer,
            raw,
            ts,
            sun_alt_max=sun_alt_max,
            eph=eph,
        )
        finalized.update(vis)
        all_finalized.append(finalized)

    if stargazer:
        passes = [p for p in all_finalized if p.get("visible")]
    else:
        passes = all_finalized

    passes.sort(
        key=lambda p: (
            p.get("culmination") or p.get("rise") or p.get("set") or {}
        ).get("time")
        or datetime.min.replace(tzinfo=timezone.utc)
    )

    out = _PassList(passes[:max_passes])
    out.geometric_count = len(raw_passes)
    out.visible_count = sum(1 for p in all_finalized if p.get("visible"))
    out.stargazer = stargazer
    return out


class _PassList(list):
    """List of passes with optional filter statistics for the CLI."""

    geometric_count: int = 0
    visible_count: int = 0
    stargazer: bool = False


def _finalize_pass(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Attach max_elevation and duration from event samples."""
    culm = raw.get("culmination")
    rise = raw.get("rise")
    set_ = raw.get("set")

    max_el = None
    if culm is not None:
        max_el = culm["alt"]
    elif rise is not None:
        max_el = rise["alt"]

    duration_s = None
    if rise is not None and set_ is not None:
        duration_s = (set_["time"] - rise["time"]).total_seconds()

    return {
        "rise": rise,
        "culmination": culm,
        "set": set_,
        "max_elevation": max_el,
        "duration_s": duration_s,
    }


def format_pass_row(p: Dict[str, Any], local: bool = False) -> Dict[str, str]:
    """Flatten a pass dict into display strings for a Rich table.

    When ``local=True``, times are converted to the system local timezone
    (still labeled with the zone abbreviation, e.g. EDT).
    """
    rise = p.get("rise")
    culm = p.get("culmination")
    set_ = p.get("set")

    def _t(ev):
        if not ev:
            return "—"
        t = ev["time"]
        if getattr(t, "tzinfo", None) is None:
            t = t.replace(tzinfo=timezone.utc)
        if local:
            t = t.astimezone()
            return t.strftime("%Y-%m-%d %H:%M %Z")
        return t.strftime("%Y-%m-%d %H:%M:%S")

    def _az(ev):
        if not ev:
            return "—"
        return f"{ev['az']:.0f}° {ev['direction']}"

    max_el = p.get("max_elevation")
    max_el_s = f"{max_el:.1f}°" if max_el is not None else "—"

    dur = p.get("duration_s")
    if dur is not None:
        mins = int(dur // 60)
        secs = int(dur % 60)
        dur_s = f"{mins}m {secs:02d}s"
    else:
        dur_s = "—"

    sun_alt = p.get("sun_alt")
    if sun_alt is None:
        sky = "—"
    else:
        # Compact sky condition for table
        if p.get("visible"):
            sky = f"★ {sun_alt:.0f}°"
        elif p.get("dark_sky") and not p.get("sunlit"):
            sky = "shadow"
        elif p.get("sunlit") and not p.get("dark_sky"):
            sky = "daylight"
        else:
            sky = f"{sun_alt:.0f}°"

    q = p.get("quality") or {}
    if q:
        quality = f"{q.get('grade', '?')} {q.get('score', '')}".strip()
    else:
        quality = "—"

    return {
        "rise": _t(rise),
        "culmination": _t(culm),
        "set": _t(set_),
        "max_el": max_el_s,
        "az_max": _az(culm or rise),
        "duration": dur_s,
        "sky": sky,
        "quality": quality,
    }


def next_pass_summary(
    sat: EarthSatellite,
    *,
    location: Optional[dict] = None,
    hours_ahead: float = 168,
    stargazer: bool = True,
    min_elevation: float = 10.0,
) -> Optional[Dict[str, Any]]:
    """Return the soonest pass (and a human countdown), or None."""
    passes = predict_passes(
        sat,
        location=location,
        hours_ahead=hours_ahead,
        min_elevation=min_elevation,
        max_passes=1,
        stargazer=stargazer,
    )
    if not passes:
        return None
    p = passes[0]
    peak = p.get("culmination") or p.get("rise") or p.get("set")
    if not peak or not peak.get("time"):
        return None
    t = peak["time"]
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    delta = t - now
    secs = int(delta.total_seconds())
    if secs < 0:
        countdown = "now / in progress"
    else:
        days, rem = divmod(secs, 86400)
        hours, rem = divmod(rem, 3600)
        mins, _ = divmod(rem, 60)
        if days:
            countdown = f"in {days}d {hours}h {mins}m"
        elif hours:
            countdown = f"in {hours}h {mins}m"
        else:
            countdown = f"in {mins}m"
    return {
        "pass": p,
        "peak_time": t,
        "countdown": countdown,
        "max_elevation": p.get("max_elevation"),
        "visible": p.get("visible"),
        "local": t.astimezone().strftime("%Y-%m-%d %H:%M %Z"),
        "utc": t.strftime("%Y-%m-%d %H:%M:%S UTC"),
    }
