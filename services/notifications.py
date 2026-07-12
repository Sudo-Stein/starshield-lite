"""Optional webhook notification system for StarShield Lite.

Design goals
------------
* Optional — core flows never depend on webhooks succeeding.
* Extensible — generic HTTP POST today; Discord / Slack payload formats ready.
* Event-driven — high-quality passes and MEDIUM/HIGH conjunctions.
* Non-blocking — default fire-and-forget via daemon threads.

Config sources (merged, highest wins last):
  1. Built-in defaults
  2. Environment (STARSHIELD_NOTIFY_*, STARSHIELD_WEBHOOK_URL*)
  3. data/notifications.json (or STARSHIELD_NOTIFY_FILE)

Quick start
-----------
  export STARSHIELD_WEBHOOK_URL=https://example.com/hook
  python main.py notify --cmd test
  python main.py notify --cmd list
"""

from __future__ import annotations

import json
import threading
import traceback
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Union
from urllib import error as urlerror
from urllib import request as urlrequest

from config import (
    DATA_DIR,
    NOTIFY_ASYNC,
    NOTIFY_CONFIG_FILE,
    NOTIFY_CONJ_RISKS,
    NOTIFY_ENABLED,
    NOTIFY_PASS_MIN_GRADE,
    NOTIFY_PASS_MIN_SCORE,
    NOTIFY_TIMEOUT_SEC,
    NOTIFY_WEBHOOK_URLS,
    __version__,
)

# Event type constants (stable API for filters / future channels)
EVENT_PASS_QUALITY = "pass.quality"
EVENT_CONJUNCTION = "conjunction.risk"
EVENT_TEST = "system.test"
EVENT_WATCHLIST_SUMMARY = "watchlist.summary"

ALL_EVENTS = (
    EVENT_PASS_QUALITY,
    EVENT_CONJUNCTION,
    EVENT_TEST,
    EVENT_WATCHLIST_SUMMARY,
)

_GRADE_ORDER = {"A": 4, "B": 3, "C": 2, "D": 1, "F": 0}

_DEFAULT_CONFIG: Dict[str, Any] = {
    "version": 1,
    "enabled": True,
    "events": {
        EVENT_PASS_QUALITY: {
            "enabled": True,
            "min_score": 70,
            "min_grade": "B",
        },
        EVENT_CONJUNCTION: {
            "enabled": True,
            "risks": ["HIGH", "MEDIUM"],
        },
        EVENT_WATCHLIST_SUMMARY: {
            "enabled": False,  # opt-in: one summary per scan even if no HIGH/MED
        },
        EVENT_TEST: {
            "enabled": True,
        },
    },
    "webhooks": [],
}


# ---------------------------------------------------------------------------
# Config load / save
# ---------------------------------------------------------------------------


def default_config() -> dict:
    return deepcopy(_DEFAULT_CONFIG)


def _env_webhook_entries() -> List[dict]:
    out = []
    for i, url in enumerate(NOTIFY_WEBHOOK_URLS):
        out.append(
            {
                "id": f"env-{i + 1}" if len(NOTIFY_WEBHOOK_URLS) > 1 else "env",
                "url": url,
                "enabled": True,
                "events": ["*"],
                "format": "generic",
            }
        )
    return out


