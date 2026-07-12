# Architecture — StarShield Lite

## Purpose

StarShield Lite answers four questions from a ground observer’s point of view:

1. **What is this object?** (catalog search)  
2. **Will I see it?** (passes + stargazer + quality score)  
3. **Where is it in my sky?** (starmap time scrubber)  
4. **What else gets close?** (watchlists + history)  
5. **Tell me when it matters** (optional webhooks)

It is intentionally **not** a certified space-traffic product; it is a clear, end-to-end engineering toolkit.

---

## Layering

```
┌────────────────────────────────────────────────────────────┐
│  Interfaces                                                │
│  CLI (main.py) · TUI (tui.py) · Streamlit (dashboard.py)   │
│  FastAPI (api/) · Scheduler (services/scheduler.py)        │
└────────────────────────────┬───────────────────────────────┘
                             │
┌────────────────────────────▼───────────────────────────────┐
│  services/  — source of truth for business rules           │
│  object_index · observers · sky · pass_quality             │
│  watchlist · database · scheduler · notifications          │
└────────────────────────────┬───────────────────────────────┘
                             │
┌────────────────────────────▼───────────────────────────────┐
│  core/  — domain primitives (Skyfield / SGP4)              │
│  tle_fetcher · propagator · predictor · simulator          │
│  starmap · visualizer                                      │
└────────────────────────────┬───────────────────────────────┘
                             │
┌────────────────────────────▼───────────────────────────────┐
│  data/  — durable state                                    │
│  *_tles.txt · starshield.db · watchlists.json              │
│  schedules.json · notifications.json · starshield.log      │
└────────────────────────────────────────────────────────────┘
```

**Rule of thumb:** UIs and HTTP handlers stay thin. Anything non-trivial lives in `services/` or `core/`.

---

## Interfaces

| Surface | Role | Talks to |
|---------|------|----------|
| **CLI** | Scripting, demos, cron wrappers | `services/` directly |
| **TUI** | Fast terminal dashboard | `services/` + `core/` |
| **Streamlit** | Interactive maps / tables | Direct services, optional HTTP API |
| **FastAPI** | Machine-readable API + OpenAPI | `services/` only |
| **Scheduler** | Unattended watchlist scans | `watchlist` + `database` + `notifications` |

CLI/TUI/Streamlit can keep working offline against local TLE caches. Streamlit may set `STARSHIELD_USE_API=1` to prefer the HTTP backend when it is healthy.

---

## Core services

### Object index (`services/object_index.py`)

- Merges configured TLE groups into one searchable catalog  
- Fields: NORAD, name, groups, aliases, epoch  
- Cache key tied to on-disk TLE file mtimes  
- **Debris** groups (Cosmos-2251, Fengyun-1C, Iridium-33) join the index only when
  their TLE cache exists (`STARSHIELD_INDEX_DEBRIS=auto`)  

### Debris (`services/debris.py`)

Optional catalog helpers + ad-hoc primary-vs-debris scans. Reuses
`services/watchlist.scan_watchlist` and the adaptive conjunction engine.  
API surface: `/debris/*`. Default watchlists: `iss-debris`, `iss-fengyun-debris`, …

### Observers (`services/observers.py`)

- Named profiles (Kingsland GA, Amelia Island, dark-sky examples)  
- Custom lat/lon/elevation  
- Used by passes, starmap, and quality scoring  

### Sky planning (`services/sky.py` + `core/starmap.py`)

- Alt–az tracks, scrub positions, rise/culm/set markers  
- Polar Plotly figure (zenith center, North up)  

### Linked visualization (`services/visualization.py`)

- Pass→starmap focus packages (window, scrub at culm, quality metadata)  
- Linked sky + ground Plotly figures (shared scrub, focus dimming, pass segment)  
- Minute scrubber helpers + play/pause advance used by Streamlit  


### Pass quality (`services/pass_quality.py`)

Weighted score (elevation, duration, darkness, sunlit fraction, magnitude proxy) with caps so pure daylight/eclipse passes cannot look “excellent.”

### Watchlist (`services/watchlist.py`)

- JSON-defined lists (default: ISS vs Starlink sample)  
- Expands to pairs via the object index  
- Uses adaptive conjunction engine in `core/simulator.py`  

### Database (`services/database.py`)

SQLite tables:

- `passes` — Grade B+ predictions worth remembering  
- `conjunction_events` — MEDIUM/HIGH approaches  
- `watchlist_runs` — scan metadata  
- `schema_meta` — version stamp for future migrations  

### Notifications (`services/notifications.py`)

Optional webhook fan-out for actionable events:

- **Events:** `pass.quality`, `conjunction.risk`, `watchlist.summary`, `system.test`  
- **Config:** env (`STARSHIELD_WEBHOOK_URL`) and/or `data/notifications.json`  
- **Formats:** `generic` JSON, `discord` embeds, `slack` blocks (extensible)  
- **Delivery:** fire-and-forget daemon threads; never raises into core flows  
- **Hooks:** CLI passes/watchlist, FastAPI routes, scheduled jobs  

### Scheduler (`services/scheduler.py`)

APScheduler interval jobs (config in `data/schedules.json`). Default: scan `iss-starlink` every 12 hours and persist results.

---

## Data flow examples

### Predict passes

```
CLI/API → ObjectIndex.resolve(name)
       → predict_passes(sat, location, stargazer=…)
       → score_passes(…)
       → optional log_passes_batch(score ≥ 70)
```

### Watchlist scan

```
CLI/API/Scheduler → get_watchlist(id)
                 → resolve pairs (index + sampling)
                 → check_conjunction (coarse → fine TCA)
                 → log_watchlist_scan (runs + MEDIUM/HIGH events)
```

---

## Design choices

| Choice | Why |
|--------|-----|
| Shared `services/` | Avoid duplicating logic across four UIs |
| Public TLEs only | No Space-Track credentials required to demo |
| Smart Starlink sampling | Full constellation × ISS is too heavy for laptops |
| Optional DB logging | Keep interactive use snappy |
| Lean Docker requirements | Smaller images; Cartopy stays local-optional |
| Stateless API location params | Easy to call from scripts without sessions |

---

## Testing

`tests/` covers object index, quality scoring, watchlists, SQLite, scheduler config, and FastAPI endpoints (`TestClient`). Prefer pure service tests; integration tests may skip if TLE caches are empty.

---

## Extension points

- **Auth:** API key middleware on FastAPI  
- **Alerts:** hook `utils/alerts.py` after MEDIUM/HIGH watchlist events  
- **More catalogs:** add URLs to `TLE_URLS` + `INDEX_GROUPS`  
- **Migrations:** bump `SCHEMA_VERSION` in `database.py` and apply ALTERs  

---

## Related docs

- [DOCKER.md](DOCKER.md) — containers and volumes  
- [USAGE.md](USAGE.md) — common recipes  
