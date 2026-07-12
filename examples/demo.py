#!/usr/bin/env python3
"""Thin wrapper that runs the guided demo (``demo/demo.py``).

Prefer calling the demo directly, or use Make::

    make demo
    make demo-auto
    python demo/demo.py --auto

This file exists so ``python examples/demo.py`` also works from the examples
folder index.

Usage::

    python examples/demo.py
    python examples/demo.py --auto
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Ensure demo package path works when run as a script
sys.path.insert(0, str(ROOT / "demo"))


def main() -> int:
    # Import as a module file
    import importlib.util

    path = ROOT / "demo" / "demo.py"
    spec = importlib.util.spec_from_file_location("starshield_demo", path)
    if spec is None or spec.loader is None:
        print("Could not load demo/demo.py", file=sys.stderr)
        return 1
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return int(mod.main())


if __name__ == "__main__":
    raise SystemExit(main())
