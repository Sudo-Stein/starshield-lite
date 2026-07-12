"""Linked-view visualization helpers for Streamlit (starmap + ground track).

Keeps pass→starmap focus packages, scrubber math, and polished Plotly figures
in one place so the dashboard stays thin.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

# Shared visual language (matches Streamlit dark theme)
PALETTE = [
    "#00d4ff",
    "#ff6b6b",
    "#7CFC00",
    "#ffd700",
    "#c084fc",
    "#f472b6",
    "#34d399",
    "#fb923c",
]
THEME = {
    "paper": "#0b1020",
    "plot": "#0b1020",
    "font": "#e8eefc",
    "grid": "rgba(255,255,255,0.12)",
    "muted": "rgba(232,238,252,0.35)",
    "accent": "#ffd700",
}


# ---------------------------------------------------------------------------
# Pass focus packages (Passes / Status → Starmap)
# ---------------------------------------------------------------------------


def _as_utc(t: Any) -> Optional[datetime]:
    if t is None:
        return None
    if hasattr(t, "strftime"):
        if getattr(t, "tzinfo", None) is None:
            return t.replace(tzinfo=timezone.utc)
        return t.astimezone(timezone.utc)
    return None


def _event_time(pass_data: dict, key: str) -> Optional[datetime]:
    ev = pass_data.get(key)
    if isinstance(ev, dict):
        return _as_utc(ev.get("time"))
    return _as_utc(ev)


def pass_to_starmap_focus(
    pass_data: dict,
    *,
    object_name: str,
    norad: Optional[int] = None,
    now: Optional[datetime] = None,
    pad_minutes: float = 25.0,
    min_window_hours: float = 2.0,
    max_window_hours: float = 24.0,
) -> Dict[str, Any]:
    """Build a session-friendly focus package for jumping to the Starmap.

    Scrub/window times are **hours from now** (tracks still start at ``now``).
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    rise_t = _event_time(pass_data, "rise")
    culm_t = _event_time(pass_data, "culmination")
    set_t = _event_time(pass_data, "set")
    peak_t = culm_t or rise_t or set_t or now

    def _hours_from_now(t: Optional[datetime]) -> Optional[float]:
        if t is None:
            return None
        return (t - now).total_seconds() / 3600.0

    scrub_h = max(0.0, _hours_from_now(peak_t) or 0.0)
    # Window must cover rise→set with padding, clamped
    start_h = scrub_h
    end_h = scrub_h
    if rise_t:
        start_h = min(start_h, max(0.0, _hours_from_now(rise_t) - pad_minutes / 60.0))
    else:
        start_h = max(0.0, scrub_h - 0.5)
    if set_t:
        end_h = max(end_h, (_hours_from_now(set_t) or scrub_h) + pad_minutes / 60.0)
    else:
        end_h = scrub_h + 0.5

    # Track always starts at now → window_hours is end of coverage
    window_hours = max(min_window_hours, end_h + 0.1)
    window_hours = min(max_window_hours, max(window_hours, scrub_h + 0.25))

    q = pass_data.get("quality") or {}
    grade = pass_data.get("quality_grade") or q.get("grade")
    score = pass_data.get("quality_score")
    if score is None:
        score = q.get("score")

    return {
        "object": object_name,
        "norad": norad,
        "quality_grade": grade,
        "quality_score": score,
        "max_el": pass_data.get("max_elevation"),
        "rise": rise_t.isoformat() if rise_t else None,
        "culm": peak_t.isoformat() if peak_t else None,
        "set": set_t.isoformat() if set_t else None,
        "rise_hours": _hours_from_now(rise_t),
        "culm_hours": _hours_from_now(peak_t),
        "set_hours": _hours_from_now(set_t),
        "scrub_hours": scrub_h,
        "scrub_minutes": scrub_h * 60.0,
        "window_hours": float(window_hours),
        "focus_mode": True,
        "pad_minutes": pad_minutes,
    }