def load_config(path: Optional[Path] = None) -> dict:
    """Load notifications config, merging defaults + env + file."""
    cfg = default_config()
    cfg["enabled"] = bool(NOTIFY_ENABLED)

    # Apply env event thresholds into defaults
    cfg["events"][EVENT_PASS_QUALITY]["min_score"] = float(NOTIFY_PASS_MIN_SCORE)
    cfg["events"][EVENT_PASS_QUALITY]["min_grade"] = str(NOTIFY_PASS_MIN_GRADE).upper()
    cfg["events"][EVENT_CONJUNCTION]["risks"] = list(NOTIFY_CONJ_RISKS)

    path = Path(path) if path else NOTIFY_CONFIG_FILE
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                if "enabled" in raw:
                    cfg["enabled"] = bool(raw["enabled"]) and bool(NOTIFY_ENABLED)
                if isinstance(raw.get("events"), dict):
                    for k, v in raw["events"].items():
                        if isinstance(v, dict):
                            cfg["events"].setdefault(k, {})
                            cfg["events"][k].update(v)
                if isinstance(raw.get("webhooks"), list):
                    cfg["webhooks"] = [w for w in raw["webhooks"] if isinstance(w, dict)]
        except Exception as exc:
            _log(f"config load failed ({path}): {exc}")

    # Env URLs always available as extra destinations (dedupe by URL)
    existing_urls = {str(w.get("url") or "").strip() for w in cfg["webhooks"]}
    for entry in _env_webhook_entries():
        if entry["url"] not in existing_urls:
            cfg["webhooks"].append(entry)
            existing_urls.add(entry["url"])

    return cfg


def save_config(cfg: dict, path: Optional[Path] = None) -> Path:
    path = Path(path) if path else NOTIFY_CONFIG_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    # Don't persist env-only ephemeral fields; write a clean snapshot
    out = {
        "version": int(cfg.get("version") or 1),
        "enabled": bool(cfg.get("enabled", True)),
        "events": cfg.get("events") or {},
        "webhooks": [
            w
            for w in (cfg.get("webhooks") or [])
            if not str(w.get("id", "")).startswith("env")
        ],
    }
    path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    return path


def ensure_config_file(path: Optional[Path] = None) -> Path:
    """Create a starter notifications.json if missing."""
    path = Path(path) if path else NOTIFY_CONFIG_FILE
    if not path.exists():
        cfg = default_config()
        cfg["enabled"] = bool(NOTIFY_ENABLED)
        # Seed empty webhook placeholder as documentation
        cfg["webhooks"] = [
            {
                "id": "example",
                "url": "https://example.com/your-webhook",
                "enabled": False,
                "events": ["*"],
                "format": "generic",
                "note": "Set enabled=true and replace URL, or use STARSHIELD_WEBHOOK_URL",
            }
        ]
        save_config(cfg, path)
    return path


def notifications_enabled(cfg: Optional[dict] = None) -> bool:
    cfg = cfg if cfg is not None else load_config()
    if not cfg.get("enabled", True):
        return False
    if not NOTIFY_ENABLED:
        return False
    return any(w.get("enabled", True) and w.get("url") for w in cfg.get("webhooks") or [])


def list_destinations(cfg: Optional[dict] = None) -> List[dict]:
    """Return webhook destinations with status (URLs partially redacted)."""
    cfg = cfg if cfg is not None else load_config()
    rows = []
    for w in cfg.get("webhooks") or []:
        url = str(w.get("url") or "")
        rows.append(
            {
                "id": w.get("id") or "?",
                "enabled": bool(w.get("enabled", True)),
                "format": w.get("format") or "generic",
                "events": w.get("events") or ["*"],
                "url_preview": _redact_url(url),
                "has_url": bool(url and "example.com" not in url),
            }
        )
    return rows


def status_summary(cfg: Optional[dict] = None) -> dict:
    cfg = cfg if cfg is not None else load_config()
    dests = list_destinations(cfg)
    active = [d for d in dests if d["enabled"] and d["has_url"]]
    return {
        "global_enabled": bool(cfg.get("enabled")) and bool(NOTIFY_ENABLED),
        "async": bool(NOTIFY_ASYNC),
        "config_file": str(NOTIFY_CONFIG_FILE),
        "destinations": len(dests),
        "active_destinations": len(active),
        "events": {
            k: {
                "enabled": bool(v.get("enabled", True)),
                **{kk: vv for kk, vv in v.items() if kk != "enabled"},
            }
            for k, v in (cfg.get("events") or {}).items()
        },
        "webhooks": dests,
    }


