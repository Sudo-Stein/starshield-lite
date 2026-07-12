# Examples

Practical scripts that use StarShield Lite **programmatically** (not the guided showcase).

For the full portfolio walkthrough, prefer:

```bash
make demo
# or: python demo/demo.py
```

## Scripts

| Script | What it shows |
|--------|----------------|
| [`call_api_client.py`](call_api_client.py) | Call the FastAPI server from Python (`httpx` or the built-in client) |
| [`custom_watchlist.py`](custom_watchlist.py) | Register a custom conjunction watchlist and run a short scan |
| [`programmatic_export.py`](programmatic_export.py) | Predict passes and write ICS / PDF without the CLI |
| [`demo.py`](demo.py) | Thin wrapper → `demo/demo.py` (showcase) |
| [`demo_workflow.py`](demo_workflow.py) | Minimal passes + ICS smoke path |

## Prerequisites

```bash
# From repo root, venv active
pip install -e ".[pdf,dev]"
python main.py fetch --group stations   # once
# optional for watchlist example:
python main.py fetch --group starlink
```

## Run

```bash
# API must be up for call_api_client.py
python main.py api &
# wait a few seconds, then:
python examples/call_api_client.py

python examples/custom_watchlist.py
python examples/programmatic_export.py
```

Outputs from the export example go under `data/examples/` (gitignored via `data/*`).
