"""Conjunction watchlists — proactive monitoring of object pairs / groups.

Watchlists are stored as JSON under data/watchlists.json.
"""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from skyfield.api import EarthSatellite

from config import (
    CONJ_HIGH_RISK_KM,
    CONJ_THRESHOLD_KM,
    DATA_DIR,
    WATCHLIST_DEFAULT_ID,
    WATCHLIST_DEBRIS_SAMPLE,
    WATCHLIST_FILE,
    WATCHLIST_STARLINK_SAMPLE,
)
from core.simulator import check_conjunction
from services.object_index import ObjectIndex, get_index

DEFAULT_WATCHLISTS: Dict[str, dict] = {
    "iss-starlink": {
        "id": "iss-starlink",
        "name": "ISS vs Starlink",
        "description": "ISS (ZARYA) against a smart sample of Starlink satellites",
        "mode": "primary_vs_group",
        "primary": "ISS",
        "group": "starlink",
        "sample": WATCHLIST_STARLINK_SAMPLE,
        "sample_strategy": "even",  # even spacing through catalog
    },
    "stations-starlink": {
        "id": "stations-starlink",
        "name": "Stations vs Starlink (sample)",
        "description": "Space stations catalog vs Starlink sample",
        "mode": "group_vs_group",
        "group1": "stations",
        "group2": "starlink",
        "primary_limit": 3,
        "sample": 25,
        "sample_strategy": "even",
    },
    "iss-visual": {
        "id": "iss-visual",
        "name": "ISS vs bright visual sats",
        "description": "ISS against CelesTrak visual group (when cached)",
        "mode": "primary_vs_group",
        "primary": "ISS",
        "group": "visual",
        "sample": 30,
        "sample_strategy": "even",
    },
    # Debris watchlists (require fetching a debris TLE group first)
    "iss-debris": {
        "id": "iss-debris",
        "name": "ISS vs debris (Cosmos-2251 sample)",
        "description": (
            "ISS against a smart sample of Cosmos-2251 debris "
            "(python main.py debris --cmd fetch --group debris)"
        ),
        "mode": "primary_vs_group",
        "primary": "ISS",
        "group": "debris",
        "sample": WATCHLIST_DEBRIS_SAMPLE,
        "sample_strategy": "even",
    },
    "iss-fengyun-debris": {
        "id": "iss-fengyun-debris",
        "name": "ISS vs Fengyun-1C debris",
        "description": "ISS against a sample of Fengyun-1C ASAT debris",
        "mode": "primary_vs_group",
        "primary": "ISS",
        "group": "fengyun-1c-debris",
        "sample": WATCHLIST_DEBRIS_SAMPLE,
        "sample_strategy": "even",
    },
    "iss-iridium-debris": {
        "id": "iss-iridium-debris",
        "name": "ISS vs Iridium-33 debris",
        "description": "ISS against a sample of Iridium-33 collision fragments",
        "mode": "primary_vs_group",
        "primary": "ISS",
        "group": "iridium-33-debris",
        "sample": WATCHLIST_DEBRIS_SAMPLE,
        "sample_strategy": "even",
    },
    "stations-debris": {
        "id": "stations-debris",
        "name": "Stations vs debris sample",
        "description": "Space stations catalog vs Cosmos-2251 debris sample",
        "mode": "group_vs_group",
        "group1": "stations",
        "group2": "debris",
        "primary_limit": 3,
        "sample": 25,
        "sample_strategy": "even",
    },
}


@dataclass
class Watchlist:
    id: str
    name: str
    description: str = ""
    mode: str = "primary_vs_group"  # primary_vs_group | group_vs_group | pairs
    primary: str = ""
    group: str = ""
    group1: str = ""
    group2: str = ""
    pairs: List[List[str]] = field(default_factory=list)  # [[a,b], ...]
    sample: int = 40
    primary_limit: int = 5
    sample_strategy: str = "even"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "mode": self.mode,
            "primary": self.primary,
            "group": self.group,
            "group1": self.group1,
            "group2": self.group2,
            "pairs": self.pairs,
            "sample": self.sample,
            "primary_limit": self.primary_limit,
            "sample_strategy": self.sample_strategy,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Watchlist":
        return cls(
            id=d["id"],
            name=d.get("name", d["id"]),
            description=d.get("description", ""),
            mode=d.get("mode", "primary_vs_group"),
            primary=d.get("primary", ""),
            group=d.get("group", ""),
            group1=d.get("group1", ""),
            group2=d.get("group2", ""),
            pairs=d.get("pairs") or [],
            sample=int(d.get("sample", 40)),
            primary_limit=int(d.get("primary_limit", 5)),
            sample_strategy=d.get("sample_strategy", "even"),
        )


