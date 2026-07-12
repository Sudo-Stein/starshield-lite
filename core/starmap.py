"""Altitude–azimuth sky geometry for the Kingsland observer (starmap)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
from skyfield.api import EarthSatellite, load

from config import LOCATION
from core.predictor import make_observer


def sky_track(
    sat: EarthSatellite,
    *,
    location: Optional[dict] = None,
    hours: float = 6,
    step_minutes: float = 1.0,
    min_elevation: float = 0.0,
) -> Dict[str, Any]:
    """Return alt/az time series for ``sat`` as seen from the observer.

    Arrays are filtered to ``alt >= min_elevation`` segments still included as
    NaN breaks so plots can skip below-horizon points cleanly.

    Returns dict with times (UTC datetime), alt_deg, az_deg, name, and
    above_horizon mask.
    """
    ts = load.timescale()
    observer = make_observer(location or LOCATION)
    t0 = ts.now()
    n = int((hours * 60) / step_minutes) + 1
    times = ts.tt_jd(np.linspace(t0.tt, t0.tt + hours / 24.0, n))

    topocentric = (sat - observer).at(times)
    alt, az, _dist = topocentric.altaz()
    alt_d = np.asarray(alt.degrees, dtype=float)
    az_d = np.asarray(az.degrees, dtype=float)
    above = alt_d >= min_elevation

    # NaN out below-horizon samples for plotting
    alt_plot = np.where(above, alt_d, np.nan)
    az_plot = np.where(above, az_d, np.nan)

    t_list = [times[i].utc_datetime() for i in range(n)]
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
    }


def sky_snapshot(
    satellites: Sequence[EarthSatellite],
    *,
    location: Optional[dict] = None,
    min_elevation: float = 0.0,
    when: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """Current (or ``when``) alt/az for many satellites above the horizon."""
    ts = load.timescale()
    observer = make_observer(location or LOCATION)
    if when is None:
        t = ts.now()
    else:
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        t = ts.from_datetime(when)

    rows = []
    for sat in satellites:
        try:
            alt, az, _ = (sat - observer).at(t).altaz()
            alt_d = float(alt.degrees)
            az_d = float(az.degrees)
        except Exception:
            continue
        if alt_d < min_elevation:
            continue
        rows.append(
            {
                "name": sat.name.strip(),
                "alt": alt_d,
                "az": az_d,
                "norad": getattr(getattr(sat, "model", None), "satnum", None),
            }
        )
    rows.sort(key=lambda r: -r["alt"])
    return rows


def build_starmap_figure(
    tracks: Sequence[Dict[str, Any]],
    *,
    title: str = "Sky view — Kingsland, GA",
    show_now_markers: bool = True,
):
    """Build a Plotly polar figure: North up, zenith at center.

    Radial coordinate is zenith distance (0° = zenith, 90° = horizon).
    Azimuth: 0° = North, clockwise (standard sky-map convention).
    """
    import plotly.graph_objects as go

    fig = go.Figure()
    # Horizon ring guides
    for r in (30, 60, 90):
        fig.add_trace(
            go.Scatterpolar(
                r=[r] * 73,
                theta=list(np.linspace(0, 360, 73)),
                mode="lines",
                line=dict(color="rgba(255,255,255,0.08)", width=1),
                hoverinfo="skip",
                showlegend=False,
            )
        )

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

    for i, tr in enumerate(tracks):
        color = palette[i % len(palette)]
        # r = zenith distance
        r = 90.0 - np.asarray(tr["alt_deg"], dtype=float)
        theta = np.asarray(tr["az_deg"], dtype=float)
        times = tr["times"]
        hover = [
            (
                f"<b>{tr['name']}</b><br>"
                f"{t.strftime('%Y-%m-%d %H:%M:%S UTC') if hasattr(t, 'strftime') else t}<br>"
                f"alt <b>{a:.1f}°</b> · az <b>{z:.1f}°</b>"
                + (f"<br>NORAD {tr['norad']}" if tr.get("norad") else "")
            )
            if np.isfinite(a)
            else f"<b>{tr['name']}</b> (below horizon)"
            for t, a, z in zip(times, tr["alt_raw"], tr["az_raw"])
        ]
        fig.add_trace(
            go.Scatterpolar(
                r=r,
                theta=theta,
                mode="lines+markers",
                name=tr["name"],
                line=dict(color=color, width=2.5),
                marker=dict(size=3, color=color, opacity=0.35),
                hovertext=hover,
                hoverinfo="text",
            )
        )
        if show_now_markers and tr.get("now_above"):
            fig.add_trace(
                go.Scatterpolar(
                    r=[90.0 - tr["now_alt"]],
                    theta=[tr["now_az"]],
                    mode="markers+text",
                    name=f"{tr['name']} (scrub)",
                    text=[tr["name"][:18]],
                    textposition="top center",
                    textfont=dict(size=11, color="#ffd700"),
                    marker=dict(
                        size=14,
                        color=color,
                        symbol="star",
                        line=dict(width=1, color="#fff"),
                    ),
                    hovertext=[
                        f"<b>{tr['name']}</b> @ scrub<br>"
                        f"alt {tr['now_alt']:.1f}° · az {tr['now_az']:.1f}°"
                    ],
                    hoverinfo="text",
                    showlegend=True,
                )
            )

    fig.update_layout(
        title=title,
        template="plotly_dark",
        height=640,
        margin=dict(l=40, r=40, t=60, b=40),
        polar=dict(
            bgcolor="#0b1020",
            radialaxis=dict(
                range=[0, 90],
                tickvals=[0, 30, 60, 90],
                ticktext=["Zenith", "60°", "30°", "Horizon"],
                showline=True,
                gridcolor="rgba(255,255,255,0.12)",
            ),
            angularaxis=dict(
                direction="clockwise",
                rotation=90,  # 0° at top = North
                tickmode="array",
                tickvals=[0, 45, 90, 135, 180, 225, 270, 315],
                ticktext=["N", "NE", "E", "SE", "S", "SW", "W", "NW"],
                gridcolor="rgba(255,255,255,0.12)",
            ),
        ),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        paper_bgcolor="#0b1020",
        font=dict(color="#e8eefc"),
    )
    return fig
