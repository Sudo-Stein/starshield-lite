#!/usr/bin/env python3
"""StarShield Lite — guided demo.

Walks through the main features with clear step banners:

  1. Object Index search
  2. High-quality pass scoring
  3. Watchlist / debris conjunction scan
  4. Starmap (Plotly HTML)
  5. Export (ICS + optional PDF)

Usage (from repo root, venv active)::

    python demo/demo.py              # interactive (Enter between steps)
    python demo/demo.py --auto       # no pauses
    python demo/demo.py --quick      # shorter windows, skip PDF
    make demo

Fetches station TLEs automatically if the index is empty (network required).
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEMO_OUT = ROOT / "data" / "demo"


def _pause(auto: bool, msg: str = "Press Enter for next step…") -> None:
    if auto:
        return
    try:
        input(f"\n  {msg} ")
    except EOFError:
        pass


def _banner(console, step: int, total: int, title: str) -> None:
    from rich.panel import Panel

    console.print()
    console.print(
        Panel(
            f"[bold]Step {step}/{total}[/bold]  ·  {title}",
            style="bold cyan",
            expand=False,
        )
    )


def _ensure_catalogs(console, *, auto: bool) -> Any:
    from services.object_index import get_index, invalidate_index
    from core.tle_fetcher import ensure_tles

    idx = get_index(force=True)
    stats = idx.stats()
    if stats["objects"] > 0 and "stations" in (stats.get("groups_loaded") or []):
        console.print(
            f"[green]✓[/green] Object index ready: "
            f"[bold]{stats['objects']}[/bold] objects · "
            f"{', '.join(stats['groups_loaded'])}"
        )
        return idx

    console.print(
        "[yellow]Catalogs missing or empty — fetching stations from CelesTrak…[/yellow]"
    )
    try:
        ensure_tles("stations", refresh=False)
        invalidate_index()
        idx = get_index(force=True)
    except Exception as exc:
        console.print(f"[red]Could not fetch TLEs:[/red] {exc}")
        console.print(
            "  Fix: [cyan]python main.py fetch --group stations[/cyan] "
            "then re-run this demo."
        )
        raise SystemExit(1) from exc

    # Optional starlink (nice for watchlist) — non-fatal
    try:
        from config import DATA_DIR

        if not (DATA_DIR / "starlink_tles.txt").exists():
            console.print("[dim]Fetching Starlink sample catalog (optional)…[/dim]")
            ensure_tles("starlink", refresh=False)
            invalidate_index()
            idx = get_index(force=True)
    except Exception as exc:
        console.print(f"[dim]Starlink fetch skipped: {exc}[/dim]")

    stats = idx.stats()
    console.print(
        f"[green]✓[/green] Index built: [bold]{stats['objects']}[/bold] objects"
    )
    return idx


def step_search(console, idx) -> None:
    _banner(console, 1, 5, "Object Index — search any catalog object")
    from rich.table import Table

    queries = ["ISS", "25544", "STARLINK", "HST"]
    for q in queries:
        hits = idx.search(q, limit=3)
        table = Table(title=f"Search: {q!r}", show_header=True, header_style="bold")
        table.add_column("Name", style="cyan")
        table.add_column("NORAD")
        table.add_column("Groups")
        for h in hits:
            table.add_row(h.name, str(h.norad), ",".join(sorted(h.groups))[:40])
        if not hits:
            table.add_row("(no hits)", "—", "—")
        console.print(table)

    rec = idx.resolve("ISS")
    if rec:
        console.print(
            f"\n[bold green]Resolved ISS →[/bold green] {rec.name}  "
            f"NORAD {rec.norad}  groups={sorted(rec.groups)}"
        )
    console.print(
        "[dim]Tip: python main.py search --search ISS · "
        "API GET /objects/search?q=ISS[/dim]"
    )


def step_passes(console, idx, observer, *, hours: float = 72) -> list:
    _banner(console, 2, 5, "Pass quality — will I see it, and how good is the pass?")
    from rich.table import Table
    from core.predictor import predict_passes, format_pass_row
    from services.pass_quality import score_passes, format_quality_breakdown

    rec = idx.resolve("ISS")
    sat = idx.get_satellite(rec) if rec else None
    if sat is None:
        console.print("[red]ISS not in index.[/red]")
        return []

    console.print(
        f"Predicting [bold]{sat.name}[/bold] from "
        f"[cyan]{observer.get('name')}[/cyan] · next {hours:g}h "
        f"(geometric ranking for reliable demo)…"
    )
    t0 = time.perf_counter()
    raw = predict_passes(
        sat,
        location=observer,
        hours_ahead=hours,
        max_passes=40,
        stargazer=False,
        min_elevation=10.0,
    )
    scored = score_passes(
        raw,
        location=observer,
        sat=sat,
        object_name=sat.name,
        min_score=0,
        sort=True,
    )
    dt = time.perf_counter() - t0
    top = scored[:6]

    table = Table(
        title=f"Top quality-ranked passes · {len(scored)} total · {dt:.1f}s",
        show_lines=False,
    )
    table.add_column("#", style="dim")
    table.add_column("Grade", justify="center")
    table.add_column("Score", justify="right")
    table.add_column("Culmination (UTC)")
    table.add_column("Max El")
    table.add_column("Duration")
    table.add_column("Sky")

    for i, p in enumerate(top, 1):
        row = format_pass_row(p)
        q = p.get("quality") or {}
        grade = q.get("grade") or p.get("quality_grade") or "?"
        score = q.get("score") if q.get("score") is not None else p.get("quality_score")
        style = {
            "A": "bold green",
            "B": "green",
            "C": "yellow",
            "D": "red",
            "F": "dim red",
        }.get(str(grade), "white")
        table.add_row(
            str(i),
            f"[{style}]{grade}[/]",
            str(score),
            row["culmination"],
            row["max_el"],
            row["duration"],
            row["sky"],
        )
    console.print(table)

    if top:
        best = top[0].get("quality") or {}
        console.print(
            f"\n[bold]Best pass:[/bold] {best.get('grade')} {best.get('score')} — "
            f"{format_quality_breakdown(best)}"
        )
    console.print(
        "[dim]Tip: python main.py passes --name ISS --hours 168 --sort quality "
        "--show_breakdown[/dim]"
    )
    return scored


def step_conjunction(console, idx, *, quick: bool) -> Optional[dict]:
    _banner(console, 3, 5, "Conjunction awareness — what else gets close?")
    from rich.table import Table

    groups = set(idx.stats().get("groups_loaded") or [])
    report = None

    # Prefer debris if cached; otherwise Starlink watchlist
    try:
        from services.debris import scan_primary_vs_debris, is_debris_group
        from config import DATA_DIR

        debris_ready = (DATA_DIR / "debris_tles.txt").exists() or "debris" in groups
        if debris_ready:
            console.print(
                "[bold]ISS vs debris sample[/bold] "
                f"({12 if quick else 24}h, sample {5 if quick else 12})…"
            )
            report = scan_primary_vs_debris(
                primary="ISS",
                debris_group="debris",
                hours=12 if quick else 24,
                sample=5 if quick else 12,
                index=idx,
            )
            label = "Debris"
        else:
            raise RuntimeError("no debris cache")
    except Exception:
        from services.watchlist import get_watchlist, scan_watchlist

        if "starlink" not in groups:
            console.print(
                "[yellow]No starlink/debris catalogs — skipping conjunction step.[/yellow]\n"
                "  Optional: [cyan]python main.py fetch --group starlink[/cyan] "
                "or [cyan]python main.py debris --cmd fetch[/cyan]"
            )
            return None
        w = get_watchlist("iss-starlink")
        if w is None:
            console.print("[yellow]Watchlist iss-starlink not found.[/yellow]")
            return None
        w.sample = 5 if quick else 12
        console.print(
            f"[bold]Watchlist iss-starlink[/bold] "
            f"({12 if quick else 24}h, sample {w.sample})…"
        )
        report = scan_watchlist(
            w,
            hours=12 if quick else 24,
            steps=100 if quick else 140,
            adaptive=True,
            progress_every=0,
            index=idx,
        )
        label = "Watchlist"

    summary = report.get("summary") or {}
    console.print(
        f"[green]✓[/green] {label} scan: "
        f"[bold]{report.get('pairs_scanned')}[/bold] pairs · "
        f"[red]HIGH {summary.get('HIGH')}[/red] · "
        f"[yellow]MEDIUM {summary.get('MEDIUM')}[/yellow] · "
        f"[green]LOW {summary.get('LOW')}[/green]"
    )
    if summary.get("closest_pair"):
        console.print(
            f"  Closest: [bold]{summary['closest_pair']}[/bold] · "
            f"[bold]{summary['closest_km']} km[/bold]"
        )

    results = (report.get("results") or [])[:8]
    if results:
        table = Table(title="Closest approaches", show_lines=False)
        table.add_column("#", style="dim")
        table.add_column("Object 1", style="cyan")
        table.add_column("Object 2", style="cyan")
        table.add_column("Min km", justify="right")
        table.add_column("Risk", justify="center")
        for i, r in enumerate(results, 1):
            risk = r.get("risk") or "LOW"
            rstyle = {"HIGH": "bold red", "MEDIUM": "yellow", "LOW": "green"}.get(
                risk, "white"
            )
            table.add_row(
                str(i),
                str(r.get("sat1"))[:22],
                str(r.get("sat2"))[:22],
                f"{r.get('min_dist_km')}",
                f"[{rstyle}]{risk}[/]",
            )
        console.print(table)

    console.print(
        "[dim]Tip: python main.py watchlist --cmd scan --wl iss-starlink --hours 48\n"
        "     python main.py debris --cmd scan --name ISS --group debris --hours 24[/dim]"
    )
    return report


def step_starmap(console, idx, observer, passes: list, *, hours: float = 4) -> Optional[Path]:
    _banner(console, 4, 5, "Starmap — sky track + ground track (linked views)")
    try:
        from services.sky import tracks_for_objects, ground_track_latlon
        from services.visualization import (
            build_linked_sky_figure,
            build_linked_ground_figure,
            attach_sky_meta_to_ground,
            pass_to_starmap_focus,
        )
    except Exception as exc:
        console.print(f"[yellow]Visualization deps unavailable: {exc}[/yellow]")
        return None

    rec = idx.resolve("ISS")
    sat = idx.get_satellite(rec) if rec else None
    if sat is None:
        return None

    focus = None
    scrub = 0.5
    if passes:
        focus = pass_to_starmap_focus(
            passes[0],
            object_name=rec.name if rec else sat.name.strip(),
            norad=rec.norad if rec else None,
        )
        scrub = min(float(focus.get("scrub_hours") or 0.5), hours - 0.05)
        hours = max(hours, min(6.0, float(focus.get("window_hours") or hours)))
        console.print(
            f"Focusing best pass: quality "
            f"[bold]{focus.get('quality_grade')} {focus.get('quality_score')}[/bold] · "
            f"scrub @ +{scrub:.2f}h"
        )
    else:
        console.print(f"Building {hours:g}h sky + ground tracks for ISS…")

    tracks = tracks_for_objects(
        [sat],
        location=observer,
        hours=hours,
        step_minutes=2.0,
        min_elevation=5.0,
    )
    gtracks = attach_sky_meta_to_ground(
        [ground_track_latlon(sat, hours=hours, step_minutes=2.0)],
        tracks,
    )
    fname = rec.name if rec else sat.name.strip()
    for tr in tracks:
        tr["name"] = fname
    for gt in gtracks:
        gt["name"] = fname

    sky = build_linked_sky_figure(
        tracks,
        scrub_hours=scrub,
        location_label=observer.get("name", ""),
        focus_name=fname,
        focus=focus,
        dim_others=False,
        height=520,
    )
    ground = build_linked_ground_figure(
        gtracks,
        location=observer,
        scrub_hours=scrub,
        focus_name=fname,
        focus=focus,
        dim_others=False,
        height=480,
    )

    DEMO_OUT.mkdir(parents=True, exist_ok=True)
    sky_path = DEMO_OUT / "demo_starmap_sky.html"
    gnd_path = DEMO_OUT / "demo_starmap_ground.html"
    sky.write_html(str(sky_path), include_plotlyjs="cdn", full_html=True)
    ground.write_html(str(gnd_path), include_plotlyjs="cdn", full_html=True)

    console.print(f"[green]✓[/green] Sky starmap:    [cyan]{sky_path}[/cyan]")
    console.print(f"[green]✓[/green] Ground track:   [cyan]{gnd_path}[/cyan]")
    console.print(
        "[dim]Open the HTML files in a browser, or run "
        "[cyan]python main.py dash[/cyan] for the interactive Starmap tab "
        "(jump from Passes, minute scrubber, play/pause).[/dim]"
    )
    return sky_path


def step_export(console, observer, passes: list, report: Optional[dict], *, skip_pdf: bool) -> None:
    _banner(console, 5, 5, "Export — ICS calendar + PDF report")
    from services.export import (
        passes_to_ics,
        write_ics,
        passes_to_pdf,
        write_pdf,
        watchlist_to_pdf,
    )

    DEMO_OUT.mkdir(parents=True, exist_ok=True)
    if not passes:
        console.print("[yellow]No passes to export.[/yellow]")
        return

    top = passes[:10]
    ics_path = DEMO_OUT / "demo_iss_passes.ics"
    write_ics(
        passes_to_ics(top, object_name="ISS", location=observer),
        ics_path,
    )
    console.print(f"[green]✓[/green] ICS calendar:  [cyan]{ics_path}[/cyan]")
    console.print("  → Import into Google Calendar / Apple Calendar / Outlook")

    if not skip_pdf:
        try:
            pdf_path = DEMO_OUT / "demo_iss_passes.pdf"
            write_pdf(
                passes_to_pdf(
                    top,
                    object_name="ISS",
                    location=observer,
                    stargazer=False,
                    hours=72,
                ),
                pdf_path,
            )
            console.print(f"[green]✓[/green] Pass PDF:      [cyan]{pdf_path}[/cyan]")
        except Exception as exc:
            console.print(f"[dim]PDF export skipped (install fpdf2): {exc}[/dim]")

        if report and report.get("results"):
            try:
                wl_pdf = DEMO_OUT / "demo_conjunction.pdf"
                write_pdf(watchlist_to_pdf(report), wl_pdf)
                console.print(f"[green]✓[/green] Conj PDF:      [cyan]{wl_pdf}[/cyan]")
            except Exception as exc:
                console.print(f"[dim]Watchlist PDF skipped: {exc}[/dim]")
    else:
        console.print("[dim]PDF skipped (--quick). Use full demo for PDF export.[/dim]")

    console.print(
        "[dim]Tip: python main.py export --cmd passes --name ISS "
        "--export_format ics --hours 72[/dim]"
    )


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="StarShield Lite guided demo")
    parser.add_argument(
        "--auto",
        action="store_true",
        help="Run without interactive pauses",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Shorter time windows; skip PDF for speed",
    )
    parser.add_argument(
        "--no-fetch",
        action="store_true",
        help="Do not auto-fetch TLEs if index is empty",
    )
    args = parser.parse_args(argv)

    from rich.console import Console
    from rich.panel import Panel
    from services.observers import format_observer, resolve_observer

    console = Console()
    auto = args.auto or args.quick

    console.print(
        Panel.fit(
            "[bold cyan]StarShield Lite[/bold cyan]  ·  v0.2.0\n"
            "[white]Guided demo[/white]\n\n"
            "Any object → will I see it, where in my sky,\n"
            "what else gets close, and tell me when it matters.",
            border_style="cyan",
        )
    )
    console.print(
        f"[dim]{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} · "
        f"mode={'quick/auto' if args.quick else ('auto' if args.auto else 'interactive')}[/dim]"
    )

    observer = resolve_observer(profile="Kingsland, GA")
    console.print(f"Observer: [bold]{format_observer(observer)}[/bold]")

    if args.no_fetch:
        from services.object_index import get_index

        idx = get_index(force=True)
        if idx.stats()["objects"] == 0:
            console.print("[red]Empty index and --no-fetch set.[/red]")
            return 1
    else:
        idx = _ensure_catalogs(console, auto=auto)

    _pause(auto)

    step_search(console, idx)
    _pause(auto)

    hours = 48 if args.quick else 72
    passes = step_passes(console, idx, observer, hours=hours)
    _pause(auto)

    report = step_conjunction(console, idx, quick=args.quick)
    _pause(auto)

    step_starmap(console, idx, observer, passes, hours=3 if args.quick else 5)
    _pause(auto)

    step_export(console, observer, passes, report, skip_pdf=args.quick)

    console.print()
    console.print(
        Panel(
            "[bold green]Demo complete.[/bold green]\n\n"
            "Next steps:\n"
            "  • [cyan]python main.py dash[/cyan]     Streamlit — Passes → Jump to Starmap\n"
            "  • [cyan]python main.py api[/cyan]      OpenAPI at http://127.0.0.1:8000/docs\n"
            "  • [cyan]python main.py tui[/cyan]      Terminal UI\n"
            "  • [cyan]docker compose --profile full up --build[/cyan]\n\n"
            f"Artifacts: [cyan]{DEMO_OUT}[/cyan]\n"
            "Guide:     [cyan]demo/demo.md[/cyan]",
            title="Done",
            border_style="green",
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
