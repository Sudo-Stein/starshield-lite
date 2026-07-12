#!/usr/bin/env python3
"""Example: predict ISS passes and export ICS / PDF from Python (no CLI).

Prerequisites::

    pip install -e ".[pdf,dev]"   # pdf extra optional but recommended
    python main.py fetch --group stations

Usage::

    python examples/programmatic_export.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT = ROOT / "data" / "examples"


def main() -> int:
    from core.predictor import predict_passes
    from services.export import (
        passes_to_ics,
        passes_to_pdf,
        write_ics,
        write_pdf,
    )
    from services.object_index import get_index
    from services.observers import format_observer, resolve_observer
    from services.pass_quality import score_passes

    OUT.mkdir(parents=True, exist_ok=True)
    observer = resolve_observer(profile="Kingsland, GA")
    print("Observer:", format_observer(observer))

    idx = get_index()
    rec = idx.resolve("ISS")
    sat = idx.get_satellite(rec) if rec else None
    if sat is None:
        print(
            "ISS not in index. Fetch catalogs first:\n"
            "  python main.py fetch --group stations",
            file=sys.stderr,
        )
        return 1

    print(f"Predicting passes for {sat.name} (72h, geometric)…")
    raw = predict_passes(
        sat,
        location=observer,
        hours_ahead=72,
        max_passes=30,
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
    )[:10]
    print(f"Using top {len(scored)} quality-ranked passes")

    # ICS calendar
    ics_path = OUT / "iss_passes.ics"
    write_ics(
        passes_to_ics(scored, object_name=sat.name.strip(), location=observer),
        ics_path,
    )
    print(f"Wrote ICS → {ics_path}")

    # PDF (optional dependency fpdf2)
    try:
        pdf_path = OUT / "iss_passes.pdf"
        write_pdf(
            passes_to_pdf(
                scored,
                object_name=sat.name.strip(),
                location=observer,
                stargazer=False,
                hours=72,
            ),
            pdf_path,
        )
        print(f"Wrote PDF → {pdf_path}")
    except Exception as exc:
        print(f"PDF skipped (install with: pip install -e '.[pdf]'): {exc}")

    if scored:
        q = scored[0].get("quality") or {}
        print(
            f"\nBest pass: grade {q.get('grade')} score {q.get('score')} · "
            f"max el {scored[0].get('max_elevation')}°"
        )
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
