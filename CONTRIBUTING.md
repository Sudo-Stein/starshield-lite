# Contributing to StarShield Lite

Thanks for your interest! StarShield Lite is a personal space domain awareness
toolkit. Small, focused contributions are welcome.

## Table of contents

- [Development setup](#development-setup)
- [Running tests, lint, and the demo](#running-tests-lint-and-the-demo)
- [Project layout](#project-layout)
- [Code style](#code-style)
- [Pull request workflow](#pull-request-workflow)
- [Adding an observer profile](#adding-an-observer-profile)
- [Adding a watchlist](#adding-a-watchlist)
- [Reporting issues](#reporting-issues)
- [License](#license)

---

## Development setup

### Local Python

```bash
git clone https://github.com/Sudo-Stein/starshield-lite.git
cd starshield-lite
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev,pdf]"
cp .env.example .env        # optional — ports, webhooks, API keys
```

Fetch catalogs once so the object index is usable:

```bash
make fetch
# or: python main.py fetch --group stations && python main.py fetch --group starlink
```

### Docker

Useful for API/dashboard work without a local scientific stack:

```bash
cp .env.example .env        # recommended for ports / webhooks
docker compose --profile full up --build
```

| Service | URL / role |
|---------|------------|
| API | http://localhost:8000/docs |
| Streamlit | http://localhost:8501 |
| Scheduler | background (profile `jobs` / `full`) |

Live-reload override:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

Details: [docs/DOCKER.md](docs/DOCKER.md).

---

## Running tests, lint, and the demo

### Local

```bash
make test                  # pytest
make lint                  # ruff check
make demo                  # interactive guided demo
make demo-auto             # non-interactive
make help                  # all targets
```

Or directly:

```bash
pytest tests/ -q
ruff check api/ services/ core/ utils/ tests/ main.py config.py
ruff format --check api/ services/ core/ utils/ tests/ main.py config.py
python demo/demo.py --auto
```

### Docker

```bash
# Full stack (API + Streamlit + scheduler)
make docker-full
# or: docker compose --profile full up --build

# Smoke: health + search inside the API container
docker compose exec api curl -sf http://127.0.0.1:8000/health
docker compose exec api python -m pytest tests/ -q   # if deps match test needs

# Seed catalogs
docker compose exec api python main.py fetch --group stations
docker compose exec api python main.py fetch --group starlink
```

CI (GitHub Actions) runs lint, pytest on Python **3.11** and **3.12**, and a Docker
image build. See [`.github/workflows/ci.yml`](.github/workflows/ci.yml).

---

## Project layout

| Area | Location |
|------|----------|
| Business logic | `services/` |
| Orbital math / TLE | `core/` |
| HTTP API | `api/` |
| CLI | `main.py` |
| Streamlit | `dashboard.py` |
| TUI | `tui.py` |
| Config / env | `config.py`, [`.env.example`](.env.example) |
| Examples | [`examples/`](examples/) |
| Guided demo | [`demo/`](demo/) |
| Tests | `tests/` |

**Prefer extending `services/`** over duplicating logic in UIs or routers.

---

## Code style

Style is enforced by [**Ruff**](https://docs.astral.sh/ruff/) and configured in
[`ruff.toml`](ruff.toml) (line length **100**, target **py311**).

Guidelines:

- Python **3.9+** (CI uses 3.11/3.12)
- Clear names over clever one-liners
- Optional features (PDF, maps, rate limits, notifications) should **fail gracefully** when deps or config are missing
- Match existing patterns in `services/` and thin API routers
- Run `ruff format` on touched files before opening a PR

---

## Pull request workflow

### 1. Branch

Create a branch from `master` (or `main`):

| Prefix | Use for |
|--------|---------|
| `feat/` | New features |
| `fix/` | Bug fixes |
| `docs/` | Documentation only |
| `chore/` | Tooling, CI, deps |
| `test/` | Tests only |

Examples: `feat/pass-export-csv`, `fix/watchlist-empty-index`, `docs/contributing`.

### 2. Commit messages

Prefer short, imperative subjects (optionally with a conventional prefix):

```text
feat: add ICS export for watchlist scans

Include rise/set times in the calendar description so observers
can plan without opening the PDF report.
```

Good examples:

```text
fix: handle empty object index in /passes
docs: clarify webhook env vars in .env.example
test: cover debris index auto mode
chore: bump ruff target notes in CONTRIBUTING
```

Avoid vague messages like `update`, `fixes`, or `wip`.

### 3. Before you open a PR

1. Keep the change focused (one feature or fix per PR).
2. Add or update tests when behavior changes.
3. Update `docs/` or the README for user-facing features.
4. Do **not** commit secrets, `data/api_keys.txt`, large TLE dumps, `de421.bsp`, or `.env`.
5. Run `make test` (and `make lint` when practical).

### 4. Review

- Fill in the PR description: **what** changed and **why**.
- Link related issues if any.
- Maintainers may request small follow-ups; force-pushes on your feature branch are fine.
- CI must be green (or explained) before merge.

---

## Adding an observer profile

Named sites live in `config.py` → `OBSERVER_PROFILES`:

```python
OBSERVER_PROFILES = {
    "My Dark Site": {
        "name": "My Dark Site",
        "lat": 41.0,
        "lon": -77.0,
        "elevation": 500.0,
        "note": "Example",
    },
    # …
}
```

Use from CLI: `python main.py passes --name ISS --observer "My Dark Site"`.

No PR needed for private profiles — keep home coordinates out of commits if you
do not want them public.

---

## Adding a watchlist

1. **Code defaults** — edit `DEFAULT_WATCHLISTS` in `services/watchlist.py`
   (merged into `data/watchlists.json` without overwriting user lists).
2. **Runtime** — use `upsert_watchlist()` or see
   [`examples/custom_watchlist.py`](examples/custom_watchlist.py).
3. **JSON** — edit `data/watchlists.json` after the first run (gitignored).

Modes: `primary_vs_group`, `group_vs_group`, `pairs`.

---

## Reporting issues

Include:

- Command or URL that failed
- Python version
- Whether TLEs were fetched
- Relevant traceback (**without** API keys or webhook URLs)

---

## License

By contributing, you agree your changes are licensed under the MIT License.