def focus_quality_label(focus: Optional[dict]) -> str:
    if not focus:
        return ""
    g = focus.get("quality_grade")
    s = focus.get("quality_score")
    if g is not None and s is not None:
        return f"{g} {s}"
    if g is not None:
        return str(g)
    if s is not None:
        return str(s)
    return ""


# ---------------------------------------------------------------------------
# Scrubber math
# ---------------------------------------------------------------------------


def hours_to_minutes(h: float) -> float:
    return float(h) * 60.0


def minutes_to_hours(m: float) -> float:
    return float(m) / 60.0


def format_scrub_clock(
    scrub_hours: float,
    *,
    now: Optional[datetime] = None,
) -> Dict[str, str]:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    t = now + timedelta(hours=float(scrub_hours))
    total_min = int(round(float(scrub_hours) * 60))
    hh, mm = divmod(max(0, total_min), 60)
    return {
        "utc": t.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "local": t.astimezone().strftime("%Y-%m-%d %H:%M %Z"),
        "offset": f"+{hh:d}h {mm:02d}m" if hh else f"+{mm:d}m",
        "iso": t.isoformat(),
    }


def event_near_scrub(
    tracks: Sequence[Dict[str, Any]],
    scrub_hours: float,
    *,
    window_minutes: float = 8.0,
) -> List[dict]:
    """Events within ±window of scrub time (relative to each track start)."""
    out = []
    for tr in tracks:
        start = tr.get("start") or (tr.get("times") or [None])[0]
        start = _as_utc(start)
        if start is None:
            continue
        scrub_abs = start + timedelta(hours=float(scrub_hours))
        for ev in tr.get("events") or []:
            et = _as_utc(ev.get("time"))
            if et is None:
                continue
            dt_min = abs((et - scrub_abs).total_seconds()) / 60.0
            if dt_min <= window_minutes:
                out.append(
                    {
                        "object": tr.get("name"),
                        "type": ev.get("type"),
                        "time": et,
                        "alt": ev.get("alt"),
                        "az": ev.get("az"),
                        "dt_min": dt_min,
                    }
                )
    out.sort(key=lambda e: e["dt_min"])
    return out


def advance_scrub(
    scrub_minutes: float,
    *,
    step_minutes: float = 1.0,
    max_minutes: float = 360.0,
) -> Tuple[float, bool]:
    """Advance scrub; returns (new_minutes, hit_end)."""
    nxt = float(scrub_minutes) + float(step_minutes)
    if nxt >= max_minutes:
        return float(max_minutes), True
    return nxt, False


# ---------------------------------------------------------------------------
# Figure builders (linked sky + ground)
# ---------------------------------------------------------------------------


def _color_for(i: int, name: str, focus_name: Optional[str]) -> str:
    if focus_name and name.strip().upper() == focus_name.strip().upper():
        return PALETTE[0]
    return PALETTE[i % len(PALETTE)]


def _is_focus(name: str, focus_name: Optional[str]) -> bool:
    if not focus_name:
        return False
    a = name.strip().upper()
    b = focus_name.strip().upper()
    if a == b:
        return True
    # Aliases / catalog suffixes (e.g. ISS vs ISS (ZARYA))
    if len(b) >= 2 and (b in a or a in b):
        return True
    return a.startswith(b + " ") or b.startswith(a + " ")


def _pass_mask(
    times: Sequence[datetime],
    rise_h: Optional[float],
    set_h: Optional[float],
    track_start: Optional[datetime],
    scrub_base_hours: float = 0.0,
) -> np.ndarray:
    """Boolean mask for samples inside the focused pass (rise→set)."""
    n = len(times)
    if rise_h is None and set_h is None:
        return np.ones(n, dtype=bool)
    mask = np.zeros(n, dtype=bool)
    start = _as_utc(track_start) or _as_utc(times[0] if times else None)
    if start is None:
        return np.ones(n, dtype=bool)
    lo = rise_h if rise_h is not None else (set_h or 0) - 0.25
    hi = set_h if set_h is not None else (rise_h or 0) + 0.25
    for i, t in enumerate(times):
        tt = _as_utc(t)
        if tt is None:
            continue
        h = (tt - start).total_seconds() / 3600.0
        if lo <= h <= hi:
            mask[i] = True
    return mask