# ---------------------------------------------------------------------------
# Event building & filtering
# ---------------------------------------------------------------------------


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_event(
    event_type: str,
    *,
    title: str,
    message: str,
    data: Optional[dict] = None,
    source: str = "starshield",
) -> dict:
    return {
        "source": "starshield-lite",
        "version": __version__,
        "event": event_type,
        "timestamp": _utc_now_iso(),
        "title": title,
        "message": message,
        "origin": source,
        "data": data or {},
    }


def _event_allowed(event_type: str, cfg: dict) -> bool:
    rules = (cfg.get("events") or {}).get(event_type) or {}
    return bool(rules.get("enabled", True))


def _webhook_accepts(webhook: dict, event_type: str) -> bool:
    if not webhook.get("enabled", True):
        return False
    url = str(webhook.get("url") or "").strip()
    if not url or "example.com/your-webhook" in url:
        return False
    events = webhook.get("events") or ["*"]
    if "*" in events or event_type in events:
        return True
    return False


def _grade_meets(grade: str, min_grade: str) -> bool:
    g = str(grade or "F").upper()[:1]
    m = str(min_grade or "B").upper()[:1]
    return _GRADE_ORDER.get(g, 0) >= _GRADE_ORDER.get(m, 3)


def pass_meets_threshold(pass_data: dict, cfg: Optional[dict] = None) -> bool:
    cfg = cfg if cfg is not None else load_config()
    rules = (cfg.get("events") or {}).get(EVENT_PASS_QUALITY) or {}
    if not rules.get("enabled", True):
        return False
    q = pass_data.get("quality") or {}
    score = pass_data.get("quality_score")
    if score is None:
        score = q.get("score")
    grade = pass_data.get("quality_grade") or q.get("grade") or "?"
    min_score = float(rules.get("min_score", NOTIFY_PASS_MIN_SCORE))
    min_grade = str(rules.get("min_grade", NOTIFY_PASS_MIN_GRADE)).upper()
    try:
        score_f = float(score) if score is not None else -1.0
    except (TypeError, ValueError):
        score_f = -1.0
    return score_f >= min_score and _grade_meets(str(grade), min_grade)


def conj_meets_threshold(result: dict, cfg: Optional[dict] = None) -> bool:
    cfg = cfg if cfg is not None else load_config()
    rules = (cfg.get("events") or {}).get(EVENT_CONJUNCTION) or {}
    if not rules.get("enabled", True):
        return False
    risks = [str(r).upper() for r in (rules.get("risks") or list(NOTIFY_CONJ_RISKS))]
    risk = str(result.get("risk") or "").upper()
    return risk in risks


# ---------------------------------------------------------------------------
# Payload formatters (channel adapters)
# ---------------------------------------------------------------------------


def format_payload(event: dict, fmt: str = "generic") -> dict:
    """Transform an internal event into a channel-specific body."""
    fmt = (fmt or "generic").lower().strip()
    if fmt in ("discord", "discord_webhook"):
        return _format_discord(event)
    if fmt in ("slack", "slack_webhook"):
        return _format_slack(event)
    return dict(event)  # generic JSON


def _format_discord(event: dict) -> dict:
    risk = (event.get("data") or {}).get("risk")
    color = 0x00D4FF
    if risk == "HIGH":
        color = 0xFF4D4F
    elif risk == "MEDIUM":
        color = 0xFAAD14
    elif event.get("event") == EVENT_PASS_QUALITY:
        color = 0x52C41A
    embed = {
        "title": event.get("title") or "StarShield Lite",
        "description": event.get("message") or "",
        "color": color,
        "timestamp": event.get("timestamp"),
        "footer": {"text": f"starshield-lite · {event.get('event')}"},
        "fields": [],
    }
    data = event.get("data") or {}
    for key in (
        "object",
        "object_name",
        "pair",
        "quality",
        "risk",
        "min_dist_km",
        "tca",
        "culmination",
        "observer",
        "watchlist_id",
    ):
        if key in data and data[key] is not None:
            embed["fields"].append(
                {
                    "name": key.replace("_", " ").title(),
                    "value": str(data[key])[:256],
                    "inline": True,
                }
            )
    return {
        "content": None,
        "embeds": [embed],
        "username": "StarShield Lite",
    }


