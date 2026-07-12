"""Optional space-debris catalog helpers.

Debris is **not** required for core StarShield features. Fetch one or more
CelesTrak debris groups, they join the Object Index automatically (when
cached), and use watchlists such as ``iss-debris`` for conjunction awareness.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from config import (
    DATA_DIR,
    DEBRIS_GROUPS,
    TLE_URLS,
    WATCHLIST_DEBRIS_SAMPLE,
    effective_index_groups,
)
from core.tle_fetcher import fetch_tles
from services.object_index import get_index, invalidate_index
from services.watchlist import (
    Watchlist,
    get_watchlist,
    scan_watchlist,
    upsert_watchlist,
)

# Human-readable labels for CLI / API
DEBRIS_GROUP_INFO: Dict[str, str] = {
    "debris": "Cosmos-2251 debris (short alias)",
    "cosmos-2251-debris": "Cosmos-2251 / Iridium-33 collision fragments",
    "fengyun-1c-debris": "Fengyun-1C ASAT debris cloud",
    "iridium-33-debris": "Iridium-33 collision fragments",
}


def is_debris_group(group: str) -> bool:
    return (group or "").strip().lower() in {g.lower() for g in DEBRIS_GROUPS}


def list_debris_groups() -> List[dict]:
    """Status of each known debris TLE group (cached object counts)."""
    rows = []
    for g in DEBRIS_GROUPS:
        path = DATA_DIR / f"{g}_tles.txt"
        n_obj = 0
        size = 0
        if path.exists():
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
                n_obj = len([ln for ln in text.splitlines() if ln.strip()]) // 3
                size = path.stat().st_size
            except OSError:
                pass
        rows.append(
            {
                "group": g,
                "description": DEBRIS_GROUP_INFO.get(g, g),
                "url": TLE_URLS.get(g),
                "cached": path.exists(),
                "path": str(path) if path.exists() else None,
                "objects_approx": n_obj,
                "bytes": size,
                "in_index": g in effective_index_groups() and path.exists(),
            }
        )
    return rows


def fetch_debris(
    group: str = "debris",
    *,
    force: bool = True,
    refresh_index: bool = True,
) -> Path:
    """Download a debris TLE group and optionally rebuild the object index."""
    group = (group or "debris").strip()
    if group not in TLE_URLS:
        raise ValueError(
            f"Unknown group '{group}'. Choose from: {', '.join(DEBRIS_GROUPS)}"
        )
    if not is_debris_group(group) and group not in DEBRIS_GROUPS:
        # Allow any TLE_URLS key for flexibility, but prefer debris groups
        pass
    path = fetch_tles(group, force=force, use_cache_on_error=True)
    if refresh_index:
        invalidate_index()
        get_index(force=True)
    return path


def debris_index_stats() -> Dict[str, Any]:
    """Snapshot of debris presence in the current object index."""
    idx = get_index()
    st = idx.stats()
    groups = list_debris_groups()
    return {
        "index_objects": st.get("objects"),
        "debris_objects": st.get("debris_objects"),
        "debris_groups_loaded": st.get("debris_groups_loaded") or [],
        "groups_loaded": st.get("groups_loaded") or [],
        "catalogs": groups,
    }


def ensure_debris_watchlists() -> List[str]:
    """Ensure default debris watchlists exist in the store; return their ids."""
    created = []
    for wl in default_debris_watchlists():
        existing = get_watchlist(wl.id)
        if existing is None:
            upsert_watchlist(wl)
            created.append(wl.id)
    return created


def default_debris_watchlists() -> List[Watchlist]:
    """Built-in debris-focused watchlist definitions."""
    sample = int(WATCHLIST_DEBRIS_SAMPLE)
    return [
        Watchlist(
            id="iss-debris",
            name="ISS vs debris (Cosmos-2251 sample)",
            description=(
                "ISS against a smart sample of Cosmos-2251 debris "
                "(fetch group 'debris' first)"
            ),
            mode="primary_vs_group",
            primary="ISS",
            group="debris",
            sample=sample,
            sample_strategy="even",
        ),
        Watchlist(
            id="iss-fengyun-debris",
            name="ISS vs Fengyun-1C debris",
            description="ISS against a sample of Fengyun-1C ASAT debris",
            mode="primary_vs_group",
            primary="ISS",
            group="fengyun-1c-debris",
            sample=sample,
            sample_strategy="even",
        ),
        Watchlist(
            id="iss-iridium-debris",
            name="ISS vs Iridium-33 debris",
            description="ISS against a sample of Iridium-33 collision fragments",
            mode="primary_vs_group",
            primary="ISS",
            group="iridium-33-debris",
            sample=sample,
            sample_strategy="even",
        ),
        Watchlist(
            id="stations-debris",
            name="Stations vs debris sample",
            description="Space stations catalog vs Cosmos-2251 debris sample",
            mode="group_vs_group",
            group1="stations",
            group2="debris",
            primary_limit=3,
            sample=min(25, sample),
            sample_strategy="even",
        ),
    ]


def scan_primary_vs_debris(
    *,
    primary: str = "ISS",
    debris_group: str = "debris",
    hours: float = 24,
    sample: int = WATCHLIST_DEBRIS_SAMPLE,
    threshold_km: float = 50.0,
    high_risk_km: float = 10.0,
    only_below: bool = False,
    index=None,
) -> Dict[str, Any]:
    """One-shot primary-vs-debris conjunction scan (does not require a saved WL)."""
    from config import CONJ_HIGH_RISK_KM, CONJ_THRESHOLD_KM

    wl = Watchlist(
        id=f"adhoc-{primary}-vs-{debris_group}",
        name=f"{primary} vs {debris_group}",
        description="Ad-hoc debris conjunction scan",
        mode="primary_vs_group",
        primary=primary,
        group=debris_group,
        sample=int(sample),
        sample_strategy="even",
    )
    return scan_watchlist(
        wl,
        hours=hours,
        threshold_km=threshold_km or CONJ_THRESHOLD_KM,
        high_risk_km=high_risk_km or CONJ_HIGH_RISK_KM,
        only_below=only_below,
        adaptive=True,
        steps=160,
        progress_every=0,
        index=index or get_index(),
    )