def build_linked_sky_figure(
    tracks: Sequence[Dict[str, Any]],
    *,
    scrub_hours: float = 0.0,
    location_label: str = "",
    focus_name: Optional[str] = None,
    focus: Optional[dict] = None,
    quality_by_name: Optional[Dict[str, str]] = None,
    show_events: bool = True,
    dim_others: bool = True,
    title: Optional[str] = None,
    height: int = 560,
):
    """Polar starmap with focus highlighting, rich hover, scrub star."""
    import plotly.graph_objects as go
    from services.sky import position_at_offset

    focus_name = focus_name or (focus or {}).get("object")
    quality_by_name = quality_by_name or {}
    if focus and focus_quality_label(focus):
        quality_by_name.setdefault(
            str(focus.get("object") or ""), focus_quality_label(focus)
        )

    fig = go.Figure()
    # Horizon guide rings
    for r in (30, 60, 90):
        fig.add_trace(
            go.Scatterpolar(
                r=[r] * 73,
                theta=list(np.linspace(0, 360, 73)),
                mode="lines",
                line=dict(color="rgba(255,255,255,0.07)", width=1),
                hoverinfo="skip",
                showlegend=False,
            )
        )

    hours = tracks[0].get("hours", 6) if tracks else 6
    clock = format_scrub_clock(scrub_hours)
    qlab = focus_quality_label(focus)
    ttl = title or (
        f"Sky · {clock['offset']} · {clock['utc']}"
        + (f" · {location_label}" if location_label else "")
        + (f" · focus {focus_name}" if focus_name else "")
        + (f" · Q {qlab}" if qlab else "")
    )

    # Draw non-focus first, focus last (on top)
    order = list(range(len(tracks)))
    if focus_name:
        order.sort(key=lambda i: _is_focus(tracks[i]["name"], focus_name))

    for i in order:
        tr = tracks[i]
        name = tr["name"]
        focused = _is_focus(name, focus_name)
        color = _color_for(i, name, focus_name if dim_others else None)
        if dim_others and focus_name and not focused:
            line_w, opacity, marker_op = 1.2, 0.35, 0.2
        else:
            line_w, opacity, marker_op = (3.2 if focused else 2.4), 1.0, 0.4

        r = 90.0 - np.asarray(tr["alt_deg"], dtype=float)
        theta = np.asarray(tr["az_deg"], dtype=float)
        times = tr["times"]
        q_str = quality_by_name.get(name, "")
        hover = []
        for t, a, z in zip(times, tr["alt_raw"], tr["az_raw"]):
            if not np.isfinite(a):
                hover.append(f"<b>{name}</b><br>(below horizon)")
                continue
            t_s = (
                t.strftime("%Y-%m-%d %H:%M:%S UTC")
                if hasattr(t, "strftime")
                else str(t)
            )
            extra = f"<br>Quality <b>{q_str}</b>" if q_str else ""
            hover.append(
                f"<b>{name}</b>{extra}<br>{t_s}<br>"
                f"alt <b>{a:.1f}°</b> · az <b>{z:.1f}°</b>"
            )

        fig.add_trace(
            go.Scatterpolar(
                r=r,
                theta=theta,
                mode="lines+markers",
                name=name + (" ★" if focused else ""),
                line=dict(color=color, width=line_w),
                marker=dict(size=3 if not focused else 4, color=color, opacity=marker_op),
                opacity=opacity,
                hovertext=hover,
                hoverinfo="text",
                legendgroup=name,
            )
        )

        # Pass segment highlight (rise→set) for focused object
        if focused and focus:
            mask = _pass_mask(
                times,
                focus.get("rise_hours"),
                focus.get("set_hours"),
                tr.get("start") or (times[0] if times else None),
            )
            if mask.any():
                r_seg = np.where(mask, r, np.nan)
                th_seg = np.where(mask, theta, np.nan)
                fig.add_trace(
                    go.Scatterpolar(
                        r=r_seg,
                        theta=th_seg,
                        mode="lines",
                        name=f"{name} (pass)",
                        line=dict(color="#ffffff", width=5),
                        opacity=0.35,
                        hoverinfo="skip",
                        showlegend=False,
                        legendgroup=name,
                    )
                )
                fig.add_trace(
                    go.Scatterpolar(
                        r=r_seg,
                        theta=th_seg,
                        mode="lines",
                        name=f"{name} pass path",
                        line=dict(color=color, width=4.5),
                        hoverinfo="skip",
                        showlegend=False,
                        legendgroup=name,
                    )
                )

        # Scrub marker
        pos = position_at_offset(tr, scrub_hours)
        if pos.get("above") and pos.get("alt") is not None:
            q_h = f"<br>Quality <b>{q_str}</b>" if q_str else ""
            fig.add_trace(
                go.Scatterpolar(
                    r=[90.0 - float(pos["alt"])],
                    theta=[float(pos["az"])],
                    mode="markers+text",
                    name=f"{name} @ scrub",
                    text=[name[:14] if focused or not focus_name else ""],
                    textposition="top center",
                    textfont=dict(size=11, color=THEME["accent"]),
                    marker=dict(
                        size=16 if focused or not focus_name else 11,
                        color=color,
                        symbol="star",
                        line=dict(width=1.5, color="#fff"),
                    ),
                    hovertext=[
                        f"<b>{name}</b> @ scrub {clock['offset']}<br>"
                        f"{clock['utc']}<br>"
                        f"alt <b>{pos['alt']:.1f}°</b> · az <b>{pos['az']:.1f}°</b>"
                        f"{q_h}"
                    ],
                    hoverinfo="text",
                    showlegend=False,
                    legendgroup=name,
                )
            )

    if show_events:
        symbols = {
            "rise": "triangle-up",
            "culmination": "diamond",
            "set": "triangle-down",
        }
        colors = {"rise": "#7CFC00", "culmination": "#ffd700", "set": "#ff6b6b"}
        seen = set()
        for tr in tracks:
            if focus_name and dim_others and not _is_focus(tr["name"], focus_name):
                continue
            for ev in tr.get("events") or []:
                if ev.get("alt", -1) < 0:
                    continue
                et = ev["type"]
                show_leg = et not in seen
                seen.add(et)
                t = ev["time"]
                t_s = t.strftime("%H:%M UTC") if hasattr(t, "strftime") else str(t)
                fig.add_trace(
                    go.Scatterpolar(
                        r=[90.0 - ev["alt"]],
                        theta=[ev["az"]],
                        mode="markers",
                        name=et.capitalize() if show_leg else et,
                        legendgroup=f"ev-{et}",
                        marker=dict(
                            size=12 if et == "culmination" else 10,
                            color=colors.get(et, "#fff"),
                            symbol=symbols.get(et, "circle"),
                            line=dict(width=1, color="#111"),
                        ),
                        hovertext=(
                            f"<b>{tr['name']}</b> · {et}<br>{t_s}<br>"
                            f"alt {ev['alt']:.1f}° · az {ev['az']:.1f}°"
                        ),
                        hoverinfo="text",
                        showlegend=show_leg,
                    )
                )

    fig.update_layout(
        title=dict(text=ttl, font=dict(size=14)),
        template="plotly_dark",
        height=height,
        margin=dict(l=30, r=30, t=70, b=30),
        polar=dict(
            bgcolor=THEME["plot"],
            radialaxis=dict(
                range=[0, 90],
                tickvals=[0, 30, 60, 90],
                ticktext=["Zenith", "60°", "30°", "Horizon"],
                showline=True,
                gridcolor=THEME["grid"],
                tickfont=dict(size=10),
            ),
            angularaxis=dict(
                direction="clockwise",
                rotation=90,
                tickmode="array",
                tickvals=[0, 45, 90, 135, 180, 225, 270, 315],
                ticktext=["N", "NE", "E", "SE", "S", "SW", "W", "NW"],
                gridcolor=THEME["grid"],
            ),
        ),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            x=0,
            bgcolor="rgba(15,20,40,0.75)",
            font=dict(size=11),
        ),
        paper_bgcolor=THEME["paper"],
        font=dict(color=THEME["font"]),
        uirevision="starshield-sky",  # keep zoom across scrub updates
    )
    return fig


