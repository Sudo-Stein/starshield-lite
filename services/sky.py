"""Sky planning helpers: tracks, scrub positions, event markers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
from skyfield.api import EarthSatellite, load

from config import LOCATION
from core.predictor import make_observer
from core.starmap import build_starmap_figure


def sky_track_from(
    sat: EarthSatellite,
    *,
    location: Optional[dict] = None,
    start: Optional[datetime] = None,
    hours: float = 6,
    step_minutes: float = 1.0,
    min_elevation: float = 0.0,
) -> Dict[str, Any]:
    """Alt/az track starting at ``start`` (default: now)."""
    ts = load.timescale()
    observer = make_observer(location or LOCATION)
    if start is None:
        t0 = ts.now()
    else:
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        t0 = ts.from_datetime(start)

    n = max(2, int((hours * 60) / step_minutes) + 1)
    times = ts.tt_jd(np.linspace(t0.tt, t0.tt + hours / 24.0, n))

    topocentric = (sat - observer).at(times)
    alt, az, _dist = topocentric.altaz()
    alt_d = np.asarray(alt.degrees, dtype=float)
    az_d = np.asarray(az.degrees, dtype=float)
    above = alt_d >= min_elevation

    alt_plot = np.where(above, alt_d, np.nan)
    az_plot = np.where(above, az_d, np.nan)
    t_list = [times[i].utc_datetime() for i in range(n)]

    # Scrub reference = first sample
    return {
        "name": sat.name.strip(),
        "times": t_list,
        "alt_deg": alt_plot,
        "az_deg": az_plot,
        "alt_raw": alt_d,
        "az_raw": az_d,
        "above": above,
        "now_alt": float(alt_d[0]),
        "now_az": float(az_d[0]),
        "now_above": bool(above[0]),
        "start": t_list[0],
        "hours": hours,
        "events": find_track_events(alt_d, az_d, t_list, min_elevation),
    }


def find_track_events(
    alt: np.ndarray,
    az: np.ndarray,
    times: Sequence[datetime],
    min_elevation: float,
) -> List[Dict[str, Any]]:
    """Detect rise / culmination / set along a discrete alt series."""
    events: List[Dict[str, Any]] = []
    above = alt >= min_elevation
    n = len(alt)
    if n < 2:
        return events

    # Rise / set crossings
    for i in range(1, n):
        if not above[i - 1] and above[i]:
            events.append(
                {
                    "type": "rise",
                    "index": i,
                    "time": times[i],
                    "alt": float(alt[i]),
                    "az": float(az[i]),
                }
            )
        if above[i - 1] and not above[i]:
            events.append(
                {
                    "type": "set",
                    "index": i - 1,
                    "time": times[i - 1],
                    "alt": float(alt[i - 1]),
                    "az": float(az[i - 1]),
                }
            )

    # Culmination: local max while above horizon
    for i in range(1, n - 1):
        if above[i] and alt[i] >= alt[i - 1] and alt[i] >= alt[i + 1]:
            # skip tiny noise peaks near horizon
            if alt[i] < min_elevation + 1:
                continue
            events.append(
                {
                    "type": "culmination",
                    "index": i,
                    "time": times[i],
                    "alt": float(alt[i]),
                    "az": float(az[i]),
                }
            )
    return events


def position_at_offset(
    track: Dict[str, Any],
    hours_from_start: float,
) -> Dict[str, Any]:
    """Nearest sample on a track for a time offset from track start."""
    times = track["times"]
    if not times:
        return {"alt": None, "az": None, "above": False, "time": None, "index": 0}
    start = times[0]
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    target = start + timedelta(hours=hours_from_start)
    # find nearest
    best_i = 0
    best_dt = None
    for i, t in enumerate(times):
        tt = t if t.tzinfo else t.replace(tzinfo=timezone.utc)
        d = abs((tt - target).total_seconds())
        if best_dt is None or d < best_dt:
            best_dt = d
            best_i = i
    alt = float(track["alt_raw"][best_i])
    az = float(track["az_raw"][best_i])
    return {
        "alt": alt,
        "az": az,
        "above": bool(track["above"][best_i]),
        "time": times[best_i],
        "index": best_i,
        "name": track.get("name"),
    }


def build_scrubber_figure(
    tracks: Sequence[Dict[str, Any]],
    *,
    scrub_hours: float = 0.0,
    location_label: str = "",
    title: Optional[str] = None,
    show_events: bool = True,
):
    """Starmap with full tracks + scrub marker + optional rise/culm/set."""
    import plotly.graph_objects as go

    # Base figure from core (tracks + optional "now" at index 0)
    # Temporarily set now_* to scrub position for star markers
    patched = []
    for tr in tracks:
        pos = position_at_offset(tr, scrub_hours)
        t2 = dict(tr)
        t2["now_alt"] = pos["alt"] if pos["alt"] is not None else -99
        t2["now_az"] = pos["az"] if pos["az"] is not None else 0
        t2["now_above"] = bool(pos["above"])
        patched.append(t2)

    hours = tracks[0].get("hours", 6) if tracks else 6
    ttl = title or (
        f"Sky view · scrub +{scrub_hours:.2f}h / {hours:g}h window"
        + (f" · {location_label}" if location_label else "")
    )
    fig = build_starmap_figure(patched, title=ttl, show_now_markers=True)

    if not show_events:
        fig.update_layout(
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                x=0,
                bgcolor="rgba(15,20,40,0.7)",
            )
        )
        return fig

    # Event markers with legend entries once per type
    symbols = {"rise": "triangle-up", "culmination": "diamond", "set": "triangle-down"}
    colors = {"rise": "#7CFC00", "culmination": "#ffd700", "set": "#ff6b6b"}
    seen_types = set()
    for tr in tracks:
        for ev in tr.get("events") or []:
            if ev["alt"] < 0:
                continue
            et = ev["type"]
            show_leg = et not in seen_types
            seen_types.add(et)
            t = ev["time"]
            t_s = t.strftime("%H:%M UTC") if hasattr(t, "strftime") else str(t)
            fig.add_trace(
                go.Scatterpolar(
                    r=[90.0 - ev["alt"]],
                    theta=[ev["az"]],
                    mode="markers",
                    name=et.capitalize() if show_leg else et,
                    legendgroup=et,
                    marker=dict(
                        size=10 if et != "culmination" else 12,
                        color=colors.get(et, "#fff"),
                        symbol=symbols.get(et, "circle"),
                        line=dict(width=1, color="#111"),
                    ),
                    hovertext=(
                        f"<b>{tr['name']}</b> {et}<br>"
                        f"{t_s}<br>"
                        f"alt {ev['alt']:.1f}° · az {ev['az']:.1f}°"
                    ),
                    hoverinfo="text",
                    showlegend=show_leg,
                )
            )
    fig.update_layout(
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            x=0,
            bgcolor="rgba(15,20,40,0.7)",
            font=dict(size=11),
        ),
        margin=dict(l=40, r=40, t=70, b=40),
    )
    return fig


def tracks_for_objects(
    satellites: Sequence[EarthSatellite],
    *,
    location: dict,
    hours: float = 6,
    step_minutes: float = 1.0,
    min_elevation: float = 5.0,
    start: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """Build scrubber tracks for a list of satellites."""
    out = []
    for sat in satellites:
        out.append(
            sky_track_from(
                sat,
                location=location,
                start=start,
                hours=hours,
                step_minutes=step_minutes,
                min_elevation=min_elevation,
            )
        )
    return out


def ground_track_latlon(
    sat: EarthSatellite,
    *,
    hours: float = 6,
    step_minutes: float = 2.0,
    start: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Sub-satellite points (lat/lon) for a simple ground-track plot."""
    from skyfield.api import wgs84

    ts = load.timescale()
    if start is None:
        t0 = ts.now()
    else:
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        t0 = ts.from_datetime(start)

    n = max(2, int((hours * 60) / step_minutes) + 1)
    times = ts.tt_jd(np.linspace(t0.tt, t0.tt + hours / 24.0, n))
    sub = wgs84.subpoint_of(sat.at(times))
    return {
        "name": sat.name.strip(),
        "lat": np.asarray(sub.latitude.degrees, dtype=float),
        "lon": np.asarray(sub.longitude.degrees, dtype=float),
        "times": [times[i].utc_datetime() for i in range(n)],
        "hours": hours,
    }


