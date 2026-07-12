#!/usr/bin/env python3
"""Register a custom conjunction watchlist and run a short scan.

Use this when you want to define primary-vs-group (or similar) monitoring in
code rather than editing JSON by hand. Watchlists persist in
``data/watchlists.json`` (auto-created).

This script upserts an example ``example-iss-visual`` list if missing, then
scans a small sample for the next few hours.

Prerequisites::

    pip install -e ".[dev]"
    python main.py fetch --group stations
    python main.py fetch --group visual   # or starlink if visual is empty

Usage::

    python examples/custom_watchlist.py
    python examples/custom_watchlist.py --scan-only   # use existing list only
    python examples/custom_watchlist.py --hours 24 --sample 10
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description="Custom watchlist example")
    parser.add_argument(
        "--scan-only",
        action="store_true",
        help="Do not create; only scan if the watchlist already exists",
    )
    parser.add_argument("--hours", type=float, default=12.0)
    parser.add_argument("--sample", type=int, default=5)
    args = parser.parse_args()

    from services.object_index import get_index
    from services.watchlist import (
        Watchlist,
        get_watchlist,
        list_watchlists,
        scan_watchlist,
        upsert_watchlist,
    )

    wl_id = "example-iss-visual"

    if not args.scan_only:
        existing = get_watchlist(wl_id)
        if existing is None:
            wl = Watchlist(
                id=wl_id,
                name="Example: ISS vs visual sats",
                description="Demo watchlist created by examples/custom_watchlist.py",
                mode="primary_vs_group",
                primary="ISS",
                group="visual",  # falls back poorly if empty — try starlink
                sample=args.sample,
                sample_strategy="even",
            )
            # Prefer a group that is actually loaded
            idx = get_index()
            loaded = set(idx.stats().get("groups_loaded") or [])
            if "visual" not in loaded and "starlink" in loaded:
                wl.group = "starlink"
                wl.name = "Example: ISS vs Starlink sample"
                wl.description += " (used starlink because visual not cached)"
            elif "visual" not in loaded and "starlink" not in loaded:
                print(
                    "Need a secondary catalog. Fetch one of:\n"
                    "  python main.py fetch --group visual\n"
                    "  python main.py fetch --group starlink"
                )
                return 1
            upsert_watchlist(wl)
            print(f"Created watchlist: {wl.id}  (group={wl.group}, sample={wl.sample})")
        else:
            print(f"Watchlist already exists: {wl_id}")

    # List all watchlists
    print("\nConfigured watchlists:")
    for w in list_watchlists():
        mark = " ←" if w.id == wl_id else ""
        print(f"  · {w.id:28} {w.mode:18} {w.name}{mark}")

    wl = get_watchlist(wl_id)
    if wl is None:
        print(f"Watchlist {wl_id} not found.", file=sys.stderr)
        return 1

    wl.sample = args.sample
    print(f"\nScanning {wl.id} · {args.hours:g}h · sample {wl.sample}…")
    idx = get_index()
    report = scan_watchlist(
        wl,
        hours=args.hours,
        steps=100,
        adaptive=True,
        progress_every=0,
        index=idx,
    )
    s = report.get("summary") or {}
    print(
        f"Pairs: {report.get('pairs_scanned')} · "
        f"HIGH={s.get('HIGH')} MEDIUM={s.get('MEDIUM')} LOW={s.get('LOW')}"
    )
    if s.get("closest_pair"):
        print(f"Closest: {s['closest_pair']} · {s['closest_km']} km")

    print(
        "\nTip: re-run later with --scan-only, or edit data/watchlists.json.\n"
        "CLI:  python main.py watchlist --cmd scan --wl "
        f"{wl_id} --hours {args.hours:g}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
