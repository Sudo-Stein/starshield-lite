# Contributing to StarShield Lite

Thanks for your interest! This project is a portfolio-grade personal SSA toolkit.
Small, focused contributions are welcome.

## Development setup

```bash
git clone https://github.com/Sudo-Stein/starshield-lite.git
cd starshield-lite
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev,pdf]"
```

## Running tests & lint

```bash
make test
make lint
# or:
pytest tests/ -q
ruff check api/ services/ core/ utils/ tests/
ruff format --check api/ services/ core/ utils/ tests/
```

## Showcase demo

```bash
make demo          # interactive
make demo-auto     # CI / recording friendly
# see demo/demo.md
```

CI runs the same checks on Python 3.11 and 3.12, plus a Docker image build.
See `.github/workflows/ci.yml`.

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

Prefer extending `services/` over duplicating logic in UIs.

## Pull requests

1. Keep changes focused (one feature or fix per PR).  
2. Add or update tests when behavior changes.  
3. Update `docs/` or README if you add user-facing features.  
4. Do not commit secrets, `data/api_keys.txt`, or large local TLE dumps.

## Code style

- Python 3.10+  
- Prefer clear names over clever one-liners  
- Optional features (PDF, maps, rate limits) should fail gracefully when deps are missing  

## Reporting issues

Include:

- Command or URL that failed  
- Python version  
- Whether TLEs were fetched  
- Relevant traceback (without API keys)

## License

By contributing, you agree your changes are licensed under the MIT License.
