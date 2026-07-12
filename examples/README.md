# Examples

Short scripts that use StarShield Lite **from Python** — useful when you want to
integrate passes, watchlists, or exports into your own tools.

For a full interactive tour of the product (CLI banners, starmap HTML, PDF/ICS),
prefer the guided demo instead:

```bash
make demo
# or: python demo/demo.py
```

---

## Index

| Script | What it does | When to use it |
|--------|--------------|----------------|
| [`call_api_client.py`](call_api_client.py) | Calls health, object search, and passes over HTTP | Integrating with a running FastAPI server |
| [`custom_watchlist.py`](custom_watchlist.py) | Creates a sample watchlist and runs a short conjunction scan | Custom monitoring pairs/groups without editing JSON by hand |
| [`programmatic_export.py`](programmatic_export.py) | Predicts ISS passes and writes ICS + PDF | Building calendars/reports from your own code |
| [`demo_workflow.py`](demo_workflow.py) | Minimal passes → quality table → ICS | Quick non-interactive smoke check |
| [`demo.py`](demo.py) | Thin wrapper → [`demo/demo.py`](../demo/demo.py) | Same entry as `make demo` |

---

## Prerequisites

From the repo root, with a venv active:

```bash
pip install -e ".[pdf,dev]"
python main.py fetch --group stations   # required for pass examples
# optional — watchlist / richer demos:
python main.py fetch --group starlink
python main.py fetch --group visual
```

---

## Run

```bash
# --- API client (start the server first) ---
python main.py api
# in another terminal:
python examples/call_api_client.py

# --- Local services (no HTTP required) ---
python examples/custom_watchlist.py
python examples/programmatic_export.py
python examples/demo_workflow.py
```

| Script | Output |
|--------|--------|
| `programmatic_export.py` | `data/examples/` (ICS + PDF) |
| `demo_workflow.py` | `data/demo_workflow_passes.ics` |
| `custom_watchlist.py` | Console table + optional JSON under `data/` |

`data/` is gitignored — safe to generate locally.

---

## Tips

1. If an example says the object index is empty, run `make fetch` and retry.
2. PDF export needs the `pdf` extra: `pip install -e ".[pdf]"`.
3. With API keys enabled, set `STARSHIELD_API_KEY` before `call_api_client.py`.
4. More recipes: [docs/USAGE.md](../docs/USAGE.md) · package layout: [docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md).
