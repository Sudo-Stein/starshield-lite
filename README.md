# StarShield Lite

**Personal space domain awareness console** · **v0.2.0**

> *Any object → will I see it, where in my sky, what else gets close, and tell me when it matters.*


[![Version](https://img.shields.io/badge/version-0.2.0-blue.svg)](CHANGELOG.md)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/API-FastAPI-009688.svg)](https://fastapi.tiangolo.com/)
[![Docker](https://img.shields.io/badge/docker-compose-2496ED.svg)](https://docs.docker.com/compose/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](#license)

StarShield Lite is a portfolio-grade toolkit for **orbital awareness** from a ground observer’s perspective. It combines public TLE catalogs, pass prediction with stargazer filtering, pass quality scoring, conjunction watchlists, optional debris awareness, SQLite history, webhook notifications, a FastAPI backend, Streamlit/TUI frontends, and Docker deployment.

**Current release: [v0.2.0](CHANGELOG.md)** — see the changelog for the full feature list.

Default home site: **Kingsland, GA** (30.8°N, 81.65°W) — switchable to other profiles or custom lat/lon.

---

## Try it now · 5-minute demo

**Fastest way to see value** (local Python):

```bash
git clone https://github.com/Sudo-Stein/starshield-lite.git
cd starshield-lite
python -m venv .venv && source .venv/bin/activate
pip install -e ".[pdf,dev]"

make demo          # or: python demo/demo.py
# non-interactive:  make demo-auto
```

The guided demo walks through **search → pass quality → conjunctions → starmap HTML → ICS/PDF export**.  
Artifacts land in `data/demo/`. Full guide: [`demo/demo.md`](demo/demo.md).

**Docker full stack** (API + Streamlit + scheduler):

```bash
docker compose --profile full up --build
# API docs:    http://localhost:8000/docs
# Dashboard:   http://localhost:8501
# Health:      http://localhost:8000/health
```

In Streamlit: **Passes** → predict ISS → click a grade button → **Starmap** (linked sky + ground, scrubber, Play).

| Goal | Command |
|------|---------|
| Guided CLI showcase | `make demo` / `python demo/demo.py` |
| Best ISS passes | `python main.py passes --name ISS --hours 168 --sort quality --show_breakdown` |
| ISS–Starlink scan | `python main.py watchlist --cmd scan --wl iss-starlink --hours 48` |
| Live dashboard | `make dash` or `python main.py dash` |
| OpenAPI | `make api` → http://127.0.0.1:8000/docs |
| Full Docker demo | `make docker-full` |

---

## Key features

| Area | What you get |
|------|----------------|
| **Object Index** | Multi-catalog search (stations, Starlink, visual, active) by name, alias, or NORAD |
| **Passes + Stargazer** | Rise / culmination / set; optional dark-sky + sunlit-satellite filter |
| **Pass quality** | 0–100 score + letter grade (elevation, duration, darkness, sunlit, brightness proxy) |
| **Starmap** | Linked sky + ground views, minute scrubber + play, pass jump/focus from Streamlit |
| **Locations** | Named observer profiles + custom coordinates |
| **Watchlists** | e.g. ISS vs Starlink sample; adaptive TCA + relative velocity |
| **Debris** | Optional CelesTrak debris catalogs; ISS/stations vs debris conjunction scans |
| **History** | SQLite log of Grade B+ passes and MEDIUM/HIGH conjunctions |
| **Interfaces** | CLI · Textual TUI · Streamlit · FastAPI · background scheduler |
| **Export** | PDF reports (passes / watchlist) and ICS calendar files |
| **API security** | Optional API keys + per-IP rate limits (HTTP 429) |
| **Notifications** | Optional webhooks for Grade B+ passes and MEDIUM/HIGH conjunctions (Discord/Slack-ready) |
| **Packaging** | `pip install -e .` with `starshield` / `starshield-api` / `starshield-dash` entry points |
| **Ops** | Docker Compose, healthchecks, persistent `data/` volume, GitHub Actions CI |

---

## Installation

### Option A — Docker (recommended for demos)

```bash
git clone https://github.com/Sudo-Stein/starshield-lite.git
cd starshield-lite

# API only
docker compose up --build
# → http://localhost:8000/docs   ·   http://localhost:8000/health

# Full showcase: API + Streamlit + background scheduler
docker compose --profile full up --build
# → http://localhost:8501  (dashboard)
```

Other profiles:

```bash
docker compose --profile ui up --build      # API + Streamlit
docker compose --profile jobs up --build    # API + watchlist scheduler
```

| Check | Command |
|-------|---------|
| Health | `curl -s http://localhost:8000/health \| jq` |
| Search | `curl -s 'http://localhost:8000/objects/search?q=ISS&limit=5' \| jq` |
| Fetch TLEs in container | `docker compose exec api python main.py fetch --group stations` |
| Stop | `docker compose --profile full down` · or `make docker-down` |

Persistent state (SQLite, TLEs, logs) lives in **`./data`** (gitignored).  
Details: [docs/DOCKER.md](docs/DOCKER.md) · Showcase guide: [demo/demo.md](demo/demo.md)

### Option B — pip (development & guided demo)

Requires **Python 3.9+** (3.11+ recommended).

```bash
git clone https://github.com/Sudo-Stein/starshield-lite.git
cd starshield-lite
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[pdf,dev]"

make demo                  # guided showcase
# or:
starshield status
starshield-api             # → http://127.0.0.1:8000/docs
starshield-dash            # Streamlit
starshield-tui
```

Optional extras:

| Extra | Install | Provides |
|-------|---------|----------|
| `pdf` | `pip install -e ".[pdf]"` | PDF export (`fpdf2`) |
| `maps` | `pip install -e ".[maps]"` | Cartopy ground-track PNGs |
| `dev` | `pip install -e ".[dev]"` | pytest, ruff |
| `full` | `pip install -e ".[full]"` | pdf + maps + dev |

If the index is empty, fetch catalogs once:

```bash
make fetch                 # stations + starlink
# or: starshield fetch --group stations
```

---

## Screenshots

Captured from a live local run (Kingsland, GA · ~16k indexed objects).

### Streamlit dashboard

![Streamlit Status — next ISS sky watch](docs/screenshots/04_streamlit_status.png)

![Object Index search](docs/screenshots/05_streamlit_object_index.png)

![Passes tab with quality scoring](docs/screenshots/06_streamlit_passes.png)

![Starmap / sky planning](docs/screenshots/08_streamlit_starmap.png)

![History (SQLite)](docs/screenshots/09_streamlit_history.png)

### FastAPI

![OpenAPI docs at /docs](docs/screenshots/01_api_docs.png)

![Object search JSON](docs/screenshots/03_api_objects_search.png)

### CLI & reports

![CLI status, search, and quality-ranked passes](docs/screenshots/10_cli_status.png)

![Conjunction HTML report](docs/screenshots/12_conjunction_report.png)

![ISS ground track (Cartopy)](docs/screenshots/11_ground_track_iss.png)

![ISS alt–az starmap (Plotly)](docs/screenshots/13_starmap_iss.png)

More images live in [`docs/screenshots/`](docs/screenshots/).

---

## Ways to run

### Local Python

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt    # full stack (Cartopy, etc.)
# or lean API stack:
# pip install -r requirements-docker.txt

python main.py status
python main.py fetch --group stations
python main.py fetch --group starlink
```

### CLI

```bash
python main.py --help
python main.py status
python main.py search --search ISS
python main.py passes --name ISS --hours 168 --sort quality --show_breakdown
python main.py watchlist --cmd scan --wl iss-starlink --hours 48
python main.py history --cmd summary
python main.py api                 # FastAPI → http://127.0.0.1:8000/docs
python main.py dash                # Streamlit
python main.py tui                 # Textual TUI
python main.py schedule --cmd list
```

### Interfaces at a glance

| Interface | Command | Best for |
|-----------|---------|----------|
| **CLI** | `python main.py <action>` | Scripts, quick checks |
| **TUI** | `python main.py tui` | Keyboard-driven terminal use |
| **Streamlit** | `python main.py dash` | Maps, starmap, interactive tables |
| **API** | `python main.py api` | Integration, OpenAPI, clients |
| **Scheduler** | `python main.py schedule --cmd start` | Unattended watchlist scans |
| **Docker** | `docker compose up` | Reproducible demos & portfolio deploys |

---

## Example workflows

### 1. Find the best visible passes tonight

```bash
python main.py fetch --group stations
python main.py passes --name ISS --hours 72 --sort quality --show_breakdown
# Or geometric ranking when no stargazer windows exist:
python main.py passes --name ISS --hours 336 --stargazer=False --sort quality --min_score 50
```

In Streamlit: **Passes** tab → object `ISS` → Sort by quality → Predict.

### 2. Monitor ISS–Starlink conjunction risk

```bash
python main.py fetch --group starlink
python main.py watchlist --cmd scan --wl iss-starlink --hours 48
python main.py history --cmd conj --object ISS --days 30
```

Schedule every 12 hours:

```bash
python main.py schedule --cmd start
# Docker: docker compose --profile jobs up -d
```

### 3. Plan the sky from another site

```bash
python main.py passes --name ISS --observer "Cherry Springs, PA" --hours 48
python main.py passes --name ISS --lat 30.67 --lon -81.46   # Amelia Island
```

Streamlit: sidebar **Observer location** → Starmap tab → time scrubber.

### 4. Call the API

```bash
python main.py api
curl -s 'http://127.0.0.1:8000/objects/search?q=ISS&limit=5' | jq
curl -s 'http://127.0.0.1:8000/passes?object=ISS&hours=48&stargazer=false&sort=quality' | jq
```

---

## Architecture

```
┌─────────────┐  ┌─────────────┐  ┌──────────────┐  ┌────────────┐
│  CLI/TUI    │  │  Streamlit  │  │   FastAPI    │  │ Scheduler  │
└──────┬──────┘  └──────┬──────┘  └──────┬───────┘  └─────┬──────┘
       │                │                │                │
       └────────────────┴───────┬────────┴────────────────┘
                                ▼
                    ┌───────────────────────┐
                    │   services/ (core)    │
                    │  object_index · sky   │
                    │  pass_quality · wl    │
                    │  database · scheduler │
                    └───────────┬───────────┘
                                ▼
                    ┌───────────────────────┐
                    │  core/  (Skyfield)    │
                    │  data/  (SQLite,TLE)  │
                    └───────────────────────┘
```

- **`services/`** — business logic (source of truth)  
- **`core/`** — orbital math, TLE fetch, simulation, plots  
- **`api/`** — thin HTTP façade over services  
- **`data/`** — TLEs, SQLite DB, watchlists, schedules, logs  

Full write-up: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

---

## Configuration

| Variable | Default | Meaning |
|----------|---------|---------|
| `STARSHIELD_DB_LOG` | `1` | Log B+ passes & MEDIUM/HIGH conjs to SQLite |
| `STARSHIELD_API_HOST` | `127.0.0.1` | API bind host (`0.0.0.0` in Docker) |
| `STARSHIELD_API_PORT` | `8000` | API port |
| `STARSHIELD_API_URL` | `http://…:8000` | Base URL for Streamlit API mode |
| `STARSHIELD_USE_API` | `0` | Streamlit uses HTTP API when reachable |
| `STARSHIELD_SCHEDULE_ENABLED` | `1` | Allow scheduler jobs |
| `STARSHIELD_API_RATE_LIMIT` | `1` | Enable per-IP rate limits (`0` to disable) |
| `STARSHIELD_API_RATE_LIMIT_PUBLIC` | `120/minute` | `/health`, `/objects/*`, list watchlists |
| `STARSHIELD_API_RATE_LIMIT_DEFAULT` | `60/minute` | `/history/*` and other default routes |
| `STARSHIELD_API_RATE_LIMIT_HEAVY` | `20/minute` | `/passes`, `/watchlist/*/scan`, `/export/*` |
| `STARSHIELD_API_KEY_REQUIRED` | `0` | Require `X-API-Key` on protected routes |
| `STARSHIELD_NOTIFY_ENABLED` | `1` | Global webhook notifications switch |
| `STARSHIELD_WEBHOOK_URL` | _(empty)_ | One or more comma-separated webhook URLs |
| `STARSHIELD_NOTIFY_PASS_MIN_SCORE` | `70` | Min pass quality score to notify (≈ Grade B) |
| `STARSHIELD_NOTIFY_CONJ_RISKS` | `HIGH,MEDIUM` | Conjunction risk levels that fire webhooks |
| `STARSHIELD_INDEX_DEBRIS` | `auto` | `auto` = index debris when cached · `1` force · `0` never |

Copy [`.env.example`](.env.example) → `.env` for local/Docker Compose.

### Debris (optional)

```bash
# Fetch a debris catalog (Cosmos-2251 alias)
starshield debris --cmd fetch --group debris
# Other catalogs: fengyun-1c-debris · iridium-33-debris

# Conjunction scan: ISS vs debris sample
starshield debris --cmd scan --name ISS --group debris --hours 24
# Or via watchlist (notifications + DB + PDF export apply)
starshield watchlist --cmd scan --wl iss-debris --hours 24

# Scheduler job (disabled by default): enable in data/schedules.json
# id: iss-debris-24h
```

### Webhooks (optional)

```bash
export STARSHIELD_WEBHOOK_URL=https://your.webhook/endpoint
starshield notify --cmd test          # or: python main.py notify --cmd test
starshield notify --cmd list
# Or edit data/notifications.json (format: generic | discord | slack)
```

Scheduled watchlist jobs and pass predictions automatically post when thresholds match.

Observer profiles are defined in `config.py` (`OBSERVER_PROFILES`). Risk bands: **HIGH** &lt; 10 km, **MEDIUM** &lt; 50 km.

---

## Project structure

```
starshield-lite/
├── pyproject.toml          # Package metadata + console scripts
├── main.py                 # CLI entry (Fire) → starshield
├── starshield_dash.py      # Streamlit launcher → starshield-dash
├── dashboard.py            # Streamlit UI
├── tui.py                  # Textual TUI → starshield-tui
├── config.py               # Paths, profiles, env config
├── api/                    # FastAPI app, rate limit, routers
├── services/               # Shared business logic (source of truth)
│   └── notifications.py    # Optional webhook alerts
├── core/                   # Propagation, prediction, sim, maps
├── utils/                  # Immutable log, alerts stub
├── demo/                   # Showcase: demo.py + demo.md
├── examples/               # Extra scripts
├── data/                   # Runtime: TLEs, starshield.db, logs (gitignored)
├── docs/                   # Architecture, Docker, usage, screenshots
├── tests/                  # pytest suite
├── Makefile                # make demo · make docker-full · make test
├── CONTRIBUTING.md
├── Dockerfile
└── docker-compose.yml
```

---

## Documentation

| Doc | Contents |
|-----|----------|
| [CHANGELOG.md](CHANGELOG.md) | Release history (Keep a Changelog) |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Layers, data flow, design choices |
| [docs/DOCKER.md](docs/DOCKER.md) | Compose profiles, volumes, troubleshooting |
| [docs/USAGE.md](docs/USAGE.md) | Common CLI/API recipes |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Dev setup, tests, PR guidelines |
| [demo/demo.md](demo/demo.md) | Showcase guide + impressive one-liners |
| [demo/demo.py](demo/demo.py) | Guided interactive demo script |
| [Makefile](Makefile) | `make demo`, `make docker-full`, `make test`, … |

---

## Continuous integration

CI workflow template: [`docs/ci/github-actions-ci.yml`](docs/ci/github-actions-ci.yml)

To enable Actions (one-time; needs a token with the `workflow` scope):

```bash
mkdir -p .github/workflows
cp docs/ci/github-actions-ci.yml .github/workflows/ci.yml
git add .github/workflows/ci.yml
git commit -m "ci: enable GitHub Actions"
git push
```

| Job | What it does |
|-----|----------------|
| **Lint** | Ruff check + format (non-blocking until fully clean) |
| **Test** | `pytest` on Python **3.11** and **3.12** |
| **Docker** | Multi-stage image build + `/health` smoke test |

## Development

```bash
git clone https://github.com/Sudo-Stein/starshield-lite.git
cd starshield-lite
python -m venv .venv && source .venv/bin/activate
pip install -e ".[pdf,dev]"

make test                  # pytest
make lint                  # ruff
make demo-auto             # non-interactive showcase
make help                  # all targets
```

See [CONTRIBUTING.md](CONTRIBUTING.md) and [demo/demo.md](demo/demo.md).
Business logic lives in `services/`; keep UIs and the API as thin adapters.

---

## License

MIT — free to use and adapt for personal and portfolio projects.

## Release

Tagged releases follow semantic versioning. Latest: **v0.2.0**.

```bash
# After tagging (see CHANGELOG + release notes)
git checkout v0.2.0
pip install -e ".[pdf,dev]"
```

---

## Acknowledgments

- [Skyfield](https://rhodesmill.org/skyfield/) & SGP4 for orbital propagation  
- [CelesTrak](https://celestrak.org/) for public GP element sets  
- FastAPI, Streamlit, Textual, Plotly, APScheduler  

---

Built as a **portfolio demonstration** of full-stack scientific Python: orbital mechanics, multi-interface UX, persistence, REST API, containers, and scheduled ops — without claiming operational space-traffic authority.
