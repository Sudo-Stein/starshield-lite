"""Multi-catalog object index — single source of truth for named objects.

Combines stations / starlink / visual / active / … TLE caches into one
searchable index (NORAD, name, groups, epoch).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from skyfield.api import EarthSatellite

from config import DATA_DIR, DEBRIS_GROUPS, INDEX_GROUPS, TLE_URLS, effective_index_groups
from core.propagator import load_satellites

# Manual aliases → preferred name substring (case-insensitive match against catalog names)
BUILTIN_ALIASES: Dict[str, str] = {
    "ISS": "ISS (ZARYA)",
    "SPACE STATION": "ISS (ZARYA)",
    "ZARYA": "ISS (ZARYA)",
    "HST": "HST",
    "HUBBLE": "HST",
    "TIANGONG": "CSS",
    "CSS": "CSS",
    "CHINESE SPACE STATION": "CSS",
}


@dataclass
class ObjectRecord:
    """One physical object as seen across one or more TLE groups."""

    norad: int
    name: str
    groups: Set[str] = field(default_factory=set)
    aliases: List[str] = field(default_factory=list)
    epoch: Optional[datetime] = None
    primary_group: str = ""

    def to_dict(self) -> dict:
        return {
            "norad": self.norad,
            "name": self.name,
            "groups": sorted(self.groups),
            "aliases": list(self.aliases),
            "epoch": self.epoch.isoformat() if self.epoch else None,
            "primary_group": self.primary_group,
        }


def _tle_path(group: str) -> Path:
    return DATA_DIR / f"{group}_tles.txt"


def _sat_epoch(sat: EarthSatellite) -> Optional[datetime]:
    try:
        # Skyfield: sat.epoch is a Time
        ep = sat.epoch
        dt = ep.utc_datetime()
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _sat_norad(sat: EarthSatellite) -> Optional[int]:
    try:
        n = getattr(sat.model, "satnum", None)
        if n is None:
            return None
        return int(n)
    except Exception:
        return None


def catalog_fingerprint(groups: Optional[Sequence[str]] = None) -> str:
    """Stable fingerprint of on-disk TLE caches (for cache busting)."""
    groups = list(groups or effective_index_groups())
    parts = []
    for g in groups:
        p = _tle_path(g)
        if p.exists():
            st = p.stat()
            parts.append(f"{g}:{st.st_mtime_ns}:{st.st_size}")
        else:
            parts.append(f"{g}:missing")
    return "|".join(parts)


class ObjectIndex:
    """In-memory multi-catalog index."""

    def __init__(self) -> None:
        self._by_norad: Dict[int, ObjectRecord] = {}
        self._name_upper: Dict[str, int] = {}  # exact name.upper() -> norad
        self._sats_by_group: Dict[str, List[EarthSatellite]] = {}
        self._sat_by_norad_group: Dict[Tuple[int, str], EarthSatellite] = {}
        self.groups_loaded: List[str] = []
        self.built_at: Optional[datetime] = None

    # ----- build -----

    def rebuild(self, groups: Optional[Sequence[str]] = None) -> "ObjectIndex":
        """Scan cached TLE files and rebuild the index."""
        groups = list(groups or effective_index_groups())
        self._by_norad.clear()
        self._name_upper.clear()
        self._sats_by_group.clear()
        self._sat_by_norad_group.clear()
        self.groups_loaded = []

        for group in groups:
            path = _tle_path(group)
            if not path.exists():
                continue
            try:
                sats, _ = load_satellites(path)
            except Exception:
                continue
            sats = list(sats)
            self._sats_by_group[group] = sats
            self.groups_loaded.append(group)

            for sat in sats:
                norad = _sat_norad(sat)
                if norad is None:
                    continue
                name = (sat.name or "").strip() or f"NORAD-{norad}"
                epoch = _sat_epoch(sat)
                rec = self._by_norad.get(norad)
                if rec is None:
                    rec = ObjectRecord(
                        norad=norad,
                        name=name,
                        groups={group},
                        primary_group=group,
                        epoch=epoch,
                    )
                    self._by_norad[norad] = rec
                else:
                    rec.groups.add(group)
                    # Prefer stations/visual names over starlink debris naming quirks
                    if group in ("stations", "visual") and "ISS" in name.upper():
                        rec.name = name
                        rec.primary_group = group
                    elif group == "stations":
                        rec.primary_group = group
                        rec.name = name
                    # Keep newest epoch
                    if epoch and (rec.epoch is None or epoch > rec.epoch):
                        rec.epoch = epoch
                        if group not in ("stations", "visual"):
                            # update name from fresher TLE if not a station
                            if rec.primary_group not in ("stations", "visual"):
                                rec.name = name
                self._sat_by_norad_group[(norad, group)] = sat
                self._name_upper[name.upper()] = norad

        # Attach built-in aliases when target exists
        for alias, target in BUILTIN_ALIASES.items():
            # find norad for target name
            t_up = target.upper()
            norad = self._name_upper.get(t_up)
            if norad is None:
                # partial
                for n_up, nid in self._name_upper.items():
                    if t_up in n_up:
                        norad = nid
                        break
            if norad is not None and norad in self._by_norad:
                rec = self._by_norad[norad]
                if alias.upper() not in [a.upper() for a in rec.aliases]:
                    rec.aliases.append(alias)

        self.built_at = datetime.now(timezone.utc)
        return self

    # ----- query -----

    def __len__(self) -> int:
        return len(self._by_norad)

    def stats(self) -> dict:
        debris_n = sum(
            1
            for r in self._by_norad.values()
            if r.groups & set(DEBRIS_GROUPS)
            or any(
                tok in (r.name or "").upper()
                for tok in (" DEB", "DEBRI", "R/B")
            )
        )
        return {
            "objects": len(self._by_norad),
            "groups_loaded": list(self.groups_loaded),
            "debris_groups_loaded": [
                g for g in self.groups_loaded if g in DEBRIS_GROUPS
            ],
            "debris_objects": debris_n,
            "built_at": self.built_at.isoformat() if self.built_at else None,
            "fingerprint": catalog_fingerprint(
                self.groups_loaded or effective_index_groups()
            ),
        }

    def get(self, norad: int) -> Optional[ObjectRecord]:
        return self._by_norad.get(int(norad))

    def all_records(self) -> List[ObjectRecord]:
        return sorted(self._by_norad.values(), key=lambda r: r.name.upper())

    def search(self, query: str, limit: int = 25) -> List[ObjectRecord]:
        """Search by NORAD, exact name, alias, or partial name."""
        q = (query or "").strip()
        if not q:
            return []

        # Pure NORAD
        if re.fullmatch(r"\d{1,9}", q):
            rec = self.get(int(q))
            return [rec] if rec else []

        q_up = q.upper()
        scored: List[Tuple[int, ObjectRecord]] = []

        for rec in self._by_norad.values():
            name_up = rec.name.upper()
            score = None
            if name_up == q_up:
                score = 0
            elif q_up in [a.upper() for a in rec.aliases]:
                score = 1
            elif name_up.startswith(q_up):
                score = 2
            elif q_up in name_up:
                score = 3
            else:
                for a in rec.aliases:
                    if q_up in a.upper():
                        score = 4
                        break
            if score is None:
                continue
            # Prefer non-debris-ish names
            if any(tok in name_up for tok in (" DEB", "R/B", "DEBRI")):
                score += 10
            scored.append((score, rec))

        scored.sort(key=lambda x: (x[0], len(x[1].name), x[1].name.upper()))
        return [r for _, r in scored[:limit]]

    def resolve(self, query: str) -> Optional[ObjectRecord]:
        """Best single match for a query (or None)."""
        hits = self.search(query, limit=1)
        return hits[0] if hits else None

    def get_satellite(
        self, rec_or_norad, preferred_group: Optional[str] = None
    ) -> Optional[EarthSatellite]:
        """Return a live EarthSatellite for a record / NORAD id."""
        if isinstance(rec_or_norad, ObjectRecord):
            rec = rec_or_norad
        else:
            rec = self.get(int(rec_or_norad))
        if rec is None:
            return None

        order: List[str] = []
        if preferred_group and preferred_group in rec.groups:
            order.append(preferred_group)
        if rec.primary_group and rec.primary_group not in order:
            order.append(rec.primary_group)
        for g in ("stations", "visual", "starlink", "active") + tuple(DEBRIS_GROUPS):
            if g in rec.groups and g not in order:
                order.append(g)
        for g in rec.groups:
            if g not in order:
                order.append(g)

        for g in order:
            sat = self._sat_by_norad_group.get((rec.norad, g))
            if sat is not None:
                return sat
        return None

    def satellites_in_group(self, group: str) -> List[EarthSatellite]:
        return list(self._sats_by_group.get(group, []))

    def is_debris_record(self, rec: ObjectRecord) -> bool:
        """True if record is tagged with a debris catalog group or debris-like name."""
        if rec.groups & set(DEBRIS_GROUPS):
            return True
        name_up = (rec.name or "").upper()
        return any(tok in name_up for tok in (" DEB", "DEBRI"))

    def search_debris(self, query: str = "", limit: int = 25) -> List[ObjectRecord]:
        """Search restricted to debris-tagged objects (or all debris if query empty)."""
        q = (query or "").strip()
        if q:
            hits = self.search(q, limit=max(limit * 3, 50))
            deb = [r for r in hits if self.is_debris_record(r)]
            return deb[:limit]
        out = [r for r in self.all_records() if self.is_debris_record(r)]
        return out[:limit]


# Module-level singleton rebuilt when fingerprint changes
_INDEX: Optional[ObjectIndex] = None
_INDEX_FP: Optional[str] = None


def get_index(
    groups: Optional[Sequence[str]] = None,
    *,
    force: bool = False,
) -> ObjectIndex:
    """Return a process-wide ObjectIndex, rebuilding when TLE files change.

    By default includes core catalogs plus any **cached debris** groups
    (see ``config.effective_index_groups``).
    """
    global _INDEX, _INDEX_FP
    groups = list(groups or effective_index_groups())
    fp = catalog_fingerprint(groups)
    if force or _INDEX is None or _INDEX_FP != fp:
        _INDEX = ObjectIndex().rebuild(groups)
        _INDEX_FP = fp
    return _INDEX


def invalidate_index() -> None:
    """Force rebuild on next get_index() (call after fetch)."""
    global _INDEX, _INDEX_FP
    _INDEX = None
    _INDEX_FP = None
