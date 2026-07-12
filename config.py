import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Package / API version (keep in sync with pyproject.toml + setup.cfg)
__version__ = "0.2.0"

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

# Public TLE sources (CelesTrak GP)
# Debris catalogs are optional — fetch only when you want conjunction awareness.
_CELESTRAK = "https://celestrak.org/NORAD/elements/gp.php"
TLE_URLS = {
    "starlink": f"{_CELESTRAK}?GROUP=starlink&FORMAT=tle",
    "active": f"{_CELESTRAK}?GROUP=active&FORMAT=tle",
    "stations": f"{_CELESTRAK}?GROUP=stations&FORMAT=tle",
    "visual": f"{_CELESTRAK}?GROUP=visual&FORMAT=tle",
    # Debris (short alias "debris" = Cosmos-2251 / Iridium-33 era fragment set)
    "debris": f"{_CELESTRAK}?GROUP=cosmos-2251-debris&FORMAT=tle",
    "cosmos-2251-debris": f"{_CELESTRAK}?GROUP=cosmos-2251-debris&FORMAT=tle",
    "fengyun-1c-debris": f"{_CELESTRAK}?GROUP=fengyun-1c-debris&FORMAT=tle",
    "iridium-33-debris": f"{_CELESTRAK}?GROUP=iridium-33-debris&FORMAT=tle",
}

# Groups treated as debris for index tags, CLI, and API
DEBRIS_GROUPS = (
    "debris",
    "cosmos-2251-debris",
    "fengyun-1c-debris",
    "iridium-33-debris",
)
# auto = include debris in Object Index when a cache file exists
# 1/true = always attempt debris groups · 0/false = never index debris
_INDEX_DEBRIS_MODE = os.getenv("STARSHIELD_INDEX_DEBRIS", "auto").strip().lower()

# Observer site — Kingsland, GA (approx) — default home
LOCATION = {"lat": 30.8, "lon": -81.65, "elevation": 5.0}

# Named observer profiles (lat/lon in degrees, elevation in meters)
OBSERVER_PROFILES = {
    "Kingsland, GA": {
        "name": "Kingsland, GA",
        "lat": 30.8,
        "lon": -81.65,
        "elevation": 5.0,
        "note": "Home default",
    },
    "Amelia Island, FL": {
        "name": "Amelia Island, FL",
        "lat": 30.67,
        "lon": -81.46,
        "elevation": 3.0,
        "note": "Coastal / nearby",
    },
    "Cherry Springs, PA": {
        "name": "Cherry Springs, PA",
        "lat": 41.66,
        "lon": -77.82,
        "elevation": 700.0,
        "note": "Dark-sky park example",
    },
    "Goldendale, WA": {
        "name": "Goldendale, WA",
        "lat": 45.82,
        "lon": -120.82,
        "elevation": 500.0,
        "note": "Dark-sky / observatory country",
    },
}
DEFAULT_OBSERVER = "Kingsland, GA"

# Core groups always considered for the multi-catalog object index.
# Debris is merged via effective_index_groups() when caches exist (optional).
INDEX_GROUPS = ["stations", "starlink", "visual", "active"]


def effective_index_groups() -> list:
    """Return index groups: core + optional debris (if cached / forced).

    Debris is **optional**. Default ``STARSHIELD_INDEX_DEBRIS=auto`` includes a
    debris group only when ``data/{group}_tles.txt`` exists. Set to ``0`` to
    exclude debris even if cached; set to ``1`` to always list debris groups
    (empty until fetched).
    """
    groups = list(INDEX_GROUPS)
    mode = _INDEX_DEBRIS_MODE
    force_on = mode in ("1", "true", "yes", "on", "always")
    force_off = mode in ("0", "false", "no", "off", "never")
    if force_off:
        return groups
    for g in DEBRIS_GROUPS:
        if g in groups:
            continue
        cache = DATA_DIR / f"{g}_tles.txt"
        if force_on or cache.exists():
            groups.append(g)
    return groups

# Pass prediction defaults
PASS_HOURS_AHEAD = 24
PASS_MIN_ELEVATION = 10.0  # degrees above horizon

# Stargazer mode (naked-eye visibility)
# Sun altitude at observer must be ≤ this (°) for "dark enough" sky.
#   -6°  = end of civil twilight (good for bright ISS / trains)
#  -12°  = nautical twilight
#  -18°  = astronomical night
STARGAZER_DEFAULT = True
STARGAZER_SUN_ALT_MAX = -6.0

# Conjunction simulation defaults
CONJ_THRESHOLD_KM = 50.0       # MEDIUM risk if below this
CONJ_HIGH_RISK_KM = 10.0       # HIGH risk if below this
CONJ_STEPS_DEFAULT = 300       # ~ time samples over the window
CONJ_STEPS_COARSE = 180        # adaptive coarse grid
CONJ_REFINE_WINDOW_MIN = 40    # minutes each side of coarse TCA for fine grid
CONJ_STEPS_FINE = 240          # fine samples inside refine window
CONJ_MAX_PAIRS = 80            # group-vs-group pair cap (performance)
CONJ_REPORT_FILE = "conjunction_report.html"

# Watchlist defaults
WATCHLIST_FILE = DATA_DIR / "watchlists.json"
WATCHLIST_DEFAULT_ID = "iss-starlink"
WATCHLIST_STARLINK_SAMPLE = 40  # smart sample size for ISS vs Starlink
WATCHLIST_DEBRIS_SAMPLE = 40  # sample size for ISS vs debris catalogs