def build_ground_track_figure(
    tracks: Sequence[Dict[str, Any]],
    *,
    location: Optional[dict] = None,
    scrub_hours: float = 0.0,
    title: Optional[str] = None,
):
    """Plotly geographic ground tracks (no Cartopy required)."""
    import plotly.graph_objects as go

    loc = location or LOCATION
    palette = [
        "#00d4ff",
        "#ff6b6b",
        "#7CFC00",
        "#ffd700",
        "#c084fc",
        "#f472b6",
        "#34d399",
        "#fb923c",
    ]
    fig = go.Figure()
    for i, tr in enumerate(tracks):
        color = palette[i % len(palette)]
        lats = np.asarray(tr["lat"], dtype=float)
        lons = np.asarray(tr["lon"], dtype=float)
        times = tr.get("times") or []
        hover = []
        for j, (la, lo) in enumerate(zip(lats, lons)):
            t = times[j] if j < len(times) else None
            t_s = t.strftime("%H:%M UTC") if t is not None and hasattr(t, "strftime") else ""
            hover.append(
                f"<b>{tr['name']}</b><br>{t_s}<br>lat {la:.2f}° · lon {lo:.2f}°"
            )
        fig.add_trace(
            go.Scattergeo(
                lat=lats,
                lon=lons,
                mode="lines",
                name=tr["name"],
                line=dict(width=2, color=color),
                hovertext=hover,
                hoverinfo="text",
            )
        )
        # Scrub marker ≈ index along the track
        n = max(1, len(lats) - 1)
        hours = float(tr.get("hours") or 6)
        frac = max(0.0, min(1.0, scrub_hours / hours if hours else 0.0))
        idx = int(round(frac * n))
        idx = max(0, min(len(lats) - 1, idx))
        fig.add_trace(
            go.Scattergeo(
                lat=[float(lats[idx])],
                lon=[float(lons[idx])],
                mode="markers+text",
                name=f"{tr['name']} (scrub)",
                text=[tr["name"][:16]],
                textposition="top center",
                marker=dict(size=12, color=color, symbol="star", line=dict(width=1, color="#fff")),
                hovertext=[hover[idx] if hover else tr["name"]],
                hoverinfo="text",
                showlegend=False,
            )
        )

    # Observer
    fig.add_trace(
        go.Scattergeo(
            lat=[float(loc.get("lat", 0))],
            lon=[float(loc.get("lon", 0))],
            mode="markers+text",
            name=loc.get("name") or "Observer",
            text=["★ home"],
            textposition="bottom center",
            marker=dict(size=11, color="#ffd700", symbol="circle", line=dict(width=1, color="#111")),
            hovertext=[
                f"<b>{loc.get('name', 'Observer')}</b><br>"
                f"{loc.get('lat'):.3f}°N, {loc.get('lon'):.3f}°E"
            ],
            hoverinfo="text",
        )
    )

    hours = tracks[0].get("hours", 6) if tracks else 6
    fig.update_layout(
        title=title
        or f"Ground track · +{scrub_hours:.2f}h / {hours:g}h · {loc.get('name', '')}",
        template="plotly_dark",
        height=520,
        margin=dict(l=10, r=10, t=50, b=10),
        geo=dict(
            projection_type="natural earth",
            showland=True,
            landcolor="#1a2238",
            showocean=True,
            oceancolor="#0b1020",
            showcountries=True,
            countrycolor="rgba(255,255,255,0.15)",
            showlakes=False,
            bgcolor="#0b1020",
            lataxis_showgrid=True,
            lonaxis_showgrid=True,
            lataxis_gridcolor="rgba(255,255,255,0.08)",
            lonaxis_gridcolor="rgba(255,255,255,0.08)",
        ),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        paper_bgcolor="#0b1020",
        font=dict(color="#e8eefc"),
    )
    return fig
