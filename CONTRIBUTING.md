# Contributing to StarShield Lite

Thanks for your interest! This project is a **portfolio-grade** personal space domain
awareness toolkit. Small, focused contributions are welcome.

## Development setup

```bash
git clone https://github.com/Sudo-Stein/starshield-lite.git
cd starshield-lite
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev,pdf]"
```

Optional: copy environment defaults for local/Docker runs:

```bash
cp .env.example .env
# Edit .env for webhooks, API keys, ports, etc.
```

## Running tests & lint

```bash
make test
make lint
```

Or directly:

```bash
pytest tests/ -q
ruff check api/ services/ core/ utils/ tests/ main.py config.py
ruff format --check api/ services/ core/ utils/ tests/ main.py config.py
```

**Code style** is defined in [`ruff.toml`](ruff.toml) (line length 100, target py311).
Run `ruff format` on touched files before opening a PR.

CI (GitHub Actions) runs lint, pytest on Python **3.11** and **3.12**, and a Docker
image build. See [`.github/workflows/ci.yml`](.github/workflows/ci.yml).

## Showcase demo

```bash
make demo          # interactive
make demo-auto     # non-interactive
# details: demo/demo.md
```

## Project layout (where to change things)

| Area | Location |
|------|----------|
| Business logic | `services/` |
| Orbital math / TLE | `core/` |
| HTTP API | `api/` |
| CLI | `main.py` |
| Streamlit | `dashboard.py` |
| TUI | `tui.py` |
| Config / env | `config.py`, `.env.example` |
| Examples | `examples/` |
| Guided demo | `demo/` |

**Prefer extending `services/`** over duplicating logic in UIs or routers.

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
No PR needed for private profiles—keep local changes out of commits if they
contain home addresses you do not want public.

## Adding a watchlist

1. **Code defaults** — edit `DEFAULT_WATCHLISTS` in `services/watchlist.py`
   (merged into `data/watchlists.json` without overwriting user lists).
2. **Runtime** — use `upsert_watchlist()` or see
   [`examples/custom_watchlist.py`](examples/custom_watchlist.py).
3. **JSON** — edit `data/watchlists.json` after the first run (gitignored).

Modes: `primary_vs_group`, `group_vs_group`, `pairs`.

## Pull request expectations

1. Keep changes focused (one feature or fix per PR).  
2. Add or update tests when behavior changes.  
3. Update `docs/` or README if you add user-facing features.  
4. Do **not** commit secrets, `data/api_keys.txt`, large TLE dumps, `de421.bsp`, or `.env`.  
5. Ensure `pytest tests/ -q` passes locally when practical.

## Code style guidelines

- Python 3.9+ (CI uses 3.11/3.12)  
- Clear names over clever one-liners  
- Optional features (PDF, maps, rate limits, notifications) should **fail gracefully** when deps or config are missing  
- Match existing patterns in `services/` and thin API routers  

## Reporting issues

Include:

- Command or URL that failed  
- Python version  
- Whether TLEs were fetched  
- Relevant traceback (**without** API keys or webhook URLs)

## License

By contributing, you agree your changes are licensed under the MIT License.
