# StarShield Lite — Demo Guide

A short path through the main features for first-time users.

## Fastest path (5 minutes)

### Option A — Local guided script

```bash
git clone https://github.com/Sudo-Stein/starshield-lite.git
cd starshield-lite
python -m venv .venv && source .venv/bin/activate
pip install -e ".[pdf,dev]"

# Guided walkthrough (pauses between steps — press Enter)
python demo/demo.py

# Or non-interactive
python demo/demo.py --auto
make demo-auto
```

The script will:

1. **Search** the Object Index (ISS, NORAD, Starlink, Hubble)  
2. **Score** upcoming ISS passes (grade A–F)  
3. **Scan** a conjunction watchlist (or debris if cached)  
4. **Write** interactive starmap HTML (sky + ground track)  
5. **Export** ICS + PDF under `data/demo/`

### Option B — Docker full stack

```bash
git clone https://github.com/Sudo-Stein/starshield-lite.git
cd starshield-lite
docker compose --profile full up --build
```

Then open:

| URL | Description |
|-----|-------------|
| http://localhost:8000/docs | FastAPI OpenAPI playground |
| http://localhost:8000/health | Health + index size |
| http://localhost:8501 | Streamlit dashboard |

Suggested Streamlit path:

1. Sidebar: confirm observer (default Kingsland, GA)  
2. **Passes** → object `ISS` → Predict → click **#1** grade button  
3. **Starmap** tab → linked sky + ground, scrubber, **Play**  
4. **Watchlist** → `iss-starlink` → Scan  

Fetch catalogs once if the index is empty (CLI inside container or host):

```bash
docker compose exec api python main.py fetch --group stations
docker compose exec api python main.py fetch --group starlink
```

---

## Common commands

```bash
# System readiness
starshield status          # or: python main.py status

# Best ISS passes tonight / this week
python main.py passes --name ISS --hours 168 --sort quality --show_breakdown

# ISS vs Starlink close approaches
python main.py watchlist --cmd scan --wl iss-starlink --hours 48

# Debris awareness (after: python main.py debris --cmd fetch)
python main.py debris --cmd scan --name ISS --group debris --hours 24

# Calendar export
python main.py export --cmd passes --name ISS --export_format ics \
  --hours 72 --stargazer=False --output data/demo/iss.ics

# Live UIs
python main.py dash        # Streamlit
python main.py api         # http://127.0.0.1:8000/docs
python main.py tui         # Terminal UI
```

---

## Demo flags

| Flag | Meaning |
|------|---------|
| *(none)* | Interactive; press Enter between steps |
| `--auto` | No pauses |
| `--quick` | Shorter windows, skip PDF (fast dry run) |
| `--no-fetch` | Fail if catalogs missing (no network) |

```bash
python demo/demo.py --quick --auto
make demo-quick
```

---

## Artifacts

After a full demo run, check:

```
data/demo/
  demo_starmap_sky.html      # open in browser
  demo_starmap_ground.html
  demo_iss_passes.ics
  demo_iss_passes.pdf        # needs fpdf2 (pip install -e ".[pdf]")
  demo_conjunction.pdf       # if watchlist/debris produced hits
```

---

## Feature highlights

1. **Multi-catalog Object Index** — one search across stations, Starlink, visual, debris  
2. **Pass quality scoring** — not just geometry: darkness, sunlit, elevation → letter grade  
3. **Conjunction watchlists** — adaptive TCA + risk bands; optional debris  
4. **Linked visualization** — jump from a scored pass into sky + ground scrubber  
5. **Ops-ready surfaces** — FastAPI, rate limits, Docker, scheduler, webhooks, exports  

> Educational / personal tool — not operational space-traffic authority software.
