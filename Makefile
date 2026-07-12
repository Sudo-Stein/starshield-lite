# StarShield Lite — common development and demo commands
# Usage: make help

.PHONY: help install demo demo-auto demo-quick test lint \
	docker-up docker-full docker-down docker-logs \
	fetch fetch-demo status api dash tui clean-demo

PY ?= python
PIP ?= pip

help:
	@echo "StarShield Lite — make targets"
	@echo ""
	@echo "  install       pip install -e '.[pdf,dev]'"
	@echo "  demo          Guided interactive demo (demo/demo.py)"
	@echo "  demo-auto     Non-interactive demo"
	@echo "  demo-quick    Fast dry-run (short windows, no PDF)"
	@echo "  test          pytest"
	@echo "  lint          ruff check"
	@echo "  fetch         Download stations + starlink TLEs"
	@echo "  fetch-demo    stations + starlink + debris"
	@echo "  status        CLI status"
	@echo "  api           Start FastAPI"
	@echo "  dash          Start Streamlit dashboard"
	@echo "  tui           Start Textual TUI"
	@echo "  docker-up     API only (docker compose up --build)"
	@echo "  docker-full   API + Streamlit + scheduler"
	@echo "  docker-down   Stop compose stack"
	@echo "  clean-demo    Remove data/demo artifacts"
	@echo ""

install:
	$(PIP) install -e ".[pdf,dev]"

demo:
	$(PY) demo/demo.py

demo-auto:
	$(PY) demo/demo.py --auto

demo-quick:
	$(PY) demo/demo.py --quick --auto

test:
	$(PY) -m pytest tests/ -q

lint:
	ruff check api/ services/ core/ utils/ tests/ demo/ || true

fetch:
	$(PY) main.py fetch --group stations
	$(PY) main.py fetch --group starlink

fetch-demo: fetch
	$(PY) main.py debris --cmd fetch --group debris || true

status:
	$(PY) main.py status

api:
	$(PY) main.py api

dash:
	$(PY) main.py dash

tui:
	$(PY) main.py tui

docker-up:
	docker compose up --build

docker-full:
	docker compose --profile full up --build

docker-down:
	docker compose --profile full down

docker-logs:
	docker compose logs -f --tail=100

clean-demo:
	rm -rf data/demo