def _format_slack(event: dict) -> dict:
    data = event.get("data") or {}
    lines = [f"*{event.get('title')}*", event.get("message") or ""]
    for key, val in list(data.items())[:8]:
        if val is not None:
            lines.append(f"• `{key}`: {val}")
    return {
        "text": f"{event.get('title')}: {event.get('message')}",
        "blocks": [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "\n".join(lines)[:2900]},
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"starshield-lite · `{event.get('event')}` · {event.get('timestamp')}",
                    }
                ],
            },
        ],
    }


# ---------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------


def _log(msg: str) -> None:
    print(f"[notify] {msg}")


def _redact_url(url: str) -> str:
    if not url:
        return "(none)"
    if "://" not in url:
        return url[:40] + ("…" if len(url) > 40 else "")
    scheme, rest = url.split("://", 1)
    if "/" in rest:
        host, path = rest.split("/", 1)
        tail = path[-12:] if len(path) > 12 else path
        return f"{scheme}://{host}/…{tail}"
    return f"{scheme}://{rest[:24]}…"


def post_webhook(
    url: str,
    payload: dict,
    *,
    timeout: float = NOTIFY_TIMEOUT_SEC,
    headers: Optional[dict] = None,
) -> Dict[str, Any]:
    """Synchronous HTTP POST of JSON payload. Never raises."""
    body = json.dumps(payload, default=str).encode("utf-8")
    hdrs = {
        "Content-Type": "application/json",
        "User-Agent": f"StarShield-Lite/{__version__} (+notifications)",
        "Accept": "application/json, text/plain, */*",
    }
    if headers:
        hdrs.update(headers)
    req = urlrequest.Request(url, data=body, headers=hdrs, method="POST")
    try:
        with urlrequest.urlopen(req, timeout=timeout) as resp:
            code = getattr(resp, "status", None) or resp.getcode()
            raw = resp.read(500)
            return {
                "ok": 200 <= int(code) < 300,
                "status": int(code),
                "body": raw.decode("utf-8", errors="replace")[:200],
            }
    except urlerror.HTTPError as exc:
        try:
            detail = exc.read(200).decode("utf-8", errors="replace")
        except Exception:
            detail = str(exc)
        return {"ok": False, "status": int(exc.code), "body": detail, "error": str(exc)}
    except Exception as exc:
        return {"ok": False, "status": None, "body": "", "error": str(exc)}


def dispatch(
    event: dict,
    *,
    cfg: Optional[dict] = None,
    async_: Optional[bool] = None,
    wait: bool = False,
) -> Dict[str, Any]:
    """Send event to all matching webhooks.

    Returns a summary dict. When async (default), returns immediately with
    ``{"queued": True, ...}`` unless ``wait=True``.
    """
    cfg = cfg if cfg is not None else load_config()
    if not cfg.get("enabled", True) or not NOTIFY_ENABLED:
        return {"ok": False, "skipped": True, "reason": "notifications disabled"}

    event_type = event.get("event") or ""
    if not _event_allowed(event_type, cfg):
        return {
            "ok": False,
            "skipped": True,
            "reason": f"event '{event_type}' disabled",
        }

    targets = [w for w in (cfg.get("webhooks") or []) if _webhook_accepts(w, event_type)]
    if not targets:
        return {"ok": False, "skipped": True, "reason": "no active webhooks for event"}

    use_async = NOTIFY_ASYNC if async_ is None else async_
    if use_async and not wait:
        t = threading.Thread(
            target=_deliver_all,
            args=(event, targets),
            kwargs={},
            daemon=True,
            name=f"starshield-notify-{event_type}",
        )
        t.start()
        return {
            "ok": True,
            "queued": True,
            "targets": len(targets),
            "event": event_type,
        }

    return _deliver_all(event, targets)


