from datetime import timedelta
from pathlib import Path

from skyfield.api import load, wgs84

from config import LOCATION


def load_satellites(tle_file):
    """Load satellites from a local TLE file.

    Returns (satellites, timescale).
    """
    ts = load.timescale()
    path = Path(tle_file)
    satellites = load.tle_file(str(path), reload=True)
    return satellites, ts


def propagate(sat, hours: float = 24, step_minutes: float = 5):
    """Propagate a satellite over `hours` at `step_minutes` resolution.

    Returns (times, positions) where positions is a Skyfield ICRF
    Geocentric object (use .subpoint() for lat/lon/alt).
    """
    ts = load.timescale()
    t0 = ts.now()
    n_steps = int((hours * 60) / step_minutes) + 1
    times = ts.utc(
        [
            (t0.utc_datetime() + timedelta(minutes=step_minutes * i))
            for i in range(n_steps)
        ]
    )
    positions = sat.at(times)
    return times, positions


def observer_location():
    """Return a WGS84 GeographicPosition for the configured observer."""
    return wgs84.latlon(
        LOCATION["lat"],
        LOCATION["lon"],
        elevation_m=LOCATION["elevation"],
    )
