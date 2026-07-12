"""Tests for webhook notification service."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from services import notifications as n


@pytest.fixture
def cfg_tmp(tmp_path, monkeypatch):
    path = tmp_path / "notifications.json"
    monkeypatch.setattr(n, "NOTIFY_CONFIG_FILE", path)
    monkeypatch.setattr(n, "NOTIFY_ENABLED", True)
    monkeypatch.setattr(n, "NOTIFY_WEBHOOK_URLS", ())
    monkeypatch.setattr(n, "NOTIFY_ASYNC", False)
    return path


def test_default_and_load_config(cfg_tmp):
    cfg = n.load_config(cfg_tmp)
    assert cfg["enabled"] is True
    assert n.EVENT_PASS_QUALITY in cfg["events"]
    assert n.EVENT_CONJUNCTION in cfg["events"]
    assert cfg["webhooks"] == []


def test_env_urls_merged(cfg_tmp, monkeypatch):
    monkeypatch.setattr(
        n, "NOTIFY_WEBHOOK_URLS", ("https://hooks.example/a", "https://hooks.example/b")
    )
    cfg = n.load_config(cfg_tmp)
    assert len(cfg["webhooks"]) == 2
    assert all(w["enabled"] for w in cfg["webhooks"])


def test_ensure_config_file(cfg_tmp):
    path = n.ensure_config_file(cfg_tmp)
    assert path.exists()
    data = json.loads(path.read_text())
    assert "webhooks" in data


def test_pass_meets_threshold(cfg_tmp):
    cfg = n.load_config(cfg_tmp)
    good = {
        "quality_score": 85,
        "quality_grade": "A",
        "quality": {"score": 85, "grade": "A"},
    }
    bad = {
        "quality_score": 40,
        "quality_grade": "D",
        "quality": {"score": 40, "grade": "D"},
    }
    assert n.pass_meets_threshold(good, cfg)
    assert not n.pass_meets_threshold(bad, cfg)


def test_conj_meets_threshold(cfg_tmp):
    cfg = n.load_config(cfg_tmp)
    assert n.conj_meets_threshold({"risk": "HIGH"}, cfg)
    assert n.conj_meets_threshold({"risk": "MEDIUM"}, cfg)
    assert not n.conj_meets_threshold({"risk": "LOW"}, cfg)


def test_format_discord_and_slack():
    event = n.build_event(
        n.EVENT_CONJUNCTION,
        title="Conjunction · HIGH",
        message="ISS ↔ STARLINK · 5 km",
        data={"risk": "HIGH", "min_dist_km": 5.0, "pair": "ISS ↔ STARLINK"},
    )
    d = n.format_payload(event, "discord")
    assert "embeds" in d
    assert d["embeds"][0]["title"]
    s = n.format_payload(event, "slack")
    assert "blocks" in s
    g = n.format_payload(event, "generic")
    assert g["event"] == n.EVENT_CONJUNCTION


def test_dispatch_posts_to_webhook(cfg_tmp, monkeypatch):
    calls = []

    def fake_post(url, payload, timeout=8, headers=None):
        calls.append({"url": url, "payload": payload})
        return {"ok": True, "status": 200, "body": "ok"}

    monkeypatch.setattr(n, "post_webhook", fake_post)
    monkeypatch.setattr(n, "NOTIFY_WEBHOOK_URLS", ("https://hooks.example/test",))
    cfg = n.load_config(cfg_tmp)
    event = n.build_event(
        n.EVENT_TEST, title="t", message="m", data={}
    )
    res = n.dispatch(event, cfg=cfg, async_=False, wait=True)
    assert res["ok"]
    assert res["sent"] == 1
    assert calls[0]["url"] == "https://hooks.example/test"
    assert calls[0]["payload"]["event"] == n.EVENT_TEST


def test_dispatch_skips_when_disabled(cfg_tmp, monkeypatch):
    monkeypatch.setattr(n, "NOTIFY_ENABLED", False)
    monkeypatch.setattr(n, "NOTIFY_WEBHOOK_URLS", ("https://hooks.example/x",))
    cfg = n.load_config(cfg_tmp)
    cfg["enabled"] = False
    res = n.dispatch(
        n.build_event(n.EVENT_TEST, title="t", message="m"),
        cfg=cfg,
        async_=False,
    )
    assert res.get("skipped")


def test_notify_high_quality_passes(cfg_tmp, monkeypatch):
    sent = []

    def fake_dispatch(event, cfg=None, async_=None, wait=False):
        sent.append(event)
        return {"ok": True, "queued": False, "sent": 1}

    monkeypatch.setattr(n, "dispatch", fake_dispatch)
    monkeypatch.setattr(n, "NOTIFY_WEBHOOK_URLS", ("https://hooks.example/p",))
    cfg = n.load_config(cfg_tmp)

    passes = [
        {
            "quality_score": 88,
            "quality_grade": "A",
            "max_elevation": 62,
            "culmination": {"time": datetime(2026, 1, 1, 3, 0, tzinfo=timezone.utc)},
            "quality": {"score": 88, "grade": "A"},
        },
        {
            "quality_score": 30,
            "quality_grade": "F",
            "quality": {"score": 30, "grade": "F"},
        },
    ]
    res = n.notify_high_quality_passes(
        passes, object_name="ISS", location={"name": "Kingsland, GA"}, cfg=cfg
    )
    assert res["n"] == 1
    assert len(sent) == 1
    assert sent[0]["event"] == n.EVENT_PASS_QUALITY


def test_notify_conjunction_events(cfg_tmp, monkeypatch):
    sent = []

    def fake_dispatch(event, cfg=None, async_=None, wait=False):
        sent.append(event)
        return {"ok": True}

    monkeypatch.setattr(n, "dispatch", fake_dispatch)
    monkeypatch.setattr(n, "NOTIFY_WEBHOOK_URLS", ("https://hooks.example/c",))
    cfg = n.load_config(cfg_tmp)

    report = {
        "watchlist_id": "iss-starlink",
        "watchlist_name": "ISS vs Starlink",
        "pairs_scanned": 10,
        "results": [
            {
                "sat1": "ISS",
                "sat2": "STARLINK-1",
                "risk": "HIGH",
                "min_dist_km": 4.2,
                "tca": datetime(2026, 1, 2, 12, 0, tzinfo=timezone.utc),
                "rel_velocity_kms": 12.0,
            },
            {
                "sat1": "ISS",
                "sat2": "STARLINK-2",
                "risk": "LOW",
                "min_dist_km": 200.0,
                "tca": datetime(2026, 1, 2, 13, 0, tzinfo=timezone.utc),
            },
        ],
        "summary": {
            "HIGH": 1,
            "MEDIUM": 0,
            "LOW": 1,
            "closest_km": 4.2,
            "closest_pair": "ISS / STARLINK-1",
        },
    }
    res = n.notify_conjunction_events(report, cfg=cfg)
    assert res["n"] == 1
    assert len(sent) == 1
    assert sent[0]["event"] == n.EVENT_CONJUNCTION
    assert "HIGH" in sent[0]["title"]


def test_post_webhook_handles_failure(monkeypatch):
    def boom(*a, **k):
        raise ConnectionError("down")

    # Force urlopen to fail
    with patch("services.notifications.urlrequest.urlopen", side_effect=boom):
        res = n.post_webhook("https://example.invalid/hook", {"x": 1}, timeout=1)
    assert res["ok"] is False
    assert "error" in res


def test_redact_url():
    preview = n._redact_url("https://hooks.slack.com/services/T00/B00/XXXXSECRET")
    assert "hooks.slack.com" in preview
    assert "XXXXSECRET" not in preview or "…" in preview
