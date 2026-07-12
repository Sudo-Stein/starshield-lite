#!/usr/bin/env python3
"""Minimal end-to-end workflow (passes + ICS).

Prefer the full guided showcase:

    python demo/demo.py
    make demo

This script remains as a short non-interactive smoke path.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running without install
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    from services.object_index import get_index
    from services.observers import format_observer, resolve_observer
    from services.pass_quality import score_passes
    from services.export import passes_to_ics, write_ics
    from core.predictor import predict_passes
    from config import DATA_DIR

    console = Console()
    console.print(Panel("StarShield Lite — demo workflow", style="bold cyan"))

    observer = resolve_observer(profile="Kingsland, GA")
    console.print(f"Observer: {format_observer(observer)}")

    idx = get_index()
    stats = idx.stats()
    console.print(
        f"Object index: {stats['objects']} objects · "
        f"groups={', '.join(stats['groups_loaded']) or 'none'}"
    )
    if stats["objects"] == 0:
        console.print(
            "[yellow]Index empty. Fetch TLEs first:[/yellow]\n"
            "  python main.py fetch --group stations"
        )
        return 1

    rec = idx.resolve("ISS")
    sat = idx.get_satellite(rec) if rec else None
    if sat is None:
        console.print("[red]ISS not found in index.[/red]")
        return 1

    console.print(f"\n[bold]Predicting passes for {sat.name}…[/bold]")
    raw = predict_passes(
        sat,
        location=observer,
        hours_ahead=72,
        max_passes=30,
        stargazer=False,
    )
    scored = score_passes(
        raw,
        location=observer,
        sat=sat,
        object_name=sat.name,
        min_score=0,
        sort=True,
    )[:5]

    table = Table(title="Top 5 quality-ranked passes (72h, geometric)")
    table.add_column("Q")
    table.add_column("Culm UTC")
    table.add_column("Max el")
    table.add_column("Sky")
    for p in scored:
        culm = (p.get("culmination") or {}).get("time")
        culm_s = culm.strftime("%Y-%m-%d %H:%M") if culm else "—"
        table.add_row(
            f"{p.get('quality_grade')} {p.get('quality_score')}",
            culm_s,
            f"{p.get('max_elevation', 0):.1f}°",
            "visible" if p.get("visible") else ("day" if p.get("sunlit") else "shadow"),
        )
    console.print(table)

    out = DATA_DIR / "demo_workflow_passes.ics"
    write_ics(
        passes_to_ics(scored, object_name=sat.name.strip(), location=observer),
        out,
    )
    console.print(f"\n[green]Wrote sample ICS:[/green] {out}")

    # Optional mini watchlist
    try:
        from services.watchlist import get_watchlist, scan_watchlist

        w = get_watchlist("iss-starlink")
        if w and "starlink" in stats["groups_loaded"]:
            w.sample = 5
            console.print("\n[bold]Mini watchlist scan (5 Starlinks, 12h)…[/bold]")
            report = scan_watchlist(
                w, hours=12, steps=80, adaptive=True, progress_every=0, index=idx
            )
            s = report["summary"]
            console.print(
                f"Closest: {s.get('closest_pair')} · {s.get('closest_km')} km · "
                f"H/M/L={s.get('HIGH')}/{s.get('MEDIUM')}/{s.get('LOW')}"
            )
    except Exception as exc:
        console.print(f"[dim]Watchlist demo skipped: {exc}[/dim]")

    console.print(
        "\n[dim]Next: python main.py dash · python main.py api · "
        "docker compose up --build[/dim]"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