# SQLite persistence
DB_PATH = DATA_DIR / "starshield.db"
DB_LOG_ENABLED = os.getenv("STARSHIELD_DB_LOG", "1") not in ("0", "false", "False")
DB_LOG_PASS_MIN_SCORE = 70          # Grade B or better
DB_LOG_CONJ_RISKS = ("HIGH", "MEDIUM")  # skip routine LOW unless forced

# FastAPI
API_HOST = os.getenv("STARSHIELD_API_HOST", "127.0.0.1")
API_PORT = int(os.getenv("STARSHIELD_API_PORT", "8000"))
# Streamlit: when True, call HTTP API instead of services directly (if reachable)
STREAMLIT_USE_API = os.getenv("STARSHIELD_USE_API", "0") not in ("0", "false", "False")
API_BASE_URL = os.getenv("STARSHIELD_API_URL", f"http://{API_HOST}:{API_PORT}")

# API key authentication (header: X-API-Key)
# Off by default so local demos work without setup.
API_KEY_REQUIRED = os.getenv("STARSHIELD_API_KEY_REQUIRED", "0") not in (
    "0",
    "false",
    "False",
    "",
)
# Comma-separated keys and/or path to a newline-delimited key file
_API_KEYS_RAW = os.getenv("STARSHIELD_API_KEYS", "")
API_KEYS_FILE = Path(
    os.getenv("STARSHIELD_API_KEYS_FILE", str(DATA_DIR / "api_keys.txt"))
)


def _parse_api_keys() -> tuple:
    keys = set()
    if _API_KEYS_RAW.strip():
        for part in _API_KEYS_RAW.replace(";", ",").split(","):
            k = part.strip()
            if k:
                keys.add(k)
    try:
        if API_KEYS_FILE.exists():
            for line in API_KEYS_FILE.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    keys.add(line)
    except OSError:
        pass
    return tuple(sorted(keys))


API_KEYS = _parse_api_keys()

# Rate limiting (in-memory sliding window) — requests per client IP
# Disable with STARSHIELD_API_RATE_LIMIT=0
API_RATE_LIMIT_ENABLED = os.getenv("STARSHIELD_API_RATE_LIMIT", "1") not in (
    "0",
    "false",
    "False",
)
# Limit strings: "N/minute", "N/hour", "N/second", "N/day"
API_RATE_LIMIT_DEFAULT = os.getenv("STARSHIELD_API_RATE_LIMIT_DEFAULT", "60/minute")
API_RATE_LIMIT_HEAVY = os.getenv("STARSHIELD_API_RATE_LIMIT_HEAVY", "20/minute")
API_RATE_LIMIT_PUBLIC = os.getenv("STARSHIELD_API_RATE_LIMIT_PUBLIC", "120/minute")

# Background scheduler (watchlist scans)
SCHEDULE_ENABLED = os.getenv("STARSHIELD_SCHEDULE_ENABLED", "1") not in (
    "0",
    "false",
    "False",
)
SCHEDULE_FILE = DATA_DIR / "schedules.json"
SCHEDULE_JOBS_DEFAULT = [
    {
        "id": "iss-starlink-12h",
        "name": "ISS vs Starlink (every 12h)",
        "enabled": True,
        "watchlist_id": "iss-starlink",
        "interval_hours": 12,
        "hours": 48,
        "sample": 30,
        "threshold_km": 50,
        "only_below": False,
        "refresh_tles": False,
    },
    # Debris scan is opt-in (disabled until user fetches debris TLEs)
    {
        "id": "iss-debris-24h",
        "name": "ISS vs debris sample (every 24h)",
        "enabled": False,
        "watchlist_id": "iss-debris",
        "interval_hours": 24,
        "hours": 24,
        "sample": 30,
        "threshold_km": 50,
        "only_below": False,
        "refresh_tles": False,
        "refresh_groups": ["debris"],
    },
]

# ---------------------------------------------------------------------------
# Notifications / webhooks (optional)
# ---------------------------------------------------------------------------
# Global switch (also controlled by data/notifications.json "enabled")
NOTIFY_ENABLED = os.getenv("STARSHIELD_NOTIFY_ENABLED", "1") not in (
    "0",
    "false",
    "False",
    "",
)
NOTIFY_CONFIG_FILE = Path(
    os.getenv("STARSHIELD_NOTIFY_FILE", str(DATA_DIR / "notifications.json"))
)
# Quick single/multi URL setup without editing JSON (comma-separated)
_NOTIFY_URLS_RAW = os.getenv("STARSHIELD_WEBHOOK_URL", "") or os.getenv(
    "STARSHIELD_WEBHOOK_URLS", ""
)
NOTIFY_WEBHOOK_URLS = tuple(
    u.strip()
    for u in _NOTIFY_URLS_RAW.replace(";", ",").split(",")
    if u.strip()
)
# Event filters (overridden by notifications.json when present)
NOTIFY_PASS_MIN_SCORE = float(os.getenv("STARSHIELD_NOTIFY_PASS_MIN_SCORE", "70"))
NOTIFY_PASS_MIN_GRADE = os.getenv("STARSHIELD_NOTIFY_PASS_MIN_GRADE", "B").upper()
_NOTIFY_CONJ = os.getenv("STARSHIELD_NOTIFY_CONJ_RISKS", "HIGH,MEDIUM")
NOTIFY_CONJ_RISKS = tuple(
    r.strip().upper() for r in _NOTIFY_CONJ.split(",") if r.strip()
) or ("HIGH", "MEDIUM")
# HTTP POST timeout seconds
NOTIFY_TIMEOUT_SEC = float(os.getenv("STARSHIELD_NOTIFY_TIMEOUT", "8"))
# Fire-and-forget by default (background thread)
NOTIFY_ASYNC = os.getenv("STARSHIELD_NOTIFY_ASYNC", "1") not in (
    "0",
    "false",
    "False",
)

