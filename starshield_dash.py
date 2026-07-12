"""Launcher for ``starshield-dash`` console script."""
import subprocess
import sys
from pathlib import Path


def main():
    dash = Path(__file__).resolve().parent / "dashboard.py"
    raise SystemExit(
        subprocess.call(
            [
                sys.executable,
                "-m",
                "streamlit",
                "run",
                str(dash),
                "--browser.gatherUsageStats=false",
            ]
        )
    )


if __name__ == "__main__":
    main()
