"""StarShield Lite — interactive Streamlit dashboard.

Launch:
  streamlit run dashboard.py
  python main.py dash
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Optional

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from config import (
    API_BASE_URL,
    CONJ_HIGH_RISK_KM,
    CONJ_THRESHOLD_KM,
    DATA_DIR,
    DB_LOG_ENABLED,
    DB_PATH,
    DEFAULT_OBSERVER,
    STARGAZER_SUN_ALT_MAX,
    STREAMLIT_USE_API,
    TLE_URLS,
    WATCHLIST_DEFAULT_ID,
    effective_index_groups,
)
from core.predictor import format_pass_row, next_pass_summary, predict_passes
from core.simulator import check_conjunction, generate_html_report, scan_conjunctions
from core.starmap import sky_snapshot
from core.tle_fetcher import fetch_tles
from services.object_index import catalog_fingerprint, get_index, invalidate_index
from services.observers import (
    format_observer,
    list_observer_names,
    resolve_observer,
)
from services.pass_quality import (
    format_quality_breakdown,
    score_passes,
)
from services.sky import (
    ground_track_latlon,
    position_at_offset,
    tracks_for_objects,
)
from services.visualization import (
    advance_scrub,
    apply_focus_to_session_state,
    attach_sky_meta_to_ground,
    build_linked_ground_figure,
    build_linked_sky_figure,
    event_near_scrub,
    focus_quality_label,
    format_scrub_clock,
    hours_to_minutes,
    minutes_to_hours,
    pass_to_starmap_focus,
)
from services.visualization import _is_focus as _viz_is_focus
from services.watchlist import (
    get_watchlist,
    list_watchlists,
    results_to_rows,
    scan_watchlist,
)
from services.database import (
    ensure_db,
    log_passes_batch,
    log_watchlist_scan,
    query_conjunctions,
    query_recent_passes,
    query_watchlist_runs,
    summary_stats,
)
from utils.immutable_log import ImmutableLog

log = ImmutableLog()

st.set_page_config(
    page_title="StarShield Lite",
    page_icon="🛡",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ---------------------------------------------------------------------------
# Cached index (resource — holds EarthSatellite objects)
# ---------------------------------------------------------------------------


@st.cache_resource(show_spinner="Building object index…")
def cached_index(fingerprint: str):
    """Multi-catalog index; fingerprint busts cache when TLE files change."""
    return get_index(force=True)


def current_index():
    return cached_index(catalog_fingerprint(effective_index_groups()))


# ---------------------------------------------------------------------------
# Sidebar — location + catalog
# ---------------------------------------------------------------------------

st.sidebar.markdown("## 🛡 StarShield Lite")

st.sidebar.header("Observer location")
profile_names = list_observer_names() + ["Custom…"]
profile_choice = st.sidebar.selectbox(
    "Profile",
    options=profile_names,
    index=profile_names.index(DEFAULT_OBSERVER)
    if DEFAULT_OBSERVER in profile_names
    else 0,
)

if profile_choice == "Custom…":
    clat = st.sidebar.number_input("Latitude °", value=30.8, format="%.4f")
    clon = st.sidebar.number_input("Longitude °", value=-81.65, format="%.4f")
    celev = st.sidebar.number_input("Elevation m", value=5.0, format="%.1f")
    observer = resolve_observer(
        lat=clat, lon=clon, elevation=celev, label="Custom"
    )
else:
    observer = resolve_observer(profile=profile_choice)

st.sidebar.caption(format_observer(observer))

st.sidebar.header("Catalog")
group = st.sidebar.selectbox(
    "Primary group (fetch)",
    options=list(TLE_URLS.keys()),
    index=list(TLE_URLS.keys()).index("stations")
    if "stations" in TLE_URLS
    else 0,
)
if st.sidebar.button("Fetch / refresh TLEs", use_container_width=True):
    with st.spinner(f"Fetching {group}…"):
        try:
            path = fetch_tles(group, force=True)
            log.append({"action": "fetch_tles", "group": group, "path": str(path)})
            invalidate_index()
            cached_index.clear()
            st.cache_resource.clear()
            st.sidebar.success(f"Saved {path.name}")
            st.rerun()
        except Exception as exc:
            st.sidebar.error(str(exc))

if st.sidebar.button("Rebuild object index", use_container_width=True):
    invalidate_index()
    cached_index.clear()
    st.rerun()

st.sidebar.header("Pass defaults")
hours = st.sidebar.slider("Hours ahead", 6, 336, 72, step=6)
min_el = st.sidebar.slider("Min elevation (°)", 5, 40, 10)
stargazer = st.sidebar.checkbox("Stargazer (visible only)", True)
local_time = st.sidebar.checkbox("Local times", True)

st.sidebar.header("Conjunction")
conj_hours = st.sidebar.slider("Conj window (h)", 1, 72, 12)
conj_thr = st.sidebar.slider("Warn threshold (km)", 10, 500, int(CONJ_THRESHOLD_KM))
conj_pairs = st.sidebar.slider("Max group pairs", 5, 80, 20)

st.sidebar.markdown("---")
# Optional FastAPI backend (when STARSHIELD_USE_API=1 and server is up)
_api_mode = False
_api_client = None
if STREAMLIT_USE_API:
    try:
        from api.client import StarShieldAPI, api_reachable

        if api_reachable():
            _api_mode = True
            _api_client = StarShieldAPI()
            st.sidebar.success(f"API mode · {API_BASE_URL}")
        else:
            st.sidebar.warning("API mode on but server unreachable — using services")
    except Exception:
        st.sidebar.caption("API client unavailable — using services")
else:
    st.sidebar.caption("Data mode: direct services (set STARSHIELD_USE_API=1 for HTTP)")

st.sidebar.caption("TUI: `python main.py tui` · API: `python main.py api`")

# ---------------------------------------------------------------------------
# Header + index
# ---------------------------------------------------------------------------

idx = current_index()
stats = idx.stats()

st.title("🚀 StarShield Lite")
st.caption(
    f"{format_observer(observer)} · "
    f"index **{stats['objects']}** objects · "
    f"groups {', '.join(stats['groups_loaded']) or 'none'} · "
    f"stargazer sun ≤ {STARGAZER_SUN_ALT_MAX:g}°"
)

if stats["objects"] == 0:
    st.warning(
        "Object index is empty. Fetch **stations** / **starlink** / **visual** TLEs "
        "from the sidebar."
    )

(
    tab_status,
    tab_search,
    tab_passes,
    tab_conj,
    tab_watch,
    tab_sky,
    tab_history,
    tab_reports,
) = st.tabs(
    [
        "Status",
        "Object Index",
        "Passes",
        "Conjunctions",
        "Watchlist",
        "Starmap",
        "History",
        "Reports",
    ]
)

# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

with tab_status:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Indexed objects", stats["objects"])
    c2.metric("Groups loaded", len(stats["groups_loaded"]))
    c3.metric("Observer lat", f"{observer['lat']}°")
    c4.metric("Observer lon", f"{observer['lon']}°")

    st.subheader("Sky watch — next ISS")
    iss_rec = idx.resolve("ISS")
    iss_sat = idx.get_satellite(iss_rec) if iss_rec else None
    if iss_sat:
        with st.spinner("Predicting next ISS pass…"):
            vis = next_pass_summary(
                iss_sat,
                location=observer,
                hours_ahead=336,
                stargazer=True,
                min_elevation=min_el,
            )
            geo = next_pass_summary(
                iss_sat,
                location=observer,
                hours_ahead=72,
                stargazer=False,
                min_elevation=min_el,
            )

        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown("**Next ★ stargazer**")
            if vis:
                st.success(
                    f"{vis['countdown']} · max el {vis['max_elevation']:.0f}°  \n"
                    f"Local `{vis['local']}`"
                )
                if st.button("Jump to Starmap ★", key="jump_vis", type="primary"):
                    # Build a minimal pass-like dict from next_pass_summary
                    fake = {
                        "culmination": {"time": vis.get("peak_time")},
                        "max_elevation": vis.get("max_elevation"),
                        "quality_grade": None,
                    }
                    focus = pass_to_starmap_focus(fake, object_name="ISS")
                    apply_focus_to_session_state(st.session_state, focus)
                    st.success(
                        "Starmap primed for next ISS stargazer pass — open the **Starmap** tab."
                    )
            else:
                st.info("No stargazer pass in the next 14 days from this site.")
        with col_b:
            st.markdown("**Next geometric**")
            if geo:
                st.write(
                    f"{geo['countdown']} · max el {geo['max_elevation']:.0f}°  \n"
                    f"Local `{geo['local']}`"
                )
            else:
                st.write("None soon.")
    else:
        st.info("Fetch **stations** to enable ISS sky watch.")

    st.subheader("Catalog files")
    cached = list(DATA_DIR.glob("*_tles.txt"))
    if cached:
        rows = []
        for p in sorted(cached):
            age_h = (
                datetime.now(timezone.utc).timestamp() - p.stat().st_mtime
            ) / 3600
            rows.append(
                {
                    "file": p.name,
                    "size_kb": round(p.stat().st_size / 1024, 1),
                    "age_h": round(age_h, 1),
                }
            )
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

# ---------------------------------------------------------------------------
# Object Index search
# ---------------------------------------------------------------------------

with tab_search:
    st.subheader("Multi-catalog object index")
    st.caption(
        "Search across stations, starlink, visual, active by name, partial name, "
        "alias (ISS, Hubble), or NORAD ID."
    )
    q = st.text_input("Search", value="ISS", placeholder="ISS · STARLINK-1008 · 25544")
    limit = st.slider("Max results", 5, 50, 20)
    if q.strip():
        hits = idx.search(q.strip(), limit=limit)
        if not hits:
            st.warning("No matches.")
        else:
            df = pd.DataFrame(
                [
                    {
                        "NORAD": h.norad,
                        "Name": h.name,
                        "Groups": ", ".join(sorted(h.groups)),
                        "Aliases": ", ".join(h.aliases) if h.aliases else "",
                        "Epoch (UTC)": h.epoch.strftime("%Y-%m-%d %H:%M")
                        if h.epoch
                        else "",
                    }
                    for h in hits
                ]
            )
            st.dataframe(df, use_container_width=True, hide_index=True)
            pick = st.selectbox(
                "Select object",
                options=[f"{h.norad} · {h.name}" for h in hits],
            )
            if pick and st.button("Use for Passes / Starmap"):
                norad = int(pick.split("·")[0].strip())
                rec = idx.get(norad)
                if rec:
                    st.session_state["selected_object"] = rec.name
                    st.session_state["selected_norad"] = rec.norad
                    st.success(f"Selected **{rec.name}** (NORAD {rec.norad})")
    st.metric("Total indexed", stats["objects"])

# ---------------------------------------------------------------------------
# Passes
# ---------------------------------------------------------------------------

with tab_passes:
    st.subheader("Best passes tonight")
    st.caption(
        f"Observer: {format_observer(observer)} · "
        "Quality 0–100 (elev · duration · darkness · sunlit · brightness proxy)"
    )
    default_name = st.session_state.get("selected_object", "ISS")
    query = st.text_input("Object (name / NORAD / alias)", value=default_name, key="pass_q")
    cqa, cqb, cqc = st.columns(3)
    with cqa:
        sort_quality = st.checkbox("Sort by quality", value=True)
    with cqb:
        min_score_ui = st.slider("Min quality score", 0, 100, 0, key="min_q")
    with cqc:
        show_bd = st.checkbox("Show best breakdown", value=True)
    run_pass = st.button("Predict passes", type="primary")

    if run_pass:
        rec = idx.resolve(query)
        sat = idx.get_satellite(rec) if rec else None
        if sat is None:
            st.error(f"No match for `{query}` in the object index.")
            alt = idx.search(query, limit=8)
            if alt:
                st.write("Did you mean:", ", ".join(f"{h.name} ({h.norad})" for h in alt))
        else:
            with st.spinner(f"Predicting & scoring {sat.name}…"):
                raw = predict_passes(
                    sat,
                    location=observer,
                    hours_ahead=hours,
                    min_elevation=min_el,
                    max_passes=30,
                    stargazer=stargazer,
                )
                passes = score_passes(
                    raw,
                    location=observer,
                    sat=sat,
                    object_name=sat.name,
                    min_score=float(min_score_ui),
                    sort=sort_quality,
                )
            mode = "Stargazer" if stargazer else "All geometric"
            st.markdown(
                f"**{sat.name}** · NORAD {rec.norad} · {mode} · "
                f"next {hours:g}h · min el {min_el:g}° · "
                f"**{len(passes)}** scored pass(es)"
            )
            if stargazer:
                st.caption(
                    f"{getattr(raw, 'visible_count', '?')}/"
                    f"{getattr(raw, 'geometric_count', '?')} geometric passes visible"
                )
            if not passes:
                st.warning(
                    "No passes in this window (or none above min score). "
                    "Try longer hours, disable Stargazer, or lower min score."
                )
            else:
                if show_bd:
                    best_q = passes[0].get("quality") or {}
                    g = best_q.get("grade", "?")
                    sc = best_q.get("score", 0)
                    color = (
                        "normal"
                        if g in ("A", "B")
                        else ("off" if g == "C" else "inverse")
                    )
                    st.success(
                        f"Top pick: **{g} {sc}** — {format_quality_breakdown(best_q)}"
                    )

                rows = []
                for i, p in enumerate(passes):
                    fr = format_pass_row(p, local=local_time)
                    q = p.get("quality") or {}
                    rows.append(
                        {
                            "Rank": i + 1,
                            "Grade": q.get("grade", "—"),
                            "Score": q.get("score", "—"),
                            "Rise": fr["rise"],
                            "Culmination": fr["culmination"],
                            "Set": fr["set"],
                            "Max El": fr["max_el"],
                            "Az @ Max": fr["az_max"],
                            "Duration": fr["duration"],
                            "Sky": fr["sky"],
                            "Sunlit %": int(
                                round((q.get("sunlit_fraction") or 0) * 100)
                            ),
                        }
                    )
                df = pd.DataFrame(rows)

                def _color_grade(val):
                    if val in ("A", "B"):
                        return "background-color: #14532d; color: #bbf7d0"
                    if val == "C":
                        return "background-color: #713f12; color: #fde68a"
                    if val in ("D", "F"):
                        return "background-color: #7f1d1d; color: #fecaca"
                    return ""

                try:
                    styled = df.style.applymap(_color_grade, subset=["Grade"])
                    st.dataframe(styled, use_container_width=True, hide_index=True)
                except Exception:
                    st.dataframe(df, use_container_width=True, hide_index=True)

                st.download_button(
                    "Download CSV",
                    data=df.to_csv(index=False).encode("utf-8"),
                    file_name=f"passes_{rec.norad}_scored.csv",
                    mime="text/csv",
                )
                # PDF / ICS exports
                try:
                    from services.export import passes_to_ics, passes_to_pdf

                    pdf_bytes = passes_to_pdf(
                        passes,
                        object_name=sat.name.strip(),
                        location=observer,
                        stargazer=stargazer,
                        hours=hours,
                    )
                    ics_text = passes_to_ics(
                        passes,
                        object_name=sat.name.strip(),
                        location=observer,
                    )
                    cexp1, cexp2 = st.columns(2)
                    with cexp1:
                        st.download_button(
                            "Download PDF report",
                            data=pdf_bytes,
                            file_name=f"passes_{rec.norad}.pdf",
                            mime="application/pdf",
                        )
                    with cexp2:
                        st.download_button(
                            "Download ICS calendar",
                            data=ics_text.encode("utf-8"),
                            file_name=f"passes_{rec.norad}.ics",
                            mime="text/calendar",
                        )
                except Exception as exc:
                    st.caption(f"PDF/ICS export unavailable: {exc}")

                st.session_state["last_passes"] = passes
                st.session_state["last_pass_object"] = rec.name
                st.session_state["last_pass_norad"] = rec.norad

                # ---- Jump to Starmap (per-pass + rank) ----
                st.markdown("##### Jump to Starmap")
                st.caption(
                    "Opens the **Starmap** tab at culmination, highlights the track, "
                    "and syncs sky + ground views."
                )
                n_jump = min(5, len(passes))
                jump_cols = st.columns(n_jump)
                for i in range(n_jump):
                    p = passes[i]
                    q = p.get("quality") or {}
                    grade = p.get("quality_grade") or q.get("grade") or "?"
                    score = p.get("quality_score")
                    if score is None:
                        score = q.get("score", "")
                    mel = p.get("max_elevation")
                    label = f"#{i+1} {grade}"
                    if mel is not None:
                        label += f" · {mel:.0f}°"
                    with jump_cols[i]:
                        if st.button(
                            label,
                            key=f"jump_pass_{i}",
                            use_container_width=True,
                            type="primary" if i == 0 else "secondary",
                        ):
                            focus = pass_to_starmap_focus(
                                p,
                                object_name=rec.name,
                                norad=rec.norad,
                            )
                            apply_focus_to_session_state(st.session_state, focus)
                            st.success(
                                f"Starmap focused on **{rec.name}** rank #{i+1} "
                                f"({grade} {score}) — open the **Starmap** tab."
                            )

                with st.expander("Jump by rank (all passes)"):
                    jump_idx = st.number_input(
                        "Pass rank",
                        min_value=1,
                        max_value=max(1, len(passes)),
                        value=1,
                        key="jump_pass_rank",
                    )
                    if st.button("Open selected rank on Starmap", key="jump_rank_btn"):
                        p = passes[int(jump_idx) - 1]
                        focus = pass_to_starmap_focus(
                            p, object_name=rec.name, norad=rec.norad
                        )
                        apply_focus_to_session_state(st.session_state, focus)
                        st.success(
                            f"Starmap primed for rank **{int(jump_idx)}** — "
                            "open the **Starmap** tab."
                        )

                if DB_LOG_ENABLED and passes:
                    try:
                        nlog = log_passes_batch(
                            passes,
                            object_name=sat.name,
                            norad=rec.norad,
                            location=observer,
                            stargazer=stargazer,
                            source="streamlit",
                        )
                        if nlog:
                            st.caption(
                                f"DB: logged {nlog} Grade B+ pass(es) → `{DB_PATH.name}`"
                            )
                    except Exception as exc:
                        st.caption(f"DB log skipped: {exc}")

            log.append(
                {
                    "action": "passes_dash",
                    "sat": sat.name,
                    "norad": rec.norad,
                    "observer": observer.get("name"),
                    "hours": hours,
                    "stargazer": stargazer,
                    "n": len(passes) if passes else 0,
                    "best_score": passes[0].get("quality_score") if passes else None,
                }
            )

# ---------------------------------------------------------------------------
# Conjunctions
# ---------------------------------------------------------------------------

with tab_conj:
    st.subheader("Conjunction scanner")
    mode = st.radio("Mode", ["Named pair", "Group sample"], horizontal=True)

    if mode == "Named pair":
        c1, c2 = st.columns(2)
        with c1:
            n1 = st.text_input("Object 1", "ISS")
        with c2:
            n2 = st.text_input("Object 2", "STARLINK-1008")
        if st.button("Scan pair", type="primary"):
            r1, r2 = idx.resolve(n1), idx.resolve(n2)
            s1 = idx.get_satellite(r1) if r1 else None
            s2 = idx.get_satellite(r2) if r2 else None
            if not s1 or not s2:
                st.error("Could not resolve one or both objects in the index.")
            else:
                with st.spinner(f"{s1.name} ↔ {s2.name}…"):
                    result = check_conjunction(
                        s1,
                        s2,
                        hours=conj_hours,
                        threshold_km=float(conj_thr),
                        high_risk_km=CONJ_HIGH_RISK_KM,
                        steps=240,
                    )
                m1, m2, m3 = st.columns(3)
                m1.metric("Min distance", f"{result['min_dist_km']} km")
                m2.metric("Risk", result["risk"])
                m3.metric(
                    "TCA (UTC)",
                    result["tca"].strftime("%Y-%m-%d %H:%M")
                    if hasattr(result["tca"], "strftime")
                    else str(result["tca"]),
                )
                fig = go.Figure()
                t_labels = [
                    t.strftime("%m-%d %H:%M") if hasattr(t, "strftime") else str(t)
                    for t in result["times"]
                ]
                fig.add_trace(
                    go.Scatter(
                        x=t_labels,
                        y=result["distances"],
                        mode="lines",
                        line=dict(color="#00d4ff", width=2),
                        name="Distance (km)",
                    )
                )
                fig.add_hline(y=conj_thr, line_dash="dash", line_color="#faad14")
                fig.add_hline(
                    y=CONJ_HIGH_RISK_KM, line_dash="dot", line_color="#ff4d4f"
                )
                fig.update_layout(
                    template="plotly_dark",
                    height=380,
                    title=f"Distance: {s1.name} ↔ {s2.name}",
                    yaxis_title="km",
                )
                st.plotly_chart(fig, use_container_width=True)
                generate_html_report([result], open_browser=False)
                log.append(
                    {
                        "action": "conj_dash",
                        "pair": f"{s1.name}/{s2.name}",
                        "min_km": result["min_dist_km"],
                        "risk": result["risk"],
                    }
                )
    else:
        g1 = st.selectbox("Primary group", list(TLE_URLS.keys()), key="gg1")
        g2 = st.selectbox(
            "Secondary group",
            list(TLE_URLS.keys()),
            index=list(TLE_URLS.keys()).index("starlink")
            if "starlink" in TLE_URLS
            else 0,
            key="gg2",
        )
        if st.button("Scan group sample", type="primary"):
            primary = idx.satellites_in_group(g1)
            secondary = idx.satellites_in_group(g2)
            if g1 == "stations":
                iss = idx.get_satellite(idx.resolve("ISS"))
                primary = [iss] if iss else primary[:1]
            else:
                primary = primary[:3]
            secondary = secondary[: max(1, conj_pairs // max(len(primary), 1))]
            if not primary or not secondary:
                st.error("Load both catalogs first.")
            else:
                with st.spinner("Scanning…"):
                    results = scan_conjunctions(
                        primary,
                        secondary,
                        hours=conj_hours,
                        threshold_km=float(conj_thr),
                        high_risk_km=CONJ_HIGH_RISK_KM,
                        steps=120,
                        max_pairs=conj_pairs,
                        progress_every=0,
                    )
                if results:
                    df = pd.DataFrame(
                        [
                            {
                                "Object 1": r["sat1"],
                                "Object 2": r["sat2"],
                                "TCA UTC": r["tca"].strftime("%Y-%m-%d %H:%M")
                                if hasattr(r["tca"], "strftime")
                                else str(r["tca"]),
                                "Min km": r["min_dist_km"],
                                "Risk": r["risk"],
                            }
                            for r in results
                        ]
                    )
                    st.dataframe(df, use_container_width=True, hide_index=True)
                    generate_html_report(results, open_browser=False)
                    st.download_button(
                        "Download CSV",
                        df.to_csv(index=False).encode("utf-8"),
                        "conjunctions.csv",
                        "text/csv",
                    )

# ---------------------------------------------------------------------------
# Watchlist
# ---------------------------------------------------------------------------

with tab_watch:
    st.subheader("Conjunction watchlist")
    st.caption(
        "Proactive monitoring of named pairs / groups. "
        "Default **iss-starlink** samples the Starlink catalog evenly (not every bird)."
    )
    wls = list_watchlists()
    wl_ids = [w.id for w in wls]
    default_i = (
        wl_ids.index(WATCHLIST_DEFAULT_ID) if WATCHLIST_DEFAULT_ID in wl_ids else 0
    )
    col_w1, col_w2 = st.columns([2, 1])
    with col_w1:
        wl_pick = st.selectbox(
            "Watchlist",
            options=wl_ids,
            index=default_i,
            format_func=lambda i: next(
                (f"{w.id} — {w.name}" for w in wls if w.id == i), i
            ),
        )
    with col_w2:
        wl_hours = st.number_input("Hours", min_value=1, max_value=168, value=48)
    wl_obj = get_watchlist(wl_pick)
    if wl_obj:
        st.write(wl_obj.description)
        st.caption(
            f"Mode `{wl_obj.mode}` · sample={wl_obj.sample} · "
            f"primary=`{wl_obj.primary or wl_obj.group1}`"
        )

    c1, c2, c3 = st.columns(3)
    with c1:
        wl_only = st.checkbox("Only below threshold", value=False)
    with c2:
        wl_thr = st.number_input(
            "Threshold km", min_value=1.0, max_value=500.0, value=float(conj_thr)
        )
    with c3:
        wl_sample = st.number_input(
            "Sample size (cap)",
            min_value=5,
            max_value=100,
            value=min(40, int(wl_obj.sample) if wl_obj else 40),
        )

    if st.button("Scan watchlist", type="primary"):
        if wl_obj is None:
            st.error("Watchlist not found.")
        else:
            wl_run = get_watchlist(wl_pick)
            wl_run.sample = int(wl_sample)
            with st.spinner(
                f"Scanning {wl_run.id} ({wl_run.sample} sample) over {wl_hours}h…"
            ):
                report = scan_watchlist(
                    wl_run,
                    hours=float(wl_hours),
                    threshold_km=float(wl_thr),
                    high_risk_km=CONJ_HIGH_RISK_KM,
                    only_below=wl_only,
                    adaptive=True,
                    steps=180,
                    progress_every=0,
                )
            st.session_state["watchlist_report"] = report
            if DB_LOG_ENABLED:
                try:
                    db_info = log_watchlist_scan(report, source="streamlit")
                    if db_info.get("run_id"):
                        st.caption(
                            f"DB: run #{db_info['run_id']} · "
                            f"{db_info['events_logged']} MEDIUM/HIGH events → `{DB_PATH.name}`"
                        )
                except Exception as exc:
                    st.caption(f"DB log skipped: {exc}")
            log.append(
                {
                    "action": "watchlist_dash",
                    "watchlist": wl_run.id,
                    "pairs": report["pairs_scanned"],
                    "n": report["summary"]["n_results"],
                    "closest_km": report["summary"]["closest_km"],
                }
            )

    report = st.session_state.get("watchlist_report")
    if report:
        s = report["summary"]
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Pairs scanned", report["pairs_scanned"])
        m2.metric("Results", s["n_results"])
        m3.metric("HIGH / MED", f"{s['HIGH']} / {s['MEDIUM']}")
        m4.metric("Closest km", s["closest_km"] if s["closest_km"] is not None else "—")
        if s.get("closest_pair"):
            st.success(f"Closest: **{s['closest_pair']}** · {s['closest_km']} km")

        rows = results_to_rows(report["results"], local=local_time)
        if rows:
            df = pd.DataFrame(rows)

            def _risk_style_df(val):
                if val == "HIGH":
                    return "background-color: #7f1d1d; color: #fecaca"
                if val == "MEDIUM":
                    return "background-color: #713f12; color: #fde68a"
                if val == "LOW":
                    return "background-color: #14532d; color: #bbf7d0"
                return ""

            try:
                st.dataframe(
                    df.style.applymap(_risk_style_df, subset=["Risk"]),
                    use_container_width=True,
                    hide_index=True,
                )
            except Exception:
                st.dataframe(df, use_container_width=True, hide_index=True)

            st.download_button(
                "Download CSV",
                data=df.to_csv(index=False).encode("utf-8"),
                file_name=f"watchlist_{report['watchlist_id']}.csv",
                mime="text/csv",
            )
            try:
                from services.export import watchlist_to_pdf

                wl_pdf = watchlist_to_pdf(report)
                st.download_button(
                    "Download PDF report",
                    data=wl_pdf,
                    file_name=f"watchlist_{report['watchlist_id']}.pdf",
                    mime="application/pdf",
                )
            except Exception as exc:
                st.caption(f"PDF export unavailable: {exc}")
            # Closest pair distance chart if series present
            best = report["results"][0]
            if best.get("times") and best.get("distances"):
                fig = go.Figure()
                tlab = [
                    t.strftime("%m-%d %H:%M") if hasattr(t, "strftime") else str(t)
                    for t in best["times"]
                ]
                fig.add_trace(
                    go.Scatter(
                        x=tlab,
                        y=best["distances"],
                        mode="lines",
                        line=dict(color="#00d4ff", width=2),
                        name="Distance (km)",
                    )
                )
                fig.add_hline(
                    y=report["threshold_km"],
                    line_dash="dash",
                    line_color="#faad14",
                )
                fig.add_hline(
                    y=CONJ_HIGH_RISK_KM, line_dash="dot", line_color="#ff4d4f"
                )
                fig.update_layout(
                    template="plotly_dark",
                    height=360,
                    title=f"Closest pair: {best['sat1']} ↔ {best['sat2']}",
                    yaxis_title="km",
                )
                st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No rows — try disabling 'Only below threshold'.")

# ---------------------------------------------------------------------------
# Starmap + time scrubber (linked sky + ground views)
# ---------------------------------------------------------------------------

with tab_sky:
    st.subheader("Starmap — linked sky + ground planning")
    st.caption(
        f"Observer **{format_observer(observer)}**. "
        "Zenith center · horizon edge · North up · clockwise. "
        "★ scrubber · ▲ rise · ◆ culm · ▼ set. "
        "Jump here from **Passes** or **Status** for a focused pass."
    )

    focus = st.session_state.get("sky_focus_pass")
    focus_mode = bool(st.session_state.get("sky_focus_mode", True))
    if focus:
        qlab = focus_quality_label(focus) or "—"
        fc1, fc2 = st.columns([4, 1])
        with fc1:
            st.info(
                f"**Linked pass:** {focus.get('object')} · quality **{qlab}** · "
                f"max el {focus.get('max_el') if focus.get('max_el') is not None else '—'}° · "
                f"culm `{focus.get('culm') or '—'}` · "
                f"window ~{focus.get('window_hours', '?')}h"
            )
        with fc2:
            if st.button("Clear focus", key="sky_clear_focus"):
                st.session_state.pop("sky_focus_pass", None)
                st.session_state["sky_focus_mode"] = False
                st.rerun()

    # Apply window seed from jump before widgets
    win_default = int(st.session_state.get("sky_win_seed", 6))
    win_default = max(1, min(24, win_default))
    if "sky_win" not in st.session_state:
        st.session_state["sky_win"] = win_default
    # If a jump just set sky_win_seed higher, honor it once
    if st.session_state.get("sky_win_seed") and st.session_state.get("_sky_win_applied") != st.session_state.get("sky_jump_nonce"):
        st.session_state["sky_win"] = win_default
        st.session_state["_sky_win_applied"] = st.session_state.get("sky_jump_nonce")

    c_win, c_min, c_step, c_view = st.columns([1.1, 1, 1, 1.4])
    with c_win:
        sky_hours = st.slider(
            "Track window (hours from now)",
            1,
            24,
            key="sky_win",
        )
    with c_min:
        sky_min = st.slider("Min elevation (°)", 0, 30, 5, key="sky_min")
    with c_step:
        step_min = st.select_slider(
            "Sample step (min)", options=[1, 2, 5], value=1, key="sky_step"
        )
    with c_view:
        view_mode = st.radio(
            "Layout",
            ["Side by side", "Sky only", "Ground only", "Tabs"],
            horizontal=True,
            key="sky_view_mode",
        )

    default_objs = st.session_state.get("sky_objects", ["ISS"])
    # Keep text input in sync after jump
    if st.session_state.get("sky_objects") and st.session_state.get("_sky_obj_applied") != st.session_state.get("sky_jump_nonce"):
        st.session_state["sky_obj_text"] = ", ".join(st.session_state["sky_objects"])
        st.session_state["_sky_obj_applied"] = st.session_state.get("sky_jump_nonce")

    ocol, fcol = st.columns([3, 1])
    with ocol:
        if "sky_obj_text" not in st.session_state:
            st.session_state["sky_obj_text"] = ", ".join(default_objs)
        obj_text = st.text_input(
            "Objects (comma-separated names / NORAD / aliases)",
            key="sky_obj_text",
            help="Examples: ISS, 25544, STARLINK-1008, Hubble",
        )
    with fcol:
        focus_mode = st.checkbox(
            "Focus mode",
            value=bool(st.session_state.get("sky_focus_mode", bool(focus))),
            key="sky_focus_mode_cb",
            help="Dim other objects and highlight the linked pass segment",
        )
        st.session_state["sky_focus_mode"] = focus_mode

    # ---- Minute-precision scrubber + playback ----
    max_minutes = float(sky_hours) * 60.0
    seed_min = float(
        st.session_state.get(
            "sky_scrub_minutes",
            hours_to_minutes(float(st.session_state.get("sky_scrub_seed", 0.0))),
        )
    )
    seed_min = max(0.0, min(seed_min, max_minutes))
    if (
        st.session_state.get("_sky_scrub_applied")
        != st.session_state.get("sky_jump_nonce")
    ):
        st.session_state["sky_scrub_minutes"] = seed_min
        st.session_state["_sky_scrub_applied"] = st.session_state.get("sky_jump_nonce")
    if "sky_scrub_minutes" not in st.session_state:
        st.session_state["sky_scrub_minutes"] = seed_min
    # Clamp if window shrunk
    if st.session_state["sky_scrub_minutes"] > max_minutes:
        st.session_state["sky_scrub_minutes"] = max_minutes

    st.markdown("##### Time scrubber")
    sc1, sc2, sc3, sc4, sc5 = st.columns([2.5, 0.7, 0.7, 0.9, 1.2])
    with sc1:
        scrub_min = st.slider(
            "Minutes from now",
            min_value=0.0,
            max_value=max_minutes,
            step=1.0,
            key="sky_scrub_minutes",
            help="1-minute steps. Jump from Passes sets this to culmination.",
        )
    with sc2:
        if st.button("◀", key="sky_step_back", help="−1 min"):
            st.session_state["sky_scrub_minutes"] = max(
                0.0, float(st.session_state["sky_scrub_minutes"]) - 1.0
            )
            st.session_state["sky_playing"] = False
            st.rerun()
    with sc3:
        if st.button("▶", key="sky_step_fwd", help="+1 min"):
            st.session_state["sky_scrub_minutes"] = min(
                max_minutes, float(st.session_state["sky_scrub_minutes"]) + 1.0
            )
            st.session_state["sky_playing"] = False
            st.rerun()
    with sc4:
        playing = bool(st.session_state.get("sky_playing", False))
        if playing:
            if st.button("⏸ Pause", key="sky_pause", type="primary"):
                st.session_state["sky_playing"] = False
                st.rerun()
        else:
            if st.button("▶ Play", key="sky_play"):
                st.session_state["sky_playing"] = True
                st.rerun()
    with sc5:
        play_speed = st.selectbox(
            "Play step",
            options=[1, 2, 5, 10],
            index=1,
            key="sky_play_speed",
            help="Minutes advanced per animation frame",
        )

    scrub_h = minutes_to_hours(float(scrub_min))
    clock = format_scrub_clock(scrub_h)
    st.markdown(
        f"**Scrub time:** `{clock['utc']}` · local `{clock['local']}` · "
        f"offset **{clock['offset']}**"
    )

    # Playback loop (fire-and-advance)
    if st.session_state.get("sky_playing"):
        import time as _time

        nxt, hit_end = advance_scrub(
            float(st.session_state["sky_scrub_minutes"]),
            step_minutes=float(play_speed),
            max_minutes=max_minutes,
        )
        st.session_state["sky_scrub_minutes"] = nxt
        if hit_end:
            st.session_state["sky_playing"] = False
        else:
            _time.sleep(0.12)
            st.rerun()

    # Resolve satellites + cache tracks by fingerprint
    names = [x.strip() for x in obj_text.split(",") if x.strip()]
    if not names:
        st.info("Add at least one object name / NORAD.")
    else:
        sats = []
        labels = []
        for name in names[:8]:
            rec = idx.resolve(name)
            sat = idx.get_satellite(rec) if rec else None
            if sat:
                sats.append(sat)
                labels.append(rec.name if rec else sat.name.strip())
            else:
                st.warning(f"Unresolved: `{name}`")

        if not sats:
            st.info("No resolved objects.")
        else:
            track_key = (
                f"{','.join(labels)}|{sky_hours}|{step_min}|{sky_min}|"
                f"{observer.get('lat')}|{observer.get('lon')}"
            )
            cache = st.session_state.get("_sky_track_cache") or {}
            if cache.get("key") != track_key:
                with st.spinner("Propagating linked sky + ground tracks…"):
                    tracks = tracks_for_objects(
                        sats,
                        location=observer,
                        hours=float(sky_hours),
                        step_minutes=float(step_min),
                        min_elevation=float(sky_min),
                        start=None,
                    )
                    # Prefer resolved catalog names on tracks
                    for tr, lab in zip(tracks, labels):
                        tr["name"] = lab
                    gtracks = [
                        ground_track_latlon(
                            s,
                            hours=float(sky_hours),
                            step_minutes=max(1.0, float(step_min)),
                        )
                        for s in sats
                    ]
                    for gt, lab in zip(gtracks, labels):
                        gt["name"] = lab
                    gtracks = attach_sky_meta_to_ground(gtracks, tracks)
                st.session_state["_sky_track_cache"] = {
                    "key": track_key,
                    "tracks": tracks,
                    "gtracks": gtracks,
                }
            else:
                tracks = cache["tracks"]
                gtracks = cache["gtracks"]

            focus_name = (focus or {}).get("object") if focus_mode else None
            # Quality label for hover (match catalog aliases like ISS / ISS (ZARYA))
            quality_by_name = {}
            if focus and focus.get("object"):
                qlab = focus_quality_label(focus)
                quality_by_name[str(focus["object"])] = qlab
                for lab in labels:
                    if _viz_is_focus(lab, str(focus["object"])):
                        quality_by_name[lab] = qlab

            sky_fig = build_linked_sky_figure(
                tracks,
                scrub_hours=float(scrub_h),
                location_label=observer.get("name", ""),
                focus_name=focus_name,
                focus=focus if focus_mode else None,
                quality_by_name=quality_by_name,
                dim_others=bool(focus_mode and focus_name),
                show_events=True,
            )
            ground_fig = build_linked_ground_figure(
                gtracks,
                location=observer,
                scrub_hours=float(scrub_h),
                focus_name=focus_name,
                focus=focus if focus_mode else None,
                quality_by_name=quality_by_name,
                dim_others=bool(focus_mode and focus_name),
            )

            # Events near scrubber
            near = event_near_scrub(tracks, float(scrub_h), window_minutes=10.0)
            if near:
                bits = [
                    f"**{e['object']}** {e['type']} ({e['dt_min']:.0f}m)"
                    for e in near[:4]
                ]
                st.caption("Near scrub: " + " · ".join(bits))

            def _show_sky():
                st.plotly_chart(sky_fig, use_container_width=True, config={
                    "displayModeBar": True,
                    "scrollZoom": False,
                })

            def _show_ground():
                st.plotly_chart(ground_fig, use_container_width=True, config={
                    "displayModeBar": True,
                })

            if view_mode == "Side by side":
                col_sky, col_gnd = st.columns(2)
                with col_sky:
                    st.markdown("##### Sky (alt–az)")
                    _show_sky()
                with col_gnd:
                    st.markdown("##### Ground track")
                    _show_ground()
            elif view_mode == "Sky only":
                _show_sky()
            elif view_mode == "Ground only":
                _show_ground()
            else:
                sub_sky, sub_gnd = st.tabs(["Sky view", "Ground track"])
                with sub_sky:
                    _show_sky()
                with sub_gnd:
                    _show_ground()

            # Positions at scrub time
            st.markdown("#### Positions at scrub time")
            pos_rows = []
            for tr in tracks:
                pos = position_at_offset(tr, float(scrub_h))
                pos_rows.append(
                    {
                        "Object": tr["name"],
                        "Alt °": round(pos["alt"], 1) if pos["alt"] is not None else None,
                        "Az °": round(pos["az"], 1) if pos["az"] is not None else None,
                        "Above horizon": "yes" if pos["above"] else "no",
                        "Quality": quality_by_name.get(tr["name"], "—"),
                    }
                )
            st.dataframe(pd.DataFrame(pos_rows), use_container_width=True, hide_index=True)

            with st.expander("Rise / culmination / set events in window"):
                ev_rows = []
                for tr in tracks:
                    for ev in tr.get("events") or []:
                        t = ev["time"]
                        if getattr(t, "tzinfo", None) is None:
                            t = t.replace(tzinfo=timezone.utc)
                        ev_rows.append(
                            {
                                "Object": tr["name"],
                                "Event": ev["type"],
                                "UTC": t.strftime("%Y-%m-%d %H:%M:%S"),
                                "Local": t.astimezone().strftime("%Y-%m-%d %H:%M %Z"),
                                "Alt °": round(ev["alt"], 1),
                                "Az °": round(ev["az"], 1),
                            }
                        )
                if ev_rows:
                    st.dataframe(
                        pd.DataFrame(ev_rows), use_container_width=True, hide_index=True
                    )
                else:
                    st.caption("No rise/set/culm events above min elevation in window.")

            with st.expander("Catalog objects above horizon at scrub time (sample)"):
                # sample first 150 of stations or active
                sample = idx.satellites_in_group("stations") or idx.satellites_in_group(
                    "visual"
                )
                scrub_abs = datetime.now(timezone.utc) + timedelta(hours=float(scrub_h))
                if sample:
                    snap = sky_snapshot(
                        sample[:150],
                        location=observer,
                        min_elevation=max(sky_min, 10),
                        when=scrub_abs,
                    )
                    if snap:
                        st.dataframe(
                            pd.DataFrame(
                                [
                                    {
                                        "Object": r["name"],
                                        "Alt °": round(r["alt"], 1),
                                        "Az °": round(r["az"], 1),
                                    }
                                    for r in snap[:30]
                                ]
                            ),
                            use_container_width=True,
                            hide_index=True,
                        )
                    else:
                        st.caption("Nothing above the cut in the sample.")

# ---------------------------------------------------------------------------
# History (SQLite)
# ---------------------------------------------------------------------------

with tab_history:
    st.subheader("Historical log (SQLite)")
    st.caption(
        f"Database: `{DB_PATH}` · logging "
        f"{'**enabled**' if DB_LOG_ENABLED else '**disabled** (STARSHIELD_DB_LOG=0)'}"
    )
    ensure_db()
    hist_days = st.slider("Lookback days", 1, 90, 7, key="hist_days")
    s = summary_stats(days=hist_days)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Passes logged", s["passes_logged"])
    c2.metric("Conjunctions", s["conjunctions_logged"])
    c3.metric("HIGH / MED", f"{s['high_risk']} / {s['medium_risk']}")
    c4.metric("Watchlist runs", s["watchlist_runs"])
    if s.get("closest_pair"):
        st.info(
            f"Closest logged approach: **{s['closest_pair']}** · "
            f"{s['closest_approach_km']} km"
        )
    if s.get("avg_pass_score") is not None:
        st.caption(f"Average logged pass quality score: {s['avg_pass_score']}")

    h1, h2 = st.tabs(["Recent passes", "Conjunction events"])
    with h1:
        pass_rows = query_recent_passes(limit=40, days=hist_days)
        if pass_rows:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Logged": (r.get("logged_at") or "")[:19],
                            "Object": r.get("object_name"),
                            "Grade": r.get("quality_grade"),
                            "Score": r.get("quality_score"),
                            "Max el": r.get("max_elevation"),
                            "Observer": r.get("observer_name"),
                            "Culm UTC": (r.get("culm_utc") or "")[:19],
                        }
                        for r in pass_rows
                    ]
                ),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.write("No high-quality passes logged yet (run Passes with Grade B+).")

    with h2:
        conj_filter = st.text_input("Filter object (optional)", value="ISS", key="hist_obj")
        conj_rows = query_conjunctions(
            object_name=conj_filter or None, days=hist_days, limit=40
        )
        if conj_rows:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "TCA": (r.get("tca_utc") or "")[:19],
                            "Sat 1": r.get("sat1"),
                            "Sat 2": r.get("sat2"),
                            "Dist km": r.get("min_dist_km"),
                            "Risk": r.get("risk"),
                            "Watchlist": r.get("watchlist_id"),
                        }
                        for r in conj_rows
                    ]
                ),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.write(
                "No MEDIUM/HIGH conjunction events logged yet "
                "(scan a watchlist that finds close approaches)."
            )

    with st.expander("Recent watchlist runs"):
        runs = query_watchlist_runs(limit=15)
        if runs:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "ID": r.get("id"),
                            "Watchlist": r.get("watchlist_id"),
                            "Started": (r.get("started_at") or "")[:19],
                            "Pairs": r.get("pairs_scanned"),
                            "Results": r.get("n_results"),
                            "H/M/L": f"{r.get('n_high')}/{r.get('n_medium')}/{r.get('n_low')}",
                            "Closest km": r.get("closest_km"),
                        }
                        for r in runs
                    ]
                ),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.write("No runs yet.")

# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

with tab_reports:
    st.subheader("Local artifacts")
    files = []
    for pattern in ("*_tles.txt", "*.html", "*.png", "*.log", "*.csv"):
        for p in sorted(DATA_DIR.glob(pattern)):
            files.append(
                {
                    "name": p.name,
                    "kb": round(p.stat().st_size / 1024, 1),
                    "modified": datetime.fromtimestamp(
                        p.stat().st_mtime, tz=timezone.utc
                    ).strftime("%Y-%m-%d %H:%M UTC"),
                }
            )
    if files:
        st.dataframe(pd.DataFrame(files), use_container_width=True, hide_index=True)

    log_path = DATA_DIR / "starshield.log"
    st.subheader("Immutable log (tail)")
    if log_path.exists():
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        st.code("\n".join(lines[-40:]), language="text")
    else:
        st.caption("Log empty.")

st.markdown("---")
st.caption(
    "StarShield Lite · Object Index + Starmap scrubber · "
    f"home default {DEFAULT_OBSERVER}"
)
