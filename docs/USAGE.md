# Usage recipes — StarShield Lite

## First run (local)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[pdf,dev]"          # recommended (console scripts)
# or: pip install -r requirements.txt

starshield status                    # or: python main.py status
starshield fetch --group stations
starshield fetch --group starlink
```

`status` shows observer, object index size, SQLite 7-day counts, and command hints.

Console entry points after `pip install -e .`:

| Command | What it launches |
|---------|------------------|
| `starshield` | CLI (Fire) |
| `starshield-api` | FastAPI / Uvicorn |
| `starshield-dash` | Streamlit dashboard |
| `starshield-tui` | Textual TUI |

---

## Search the catalog

```bash
python main.py search --search ISS
python main.py search --search 25544
python main.py search --search STARLINK-1008
```

API:

```bash
curl -s 'http://127.0.0.1:8000/objects/search?q=ISS&limit=10' | jq
```

---

## Best passes

```bash
# Quality-ranked, stargazer (dark + sunlit) when available
python main.py passes --name ISS --hours 168 --sort quality --show_breakdown

# All geometric passes ranked for observation usefulness
python main.py passes --name ISS --hours 336 --stargazer=False --sort quality

# Filter score
python main.py passes --name ISS --hours 336 --stargazer=False --min_score 50

# Other site
python main.py passes --name ISS --observer "Cherry Springs, PA" --hours 48
```

Chronological order:

```bash
python main.py passes --name ISS --sort time --stargazer=False
```

---

## Starmap (Streamlit)

```bash
python main.py dash
```

1. Sidebar → pick observer (or custom lat/lon)  
2. **Starmap** tab → objects e.g. `ISS, STARLINK-1008`  
3. Drag **time scrubber** to move markers  
4. Expand event table for rise / culm / set  

---

## Conjunction watchlist

```bash
python main.py watchlist --cmd list
python main.py watchlist --cmd scan --wl iss-starlink --hours 48
python main.py watchlist --cmd scan --wl iss-starlink --hours 24 --only_below
python main.py watchlist --cmd scan --wl iss-starlink --max_pairs 15 --csv data/wl.csv
```

API:

```bash
curl -s -X POST http://127.0.0.1:8000/watchlist/scan \
  -H 'Content-Type: application/json' \
  -d '{"watchlist_id":"iss-starlink","hours":24,"sample":20,"persist":true}' | jq
```

---

## History

```bash
python main.py history --cmd summary --days 7
python main.py history --cmd passes --days 14
python main.py history --cmd conj --object ISS --days 30
python main.py history --cmd runs
```

Disable persistence for a one-off:

```bash
python main.py passes --name ISS --persist=False
python main.py watchlist --cmd scan --wl iss-starlink --persist=False
```

---

## Scheduler

```bash
python main.py schedule --cmd list
python main.py schedule --cmd run --job iss-starlink-12h
python main.py schedule --cmd start          # blocking
```

Edit jobs in `data/schedules.json` (auto-created).

---

## TUI

```bash
python main.py tui
```

Keys: `1–5` tabs · `r` refresh · `q` quit  

Status tab: observer profile name · fetch TLEs · next ISS countdown.  
Passes: name/NORAD → Predict (quality column).  
Conjunctions: pair/group or watchlist scan.

---

## Ground track map (local, needs Cartopy)

```bash
pip install cartopy   # if not installed
python main.py map --name ISS --hours 6 --show=False
# PNG under data/
```

---



## API Authentication

Auth is **off by default**. To protect sensitive endpoints:

```bash
# Generate a key (appended to data/api_keys.txt)
python main.py apikey --cmd generate

# Enable auth for the API process
export STARSHIELD_API_KEY_REQUIRED=1
export STARSHIELD_API_KEYS='your-generated-key'   # and/or use data/api_keys.txt
export STARSHIELD_API_KEY='your-generated-key'    # for Streamlit client

