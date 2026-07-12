# Docker guide — StarShield Lite

## Prerequisites

- Docker Engine 20+ and Docker Compose v2  
- Recommended: `cp .env.example .env` (ports, webhooks, API keys — all optional)  

## Images

Multi-stage build (`Dockerfile`):

1. **builder** — install Python deps into a venv  
2. **runtime** — slim image, non-root user `starshield`, expose **8000**  

Default command: FastAPI via Uvicorn.

Lean dependency set: `requirements-docker.txt` (no Cartopy/GEOS stack).

## Compose services

| Service | Profile | Port | Purpose |
|---------|---------|------|---------|
| `api` | *(default)* | 8000 | FastAPI + OpenAPI `/docs` |
| `streamlit` | `ui`, `full` | 8501 | Interactive dashboard |
| `scheduler` | `jobs`, `full` | — | APScheduler watchlist loop |

Shared volume: **`./data:/app/data`** — SQLite DB, TLE caches, logs, JSON configs.

## 5-minute Docker demo

```bash
git clone https://github.com/Sudo-Stein/starshield-lite.git
cd starshield-lite
docker compose --profile full up --build
```

| URL | Description |
|-----|-------------|
| http://localhost:8000/docs | Interactive OpenAPI (search objects, passes) |
| http://localhost:8000/health | Liveness + index size |
| http://localhost:8501 | Streamlit dashboard (Passes, Starmap, Watchlist) |

Seed catalogs if the index is empty:

```bash
docker compose exec api python main.py fetch --group stations
docker compose exec api python main.py fetch --group starlink
```

Makefile helpers (host Docker required):

```bash
make docker-full    # compose --profile full up --build
make docker-down
make docker-logs
```

For a CLI-only demo without Docker, see [`demo/demo.md`](../demo/demo.md).

## Common commands

```bash
# Build and start API
docker compose up --build
# same: make docker-up

# Detached API
docker compose up api -d

# Logs
docker compose logs -f api

# API + Streamlit
docker compose --profile ui up --build

# API + scheduler
docker compose --profile jobs up --build

# Full stack (best for demos)
docker compose --profile full up --build

# Stop
docker compose --profile full down
```

### Development override

Live code reload:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

Mounts the repo into `/app` and runs Uvicorn with `--reload`.

## Environment variables

| Variable | Example | Notes |
|----------|---------|-------|
| `STARSHIELD_DB_LOG` | `1` | Persist B+ passes / MEDIUM+HIGH conjs |
| `STARSHIELD_API_PORT` | `8000` | Host port mapping |
| `STARSHIELD_STREAMLIT_PORT` | `8501` | Streamlit host port |
| `STARSHIELD_USE_API` | `1` | Streamlit prefers HTTP API |
| `STARSHIELD_API_URL` | `http://api:8000` | In-compose service DNS |
| `STARSHIELD_SCHEDULE_ENABLED` | `1` | Scheduler jobs allowed |

## First-time data

Containers start with an empty `data/` volume. Fetch TLEs via API host tools or exec:

```bash
docker compose exec api python main.py fetch --group stations
docker compose exec api python main.py fetch --group starlink
```

Or run the same commands on the host with a local venv — both write to `./data`.

## Healthcheck

The `api` service probes `GET /health` every 30s. Streamlit and scheduler wait for healthy API when using Compose dependencies.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Port already in use | Change `STARSHIELD_API_PORT` in `.env` |
| Empty object index | Fetch stations/starlink TLEs into `data/` |
| Streamlit “API unreachable” | Ensure `api` is healthy; check `STARSHIELD_API_URL` |
| Permission errors on `data/` | Ensure `./data` is writable; recreate volume |
| Slow first Skyfield run | Ephemeris/TLE downloads on first use |

## Production notes

- Keep the image non-root (default)  
- Mount a durable volume for `/app/data`  
- Put a reverse proxy (Caddy/Nginx) in front if exposing publicly  
- Do **not** treat this as certified SSA infrastructure  

## Related

- [ARCHITECTURE.md](ARCHITECTURE.md)  
- [USAGE.md](USAGE.md)

## API keys in Docker

```bash
# Generate on host (writes data/api_keys.txt — mounted into containers)
python main.py apikey --cmd generate

# Enable in .env
echo 'STARSHIELD_API_KEY_REQUIRED=1' >> .env
echo 'STARSHIELD_API_KEYS=your-key-here' >> .env
echo 'STARSHIELD_API_KEY=your-key-here' >> .env   # Streamlit client

docker compose up api -d
```

Keys file at `./data/api_keys.txt` is bind-mounted with the `data/` volume.
