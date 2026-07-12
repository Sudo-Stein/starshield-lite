"""Conjunction detection, distance time series, and HTML reports."""

from __future__ import annotations

import html as html_lib
import webbrowser
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
from skyfield.api import EarthSatellite, load

from config import (
    CONJ_HIGH_RISK_KM,
    CONJ_REFINE_WINDOW_MIN,
    CONJ_REPORT_FILE,
    CONJ_STEPS_COARSE,
    CONJ_STEPS_DEFAULT,
    CONJ_STEPS_FINE,
    CONJ_THRESHOLD_KM,
    DATA_DIR,
)


def _risk_level(
    min_dist_km: float,
    threshold_km: float = CONJ_THRESHOLD_KM,
    high_risk_km: float = CONJ_HIGH_RISK_KM,
) -> str:
    if min_dist_km < high_risk_km:
        return "HIGH"
    if min_dist_km < threshold_km:
        return "MEDIUM"
    return "LOW"


def _norad(sat: EarthSatellite):
    return getattr(getattr(sat, "model", None), "satnum", None)


def _time_grid(hours: float, steps: int, t_start=None):
    """Return Skyfield Time array spanning ``hours`` with ``steps`` samples."""
    ts = load.timescale()
    t0 = t_start if t_start is not None else ts.now()
    jd = np.linspace(t0.tt, t0.tt + hours / 24.0, int(steps))
    return ts.tt_jd(jd), t0, ts


def _positions_and_distances(sat1, sat2, times):
    p1 = sat1.at(times).position.km  # (3, N)
    p2 = sat2.at(times).position.km
    deltas = p1 - p2
    distances = np.linalg.norm(deltas, axis=0)
    return p1, p2, deltas, distances


def _relative_velocity_kms(sat1, sat2, t_tca) -> float:
    """Relative speed (km/s) at TCA using Skyfield velocity vectors."""
    try:
        v1 = sat1.at(t_tca).velocity.km_per_s  # (3,)
        v2 = sat2.at(t_tca).velocity.km_per_s
        return float(np.linalg.norm(np.asarray(v1) - np.asarray(v2)))
    except Exception:
        return float("nan")