def _deliver_all(event: dict, targets: Sequence[dict]) -> Dict[str, Any]:
    results = []
    for w in targets:
        url = str(w.get("url") or "").strip()
        fmt = w.get("format") or "generic"
        payload = format_payload(event, fmt)
        extra_headers = w.get("headers") if isinstance(w.get("headers"), dict) else None
        res = post_webhook(url, payload, headers=extra_headers)
        results.append(
            {
                "id": w.get("id"),
                "format": fmt,
                "url_preview": _redact_url(url),
                **res,
            }
        )
        if res.get("ok"):
            _log(f"sent {event.get('event')} → {w.get('id')} ({res.get('status')})")
        else:
            _log(
                f"FAILED {event.get('event')} → {w.get('id')}: "
                f"{res.get('error') or res.get('status')} {res.get('body', '')[:80]}"
            )
    ok_n = sum(1 for r in results if r.get("ok"))
    return {
        "ok": ok_n > 0,
        "queued": False,
        "sent": ok_n,
        "failed": len(results) - ok_n,
        "results": results,
        "event": event.get("event"),
    }


# ---------------------------------------------------------------------------
# High-level notifiers (integrate with passes / watchlists)
# ---------------------------------------------------------------------------


def _fmt_time(t: Any) -> str:
    if t is None:
        return "—"
    if hasattr(t, "strftime"):
        if getattr(t, "tzinfo", None) is None:
            t = t.replace(tzinfo=timezone.utc)
        return t.strftime("%Y-%m-%d %H:%M UTC")
    return str(t)


def notify_high_quality_passes(
    passes: Sequence[dict],
    *,
    object_name: str = "",
    location: Optional[dict] = None,
    source: str = "cli",
    async_: Optional[bool] = None,
    cfg: Optional[dict] = None,
) -> Dict[str, Any]:
    """Notify for each pass that meets quality thresholds. Non-fatal."""
    try:
        cfg = cfg if cfg is not None else load_config()
        if not notifications_enabled(cfg):
            return {"ok": False, "skipped": True, "reason": "no active destinations"}

        qualifying = [p for p in passes if pass_meets_threshold(p, cfg)]
        if not qualifying:
            return {"ok": True, "skipped": True, "reason": "no passes meet threshold", "n": 0}

        observer = (location or {}).get("name") or ""
        summaries = []
        # Cap to avoid webhook spam (best N)
        for p in qualifying[:5]:
            q = p.get("quality") or {}
            grade = p.get("quality_grade") or q.get("grade") or "?"
            score = p.get("quality_score")
            if score is None:
                score = q.get("score")
            culm = p.get("culmination") or {}
            rise = p.get("rise") or {}
            peak_t = culm.get("time") or rise.get("time")
            max_el = p.get("max_elevation")
            title = f"Pass alert · {object_name or 'object'} · {grade} {score}"
            parts = [
                f"High-quality pass of {object_name or 'object'}",
                f"grade {grade} (score {score})",
            ]
            if max_el is not None:
                parts.append(f"max elevation {float(max_el):.0f}°")
            parts.append(f"culmination {_fmt_time(peak_t)}")
            if observer:
                parts.append(f"from {observer}")
            message = " · ".join(parts)

            event = build_event(
                EVENT_PASS_QUALITY,
                title=title,
                message=message,
                source=source,
                data={
                    "object": object_name,
                    "quality": f"{grade} {score}",
                    "grade": grade,
                    "score": score,
                    "max_elevation": max_el,
                    "culmination": _fmt_time(peak_t),
                    "observer": observer,
                    "visible": p.get("visible"),
                },
            )
            summaries.append(dispatch(event, cfg=cfg, async_=async_))

        return {
            "ok": True,
            "n": len(qualifying),
            "notified": min(5, len(qualifying)),
            "results": summaries,
        }
    except Exception as exc:
        _log(f"notify_high_quality_passes error: {exc}")
        return {"ok": False, "error": str(exc)}


