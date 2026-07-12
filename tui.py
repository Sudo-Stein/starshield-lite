"""StarShield Lite — Textual TUI dashboard.

Launch:
  python main.py tui
  python tui.py
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import (
    Button,
    Checkbox,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    RichLog,
    Static,
    TabbedContent,
    TabPane,
)

from config import (
    CONJ_HIGH_RISK_KM,
    CONJ_MAX_PAIRS,
    CONJ_REPORT_FILE,
    CONJ_THRESHOLD_KM,
    DATA_DIR,
    DEFAULT_OBSERVER,
    LOCATION,
    PASS_HOURS_AHEAD,
    PASS_MIN_ELEVATION,
    STARGAZER_DEFAULT,
    STARGAZER_SUN_ALT_MAX,
    TLE_URLS,
)
from core.propagator import load_satellites
from core.predictor import (
    find_satellite_by_name,
    format_pass_row,
    next_pass_summary,
    predict_passes,
)
from services.object_index import get_index, invalidate_index
from services.observers import format_observer, list_observer_names, resolve_observer
from services.pass_quality import score_passes
from services.watchlist import get_watchlist, list_watchlists, scan_watchlist
from services.database import log_passes_batch, log_watchlist_scan, summary_stats
from config import DB_LOG_ENABLED, DB_PATH, WATCHLIST_DEFAULT_ID
from core.simulator import (
    check_conjunction,
    generate_html_report,
    open_latest_report,
    scan_conjunctions,
)
from core.tle_fetcher import fetch_tles
from utils.immutable_log import ImmutableLog

log = ImmutableLog()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tle_path(group: str) -> Path:
    return DATA_DIR / f"{group}_tles.txt"


def _ensure_tles(group: str) -> Path:
    if group not in TLE_URLS:
        raise ValueError(f"Unknown group '{group}'. Choose: {', '.join(TLE_URLS)}")
    path = _tle_path(group)
    if not path.exists():
        path = fetch_tles(group)
        log.append({"action": "fetch_tles", "group": group, "path": str(path)})
    return path


def _risk_text(risk: str) -> Text:
    styles = {
        "HIGH": "bold white on red",
        "MEDIUM": "bold black on yellow",
        "LOW": "bold black on green",
    }
    return Text(risk, style=styles.get(risk, "white"))


def _cache_age(path: Path) -> str:
    if not path.exists():
        return "missing"
    age_s = datetime.now(timezone.utc).timestamp() - path.stat().st_mtime
    if age_s < 3600:
        return f"{int(age_s // 60)}m old"
    if age_s < 86400:
        return f"{age_s / 3600:.1f}h old"
    return f"{age_s / 86400:.1f}d old"


def build_status_renderable(
    next_iss: Optional[dict] = None,
    observer: Optional[dict] = None,
) -> Group:
    obs = observer or resolve_observer(profile=DEFAULT_OBSERVER)
    table = Table(title="System Status", expand=True, show_header=True)
    table.add_column("Item", style="cyan", no_wrap=True)
    table.add_column("Value")
    table.add_row("Data dir", str(DATA_DIR))
    table.add_row("Observer", format_observer(obs))
    table.add_row("TLE groups", ", ".join(TLE_URLS.keys()))
    try:
        st_idx = get_index().stats()
        table.add_row(
            "Object index",
            f"{st_idx['objects']} objects · {', '.join(st_idx['groups_loaded']) or 'none'}",
        )
    except Exception:
        table.add_row("Object index", "(unavailable)")
    table.add_row(
        "Stargazer",
        f"{'on' if STARGAZER_DEFAULT else 'off'} · sun ≤ {STARGAZER_SUN_ALT_MAX:g}°",
    )
    table.add_row(
        "Conjunction",
        f"MEDIUM < {CONJ_THRESHOLD_KM:g} km · HIGH < {CONJ_HIGH_RISK_KM:g} km",
    )
    try:
        stats_db = summary_stats(days=7)
        table.add_row(
            "SQLite (7d)",
            f"passes={stats_db['passes_logged']} · conj={stats_db['conjunctions_logged']} · "
            f"runs={stats_db['watchlist_runs']} · log={'on' if DB_LOG_ENABLED else 'off'}",
        )
    except Exception:
        table.add_row("SQLite", str(DB_PATH.name))

    cached = sorted(DATA_DIR.glob("*_tles.txt"))
    if cached:
        ages = ", ".join(f"{p.stem.replace('_tles', '')} ({_cache_age(p)})" for p in cached)
        table.add_row("Cached TLEs", ages)
    else:
        table.add_row("Cached TLEs", "(none — fetch below)")

    report = DATA_DIR / CONJ_REPORT_FILE
    table.add_row(
        "HTML report",
        f"{report.name} ({_cache_age(report)})" if report.exists() else "(none yet)",
    )
    log_path = DATA_DIR / "starshield.log"
    if log_path.exists():
        n_lines = sum(1 for _ in open(log_path, encoding="utf-8", errors="ignore"))
        table.add_row("Log entries", f"{n_lines} lines")
    else:
        table.add_row("Log entries", "(empty)")

    parts = [table]

    # Next ISS banner
    if next_iss:
        el = next_iss.get("max_elevation")
        el_s = f"{el:.0f}°" if el is not None else "?"
        mode = "★ stargazer" if next_iss.get("visible") else "geometric"
        banner = (
            f"[bold cyan]Next ISS[/bold cyan]  {next_iss['countdown']}  ·  "
            f"max el {el_s}  ·  {next_iss['local']}  ·  {mode}\n"
            f"[dim]UTC {next_iss['utc']}[/dim]"
        )
        parts.append(Panel(banner, title="Sky watch", border_style="cyan"))
    else:
        parts.append(
            Panel(
                "[dim]No ISS pass found in cache window — fetch stations & wait, "
                "or open Passes tab with Stargazer off / longer hours.[/dim]",
                title="Sky watch",
                border_style="blue",
            )
        )

    tips = (
        "[dim]Keys: [b]1–5[/b] tabs · [b]r[/b] refresh · [b]q[/b] quit · "
        "CelesTrak 403s auto-retry / fall back to cache[/dim]"
    )
    parts.append(tips)
    return Group(*parts)


def build_reports_panel() -> Panel:
    lines = []
    for pattern in ("*_tles.txt", "*.html", "*.png", "*.log"):
        for p in sorted(DATA_DIR.glob(pattern)):
            size_kb = p.stat().st_size / 1024
            mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
            lines.append(
                f"[cyan]{p.name:40}[/]  {size_kb:8.1f} KB  "
                f"{mtime.strftime('%Y-%m-%d %H:%M UTC')}  "
                f"[dim]{_cache_age(p)}[/dim]"
            )
    body = "\n".join(lines) if lines else "[dim]No files in data/ yet.[/dim]"
    return Panel(body, title="data/ artifacts", border_style="blue")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------


class StarShieldTUI(App):
    """Keyboard-driven dashboard for StarShield Lite."""

    TITLE = "StarShield Lite"
    SUB_TITLE = "orbital awareness · Kingsland, GA"
    CSS = """
    Screen {
        background: #0b1020;
    }
    Header {
        background: #141a2f;
        color: #00d4ff;
    }
    Footer {
        background: #141a2f;
    }
    #status-view, #passes-out, #conj-out, #reports-view {
        height: 1fr;
        border: solid #243056;
        padding: 1 2;
        background: #0f1528;
    }
    #log-view {
        height: 1fr;
        border: solid #243056;
        background: #0f1528;
    }
    .form-row {
        height: auto;
        margin: 0 0 1 0;
    }
    .form-row Input {
        width: 1fr;
        margin-right: 1;
    }
    .form-row Checkbox {
        width: auto;
        margin-right: 2;
    }
    Label.hint {
        color: #8b97b8;
        margin: 0 0 1 1;
    }
    #status-btns, #passes-btns, #conj-btns, #reports-btns {
        height: auto;
        margin: 0 0 1 0;
    }
    Button {
        margin-right: 1;
    }
    Button.-primary {
        background: #00d4ff;
        color: #0b1020;
        text-style: bold;
    }
    DataTable {
        height: 1fr;
        border: solid #243056;
    }
    TabbedContent {
        height: 1fr;
    }
    #conj-out {
        height: auto;
        max-height: 6;
        margin-top: 1;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("1", "show_tab('status')", "Status", show=False),
        Binding("2", "show_tab('passes')", "Passes", show=False),
        Binding("3", "show_tab('conj')", "Conj", show=False),
        Binding("4", "show_tab('reports')", "Reports", show=False),
        Binding("5", "show_tab('log')", "Log", show=False),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with TabbedContent(initial="status"):
            with TabPane("Status", id="status"):
                yield Label(
                    "System readiness · observer profile · object index · next ISS",
                    classes="hint",
                )
                with Horizontal(classes="form-row"):
                    yield Input(
                        value=DEFAULT_OBSERVER,
                        placeholder="observer profile name",
                        id="obs-profile",
                    )
                with Horizontal(id="status-btns", classes="form-row"):
                    yield Button("Refresh", id="btn-status-refresh", variant="primary")
                    yield Button("Fetch stations", id="btn-fetch-stations")
                    yield Button("Fetch starlink", id="btn-fetch-starlink")
                    yield Button("Fetch active", id="btn-fetch-active")
                yield Static(id="status-view")

            with TabPane("Passes", id="passes"):
                yield Label(
                    "Passes via object index (name/NORAD/alias) · uses observer profile from Status",
                    classes="hint",
                )
                with Horizontal(classes="form-row"):
                    yield Input(value="stations", placeholder="group", id="pass-group")
                    yield Input(value="ISS", placeholder="name / NORAD", id="pass-name")
                    yield Input(value="168", placeholder="hours", id="pass-hours")
                    yield Input(value="10", placeholder="min elev °", id="pass-min-el")
                    yield Checkbox(
                        "Stargazer",
                        value=STARGAZER_DEFAULT,
                        id="pass-stargazer",
                    )
                    yield Checkbox("Local time", value=True, id="pass-local")
                with Horizontal(id="passes-btns", classes="form-row"):
                    yield Button("Predict", id="btn-passes-run", variant="primary")
                    yield Button("Clear", id="btn-passes-clear")
                yield Static(
                    "[dim]Press Predict (or r). Default window 168h for stargazer ISS.[/dim]",
                    id="passes-out",
                )

            with TabPane("Conjunctions", id="conj"):
                yield Label(
                    "Pair / group conj · or Watchlist scan (iss-starlink) · "
                    f"HIGH < {CONJ_HIGH_RISK_KM:g} km",
                    classes="hint",
                )
                with Horizontal(classes="form-row"):
                    yield Input(
                        value=WATCHLIST_DEFAULT_ID,
                        placeholder="watchlist id",
                        id="wl-id",
                    )
                    yield Input(value="24", placeholder="wl hours", id="wl-hours")
                    yield Button("Scan watchlist", id="btn-wl-scan", variant="primary")
                with Horizontal(classes="form-row"):
                    yield Input(value="stations", placeholder="group1", id="conj-g1")
                    yield Input(value="starlink", placeholder="group2", id="conj-g2")
                    yield Input(value="ISS", placeholder="name1", id="conj-n1")
                    yield Input(
                        value="STARLINK-1008", placeholder="name2", id="conj-n2"
                    )
                with Horizontal(classes="form-row"):
                    yield Input(value="12", placeholder="hours", id="conj-hours")
                    yield Input(
                        value=str(int(CONJ_THRESHOLD_KM)),
                        placeholder="threshold km",
                        id="conj-thr",
                    )
                    yield Input(
                        value=str(min(CONJ_MAX_PAIRS, 20)),
                        placeholder="max pairs",
                        id="conj-pairs",
                    )
                    yield Checkbox("Write HTML", value=True, id="conj-html")
                    yield Checkbox("Local TCA", value=True, id="conj-local")
                with Horizontal(id="conj-btns", classes="form-row"):
                    yield Button("Scan pair", id="btn-conj-pair", variant="primary")
                    yield Button("Scan group", id="btn-conj-group")
                    yield Button("Open HTML", id="btn-conj-html")
                with Vertical():
                    yield DataTable(id="conj-table")
                    yield Static("", id="conj-out")

            with TabPane("Reports", id="reports"):
                yield Label(
                    "Cached TLEs, maps, and HTML reports under data/",
                    classes="hint",
                )
                with Horizontal(id="reports-btns", classes="form-row"):
                    yield Button(
                        "Refresh list", id="btn-reports-refresh", variant="primary"
                    )
                    yield Button("Open conj HTML", id="btn-reports-open")
                yield Static(id="reports-view")

            with TabPane("Log", id="log"):
                yield Label(
                    "Append-only immutable log (data/starshield.log) · r to reload",
                    classes="hint",
                )
                yield RichLog(id="log-view", highlight=True, markup=True, wrap=True)

        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#conj-table", DataTable)
        table.cursor_type = "row"
        table.zebra_stripes = True
        table.add_columns("Object 1", "Object 2", "TCA", "Min dist", "Risk")
        self._observer = resolve_observer(profile=DEFAULT_OBSERVER)
        self.refresh_status()
        self.refresh_reports()
        self.refresh_log()
        self._load_next_iss()
        self.notify("StarShield Lite ready · tabs 1–5 · q quit", timeout=3)

    def _current_observer(self) -> dict:
        try:
            name = self.query_one("#obs-profile", Input).value.strip()
        except Exception:
            name = DEFAULT_OBSERVER
        # exact profile or default
        names = list_observer_names()
        if name in names:
            self._observer = resolve_observer(profile=name)
        elif not name:
            self._observer = resolve_observer(profile=DEFAULT_OBSERVER)
        # else keep previous / try as profile fallback
        else:
            self._observer = resolve_observer(profile=name)
        return self._observer

    # ----- refresh helpers -----

    def refresh_status(self, next_iss: Optional[dict] = None) -> None:
        if next_iss is None:
            next_iss = getattr(self, "_next_iss", None)
        else:
            self._next_iss = next_iss
        obs = self._current_observer()
        self.query_one("#status-view", Static).update(
            build_status_renderable(getattr(self, "_next_iss", None), observer=obs)
        )

    def refresh_reports(self) -> None:
        self.query_one("#reports-view", Static).update(build_reports_panel())

    def refresh_log(self) -> None:
        view = self.query_one("#log-view", RichLog)
        view.clear()
        path = DATA_DIR / "starshield.log"
        if not path.exists():
            view.write("[dim]Log empty — actions will append here.[/dim]")
            return
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as exc:
            view.write(f"[red]Could not read log: {exc}[/red]")
            return
        for line in lines[-200:]:
            view.write(line)
        view.write(f"\n[dim]— {len(lines)} total lines —[/dim]")

    def action_refresh(self) -> None:
        tabs = self.query_one(TabbedContent)
        active = tabs.active
        if active == "status":
            self.refresh_status()
            self._load_next_iss()
            self.notify("Status refreshed")
        elif active == "passes":
            self.run_passes()
        elif active == "conj":
            self.notify("Use Scan pair / Scan group on Conjunctions tab")
        elif active == "reports":
            self.refresh_reports()
            self.notify("Reports refreshed")
        elif active == "log":
            self.refresh_log()
            self.notify("Log reloaded")

    def action_show_tab(self, tab_id: str) -> None:
        self.query_one(TabbedContent).active = tab_id

    def _set_passes_out(self, content) -> None:
        self.query_one("#passes-out", Static).update(content)

    def _set_conj_out(self, content) -> None:
        self.query_one("#conj-out", Static).update(content)

    def _fill_conj_table(self, rows: List[tuple]) -> None:
        table = self.query_one("#conj-table", DataTable)
        table.clear()
        for row in rows:
            table.add_row(*row)

    # ----- Status -----

    @on(Button.Pressed, "#btn-status-refresh")
    def _on_status_refresh(self) -> None:
        self.refresh_status()
        self._load_next_iss()
        self.notify("Status refreshed")

    @on(Button.Pressed, "#btn-fetch-stations")
    def _on_fetch_stations(self) -> None:
        self._fetch_group("stations")

    @on(Button.Pressed, "#btn-fetch-starlink")
    def _on_fetch_starlink(self) -> None:
        self._fetch_group("starlink")

    @on(Button.Pressed, "#btn-fetch-active")
    def _on_fetch_active(self) -> None:
        self._fetch_group("active")

    @work(exclusive=True, thread=True)
    def _fetch_group(self, group: str) -> None:
        self.call_from_thread(self.notify, f"Fetching {group}…")
        try:
            path = fetch_tles(group, force=True)
            invalidate_index()
            log.append({"action": "fetch_tles", "group": group, "path": str(path)})
            self.call_from_thread(
                self.notify, f"Saved {path.name}", severity="information"
            )
        except Exception as exc:
            self.call_from_thread(
                self.notify, f"Fetch failed: {exc}", severity="error"
            )
        self.call_from_thread(self.refresh_status)
        self.call_from_thread(self.refresh_log)
        if group == "stations":
            self.call_from_thread(self._load_next_iss)

    @work(exclusive=True, thread=True)
    def _load_next_iss(self) -> None:
        """Background: next ISS pass for Status sky-watch panel."""
        try:
            idx = get_index()
            rec = idx.resolve("ISS")
            sat = idx.get_satellite(rec) if rec else None
            if sat is None:
                self.call_from_thread(self.refresh_status, None)
                return
            obs = getattr(self, "_observer", None) or resolve_observer(
                profile=DEFAULT_OBSERVER
            )
            summary = next_pass_summary(
                sat, location=obs, hours_ahead=336, stargazer=True
            )
            if summary is None:
                summary = next_pass_summary(
                    sat, location=obs, hours_ahead=72, stargazer=False
                )
                if summary:
                    summary["visible"] = False
            self.call_from_thread(self.refresh_status, summary)
        except Exception:
            pass

    # ----- Passes -----

    @on(Button.Pressed, "#btn-passes-run")
    def _on_passes_run(self) -> None:
        self.run_passes()

    @on(Button.Pressed, "#btn-passes-clear")
    def _on_passes_clear(self) -> None:
        self.query_one("#passes-out", Static).update(
            "[dim]Cleared. Press Predict to run again.[/dim]"
        )

    def run_passes(self) -> None:
        group = self.query_one("#pass-group", Input).value.strip() or "stations"
        name = self.query_one("#pass-name", Input).value.strip() or "ISS"
        try:
            hours = float(self.query_one("#pass-hours", Input).value or PASS_HOURS_AHEAD)
            min_el = float(
                self.query_one("#pass-min-el", Input).value or PASS_MIN_ELEVATION
            )
        except ValueError:
            self.notify("hours / min elev must be numbers", severity="error")
            return
        stargazer = self.query_one("#pass-stargazer", Checkbox).value
        local = self.query_one("#pass-local", Checkbox).value
        obs = self._current_observer()
        self.query_one("#passes-out", Static).update(
            f"[cyan]Predicting {name} @ {obs.get('name')} · {hours:g}h · "
            f"stargazer={'on' if stargazer else 'off'}…[/cyan]"
        )
        self._run_passes_worker(group, name, hours, min_el, stargazer, local, obs)

    @work(exclusive=True, thread=True)
    def _run_passes_worker(
        self,
        group: str,
        name: str,
        hours: float,
        min_el: float,
        stargazer: bool,
        local: bool,
        observer: dict,
    ) -> None:
        try:
            idx = get_index()
            rec = idx.resolve(name)
            sat = idx.get_satellite(rec, preferred_group=group) if rec else None
            if sat is None:
                path = _ensure_tles(group)
                sats, _ = load_satellites(path)
                sat = find_satellite_by_name(sats, name)
            if sat is None:
                self.call_from_thread(
                    self._set_passes_out,
                    f"[red]No satellite matching '{name}'. Try Object Index search.[/red]",
                )
                return
            raw = predict_passes(
                sat,
                location=observer,
                hours_ahead=hours,
                min_elevation=min_el,
                max_passes=20,
                stargazer=stargazer,
            )
            passes = score_passes(
                raw,
                location=observer,
                sat=sat,
                object_name=sat.name,
                min_score=0,
                sort=True,
            )[:12]
            tz_label = "Local" if local else "UTC"
            table = Table(
                title=f"Best Passes — {sat.name}",
                expand=True,
            )
            table.add_column("Q", justify="center")
            table.add_column(f"Rise ({tz_label})", style="green")
            table.add_column(f"Culm ({tz_label})", style="yellow")
            table.add_column(f"Set ({tz_label})", style="red")
            table.add_column("Max El")
            table.add_column("Az @ Max")
            table.add_column("Dur")
            table.add_column("Sky")

            if not passes:
                msg = (
                    f"[yellow]No {'visible ' if stargazer else ''}passes "
                    f"in next {hours:g}h.[/yellow]\n"
                    f"[dim]geo={getattr(raw, 'geometric_count', '?')} "
                    f"visible={getattr(raw, 'visible_count', '?')} · "
                    f"try longer hours or uncheck Stargazer[/dim]"
                )
                self.call_from_thread(self._set_passes_out, msg)
            else:
                for p in passes:
                    row = format_pass_row(p, local=local)
                    sky = row["sky"]
                    sky_cell = Text(sky, style="bold cyan") if "★" in sky else sky
                    grade = (p.get("quality") or {}).get("grade", "?")
                    q_style = {
                        "A": "bold green",
                        "B": "green",
                        "C": "yellow",
                        "D": "red",
                        "F": "red",
                    }.get(grade, "white")
                    table.add_row(
                        Text(row["quality"], style=q_style),
                        row["rise"],
                        row["culmination"],
                        row["set"],
                        row["max_el"],
                        row["az_max"],
                        row["duration"],
                        sky_cell,
                    )
                geo = getattr(raw, "geometric_count", None)
                vis = getattr(raw, "visible_count", None)
                best = passes[0].get("quality") or {}
                subtitle = (
                    f"Top: {best.get('grade')} {best.get('score')} · "
                    f"geo visible {vis}/{geo}"
                    if stargazer and geo is not None
                    else f"Top: {best.get('grade')} {best.get('score')}"
                )
                self.call_from_thread(
                    self._set_passes_out,
                    Panel(table, subtitle=subtitle, border_style="cyan"),
                )

            if DB_LOG_ENABLED and passes:
                try:
                    norad = getattr(getattr(sat, "model", None), "satnum", None)
                    log_passes_batch(
                        passes,
                        object_name=sat.name,
                        norad=int(norad) if norad is not None else None,
                        location=observer,
                        stargazer=stargazer,
                        source="tui",
                    )
                except Exception:
                    pass

            log.append(
                {
                    "action": "passes_tui",
                    "sat": sat.name,
                    "group": group,
                    "hours": hours,
                    "stargazer": stargazer,
                    "n_passes": len(passes),
                    "best_score": passes[0].get("quality_score") if passes else None,
                }
            )
            self.call_from_thread(self.refresh_log)
        except Exception as exc:
            self.call_from_thread(self._set_passes_out, f"[red]Error: {exc}[/red]")
            self.call_from_thread(self.notify, str(exc), severity="error")

    # ----- Conjunctions -----

    @on(Button.Pressed, "#btn-conj-pair")
    def _on_conj_pair(self) -> None:
        self.run_conj(mode="pair")

    @on(Button.Pressed, "#btn-conj-group")
    def _on_conj_group(self) -> None:
        self.run_conj(mode="group")

    @on(Button.Pressed, "#btn-conj-html")
    def _on_conj_html(self) -> None:
        path = open_latest_report()
        if path is None:
            self.notify("No HTML report yet — run a scan first", severity="warning")
        else:
            self.notify(f"Opened {path.name}")

    @on(Button.Pressed, "#btn-wl-scan")
    def _on_wl_scan(self) -> None:
        wl_id = self.query_one("#wl-id", Input).value.strip() or WATCHLIST_DEFAULT_ID
        try:
            wl_hours = float(self.query_one("#wl-hours", Input).value or 24)
        except ValueError:
            self.notify("Watchlist hours must be a number", severity="error")
            return
        self._set_conj_out(f"[cyan]Scanning watchlist {wl_id}…[/cyan]")
        self._run_watchlist_worker(wl_id, wl_hours)

    @work(exclusive=True, thread=True)
    def _run_watchlist_worker(self, wl_id: str, hours: float) -> None:
        try:
            w = get_watchlist(wl_id)
            if w is None:
                ids = ", ".join(x.id for x in list_watchlists())
                self.call_from_thread(
                    self._set_conj_out,
                    f"[red]Unknown watchlist '{wl_id}'. Try: {ids}[/red]",
                )
                return
            # Keep TUI scans snappy
            w.sample = min(w.sample, 20)
            report = scan_watchlist(
                w,
                hours=hours,
                adaptive=True,
                steps=120,
                progress_every=0,
            )
            results = report["results"][:25]
            rows = []
            for r in results:
                tca = r["tca"]
                tca_s = (
                    tca.strftime("%m-%d %H:%M")
                    if hasattr(tca, "strftime")
                    else str(tca)
                )
                rows.append(
                    (
                        r["sat1"][:22],
                        r["sat2"][:22],
                        tca_s,
                        f"{r['min_dist_km']:.1f} km",
                        r["risk"],
                    )
                )
            self.call_from_thread(self._fill_conj_table, rows)
            s = report["summary"]
            msg = (
                f"Watchlist [bold]{w.id}[/bold]: {report['pairs_scanned']} pairs · "
                f"H/M/L {s['HIGH']}/{s['MEDIUM']}/{s['LOW']} · "
                f"closest {s['closest_km']} km ({s['closest_pair']})"
            )
            if DB_LOG_ENABLED:
                try:
                    log_watchlist_scan(report, source="tui")
                except Exception:
                    pass
            self.call_from_thread(self._set_conj_out, msg)
            log.append(
                {
                    "action": "watchlist_tui",
                    "watchlist": w.id,
                    "pairs": report["pairs_scanned"],
                    "closest_km": s["closest_km"],
                }
            )
            self.call_from_thread(self.refresh_log)
            self.call_from_thread(
                self.notify, f"Watchlist done · closest {s['closest_km']} km"
            )
        except Exception as exc:
            self.call_from_thread(self._set_conj_out, f"[red]Error: {exc}[/red]")
            self.call_from_thread(self.notify, str(exc), severity="error")

    def run_conj(self, mode: str = "pair") -> None:
        g1 = self.query_one("#conj-g1", Input).value.strip() or "stations"
        g2 = self.query_one("#conj-g2", Input).value.strip() or "starlink"
        n1 = self.query_one("#conj-n1", Input).value.strip()
        n2 = self.query_one("#conj-n2", Input).value.strip()
        try:
            hours = float(self.query_one("#conj-hours", Input).value or 12)
            thr = float(self.query_one("#conj-thr", Input).value or CONJ_THRESHOLD_KM)
            max_pairs = int(self.query_one("#conj-pairs", Input).value or 20)
        except ValueError:
            self.notify(
                "hours / threshold / max pairs must be numbers", severity="error"
            )
            return
        write_html = self.query_one("#conj-html", Checkbox).value
        local = self.query_one("#conj-local", Checkbox).value

        if mode == "pair" and (not n1 or not n2):
            self.notify("Pair mode needs name1 and name2", severity="error")
            return

        self.query_one("#conj-out", Static).update(
            f"[cyan]Running {mode} scan…[/cyan]"
        )
        self._run_conj_worker(
            mode, g1, g2, n1, n2, hours, thr, max_pairs, write_html, local
        )

    @work(exclusive=True, thread=True)
    def _run_conj_worker(
        self,
        mode: str,
        g1: str,
        g2: str,
        n1: str,
        n2: str,
        hours: float,
        thr: float,
        max_pairs: int,
        write_html: bool,
        local: bool,
    ) -> None:
        try:
            path1 = _ensure_tles(g1)
            path2 = path1 if g2 == g1 else _ensure_tles(g2)
            sats1, _ = load_satellites(path1)
            sats2 = sats1 if path2 == path1 else load_satellites(path2)[0]

            results: List[dict] = []
            if mode == "pair":
                sat1 = find_satellite_by_name(sats1, n1)
                sat2 = find_satellite_by_name(sats2, n2)
                if sat1 is None or sat2 is None:
                    missing = []
                    if sat1 is None:
                        missing.append(n1)
                    if sat2 is None:
                        missing.append(n2)
                    self.call_from_thread(
                        self.notify,
                        f"Not found: {', '.join(missing)}",
                        severity="error",
                    )
                    return
                results = [
                    check_conjunction(
                        sat1,
                        sat2,
                        hours=hours,
                        threshold_km=thr,
                        high_risk_km=CONJ_HIGH_RISK_KM,
                        steps=180,
                    )
                ]
            else:
                primary = list(sats1)
                if g1 == "stations":
                    iss = find_satellite_by_name(sats1, "ISS")
                    primary = [iss] if iss else primary[:1]
                else:
                    primary = primary[: min(3, len(primary))]
                secondary = list(sats2)[
                    : max(1, max_pairs // max(len(primary), 1))
                ]
                results = scan_conjunctions(
                    primary,
                    secondary,
                    hours=hours,
                    threshold_km=thr,
                    high_risk_km=CONJ_HIGH_RISK_KM,
                    steps=120,
                    max_pairs=max_pairs,
                    progress_every=0,
                )

            rows = []
            for r in results[:40]:
                tca = r["tca"]
                if hasattr(tca, "strftime"):
                    if getattr(tca, "tzinfo", None) is None:
                        tca = tca.replace(tzinfo=timezone.utc)
                    if local:
                        tca_s = tca.astimezone().strftime("%Y-%m-%d %H:%M %Z")
                    else:
                        tca_s = tca.strftime("%Y-%m-%d %H:%M:%S UTC")
                else:
                    tca_s = str(tca)
                rows.append(
                    (
                        r["sat1"],
                        r["sat2"],
                        tca_s,
                        f"{r['min_dist_km']:.2f} km",
                        _risk_text(r["risk"]),
                    )
                )
            self.call_from_thread(self._fill_conj_table, rows)

            if not results:
                self.call_from_thread(
                    self._set_conj_out, "[yellow]No results.[/yellow]"
                )
                return

            best = results[0]
            risk_style = {
                "HIGH": "bold red",
                "MEDIUM": "bold yellow",
                "LOW": "green",
            }.get(best["risk"], "white")
            summary = (
                f"Closest: [bold]{best['sat1']}[/bold] ↔ [bold]{best['sat2']}[/bold]  ·  "
                f"[{risk_style}]{best['risk']}[/]  ·  [b]{best['min_dist_km']} km[/b]  ·  "
                f"{len(results)} pair(s)"
            )
            report_note = ""
            if write_html:
                path = generate_html_report(results, open_browser=False)
                report_note = f"\n[green]HTML → {path}[/green]  (Open HTML)"
                self.call_from_thread(self.refresh_reports)

            self.call_from_thread(self._set_conj_out, summary + report_note)
            log.append(
                {
                    "action": "conjunction_tui",
                    "mode": mode,
                    "hours": hours,
                    "threshold_km": thr,
                    "n_results": len(results),
                    "closest_km": best["min_dist_km"],
                    "risk": best["risk"],
                }
            )
            self.call_from_thread(self.refresh_log)
            self.call_from_thread(
                self.notify,
                f"Done · closest {best['min_dist_km']} km ({best['risk']})",
            )
        except Exception as exc:
            self.call_from_thread(self._set_conj_out, f"[red]Error: {exc}[/red]")
            self.call_from_thread(self.notify, str(exc), severity="error")

    # ----- Reports -----

    @on(Button.Pressed, "#btn-reports-refresh")
    def _on_reports_refresh(self) -> None:
        self.refresh_reports()

    @on(Button.Pressed, "#btn-reports-open")
    def _on_reports_open(self) -> None:
        path = open_latest_report()
        if path is None:
            self.notify("No conjunction HTML report found", severity="warning")
        else:
            self.notify(f"Opened {path.name}")


def run_tui() -> None:
    """Entry point used by main.py and ``python tui.py``."""
    StarShieldTUI().run()


if __name__ == "__main__":
    run_tui()