def attach_sky_meta_to_ground(
    gtracks: Sequence[Dict[str, Any]],
    sky_tracks: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Copy alt samples onto ground tracks (matched by name) for richer hover."""
    by_name = {t["name"]: t for t in sky_tracks}
    out = []
    for gt in gtracks:
        g2 = dict(gt)
        sky = by_name.get(gt["name"])
        if sky is not None:
            # resample-ish: use nearest time index
            g2["alt_raw"] = sky.get("alt_raw")
            g2["az_raw"] = sky.get("az_raw")
            g2["sky_times"] = sky.get("times")
        out.append(g2)
    return out


def build_linked_ground_figure(
    tracks: Sequence[Dict[str, Any]],
    *,
    location: Optional[dict] = None,
    scrub_hours: float = 0.0,
    focus_name: Optional[str] = None,
    focus: Optional[dict] = None,
    quality_by_name: Optional[Dict[str, str]] = None,
    dim_others: bool = True,
    title: Optional[str] = None,
    height: int = 520,
):
    """World map ground tracks linked to the same scrub / focus as the sky view."""
    import plotly.graph_objects as go
    from config import LOCATION

    loc = location or LOCATION
    focus_name = focus_name or (focus or {}).get("object")
    quality_by_name = quality_by_name or {}
    clock = format_scrub_clock(scrub_hours)
    hours = tracks[0].get("hours", 6) if tracks else 6
    qlab = focus_quality_label(focus)
    ttl = title or (
        f"Ground track · {clock['offset']} · {clock['utc']}"
        + (f" · {loc.get('name', '')}" if loc.get("name") else "")
        + (f" · {focus_name}" if focus_name else "")
        + (f" · Q {qlab}" if qlab else "")
    )

    fig = go.Figure()
    order = list(range(len(tracks)))
    if focus_name:
        order.sort(key=lambda i: _is_focus(tracks[i]["name"], focus_name))

    for i in order:
        tr = tracks[i]
        name = tr["name"]
        focused = _is_focus(name, focus_name)
        color = _color_for(i, name, focus_name if dim_others else None)
        if dim_others and focus_name and not focused:
            width, opacity = 1.2, 0.35
        else:
            width, opacity = (3.0 if focused else 2.0), 1.0

        lats = np.asarray(tr["lat"], dtype=float)
        lons = np.asarray(tr["lon"], dtype=float)
        times = tr.get("times") or []
        alts = tr.get("alt_raw")
        q_str = quality_by_name.get(name, "")
        hover = []
        for j, (la, lo) in enumerate(zip(lats, lons)):
            t = times[j] if j < len(times) else None
            t_s = (
                t.strftime("%Y-%m-%d %H:%M UTC")
                if t is not None and hasattr(t, "strftime")
                else ""
            )
            alt_s = ""
            if alts is not None and j < len(alts) and np.isfinite(alts[j]):
                alt_s = f"<br>alt <b>{float(alts[j]):.1f}°</b>"
            q_h = f"<br>Quality <b>{q_str}</b>" if q_str else ""
            hover.append(
                f"<b>{name}</b>{q_h}<br>{t_s}<br>"
                f"lat {la:.2f}° · lon {lo:.2f}°{alt_s}"
            )

        fig.add_trace(
            go.Scattergeo(
                lat=lats,
                lon=lons,
                mode="lines",
                name=name + (" ★" if focused else ""),
                line=dict(width=width, color=color),
                opacity=opacity,
                hovertext=hover,
                hoverinfo="text",
                legendgroup=name,
            )
        )

        # Pass segment on ground
        if focused and focus and times:
            start = times[0]
            mask = _pass_mask(
                times,
                focus.get("rise_hours"),
                focus.get("set_hours"),
                start,
            )
            if mask.any():
                fig.add_trace(
                    go.Scattergeo(
                        lat=np.where(mask, lats, np.nan),
                        lon=np.where(mask, lons, np.nan),
                        mode="lines",
                        name=f"{name} pass",
                        line=dict(width=5, color=color),
                        hoverinfo="skip",
                        showlegend=False,
                        legendgroup=name,
                    )
                )

        # Scrub marker
        n = max(1, len(lats) - 1)
        hrs = float(tr.get("hours") or hours)
        frac = max(0.0, min(1.0, scrub_hours / hrs if hrs else 0.0))
        idx = int(round(frac * n))
        idx = max(0, min(len(lats) - 1, idx))
        alt_s = ""
        if alts is not None and idx < len(alts) and np.isfinite(alts[idx]):
            alt_s = f"<br>alt <b>{float(alts[idx]):.1f}°</b>"
        fig.add_trace(
            go.Scattergeo(
                lat=[float(lats[idx])],
                lon=[float(lons[idx])],
                mode="markers+text",
                name=f"{name} scrub",
                text=[name[:14] if focused or not focus_name else ""],
                textposition="top center",
                marker=dict(
                    size=14 if focused or not focus_name else 10,
                    color=color,
                    symbol="star",
                    line=dict(width=1, color="#fff"),
                ),
                hovertext=[
                    f"<b>{name}</b> @ scrub {clock['offset']}<br>"
                    f"{clock['utc']}<br>"
                    f"lat {lats[idx]:.2f}° · lon {lons[idx]:.2f}°{alt_s}"
                ],
                hoverinfo="text",
                showlegend=False,
                legendgroup=name,
            )
        )

    # Observer home
    fig.add_trace(
        go.Scattergeo(
            lat=[float(loc.get("lat", 0))],
            lon=[float(loc.get("lon", 0))],
            mode="markers+text",
            name=loc.get("name") or "Observer",
            text=["★ home"],
            textposition="bottom center",
            marker=dict(
                size=12,
                color=THEME["accent"],
                symbol="circle",
                line=dict(width=1, color="#111"),
            ),
            hovertext=[
                f"<b>{loc.get('name', 'Observer')}</b><br>"
                f"{loc.get('lat'):.3f}°, {loc.get('lon'):.3f}°"
            ],
            hoverinfo="text",
        )
    )

    fig.update_layout(
        title=dict(text=ttl, font=dict(size=14)),
        template="plotly_dark",
        height=height,
        margin=dict(l=10, r=10, t=60, b=10),
        geo=dict(
            projection_type="natural earth",
            showland=True,
            landcolor="#1a2238",
            showocean=True,
            oceancolor="#0b1020",
            showcountries=True,
            countrycolor="rgba(255,255,255,0.15)",
            showlakes=False,
            bgcolor=THEME["plot"],
            lataxis_showgrid=True,
            lonaxis_showgrid=True,
            lataxis_gridcolor="rgba(255,255,255,0.08)",
            lonaxis_gridcolor="rgba(255,255,255,0.08)",
        ),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        paper_bgcolor=THEME["paper"],
        font=dict(color=THEME["font"]),
        uirevision="starshield-ground",
    )
    return fig


def apply_focus_to_session_state(state: dict, focus: dict) -> None:
    """Write focus package into a Streamlit-like session_state mapping."""
    state["sky_focus_pass"] = focus
    state["sky_objects"] = [focus.get("object") or "ISS"]
    state["sky_scrub_seed"] = float(focus.get("scrub_hours") or 0.0)
    state["sky_scrub_minutes"] = float(
        focus.get("scrub_minutes") or hours_to_minutes(focus.get("scrub_hours") or 0)
    )
    state["sky_win_seed"] = int(max(1, min(24, round(float(focus.get("window_hours") or 6)))))
    state["sky_focus_mode"] = bool(focus.get("focus_mode", True))
    # Force widget refresh keys
    state["sky_jump_nonce"] = int(state.get("sky_jump_nonce") or 0) + 1