python main.py api
```

| Access | Endpoints |
|--------|-----------|
| **Public** | `GET /health`, `GET /objects/*`, `GET /watchlist` |
| **Protected** | `GET /passes`, `POST /watchlist/scan`, `GET /history/*` |

```bash
# Public
curl -s http://127.0.0.1:8000/health | jq

# Protected — include header
curl -s 'http://127.0.0.1:8000/passes?object=ISS&hours=24&stargazer=false' \
  -H "X-API-Key: $STARSHIELD_API_KEY" | jq
```

In Swagger UI (`/docs`), click **Authorize** and paste the key when auth is enabled.

Streamlit with API mode:

```bash
export STARSHIELD_USE_API=1
export STARSHIELD_API_KEY=your-generated-key
python main.py dash
```

CLI/TUI call `services/` directly and do **not** need an API key.



## Export PDF and ICS

```bash
# Passes → calendar (import into Google/Apple Calendar)
python main.py export --cmd passes --name ISS --export_format ics \
  --hours 72 --stargazer=False --output data/iss_passes.ics

# Passes → PDF report (quality scores + table)
python main.py export --cmd passes --name ISS --export_format pdf \
  --hours 72 --sort quality --output data/iss_passes.pdf

# Watchlist scan → PDF
python main.py export --cmd watchlist --wl iss-starlink --export_format pdf \
  --hours 48 --max_pairs 20 --output data/wl_report.pdf
```

API (auth required when enabled):

```bash
curl -OJ "http://127.0.0.1:8000/export/passes.pdf?object=ISS&hours=72&stargazer=false" \
  -H "X-API-Key: $STARSHIELD_API_KEY"
curl -OJ "http://127.0.0.1:8000/export/passes.ics?object=ISS&hours=72" \
  -H "X-API-Key: $STARSHIELD_API_KEY"
```

Streamlit: after predicting passes or scanning a watchlist, use **Download PDF** / **Download ICS**.

---

## Starmap — linked sky + ground views (Streamlit)

The **Starmap** tab is the richest visualization surface:

1. **Jump from Passes / Status**  
   - On **Passes**, use the grade buttons (`#1 A · 55°`, …) or *Jump by rank*.  
   - On **Status**, use **Jump to Starmap ★** for the next ISS stargazer pass.  
   - Jump sets: object list, track window, scrubber at culmination, and **focus mode**.

2. **Linked views**  
   - Layouts: side-by-side, sky only, ground only, or tabs.  
   - Both views share the same scrubber time and focus highlight.  
   - Hover shows time, alt/az (sky), lat/lon (+ alt when available on ground), and quality when linked from Passes.

3. **Time scrubber**  
   - Minute resolution (not just hours).  
   - ◀ / ▶ step 1 minute; **Play / Pause** animates at 1–10 min per frame.  
   - Caption shows UTC, local time, and offset (`+2h 05m`).  
   - “Near scrub” callouts when rise/culm/set are close.

4. **Focus mode**  
   - Dims other objects, thickens the selected pass segment (rise→set), stars the scrub position.  
   - Clear focus returns to multi-object overview.

```bash
python main.py dash
# Streamlit → Passes → predict → click #1 grade button → Starmap tab
```

Tracks are cached in session state while objects/window/step are unchanged, so scrubbing stays responsive.

---

## Debris catalogs (optional)

Debris support is **optional**. Core passes/watchlists work without any debris TLEs.
When you fetch a debris group, it is cached under `data/` and automatically merged
into the Object Index (`STARSHIELD_INDEX_DEBRIS=auto`).

### Fetch debris TLEs

```bash
# Short alias → CelesTrak cosmos-2251-debris
python main.py debris --cmd fetch --group debris

# Other CelesTrak debris clouds
python main.py debris --cmd fetch --group fengyun-1c-debris
python main.py debris --cmd fetch --group iridium-33-debris

# Equivalent via generic fetch
python main.py fetch --group debris

# Status
python main.py debris --cmd list
python main.py debris --cmd status
```

### Conjunction checks vs debris

```bash
# Ad-hoc: primary object vs debris sample (24h window)
python main.py debris --cmd scan --name ISS --group debris --hours 24 --max_pairs 30

# Named watchlists (seeded into data/watchlists.json)
python main.py watchlist --cmd list
python main.py watchlist --cmd scan --wl iss-debris --hours 24
python main.py watchlist --cmd scan --wl iss-fengyun-debris --hours 24
python main.py watchlist --cmd scan --wl stations-debris --hours 24
```

Results reuse the same adaptive conjunction engine (TCA, min distance, relative
velocity, HIGH/MEDIUM/LOW). MEDIUM/HIGH hits:

- Log to SQLite history  
- Fire webhook notifications (if configured)  
- Export via PDF / HTML / CSV like other watchlist scans  

```bash
# PDF export of a debris watchlist scan
python main.py export --cmd watchlist --wl iss-debris --export_format pdf \
  --hours 24 --max_pairs 30 --output data/iss_debris.pdf
```

### Scheduler

Default job `iss-debris-24h` is **disabled**. Enable it after fetching debris:

```bash
# Edit data/schedules.json → set "enabled": true on iss-debris-24h
# Or run once:
python main.py schedule --cmd run --job iss-debris-24h
```

### API

```bash
# Public
curl -s http://127.0.0.1:8000/debris/groups | jq
curl -s http://127.0.0.1:8000/debris/status | jq
curl -s 'http://127.0.0.1:8000/debris/search?q=DEB&limit=10' | jq

# Protected when API keys enabled
curl -s -X POST http://127.0.0.1:8000/debris/fetch \
  -H 'Content-Type: application/json' \
  -d '{"group":"debris","force":true}'

curl -s -X POST http://127.0.0.1:8000/debris/scan \
  -H 'Content-Type: application/json' \
  -d '{"primary":"ISS","debris_group":"debris","hours":24,"sample":30}'
```

### Search

Debris objects appear in the normal object index once cached:

```bash
python main.py search --search DEB
python main.py search --search 34454   # example NORAD if present
```

---

## Webhook notifications

StarShield can POST JSON alerts when:

- A **high-quality pass** is found (default: score ≥ 70 / Grade B+)
- A watchlist approach is **MEDIUM** or **HIGH** risk

Notifications are **optional**. Failures never break passes, watchlists, or the scheduler.

### Quick setup (environment)

```bash
# Any HTTPS endpoint that accepts JSON POST
export STARSHIELD_WEBHOOK_URL=https://webhook.site/your-unique-id
# or multiple:
# export STARSHIELD_WEBHOOK_URLS=https://a.example/hook,https://b.example/hook

python main.py notify --cmd test     # send a test payload (sync)
python main.py notify --cmd list     # show destinations + event rules
```

### Config file

```bash
python main.py notify --cmd init     # creates data/notifications.json
```

Example `data/notifications.json`:

```json
{
  "version": 1,
  "enabled": true,
  "events": {
    "pass.quality": { "enabled": true, "min_score": 70, "min_grade": "B" },
    "conjunction.risk": { "enabled": true, "risks": ["HIGH", "MEDIUM"] },
    "watchlist.summary": { "enabled": false },
    "system.test": { "enabled": true }
  },
  "webhooks": [
    {
      "id": "my-hook",
      "url": "https://hooks.example.com/starshield",
      "enabled": true,
      "events": ["*"],
      "format": "generic"
    },
    {
      "id": "discord",
      "url": "https://discord.com/api/webhooks/…/…",
      "enabled": true,
      "events": ["pass.quality", "conjunction.risk"],
      "format": "discord"
    },
    {
      "id": "slack",
      "url": "https://hooks.slack.com/services/…",
      "enabled": true,
      "events": ["*"],
      "format": "slack"
    }
  ]
}
```

| `format` | Body style |
|----------|------------|
| `generic` | StarShield JSON (`event`, `title`, `message`, `data`, …) |
| `discord` | Discord webhook embeds |
| `slack` | Slack Block Kit–style payload |

### When notifications fire

| Source | Trigger |
|--------|---------|
| `python main.py passes …` | Each pass ≥ min_score / min_grade (max 5) |
| `python main.py watchlist --cmd scan` | Each MEDIUM/HIGH result (max 10) |
| `python main.py schedule` / Docker jobs | Same as watchlist scan |
| `GET /passes`, `POST /watchlist/scan` | Same rules, origin `api` |

### Disable

```bash
export STARSHIELD_NOTIFY_ENABLED=0
# or set "enabled": false in notifications.json
# or leave webhooks empty / disabled
```

### Generic payload shape

```json
{
  "source": "starshield-lite",
  "version": "0.2.0",
  "event": "conjunction.risk",
  "timestamp": "2026-07-12T12:00:00+00:00",
  "title": "Conjunction · HIGH · ISS ↔ STARLINK-…",
  "message": "HIGH risk approach: …",
  "origin": "scheduler",
  "data": { "risk": "HIGH", "min_dist_km": 8.2, "pair": "…" }
}
```

(`version` tracks `config.__version__` / package version.)

Delivery is **async by default** (daemon thread) so CLI/API latency stays low.  
Use `notify --cmd test` for a synchronous check.

## Advanced configuration notes

Copy defaults once:

```bash
cp .env.example .env
```

| Setting | Where | Meaning |
|---------|--------|---------|
| `STARSHIELD_INDEX_DEBRIS` | env | `auto` = index debris only when `data/*_tles.txt` exists; `1` = always list debris groups; `0` = never |
| `STARSHIELD_NOTIFY_*` | env / `data/notifications.json` | Webhook enablement, pass min score/grade, conjunction risk filter |
| `STARSHIELD_API_RATE_LIMIT*` | env | Per-IP quotas; set `STARSHIELD_API_RATE_LIMIT=0` to disable |
| `CONJ_THRESHOLD_KM` / `CONJ_HIGH_RISK_KM` | `config.py` | Risk bands: MEDIUM &lt; 50 km, HIGH &lt; 10 km (defaults) |
| `DB_LOG_PASS_MIN_SCORE` | `config.py` | Default 70 (≈ Grade B) for SQLite pass logging |
| `OBSERVER_PROFILES` | `config.py` | Named lat/lon sites for CLI / Streamlit |

### Common tweaks

**Debris in search (`STARSHIELD_INDEX_DEBRIS`)**  
Leave at `auto`. After you fetch a debris group, it appears in the Object Index
without restarting. Set `0` if you want passes/search to ignore debris caches.

```bash
python main.py debris --cmd fetch --group debris
# search now includes debris objects when INDEX_DEBRIS=auto
python main.py search --search DEB
```

**Rate limits**  
Three buckets: *public* (health/search), *default* (history), *heavy* (passes,
scans, export). For local scripting against a long-lived API:

```bash
export STARSHIELD_API_RATE_LIMIT=0
```

**Risk thresholds**  
Not env vars — edit `config.py` if you need research bands other than
MEDIUM &lt; 50 km / HIGH &lt; 10 km. Webhooks and history use the same bands.

**Webhooks**  
Set `STARSHIELD_WEBHOOK_URL` (or edit `data/notifications.json`) then:

```bash
python main.py notify --cmd test
```

Debris fetch does **not** happen automatically—run `python main.py debris --cmd fetch`
when you want those catalogs. See also [README Configuration](../README.md#configuration)
and [`.env.example`](../.env.example).

Programmatic usage samples: [`examples/`](../examples/).

## Tips

1. Pre-fetch **stations** + **starlink** so the object index is full.  
2. Use **quality sort + stargazer=False** if the current epoch has no naked-eye ISS windows.  
3. After a watchlist scan, check **OpenAPI** (`/docs`) and the **History** tab.  
4. Full stack in one command: `docker compose --profile full up --build`.  

