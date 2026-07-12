"""Orbit visualization: simple plots and Cartopy ground-track maps."""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Sequence

import matplotlib.pyplot as plt
from skyfield.api import EarthSatellite, wgs84

from config import DATA_DIR, LOCATION
from core.propagator import propagate


def quick_plot(sat: EarthSatellite, hours: float = 6, step_minutes: float = 2):
    """Plot a simple ground track (lat/lon) without Cartopy."""
    _times, positions = propagate(sat, hours=hours, step_minutes=step_minutes)
    subpoints = wgs84.subpoint_of(positions)

    lats = subpoints.latitude.degrees
    lons = subpoints.longitude.degrees

    plt.figure(figsize=(10, 5))
    plt.plot(lons, lats, ".", markersize=2)
    plt.xlabel("Longitude (°)")
    plt.ylabel("Latitude (°)")
    name = getattr(sat, "name", "satellite")
    plt.title(f"Ground track: {name} ({hours}h)")
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.show()


def _split_antimeridian(lons, lats):
    """Split track into segments that do not cross ±180° (for clean map lines)."""
    import numpy as np

    lons = np.asarray(lons, dtype=float)
    lats = np.asarray(lats, dtype=float)
    segments = []
    start = 0
    for i in range(1, len(lons)):
        if abs(lons[i] - lons[i - 1]) > 180:
            segments.append((lons[start:i], lats[start:i]))
            start = i
    segments.append((lons[start:], lats[start:]))
    return segments


def map_ground_track(
    sat: EarthSatellite,
    hours: float = 6,
    step_minutes: float = 1.0,
    location: Optional[dict] = None,
    save_path: Optional[Path] = None,
    show: bool = True,
    title: Optional[str] = None,
):
    """Cartopy world map with ground track + observer marker.

    Falls back to ``quick_plot`` if Cartopy is not installed.
    """
    try:
        import cartopy.crs as ccrs
        import cartopy.feature as cfeature
    except ImportError:
        print("Cartopy not available — falling back to simple plot.")
        quick_plot(sat, hours=hours, step_minutes=step_minutes)
        return None

    loc = location or LOCATION
    _times, positions = propagate(sat, hours=hours, step_minutes=step_minutes)
    subpoints = wgs84.subpoint_of(positions)
    lats = subpoints.latitude.degrees
    lons = subpoints.longitude.degrees

    fig = plt.figure(figsize=(12, 6))
    ax = fig.add_subplot(1, 1, 1, projection=ccrs.PlateCarree())
    ax.set_global()
    ax.add_feature(cfeature.LAND, facecolor="#1a1a2e", zorder=0)
    ax.add_feature(cfeature.OCEAN, facecolor="#0f3460", zorder=0)
    ax.add_feature(cfeature.COASTLINE, edgecolor="#e0e0e0", linewidth=0.5)
    ax.add_feature(cfeature.BORDERS, edgecolor="#666666", linewidth=0.3, linestyle=":")
    ax.gridlines(draw_labels=True, dms=True, x_inline=False, y_inline=False, alpha=0.35)

    for seg_lons, seg_lats in _split_antimeridian(lons, lats):
        if len(seg_lons) < 2:
            continue
        ax.plot(
            seg_lons,
            seg_lats,
            color="#00d4ff",
            linewidth=1.6,
            transform=ccrs.Geodetic(),
            zorder=3,
        )

    # Start / end markers
    ax.plot(
        lons[0],
        lats[0],
        "o",
        color="#7CFC00",
        markersize=7,
        transform=ccrs.PlateCarree(),
        label="Start",
        zorder=4,
    )
    ax.plot(
        lons[-1],
        lats[-1],
        "s",
        color="#ff6b6b",
        markersize=6,
        transform=ccrs.PlateCarree(),
        label="End",
        zorder=4,
    )

    # Observer (Kingsland, GA by default)
    ax.plot(
        loc["lon"],
        loc["lat"],
        marker="*",
        color="#ffd700",
        markersize=16,
        markeredgecolor="black",
        markeredgewidth=0.6,
        transform=ccrs.PlateCarree(),
        label=f"Observer ({loc['lat']:.2f}°, {loc['lon']:.2f}°)",
        zorder=5,
    )

    name = getattr(sat, "name", "satellite")
    ax.set_title(title or f"Ground track: {name}  ·  next {hours:g}h")
    ax.legend(loc="lower left", framealpha=0.85)

    out = save_path
    if out is None:
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)[:40]
        out = DATA_DIR / f"ground_track_{safe}.png"
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    print(f"Saved map → {out}")

    if show:
        plt.show()
    else:
        plt.close(fig)
    return out


def map_multi_tracks(
    sats: Sequence[EarthSatellite],
    hours: float = 3,
    step_minutes: float = 1.0,
    location: Optional[dict] = None,
    save_path: Optional[Path] = None,
    show: bool = True,
    max_sats: int = 8,
):
    """Plot several satellite ground tracks on one Cartopy map (e.g. Starlink)."""
    try:
        import cartopy.crs as ccrs
        import cartopy.feature as cfeature
        import matplotlib.cm as cm
    except ImportError:
        print("Cartopy not available.")
        return None

    loc = location or LOCATION
    fig = plt.figure(figsize=(12, 6))
    ax = fig.add_subplot(1, 1, 1, projection=ccrs.PlateCarree())
    ax.set_global()
    ax.add_feature(cfeature.LAND, facecolor="#1a1a2e", zorder=0)
    ax.add_feature(cfeature.OCEAN, facecolor="#0f3460", zorder=0)
    ax.add_feature(cfeature.COASTLINE, edgecolor="#e0e0e0", linewidth=0.5)
    ax.gridlines(draw_labels=True, alpha=0.3)

    colors = cm.get_cmap("turbo")
    subset = list(sats)[:max_sats]
    for i, sat in enumerate(subset):
        _times, positions = propagate(sat, hours=hours, step_minutes=step_minutes)
        subpoints = wgs84.subpoint_of(positions)
        lats = subpoints.latitude.degrees
        lons = subpoints.longitude.degrees
        color = colors(i / max(len(subset) - 1, 1))
        for seg_lons, seg_lats in _split_antimeridian(lons, lats):
            if len(seg_lons) < 2:
                continue
            ax.plot(
                seg_lons,
                seg_lats,
                color=color,
                linewidth=1.2,
                alpha=0.85,
                transform=ccrs.Geodetic(),
            )

    ax.plot(
        loc["lon"],
        loc["lat"],
        marker="*",
        color="#ffd700",
        markersize=16,
        markeredgecolor="black",
        transform=ccrs.PlateCarree(),
        label="Observer",
        zorder=5,
    )
    ax.set_title(f"Ground tracks × {len(subset)}  ·  next {hours:g}h")
    ax.legend(loc="lower left")

    out = Path(save_path) if save_path else DATA_DIR / "ground_track_multi.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out, dpi=150, bbox_inches="tight")
    print(f"Saved map → {out}")
    if show:
        plt.show()
    else:
        plt.close(fig)
    return out