def notify_conjunction_events(
    report: dict,
    *,
    source: str = "cli",
    async_: Optional[bool] = None,
    cfg: Optional[dict] = None,
    include_summary: bool = True,
) -> Dict[str, Any]:
    """Notify for MEDIUM/HIGH approaches in a watchlist report. Non-fatal."""
    try:
        cfg = cfg if cfg is not None else load_config()
        if not notifications_enabled(cfg):
            return {"ok": False, "skipped": True, "reason": "no active destinations"}

        results = list(report.get("results") or [])
        hits = [r for r in results if conj_meets_threshold(r, cfg)]
        wl_id = report.get("watchlist_id") or ""
        wl_name = report.get("watchlist_name") or wl_id
        summary = report.get("summary") or {}

        dispatched = []
        for r in hits[:10]:
            risk = r.get("risk")
            pair = f"{r.get('sat1')} ↔ {r.get('sat2')}"
            dist = r.get("min_dist_km")
            title = f"Conjunction · {risk} · {pair}"
            message = (
                f"{risk} risk approach: {pair} · "
                f"{dist} km at TCA {_fmt_time(r.get('tca'))}"
            )
            if r.get("rel_velocity_kms") is not None:
                message += f" · v_rel {r['rel_velocity_kms']:.2f} km/s"
            if wl_name:
                message += f" · watchlist {wl_name}"

            event = build_event(
                EVENT_CONJUNCTION,
                title=title,
                message=message,
                source=source,
                data={
                    "risk": risk,
                    "pair": pair,
                    "sat1": r.get("sat1"),
                    "sat2": r.get("sat2"),
                    "min_dist_km": dist,
                    "tca": _fmt_time(r.get("tca")),
                    "rel_velocity_kms": r.get("rel_velocity_kms"),
                    "watchlist_id": wl_id,
                    "watchlist_name": wl_name,
                },
            )
            dispatched.append(dispatch(event, cfg=cfg, async_=async_))

        # Optional one-line summary when enabled or when there were hits
        sum_rules = (cfg.get("events") or {}).get(EVENT_WATCHLIST_SUMMARY) or {}
        if include_summary and (
            sum_rules.get("enabled") or (hits and sum_rules.get("enabled", False))
        ):
            event = build_event(
                EVENT_WATCHLIST_SUMMARY,
                title=f"Watchlist scan · {wl_name or wl_id}",
                message=(
                    f"Scan complete: HIGH={summary.get('HIGH')} "
                    f"MEDIUM={summary.get('MEDIUM')} LOW={summary.get('LOW')} · "
                    f"closest {summary.get('closest_km')} km "
                    f"({summary.get('closest_pair')})"
                ),
                source=source,
                data={
                    "watchlist_id": wl_id,
                    "HIGH": summary.get("HIGH"),
                    "MEDIUM": summary.get("MEDIUM"),
                    "LOW": summary.get("LOW"),
                    "closest_km": summary.get("closest_km"),
                    "closest_pair": summary.get("closest_pair"),
                    "pairs_scanned": report.get("pairs_scanned"),
                },
            )
            dispatched.append(dispatch(event, cfg=cfg, async_=async_))

        if not hits and not dispatched:
            return {
                "ok": True,
                "skipped": True,
                "reason": "no conjunctions meet risk threshold",
                "n": 0,
            }

        return {
            "ok": True,
            "n": len(hits),
            "notified": min(10, len(hits)),
            "results": dispatched,
        }
    except Exception as exc:
        _log(f"notify_conjunction_events error: {exc}")
        traceback.print_exc()
        return {"ok": False, "error": str(exc)}


def send_test_notification(
    *,
    message: str = "StarShield Lite webhook test",
    async_: bool = False,
    cfg: Optional[dict] = None,
) -> Dict[str, Any]:
    """Send a test event (synchronous by default so CLI can show result)."""
    cfg = cfg if cfg is not None else load_config()
    event = build_event(
        EVENT_TEST,
        title="StarShield Lite · test",
        message=message,
        source="cli",
        data={"hint": "If you received this, webhooks are configured correctly."},
    )
    return dispatch(event, cfg=cfg, async_=async_, wait=True)


def seed_example_config() -> Path:
    """Write starter notifications.json and return path."""
    return ensure_config_file()