def _ensure_store(path: Path = WATCHLIST_FILE) -> dict:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        data = {"version": 1, "watchlists": deepcopy(DEFAULT_WATCHLISTS)}
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return data
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        data = {"version": 1, "watchlists": {}}
    # Merge missing defaults without overwriting user lists
    wls = data.setdefault("watchlists", {})
    for k, v in DEFAULT_WATCHLISTS.items():
        if k not in wls:
            wls[k] = deepcopy(v)
    return data


def save_store(data: dict, path: Path = WATCHLIST_FILE) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def list_watchlists(path: Path = WATCHLIST_FILE) -> List[Watchlist]:
    data = _ensure_store(path)
    return [Watchlist.from_dict(v) for v in data["watchlists"].values()]


def get_watchlist(wl_id: str, path: Path = WATCHLIST_FILE) -> Optional[Watchlist]:
    data = _ensure_store(path)
    raw = data["watchlists"].get(wl_id)
    if raw is None:
        # try case-insensitive / name match
        for k, v in data["watchlists"].items():
            if k.lower() == wl_id.lower() or v.get("name", "").lower() == wl_id.lower():
                return Watchlist.from_dict(v)
        return None
    return Watchlist.from_dict(raw)


def upsert_watchlist(wl: Watchlist, path: Path = WATCHLIST_FILE) -> Watchlist:
    data = _ensure_store(path)
    data["watchlists"][wl.id] = wl.to_dict()
    save_store(data, path)
    return wl


def _sample_sats(
    sats: Sequence[EarthSatellite],
    n: int,
    strategy: str = "even",
) -> List[EarthSatellite]:
    sats = list(sats)
    if not sats or n <= 0:
        return []
    if n >= len(sats):
        return sats
    if strategy == "first":
        return sats[:n]
    # even spacing through catalog (diversity across planes / IDs)
    idxs = [int(round(i * (len(sats) - 1) / max(n - 1, 1))) for i in range(n)]
    seen = set()
    out = []
    for i in idxs:
        if i not in seen:
            seen.add(i)
            out.append(sats[i])
    return out


def _norad(sat: EarthSatellite):
    return getattr(getattr(sat, "model", None), "satnum", None)


def resolve_watchlist_pairs(
    wl: Watchlist,
    index: Optional[ObjectIndex] = None,
) -> Tuple[List[Tuple[EarthSatellite, EarthSatellite]], Dict[str, Any]]:
    """Expand a watchlist into concrete satellite pairs + meta."""
    idx = index or get_index()
    pairs: List[Tuple[EarthSatellite, EarthSatellite]] = []
    meta: Dict[str, Any] = {"mode": wl.mode, "skipped": [], "primary": None}

    if wl.mode == "pairs":
        for a_name, b_name in wl.pairs:
            ra, rb = idx.resolve(a_name), idx.resolve(b_name)
            sa = idx.get_satellite(ra) if ra else None
            sb = idx.get_satellite(rb) if rb else None
            if sa and sb and _norad(sa) != _norad(sb):
                pairs.append((sa, sb))
            else:
                meta["skipped"].append(f"{a_name}/{b_name}")
        return pairs, meta

    if wl.mode == "primary_vs_group":
        rec = idx.resolve(wl.primary)
        primary = idx.get_satellite(rec) if rec else None
        if primary is None:
            meta["skipped"].append(f"primary:{wl.primary}")
            return [], meta
        meta["primary"] = primary.name.strip()
        group_sats = idx.satellites_in_group(wl.group)
        if not group_sats:
            meta["skipped"].append(f"empty_group:{wl.group}")
            return [], meta
        secondary = _sample_sats(group_sats, wl.sample, wl.sample_strategy)
        p_norad = _norad(primary)
        for s in secondary:
            if _norad(s) != p_norad:
                pairs.append((primary, s))
        meta["secondary_count"] = len(secondary)
        meta["group"] = wl.group
        return pairs, meta

    if wl.mode == "group_vs_group":
        g1 = idx.satellites_in_group(wl.group1)
        g2 = idx.satellites_in_group(wl.group2)
        if wl.group1 == "stations":
            iss = idx.get_satellite(idx.resolve("ISS"))
            primary_list = [iss] if iss else g1[: wl.primary_limit]
        else:
            primary_list = g1[: wl.primary_limit]
        secondary = _sample_sats(g2, wl.sample, wl.sample_strategy)
        for a in primary_list:
            if a is None:
                continue
            for b in secondary:
                if _norad(a) != _norad(b):
                    pairs.append((a, b))
        meta["primary_count"] = len(primary_list)
        meta["secondary_count"] = len(secondary)
        return pairs, meta

    meta["skipped"].append(f"unknown_mode:{wl.mode}")
    return [], meta