def check_conjunction(
    sat1: EarthSatellite,
    sat2: EarthSatellite,
    hours: float = 24,
    threshold_km: float = CONJ_THRESHOLD_KM,
    high_risk_km: float = CONJ_HIGH_RISK_KM,
    steps: int = CONJ_STEPS_DEFAULT,
    adaptive: bool = True,
    refine_window_min: float = CONJ_REFINE_WINDOW_MIN,
    fine_steps: int = CONJ_STEPS_FINE,
) -> Dict[str, Any]:
    """Minimum approach between two satellites over a time window.

    Coarse grid first; optionally refine around the coarse TCA with a denser
    local grid (adaptive stepping). Also reports relative velocity at TCA.

    Returns dict with tca, min_dist_km, rel_velocity_kms, risk, time series, …
    """
    coarse_steps = int(steps) if steps else CONJ_STEPS_COARSE
    if adaptive and coarse_steps > CONJ_STEPS_COARSE:
        coarse_steps = max(CONJ_STEPS_COARSE, coarse_steps // 2)

    times, t0, ts = _time_grid(hours, coarse_steps)
    _p1, _p2, _dlt, distances = _positions_and_distances(sat1, sat2, times)
    idx = int(np.argmin(distances))
    min_dist = float(distances[idx])
    tca_time = times[idx]

    # Adaptive fine search around coarse TCA (± refine_window_min minutes)
    refined = False
    if adaptive and hours > 0:
        half_days = (float(refine_window_min) / 60.0) / 24.0
        jd_lo = max(t0.tt, tca_time.tt - half_days)
        jd_hi = min(t0.tt + hours / 24.0, tca_time.tt + half_days)
        if jd_hi > jd_lo:
            fine = ts.tt_jd(np.linspace(jd_lo, jd_hi, int(fine_steps)))
            _a, _b, _c, d_fine = _positions_and_distances(sat1, sat2, fine)
            j = int(np.argmin(d_fine))
            min_dist = float(d_fine[j])
            tca_time = fine[j]
            refined = True
            # merge series for plotting: coarse downsampled + fine near TCA
            times = fine
            distances = d_fine

    tca_dt = tca_time.utc_datetime()
    if tca_dt.tzinfo is None:
        tca_dt = tca_dt.replace(tzinfo=timezone.utc)

    rel_v = _relative_velocity_kms(sat1, sat2, tca_time)

    n = len(distances)
    stride = max(1, n // 400)
    t_series = [times[i].utc_datetime() for i in range(0, n, stride)]
    d_series = [float(distances[i]) for i in range(0, n, stride)]

    risk = _risk_level(min_dist, threshold_km, high_risk_km)
    n1, n2 = _norad(sat1), _norad(sat2)

    return {
        "sat1": sat1.name.strip(),
        "sat2": sat2.name.strip(),
        "norad1": n1,
        "norad2": n2,
        "tca": tca_dt,
        "min_dist_km": round(min_dist, 3),
        "rel_velocity_kms": round(rel_v, 3) if rel_v == rel_v else None,
        "risk": risk,
        "threshold_km": threshold_km,
        "high_risk_km": high_risk_km,
        "hours": hours,
        "steps": coarse_steps,
        "adaptive": adaptive,
        "refined": refined,
        "t0": t0.utc_datetime(),
        "times": t_series,
        "distances": d_series,
        "below_threshold": min_dist < threshold_km,
    }


def scan_conjunctions(
    primary: Sequence[EarthSatellite],
    secondary: Sequence[EarthSatellite],
    hours: float = 12,
    threshold_km: float = CONJ_THRESHOLD_KM,
    high_risk_km: float = CONJ_HIGH_RISK_KM,
    steps: int = CONJ_STEPS_DEFAULT,
    max_pairs: int = 200,
    progress_every: int = 25,
) -> List[Dict[str, Any]]:
    """Brute-force min-distance scan for group-vs-group pairs.

    Caps work at ``max_pairs`` (primary × secondary ordered pairs, skipping
    identical NORAD IDs). Returns results sorted by min distance (closest first).
    """
    pairs: List[Tuple[EarthSatellite, EarthSatellite]] = []
    for a in primary:
        for b in secondary:
            na = getattr(getattr(a, "model", None), "satnum", id(a))
            nb = getattr(getattr(b, "model", None), "satnum", id(b))
            if na == nb:
                continue
            pairs.append((a, b))
            if len(pairs) >= max_pairs:
                break
        if len(pairs) >= max_pairs:
            break

    results: List[Dict[str, Any]] = []
    for i, (a, b) in enumerate(pairs, 1):
        if progress_every and i % progress_every == 0:
            print(f"  … scanned {i}/{len(pairs)} pairs")
        try:
            r = check_conjunction(
                a,
                b,
                hours=hours,
                threshold_km=threshold_km,
                high_risk_km=high_risk_km,
                steps=steps,
            )
            results.append(r)
        except Exception as exc:
            print(f"  skip {a.name} / {b.name}: {exc}")

    results.sort(key=lambda r: r["min_dist_km"])
    return results


def basic_conjunction_check(
    sats,
    target_sat,
    threshold_km: float = CONJ_THRESHOLD_KM,
    hours: float = 24,
):
    """Compatibility helper: scan ``sats`` against ``target_sat``."""
    hits = []
    for s in sats:
        if s is target_sat:
            continue
        r = check_conjunction(
            target_sat, s, hours=hours, threshold_km=threshold_km
        )
        if r["below_threshold"]:
            hits.append(r)
    hits.sort(key=lambda r: r["min_dist_km"])
    return hits


def _risk_badge(risk: str) -> str:
    colors = {
        "HIGH": "#ff4d4f",
        "MEDIUM": "#faad14",
        "LOW": "#52c41a",
    }
    c = colors.get(risk, "#999")
    return (
        f'<span style="background:{c};color:#111;padding:2px 10px;'
        f'border-radius:999px;font-weight:700;font-size:12px">{risk}</span>'
    )


def generate_html_report(
    results: Any,
    filename: str = CONJ_REPORT_FILE,
    open_browser: bool = False,
    title: str = "StarShield Lite — Conjunction Report",
) -> Path:
    """Write an HTML dashboard for one or many conjunction results.

    ``results`` may be a single check dict or a list of dicts.
    Embeds an interactive Plotly distance chart when plotly is available.
    """
    if isinstance(results, dict):
        items = [results]
    else:
        items = list(results)

    path = DATA_DIR / filename
    path.parent.mkdir(parents=True, exist_ok=True)

    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    # Summary table rows
    rows_html = []
    for r in items:
        tca = r.get("tca")
        tca_s = (
            tca.strftime("%Y-%m-%d %H:%M:%S UTC")
            if hasattr(tca, "strftime")
            else str(tca)
        )
        rows_html.append(
            "<tr>"
            f"<td>{html_lib.escape(str(r.get('sat1', '')))}</td>"
            f"<td>{html_lib.escape(str(r.get('sat2', '')))}</td>"
            f"<td>{tca_s}</td>"
            f"<td><b>{r.get('min_dist_km')}</b></td>"
            f"<td>{_risk_badge(str(r.get('risk', '')))}</td>"
            f"<td>{r.get('hours', '')}h</td>"
            "</tr>"
        )

    # Primary chart: first (closest) pair distance series
    chart_div = "<p class='muted'>No distance series available.</p>"
    primary = items[0] if items else None
    if primary and primary.get("times") and primary.get("distances"):
        try:
            import plotly.graph_objects as go

            t_labels = [
                t.strftime("%m-%d %H:%M") if hasattr(t, "strftime") else str(t)
                for t in primary["times"]
            ]
            fig = go.Figure()
            fig.add_trace(
                go.Scatter(
                    x=t_labels,
                    y=primary["distances"],
                    mode="lines",
                    name="Distance (km)",
                    line=dict(color="#00d4ff", width=2),
                )
            )
            thr = primary.get("threshold_km", CONJ_THRESHOLD_KM)
            hi = primary.get("high_risk_km", CONJ_HIGH_RISK_KM)
            fig.add_hline(
                y=thr,
                line_dash="dash",
                line_color="#faad14",
                annotation_text=f"warn {thr} km",
            )
            fig.add_hline(
                y=hi,
                line_dash="dot",
                line_color="#ff4d4f",
                annotation_text=f"high {hi} km",
            )
            fig.update_layout(
                title=f"Distance: {primary.get('sat1')} ↔ {primary.get('sat2')}",
                xaxis_title="Time (UTC)",
                yaxis_title="Distance (km)",
                template="plotly_dark",
                height=420,
                margin=dict(l=50, r=20, t=50, b=50),
            )
            chart_div = fig.to_html(
                full_html=False,
                include_plotlyjs="cdn",
                config={"displayModeBar": True},
            )
        except Exception as exc:
            chart_div = (
                f"<p class='muted'>Plotly chart unavailable: "
                f"{html_lib.escape(str(exc))}</p>"
            )

    headline = "No conjunctions computed."
    if primary:
        headline = (
            f"Closest: <b>{html_lib.escape(primary.get('sat1', ''))}</b> ↔ "
            f"<b>{html_lib.escape(primary.get('sat2', ''))}</b> · "
            f"<b>{primary.get('min_dist_km')} km</b> · "
            f"{_risk_badge(str(primary.get('risk', '')))}"
        )

    n_high = sum(1 for r in items if r.get("risk") == "HIGH")
    n_med = sum(1 for r in items if r.get("risk") == "MEDIUM")
    n_low = sum(1 for r in items if r.get("risk") == "LOW")

    doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>{html_lib.escape(title)}</title>
  <style>
    :root {{
      --bg: #0b1020;
      --card: #141a2f;
      --text: #e8eefc;
      --muted: #8b97b8;
      --accent: #00d4ff;
      --border: #243056;
    }}
    body {{
      margin: 0; font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
      background: radial-gradient(1200px 600px at 10% -10%, #1a274d 0%, var(--bg) 55%);
      color: var(--text); padding: 28px;
    }}
    h1 {{ margin: 0 0 6px; font-size: 1.6rem; letter-spacing: 0.02em; }}
    .sub {{ color: var(--muted); margin-bottom: 20px; }}
    .card {{
      background: var(--card); border: 1px solid var(--border);
      border-radius: 14px; padding: 18px 20px; margin-bottom: 18px;
      box-shadow: 0 10px 30px rgba(0,0,0,0.25);
    }}
    .stats {{ display: flex; gap: 12px; flex-wrap: wrap; }}
    .stat {{
      background: #0f1528; border: 1px solid var(--border);
      border-radius: 10px; padding: 10px 14px; min-width: 110px;
    }}
    .stat b {{ display: block; font-size: 1.25rem; color: var(--accent); }}
    .muted {{ color: var(--muted); }}
    table {{ width: 100%; border-collapse: collapse; font-size: 0.92rem; }}
    th, td {{ text-align: left; padding: 10px 8px; border-bottom: 1px solid var(--border); }}
    th {{ color: var(--muted); font-weight: 600; font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.04em; }}
    tr:hover td {{ background: rgba(0, 212, 255, 0.04); }}
    footer {{ color: var(--muted); font-size: 0.8rem; margin-top: 8px; }}
  </style>
</head>
<body>
  <h1>🛡 {html_lib.escape(title)}</h1>
  <p class="sub">Generated {generated} · {len(items)} pair(s) analyzed</p>

  <div class="card">
    <p style="margin-top:0">{headline}</p>
    <div class="stats">
      <div class="stat"><span class="muted">Pairs</span><b>{len(items)}</b></div>
      <div class="stat"><span class="muted">HIGH</span><b>{n_high}</b></div>
      <div class="stat"><span class="muted">MEDIUM</span><b>{n_med}</b></div>
      <div class="stat"><span class="muted">LOW</span><b>{n_low}</b></div>
    </div>
  </div>

  <div class="card">
    <h2 style="margin-top:0;font-size:1.1rem">Distance over time</h2>
    {chart_div}
  </div>

  <div class="card">
    <h2 style="margin-top:0;font-size:1.1rem">Close approaches</h2>
    <table>
      <thead>
        <tr>
          <th>Object 1</th><th>Object 2</th><th>TCA (UTC)</th>
          <th>Min dist (km)</th><th>Risk</th><th>Window</th>
        </tr>
      </thead>
      <tbody>
        {''.join(rows_html) if rows_html else '<tr><td colspan="6">No data</td></tr>'}
      </tbody>
    </table>
  </div>

  <footer>
    StarShield Lite · thresholds: HIGH &lt; {CONJ_HIGH_RISK_KM} km,
    MEDIUM &lt; {CONJ_THRESHOLD_KM} km · append-only log in data/starshield.log
  </footer>
</body>
</html>
"""
    path.write_text(doc, encoding="utf-8")

    if open_browser:
        webbrowser.open(path.resolve().as_uri())

    return path


def open_latest_report(filename: str = CONJ_REPORT_FILE) -> Optional[Path]:
    """Open an existing HTML report in the default browser."""
    path = DATA_DIR / filename
    if not path.exists():
        return None
    webbrowser.open(path.resolve().as_uri())
    return path
