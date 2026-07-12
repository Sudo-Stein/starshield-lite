# Changelog

All notable changes to **StarShield Lite** are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project aims to follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

---

## [0.2.0] — 2026-07-12

First public release: full multi-interface SSA toolkit with optional debris
awareness, webhooks, packaging, and ops hardening.

### Added

#### Core domain

- **Object Index** — multi-catalog search (stations, Starlink, visual, active) by name, alias, or NORAD
- **Pass prediction** with stargazer filtering (dark sky + sunlit satellite)
- **Pass quality scoring** — 0–100 score and letter grade with component breakdown
- **Conjunction watchlists** — adaptive TCA, relative velocity, HIGH/MEDIUM/LOW risk bands
- **Debris support** — optional CelesTrak debris groups (`debris`, `fengyun-1c-debris`, `iridium-33-debris`, …); ISS/stations vs debris scans; `/debris` API
- **Observer profiles** — Kingsland GA default plus named sites and custom lat/lon
- **SQLite history** — Grade B+ passes and MEDIUM/HIGH conjunctions

#### Visualization

- Streamlit **Starmap** with polar alt–az sky view and Plotly ground track
- **Linked Passes → Starmap** jump (culmination time, focus mode, pass segment highlight)
- **Minute scrubber** with ◀/▶ step and **Play/Pause** animation
- Side-by-side / tabs layouts for sky + ground; session-cached tracks for responsive scrubbing

#### Interfaces & ops

- **CLI** (`starshield` / `python main.py`) — status, fetch, passes, watchlist, debris, notify, export, schedule, …
- **Textual TUI**, **Streamlit** dashboard, **FastAPI** OpenAPI backend
- **Background scheduler** (APScheduler) for watchlist jobs
- **Docker Compose** multi-stage image, profiles (`ui`, `jobs`, `full`), healthchecks
- **GitHub Actions CI** — lint, pytest (3.11/3.12), Docker smoke

#### Security, packaging & integrations

- Optional **API key** auth (`X-API-Key`) on protected routes
- Configurable **per-IP rate limiting** with HTTP 429 and bucketed limits
- **Webhook notifications** for high-quality passes and MEDIUM/HIGH conjunctions (generic / Discord / Slack formats)
- **Export** — PDF reports (`fpdf2`) and ICS calendar files
- **pip-installable** package with console scripts: `starshield`, `starshield-api`, `starshield-dash`, `starshield-tui`
- Optional extras: `pdf`, `maps`, `dev`, `full`
- Documentation suite: README, USAGE, ARCHITECTURE, DOCKER, CONTRIBUTING, examples, screenshots

### Changed

- Default home observer: **Kingsland, GA**
- Services layer (`services/`) is the source of truth; UIs and API stay thin adapters
- Debris catalogs join the Object Index automatically when TLE caches exist (`STARSHIELD_INDEX_DEBRIS=auto`)

### Notes

- Educational / personal tool — not operational space-traffic authority software
- Debris, PDF maps (Cartopy), webhooks, and API keys are **optional** and fail gracefully when unused

---

## [0.1.0] — 2026-06

Early prototype: TLE fetch, basic passes, CLI and Streamlit experiments.
Superseded by **0.2.0**.

[Unreleased]: https://github.com/Sudo-Stein/starshield-lite/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/Sudo-Stein/starshield-lite/releases/tag/v0.2.0