def scan_watchlist(
    wl: Watchlist,
    *,
    hours: float = 48,
    threshold_km: float = CONJ_THRESHOLD_KM,
    high_risk_km: float = CONJ_HIGH_RISK_KM,
    only_below: bool = False,
    adaptive: bool = True,
    steps: int = 200,
    index: Optional[ObjectIndex] = None,
    progress_every: int = 20,
) -> Dict[str, Any]:
    """Scan all pairs in a watchlist; return ranked approaches."""
    idx = index or get_index()
    pairs, meta = resolve_watchlist_pairs(wl, idx)
    results: List[dict] = []
    errors = 0

    for i, (a, b) in enumerate(pairs, 1):
        if progress_every and i % progress_every == 0:
            print(f"  … watchlist {wl.id}: {i}/{len(pairs)} pairs")
        try:
            r = check_conjunction(
                a,
                b,
                hours=hours,
                threshold_km=threshold_km,
                high_risk_km=high_risk_km,
                steps=steps,
                adaptive=adaptive,
            )
            r["watchlist"] = wl.id
            if only_below and not r.get("below_threshold"):
                continue
            results.append(r)
        except Exception:
            errors += 1

    results.sort(key=lambda r: r["min_dist_km"])
    n_high = sum(1 for r in results if r["risk"] == "HIGH")
    n_med = sum(1 for r in results if r["risk"] == "MEDIUM")
    n_low = sum(1 for r in results if r["risk"] == "LOW")

    return {
        "watchlist_id": wl.id,
        "watchlist_name": wl.name,
        "hours": hours,
        "threshold_km": threshold_km,
        "high_risk_km": high_risk_km,
        "only_below": only_below,
        "pairs_scanned": len(pairs),
        "results": results,
        "meta": meta,
        "errors": errors,
        "summary": {
            "n_results": len(results),
            "HIGH": n_high,
            "MEDIUM": n_med,
            "LOW": n_low,
            "closest_km": results[0]["min_dist_km"] if results else None,
            "closest_pair": (
                f"{results[0]['sat1']} / {results[0]['sat2']}" if results else None
            ),
            "scanned_at": datetime.now(timezone.utc).isoformat(),
        },
    }


def results_to_rows(results: Sequence[dict], local: bool = False) -> List[dict]:
    """Flatten scan results for tables / CSV."""
    rows = []
    for r in results:
        tca = r.get("tca")
        if hasattr(tca, "strftime"):
            if getattr(tca, "tzinfo", None) is None:
                tca = tca.replace(tzinfo=timezone.utc)
            tca_s = (
                tca.astimezone().strftime("%Y-%m-%d %H:%M %Z")
                if local
                else tca.strftime("%Y-%m-%d %H:%M:%S UTC")
            )
        else:
            tca_s = str(tca)
        rv = r.get("rel_velocity_kms")
        rows.append(
            {
                "Object 1": r.get("sat1"),
                "Object 2": r.get("sat2"),
                "NORAD 1": r.get("norad1"),
                "NORAD 2": r.get("norad2"),
                "TCA": tca_s,
                "Min dist km": r.get("min_dist_km"),
                "Rel vel km/s": rv if rv is not None else "",
                "Risk": r.get("risk"),
            }
        )
    return rows


def export_results_csv(results: Sequence[dict], path: Path, local: bool = False) -> Path:
    import csv

    path = Path(path)
    rows = results_to_rows(results, local=local)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("Object 1,Object 2,TCA,Min dist km,Rel vel km/s,Risk\n")
        return path
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    return path
