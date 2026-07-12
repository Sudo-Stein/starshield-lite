"""StarShield Lite — CLI entry point (Rich + Fire)."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from config import (
    CONJ_HIGH_RISK_KM,
    CONJ_MAX_PAIRS,
    CONJ_REPORT_FILE,
    CONJ_STEPS_DEFAULT,
    CONJ_THRESHOLD_KM,
    DATA_DIR,
    DB_LOG_ENABLED,
    DB_PATH,
    DEFAULT_OBSERVER,
    LOCATION,
    PASS_HOURS_AHEAD,
    PASS_MIN_ELEVATION,
    STARGAZER_DEFAULT,
    STARGAZER_SUN_ALT_MAX,
    TLE_URLS,
    WATCHLIST_DEFAULT_ID,
)
from services.object_index import get_index, invalidate_index
from services.observers import format_observer, resolve_observer
from services.pass_quality import (
    format_quality_breakdown,
    grade_style,
    score_passes,
)
from services.watchlist import (
    export_results_csv,
    get_watchlist,
    list_watchlists,
    scan_watchlist,
)
from services.database import (
    ensure_db,
    log_passes_batch,
    log_watchlist_scan,
    query_conjunctions,
    query_recent_passes,
    query_watchlist_runs,
    summary_stats,
)
from core.propagator import load_satellites
from core.predictor import (
    find_satellite_by_name,
    format_pass_row,
    predict_passes,
    search_satellites,
)
from core.simulator import (
    check_conjunction,
    generate_html_report,
    open_latest_report,
    scan_conjunctions,
)
from core.tle_fetcher import fetch_tles
from core.visualizer import map_ground_track, map_multi_tracks
from utils.immutable_log import ImmutableLog

console = Console()
log = ImmutableLog()


def _tle_path(group: str) -> Path:
    return DATA_DIR / f"{group}_tles.txt"


def _ensure_tles(group: str) -> Optional[Path]:
    if group not in TLE_URLS:
        console.print(
            f"[red]Unknown group '{group}'. "
            f"Choose from: {', '.join(TLE_URLS)}[/red]"
        )
        return None
    path = _tle_path(group)
    if not path.exists():
        console.print(
            f"[yellow]No cached TLEs for '{group}'. Fetching…[/yellow]"
        )
        path = fetch_tles(group)
        log.append({"action": "fetch_tles", "group": group, "path": str(path)})
    return path


def _resolve_sat(sats, name: Optional[str], group: str):
    """Pick a satellite by name, or a sensible default for the group."""
    if name:
        sat = find_satellite_by_name(sats, name)
        if sat is None:
            hits = search_satellites(sats, name, limit=12)
            console.print(f"[red]No satellite matching '{name}' in {group}.[/red]")
            if hits:
                console.print("Closest matches:")
                for h in hits:
                    console.print(f"  • {h.name}")
            else:
                console.print(
                    "Tip: try [bold]--group stations --name ISS[/bold] "
                    "or [bold]--group starlink --name STARLINK-1234[/bold]"
                )
            return None
        return sat

    # Defaults when no name given
    if group == "stations":
        sat = find_satellite_by_name(sats, "ISS")
        if sat:
            return sat
    if group == "starlink":
        for s in sats:
            if "STARLINK" in s.name.upper():
                return s
    return sats[0] if sats else None


def _risk_style(risk: str) -> str:
    return {"HIGH": "bold red", "MEDIUM": "bold yellow", "LOW": "green"}.get(
        risk, "white"
    )




def _run_export(
    *,
    cmd: str,
    name: Optional[str],
    wl_id: str,
    export_format: str,
    output: Optional[str],
    hours: float,
    observer: dict,
    stargazer: bool,
    sort: str,
    min_score: float,
    max_passes: int,
    threshold: float,
    only_below: bool,
    max_pairs: int,
):
    """Export passes or watchlist results to PDF / ICS."""
    from pathlib import Path as _Path
    from services.export import (
        ExportError,
        passes_to_ics,
        passes_to_pdf,
        watchlist_to_pdf,
        write_bytes,
        write_ics,
        write_pdf,
    )
    from services.object_index import get_index
    from services.pass_quality import score_passes
    from services.watchlist import get_watchlist, scan_watchlist
    from core.predictor import predict_passes
    from services.observers import format_observer

    cmd = (cmd or "passes").lower().strip()
    fmt = (export_format or "pdf").lower().strip().lstrip(".")
    console.print(Panel("📤 StarShield Export", style="bold cyan"))

    if cmd in ("passes", "pass"):
        qname = name or "ISS"
        idx = get_index()
        rec = idx.resolve(qname)
        sat = idx.get_satellite(rec) if rec else None
        if sat is None:
            console.print(f"[red]Object not found: {qname}[/red]")
            return
        with console.status("[bold cyan]Predicting & scoring…"):
            raw = predict_passes(
                sat,
                location=observer,
                hours_ahead=hours,
                max_passes=max(max_passes * 2, 20),
                stargazer=stargazer,
            )
            sort_q = str(sort).lower() in ("quality", "score", "best")
            passes = score_passes(
                raw,
                location=observer,
                sat=sat,
                object_name=sat.name,
                min_score=float(min_score),
                sort=sort_q,
            )[:max_passes]

        default_name = f"passes_{rec.norad if rec else 'obj'}.{fmt}"
        out = _Path(output or str(DATA_DIR / default_name))

        try:
            if fmt == "ics":
                content = passes_to_ics(
                    passes, object_name=sat.name.strip(), location=observer
                )
                write_ics(content, out)
            elif fmt == "pdf":
                data = passes_to_pdf(
                    passes,
                    object_name=sat.name.strip(),
                    location=observer,
                    stargazer=stargazer,
                    hours=hours,
                )
                write_pdf(data, out)
            else:
                console.print(f"[red]Unknown format '{fmt}'. Use pdf or ics.[/red]")
                return
        except ExportError as exc:
            console.print(f"[red]{exc}[/red]")
            return

        console.print(f"[green]Wrote[/green] {out.resolve()}")
        console.print(
            f"[dim]{len(passes)} pass(es) · {format_observer(observer)} · {fmt}[/dim]"
        )
        log.append(
            {
                "action": "export_passes",
                "object": sat.name,
                "format": fmt,
                "path": str(out),
                "n": len(passes),
            }
        )
        return

    if cmd in ("watchlist", "wl", "conj"):
        if fmt != "pdf":
            console.print("[red]Watchlist export supports format=pdf only.[/red]")
            return
        w = get_watchlist(wl_id)
        if w is None:
            console.print(f"[red]Unknown watchlist '{wl_id}'[/red]")
            return
        if max_pairs:
            w.sample = min(w.sample, max_pairs)
        with console.status(f"[bold cyan]Scanning {w.id}…"):
            report = scan_watchlist(
                w,
                hours=hours,
                threshold_km=threshold,
                only_below=only_below,
                adaptive=True,
                steps=160,
                progress_every=0,
            )
        out = _Path(output or str(DATA_DIR / f"watchlist_{w.id}.pdf"))
        try:
            data = watchlist_to_pdf(report)
            write_pdf(data, out)
        except ExportError as exc:
            console.print(f"[red]{exc}[/red]")
            return
        console.print(f"[green]Wrote[/green] {out.resolve()}")
        console.print(
            f"[dim]pairs={report.get('pairs_scanned')} results={report['summary'].get('n_results')}[/dim]"
        )
        log.append(
            {
                "action": "export_watchlist",
                "watchlist": w.id,
                "path": str(out),
                "n": report["summary"].get("n_results"),
            }
        )
        return

    console.print(
        "[red]Unknown export cmd. Use --cmd passes|watchlist and --export_format pdf|ics[/red]"
    )
    console.print(
        "[dim]Examples:\\n"
        "  python main.py export --cmd passes --name ISS --export_format ics\\n"
        "  python main.py export --cmd passes --name ISS --export_format pdf --output report.pdf\\n"
        "  python main.py export --cmd watchlist --wl iss-starlink --export_format pdf[/dim]"
    )


def _run_debris(
    *,
    cmd: str,
    group: str,
    name: Optional[str],
    hours: float,
    threshold: float,
    high_risk: float,
    only_below: bool,
    max_pairs: int,
    csv_path: Optional[str],
    html: bool,
    persist: bool = True,
):
    """Debris catalog fetch / status / conjunction scans."""
    from config import DEBRIS_GROUPS, DB_LOG_ENABLED, DB_PATH
    from services.debris import (
        debris_index_stats,
        fetch_debris,
        is_debris_group,
        list_debris_groups,
        scan_primary_vs_debris,
    )
    from services.database import log_watchlist_scan
    from services.export import watchlist_to_pdf, write_pdf
    from services.notifications import notify_conjunction_events

    cmd = (cmd or "list").lower().strip()
    console.print(Panel("🛰 Debris awareness", style="bold cyan"))

    # Allow Fire-style: python main.py debris fetch --group debris
    if cmd in DEBRIS_GROUPS or is_debris_group(cmd):
        group = cmd
        cmd = "fetch"

    if cmd in ("list", "ls", "groups"):
        table = Table(title="Debris TLE catalogs (CelesTrak)")
        table.add_column("Group", style="cyan")
        table.add_column("Cached")
        table.add_column("~Objects")
        table.add_column("In index")
        table.add_column("Description")
        for row in list_debris_groups():
            table.add_row(
                row["group"],
                "yes" if row["cached"] else "no",
                str(row["objects_approx"]) if row["cached"] else "—",
                "yes" if row["in_index"] else "no",
                row["description"][:48],
            )
        console.print(table)
        console.print(
            "\n[dim]Fetch: python main.py debris --cmd fetch --group debris\n"
            "Scan:  python main.py debris --cmd scan --name ISS --group debris --hours 24\n"
            "Or:    python main.py watchlist --cmd scan --wl iss-debris --hours 24[/dim]"
        )
        return

    if cmd in ("status", "stats"):
        st = debris_index_stats()
        table = Table(title="Debris index status")
        table.add_column("Item", style="cyan")
        table.add_column("Value")
        table.add_row("Index objects", str(st.get("index_objects")))
        table.add_row("Debris-tagged objects", str(st.get("debris_objects")))
        table.add_row(
            "Debris groups loaded",
            ", ".join(st.get("debris_groups_loaded") or []) or "(none)",
        )
        table.add_row(
            "All groups loaded",
            ", ".join(st.get("groups_loaded") or []) or "(none)",
        )
        console.print(table)
        return

    if cmd in ("fetch", "download", "get"):
        g = group if is_debris_group(group) else "debris"
        if group and group not in ("stations", "starlink", "active", "visual"):
            # User may pass --group fengyun-1c-debris while default action group is stations
            if is_debris_group(group) or group in DEBRIS_GROUPS:
                g = group
        # Fire default group is "stations" — map to debris when still default
        if group == "stations":
            g = "debris"
            console.print(
                "[dim]Defaulting --group debris (override with --group fengyun-1c-debris etc.)[/dim]"
            )
        console.print(f"Fetching debris catalog [bold]{g}[/bold]…")
        try:
            path = fetch_debris(g, force=True, refresh_index=True)
        except Exception as exc:
            console.print(f"[red]Fetch failed:[/red] {exc}")
            return
        st = debris_index_stats()
        console.print(f"[green]Saved[/green] {path}")
        console.print(
            f"[dim]Index now: {st.get('index_objects')} objects · "
            f"debris-tagged ≈ {st.get('debris_objects')} · "
            f"debris groups: {', '.join(st.get('debris_groups_loaded') or []) or '—'}[/dim]"
        )
        log.append({"action": "debris_fetch", "group": g, "path": str(path)})
        return

    if cmd in ("scan", "check", "conj"):
        primary = name or "ISS"
        g = group if (is_debris_group(group) or group in DEBRIS_GROUPS) else "debris"
        if group == "stations":
            g = "debris"
        sample = max_pairs if max_pairs and max_pairs < 200 else 40
        console.print(
            f"[dim]{primary} vs debris group [bold]{g}[/bold] · "
            f"{hours:g}h · sample {sample} · threshold {threshold:g} km[/dim]"
        )
        with console.status(f"[bold cyan]Scanning {primary} vs {g}…"):
            report = scan_primary_vs_debris(
                primary=primary,
                debris_group=g,
                hours=hours,
                sample=sample,
                threshold_km=threshold,
                high_risk_km=high_risk,
                only_below=only_below,
            )
        if report.get("pairs_scanned", 0) == 0:
            console.print(
                "[yellow]No pairs resolved.[/yellow] "
                f"Fetch debris first: python main.py debris --cmd fetch --group {g}\n"
                f"Skipped: {(report.get('meta') or {}).get('skipped')}"
            )
            return

        summary = report.get("summary") or {}
        console.print(
            f"Scanned [bold]{report['pairs_scanned']}[/bold] pairs · "
            f"[red]HIGH {summary.get('HIGH')}[/red] · "
            f"[yellow]MEDIUM {summary.get('MEDIUM')}[/yellow] · "
            f"[green]LOW {summary.get('LOW')}[/green]"
        )
        results = report.get("results") or []
        table = Table(title=f"Debris conjunctions — {primary} vs {g}", show_lines=False)
        table.add_column("#", style="dim")
        table.add_column("Object 1", style="cyan")
        table.add_column("Object 2", style="cyan")
        table.add_column("TCA (UTC)")
        table.add_column("Min dist", justify="right")
        table.add_column("Risk", justify="center")
        for i, r in enumerate(results[:40], 1):
            tca = r.get("tca")
            tca_s = (
                tca.strftime("%Y-%m-%d %H:%M:%S")
                if hasattr(tca, "strftime")
                else str(tca)
            )
            table.add_row(
                str(i),
                str(r.get("sat1")),
                str(r.get("sat2")),
                tca_s,
                f"{r.get('min_dist_km'):.2f} km",
                f"[{_risk_style(r.get('risk'))}]{r.get('risk')}[/]",
            )
        if results:
            console.print(table)
        else:
            console.print("[yellow]No approaches in window (try longer --hours).[/yellow]")

        if csv_path:
            from services.watchlist import export_results_csv

            out = export_results_csv(results, Path(csv_path))
            console.print(f"[green]CSV:[/green] {out}")

        if html and results:
            from core.simulator import generate_html_report

            report_path = generate_html_report(results, open_browser=False)
            console.print(f"[green]HTML report:[/green] {report_path}")

        if persist and DB_LOG_ENABLED:
            try:
                db_info = log_watchlist_scan(report, source="cli-debris")
                if db_info.get("run_id"):
                    console.print(
                        f"[dim]DB: run #{db_info['run_id']} · "
                        f"{db_info.get('events_logged')} MEDIUM/HIGH → {DB_PATH.name}[/dim]"
                    )
            except Exception as exc:
                console.print(f"[dim]DB log skipped: {exc}[/dim]")

        try:
            nres = notify_conjunction_events(report, source="cli-debris")
            n_n = nres.get("notified") or nres.get("n") or 0
            if n_n and not nres.get("skipped"):
                console.print(f"[dim]Notify: queued {n_n} conjunction alert(s)[/dim]")
        except Exception as exc:
            console.print(f"[dim]Notify skipped: {exc}[/dim]")

        try:
            if results:
                pdf_path = DATA_DIR / f"debris_{g}_{primary.replace(' ', '_')}.pdf"
                write_pdf(watchlist_to_pdf(report), pdf_path)
                console.print(f"[dim]PDF: {pdf_path}[/dim]")
        except Exception:
            pass

        log.append(
            {
                "action": "debris_scan",
                "primary": primary,
                "group": g,
                "hours": hours,
                "pairs": report.get("pairs_scanned"),
                "HIGH": summary.get("HIGH"),
                "MEDIUM": summary.get("MEDIUM"),
                "closest_km": summary.get("closest_km"),
            }
        )
        return

    console.print(
        f"[red]Unknown debris cmd '{cmd}'. "
        "Use: list | status | fetch | scan[/red]"
    )


def _run_notify(*, cmd: str):
    """List / test / init webhook notifications."""
    from services.notifications import (
        ensure_config_file,
        list_destinations,
        load_config,
        send_test_notification,
        status_summary,
    )
    from config import (
        NOTIFY_CONFIG_FILE,
        NOTIFY_ENABLED,
        NOTIFY_WEBHOOK_URLS,
    )

    cmd = (cmd or "list").lower().strip()
    console.print(Panel("🔔 Notifications", style="bold cyan"))

    if cmd in ("init", "seed", "setup"):
        path = ensure_config_file()
        console.print(f"[green]Config ready:[/green] {path}")
        console.print(
            "[dim]Edit webhooks[].url, set enabled=true, or:\n"
            "  export STARSHIELD_WEBHOOK_URL=https://hooks.example/…\n"
            "  python main.py notify --cmd test[/dim]"
        )
        return

    if cmd in ("list", "ls", "status", "show"):
        cfg = load_config()
        st = status_summary(cfg)
        table = Table(title="Notification status")
        table.add_column("Item", style="cyan")
        table.add_column("Value")
        table.add_row("Global enabled", str(st["global_enabled"]))
        table.add_row("Env NOTIFY_ENABLED", str(NOTIFY_ENABLED))
        table.add_row("Config file", st["config_file"])
        table.add_row("Async delivery", str(st["async"]))
        table.add_row(
            "Destinations",
            f"{st['active_destinations']} active / {st['destinations']} total",
        )
        env_urls = len(NOTIFY_WEBHOOK_URLS)
        table.add_row("Env webhook URLs", str(env_urls))
        console.print(table)

        ev = Table(title="Event rules")
        ev.add_column("Event")
        ev.add_column("Enabled")
        ev.add_column("Filters")
        for name, rules in (st.get("events") or {}).items():
            filt = {
                k: v
                for k, v in rules.items()
                if k != "enabled"
            }
            ev.add_row(
                name,
                "yes" if rules.get("enabled", True) else "no",
                ", ".join(f"{k}={v}" for k, v in filt.items()) or "—",
            )
        console.print(ev)

        dests = list_destinations(cfg)
        if dests:
            wt = Table(title="Webhooks")
            wt.add_column("ID")
            wt.add_column("On")
            wt.add_column("Format")
            wt.add_column("Events")
            wt.add_column("URL")
            for d in dests:
                wt.add_row(
                    str(d["id"]),
                    "yes" if d["enabled"] else "no",
                    str(d["format"]),
                    ",".join(d["events"]) if isinstance(d["events"], list) else str(d["events"]),
                    d["url_preview"],
                )
            console.print(wt)
        else:
            console.print(
                "[yellow]No webhooks configured.[/yellow]\n"
                "  export STARSHIELD_WEBHOOK_URL=https://…\n"
                "  or: python main.py notify --cmd init"
            )
        console.print(
            f"\n[dim]Test: python main.py notify --cmd test\n"
            f"Config: {NOTIFY_CONFIG_FILE}[/dim]"
        )
        return

    if cmd in ("test", "ping", "send"):
        cfg = load_config()
        dests = [d for d in list_destinations(cfg) if d["enabled"] and d["has_url"]]
        if not dests:
            console.print(
                "[yellow]No active webhook destinations.[/yellow]\n"
                "Set STARSHIELD_WEBHOOK_URL or edit data/notifications.json, "
                "then retry."
            )
            return
        console.print(
            f"Sending test to [bold]{len(dests)}[/bold] destination(s)…"
        )
        res = send_test_notification(
            message="StarShield Lite webhook test — if you see this, config works.",
            async_=False,
            cfg=cfg,
        )
        if res.get("skipped"):
            console.print(f"[yellow]Skipped:[/yellow] {res.get('reason')}")
            return
        for r in res.get("results") or []:
            if r.get("ok"):
                console.print(
                    f"  [green]OK[/green] {r.get('id')} → "
                    f"{r.get('url_preview')} ({r.get('status')})"
                )
            else:
                console.print(
                    f"  [red]FAIL[/red] {r.get('id')} → "
                    f"{r.get('error') or r.get('status')} "
                    f"{(r.get('body') or '')[:80]}"
                )
        log.append(
            {
                "action": "notify_test",
                "sent": res.get("sent"),
                "failed": res.get("failed"),
            }
        )
        return

    console.print(
        f"[red]Unknown notify cmd '{cmd}'. Use: list | status | test | init[/red]"
    )


def _run_apikey(*, cmd: str):
    """Generate / list API keys for FastAPI auth."""
    from api.security import (
        generate_api_key,
        get_valid_keys,
        list_stored_keys_masked,
    )
    from config import API_KEY_REQUIRED, API_KEYS_FILE

    cmd = (cmd or "list").lower().strip()
    console.print(Panel("🔑 API Keys", style="bold cyan"))
    console.print(
        f"[dim]Auth required: {API_KEY_REQUIRED} · keys file: {API_KEYS_FILE}[/dim]\n"
    )

    if cmd in ("list", "ls", "status"):
        masked = list_stored_keys_masked()
        table = Table(title="Configured API keys")
        table.add_column("#")
        table.add_column("Preview")
        table.add_column("Length")
        for i, row in enumerate(masked, 1):
            table.add_row(str(i), row["preview"], str(row["length"]))
        if not masked:
            console.print(
                "[yellow]No keys configured.[/yellow] "
                "Run: python main.py apikey --cmd generate"
            )
        else:
            console.print(table)
        console.print(
            "\n[dim]Enable auth:\n"
            "  export STARSHIELD_API_KEY_REQUIRED=1\n"
            "  export STARSHIELD_API_KEY=<key>\n"
            "Header: X-API-Key: <key>[/dim]"
        )
        return

    if cmd in ("generate", "gen", "new", "create"):
        key = generate_api_key(persist=True, label="cli-generated")
        console.print("[green]Generated API key (saved to api_keys file):[/green]")
        console.print(f"  [bold]{key}[/bold]")
        console.print(
            "\n[dim]Enable auth:\n"
            "  export STARSHIELD_API_KEY_REQUIRED=1\n"
            f"  export STARSHIELD_API_KEY={key}\n"
            "  python main.py api[/dim]"
        )
        log.append({"action": "apikey_generate", "keys_now": len(get_valid_keys())})
        return

    console.print(
        f"[red]Unknown apikey cmd '{cmd}'. Use: list | generate[/red]"
    )


def _run_schedule(
    *,
    cmd: str,
    job_id: Optional[str],
    foreground: bool,
    immediately: bool,
):
    """Manage background watchlist scheduler."""
    from services.scheduler import (
        list_jobs,
        run_job_once,
        set_job_enabled,
        start_scheduler,
    )
    from config import SCHEDULE_FILE, SCHEDULE_ENABLED

    cmd = (cmd or "list").lower().strip()
    console.print(Panel("⏱ StarShield Scheduler", style="bold cyan"))
    console.print(
        f"[dim]Config: {SCHEDULE_FILE} · "
        f"enabled={SCHEDULE_ENABLED}[/dim]\n"
    )

    if cmd in ("list", "ls", "status"):
        jobs = list_jobs()
        table = Table(title="Scheduled jobs")
        table.add_column("ID", style="cyan")
        table.add_column("Name")
        table.add_column("Watchlist")
        table.add_column("Every")
        table.add_column("On")
        table.add_column("Last run")
        for j in jobs:
            hrs = j.get("interval_hours") or (j.get("interval_seconds", 0) / 3600)
            table.add_row(
                j.get("id", ""),
                j.get("name", ""),
                j.get("watchlist_id", ""),
                f"{hrs:g}h",
                "yes" if j.get("enabled", True) else "no",
                (j.get("last_run") or "—")[:19],
            )
        if not jobs:
            console.print("[yellow]No jobs configured.[/yellow]")
        else:
            console.print(table)
        console.print(
            "\n[dim]Start: python main.py schedule --cmd start\n"
            "Run once: python main.py schedule --cmd run --job iss-starlink-12h[/dim]"
        )
        return

    if cmd in ("start", "run-loop", "serve"):
        console.print(
            "[cyan]Starting scheduler (blocking). Ctrl+C to stop.[/cyan]\n"
            "[dim]Docker: docker compose --profile jobs up scheduler[/dim]"
        )
        start_scheduler(foreground=True, run_immediately=immediately)
        return

    if cmd in ("run", "once", "fire"):
        jid = job_id or "iss-starlink-12h"
        console.print(f"[cyan]Running job [bold]{jid}[/bold] once…[/cyan]")
        result = run_job_once(jid)
        if result.get("ok"):
            console.print(
                f"[green]OK[/green] pairs={result.get('pairs_scanned')} · "
                f"closest={result.get('closest_km')} km · "
                f"H/M/L={result.get('HIGH')}/{result.get('MEDIUM')}/{result.get('LOW')} · "
                f"db_run={result.get('db_run_id')}"
            )
        else:
            console.print(f"[red]Failed:[/red] {result.get('error')}")
        log.append({"action": "schedule_cli_run", **result})
        return

    if cmd in ("enable", "disable"):
        jid = job_id or "iss-starlink-12h"
        ok = set_job_enabled(jid, enabled=(cmd == "enable"))
        if ok:
            console.print(f"[green]Job {jid} {cmd}d.[/green]")
        else:
            console.print(f"[red]Job '{jid}' not found.[/red]")
        return

    if cmd in ("stop",):
        console.print(
            "[yellow]Stop is only needed for a running foreground scheduler "
            "(Ctrl+C) or `docker compose stop scheduler`.[/yellow]"
        )
        return

    console.print(
        f"[red]Unknown schedule cmd '{cmd}'. "
        "Use: list | start | run | enable | disable | stop[/red]"
    )


def _run_history(
    *,
    cmd: str,
    days: int,
    object_name: Optional[str],
    wl_id: str,
):
    """Query SQLite history."""
    cmd = (cmd or "summary").lower().strip()
    ensure_db()
    console.print(f"[dim]Database: {DB_PATH} · logging={'on' if DB_LOG_ENABLED else 'off'}[/dim]\n")

    if cmd in ("summary", "stats", "status"):
        s = summary_stats(days=days)
        table = Table(title=f"History summary — last {days}d")
        table.add_column("Metric", style="cyan")
        table.add_column("Value")
        for k, v in s.items():
            if k == "db_path":
                continue
            table.add_row(k, str(v))
        console.print(table)
        return

    if cmd in ("passes", "pass"):
        rows = query_recent_passes(
            limit=30, object_name=object_name, days=days
        )
        table = Table(title=f"Logged passes — last {days}d")
        table.add_column("When")
        table.add_column("Object")
        table.add_column("Q")
        table.add_column("Max el")
        table.add_column("Observer")
        table.add_column("Culm UTC")
        for r in rows:
            table.add_row(
                (r.get("logged_at") or "")[:19],
                r.get("object_name") or "",
                f"{r.get('quality_grade') or '—'} {r.get('quality_score') or ''}",
                f"{r.get('max_elevation'):.1f}°" if r.get("max_elevation") is not None else "—",
                r.get("observer_name") or "—",
                (r.get("culm_utc") or "")[:19],
            )
        if not rows:
            console.print("[yellow]No passes logged yet (need Grade B+).[/yellow]")
        else:
            console.print(table)
        return

    if cmd in ("conj", "conjunctions", "events"):
        rows = query_conjunctions(
            object_name=object_name, days=days, limit=40
        )
        table = Table(title=f"Conjunction events — last {days}d")
        table.add_column("TCA")
        table.add_column("Pair")
        table.add_column("Dist")
        table.add_column("Risk")
        table.add_column("Watchlist")
        for r in rows:
            table.add_row(
                (r.get("tca_utc") or "")[:19],
                f"{r.get('sat1')} ↔ {r.get('sat2')}",
                f"{r.get('min_dist_km')} km" if r.get("min_dist_km") is not None else "—",
                r.get("risk") or "—",
                r.get("watchlist_id") or "—",
            )
        if not rows:
            console.print(
                "[yellow]No MEDIUM/HIGH conjunctions logged yet.[/yellow]"
            )
        else:
            console.print(table)
        return

    if cmd in ("runs", "watchlist-runs"):
        rows = query_watchlist_runs(
            watchlist_id=wl_id if wl_id != WATCHLIST_DEFAULT_ID else None,
            limit=20,
        )
        # If user passed default id, still show all unless they want filter —
        # show all runs by default
        if not rows:
            rows = query_watchlist_runs(limit=20)
        table = Table(title="Watchlist runs")
        table.add_column("ID")
        table.add_column("Watchlist")
        table.add_column("Started")
        table.add_column("Pairs")
        table.add_column("H/M/L")
        table.add_column("Closest")
        for r in rows:
            table.add_row(
                str(r.get("id")),
                r.get("watchlist_id") or "",
                (r.get("started_at") or "")[:19],
                str(r.get("pairs_scanned") or "—"),
                f"{r.get('n_high') or 0}/{r.get('n_medium') or 0}/{r.get('n_low') or 0}",
                f"{r.get('closest_km')} km" if r.get("closest_km") is not None else "—",
            )
        if not rows:
            console.print("[yellow]No watchlist runs logged yet.[/yellow]")
        else:
            console.print(table)
        return

    console.print(
        f"[red]Unknown history cmd '{cmd}'. "
        "Use: summary | passes | conj | runs[/red]"
    )


def _run_watchlist(
    *,
    cmd: str,
    wl_id: str,
    hours: float,
    threshold: float,
    high_risk: float,
    only_below: bool,
    max_pairs: int,
    csv_path: Optional[str],
    html: bool,
    persist: bool = True,
):
    """List or scan conjunction watchlists."""
    cmd = (cmd or "list").lower().strip()

    if cmd in ("list", "ls", "show"):
        wls = list_watchlists()
        table = Table(title="Conjunction Watchlists")
        table.add_column("ID", style="cyan")
        table.add_column("Name")
        table.add_column("Mode")
        table.add_column("Description")
        for w in wls:
            table.add_row(w.id, w.name, w.mode, w.description[:60])
        console.print(table)
        console.print(
            f"\n[dim]Scan: python main.py watchlist --cmd scan --wl {WATCHLIST_DEFAULT_ID} "
            f"--hours 48[/dim]"
        )
        if cmd == "show" and wl_id:
            w = get_watchlist(wl_id)
            if w:
                console.print_json(data=w.to_dict())
        return

    if cmd != "scan":
        console.print(f"[red]Unknown watchlist cmd '{cmd}'. Use list|scan|show.[/red]")
        return

    w = get_watchlist(wl_id)
    if w is None:
        console.print(f"[red]Unknown watchlist '{wl_id}'.[/red]")
        console.print("Available:", ", ".join(x.id for x in list_watchlists()))
        return

    # Cap sample from max_pairs for speed if user set a low cap
    if w.mode in ("primary_vs_group", "group_vs_group") and max_pairs:
        w.sample = min(w.sample, max_pairs)

    console.print(
        f"[dim]Watchlist [bold]{w.id}[/bold] — {w.name} · "
        f"{hours:g}h · threshold {threshold:g} km · "
        f"only_below={only_below}[/dim]"
    )
    with console.status(f"[bold cyan]Scanning watchlist {w.id}…"):
        report = scan_watchlist(
            w,
            hours=hours,
            threshold_km=threshold,
            high_risk_km=high_risk,
            only_below=only_below,
            adaptive=True,
            steps=min(CONJ_STEPS_DEFAULT, 220),
            progress_every=15,
        )

    results = report["results"]
    summary = report["summary"]
    console.print(
        f"Scanned [bold]{report['pairs_scanned']}[/bold] pairs · "
        f"results [bold]{summary['n_results']}[/bold] · "
        f"[red]HIGH {summary['HIGH']}[/red] · "
        f"[yellow]MEDIUM {summary['MEDIUM']}[/yellow] · "
        f"[green]LOW {summary['LOW']}[/green]"
    )
    if report["meta"].get("skipped"):
        console.print(f"[dim]Skipped: {report['meta']['skipped']}[/dim]")

    if not results:
        console.print(
            "[yellow]No approaches to report "
            "(try --only_below=False or raise --threshold).[/yellow]"
        )
        log.append(
            {
                "action": "watchlist_scan",
                "watchlist": w.id,
                "hours": hours,
                "pairs": report["pairs_scanned"],
                "n_results": 0,
            }
        )
        return

    table = Table(title=f"Watchlist scan — {w.name}", show_lines=False)
    table.add_column("#", style="dim")
    table.add_column("Object 1", style="cyan")
    table.add_column("Object 2", style="cyan")
    table.add_column("TCA (UTC)")
    table.add_column("Min dist", justify="right")
    table.add_column("Rel v", justify="right")
    table.add_column("Risk", justify="center")

    for i, r in enumerate(results[:40], 1):
        tca = r["tca"]
        tca_s = (
            tca.strftime("%Y-%m-%d %H:%M:%S")
            if hasattr(tca, "strftime")
            else str(tca)
        )
        rv = r.get("rel_velocity_kms")
        rv_s = f"{rv:.2f} km/s" if rv is not None else "—"
        risk = r["risk"]
        table.add_row(
            str(i),
            r["sat1"],
            r["sat2"],
            tca_s,
            f"{r['min_dist_km']:.2f} km",
            rv_s,
            f"[{_risk_style(risk)}]{risk}[/]",
        )
    console.print(table)

    best = results[0]
    console.print(
        f"\nClosest: [bold]{best['sat1']}[/bold] ↔ [bold]{best['sat2']}[/bold] · "
        f"[{_risk_style(best['risk'])}]{best['risk']}[/] · "
        f"[bold]{best['min_dist_km']} km[/bold] · "
        f"v_rel={best.get('rel_velocity_kms')} km/s · TCA {best['tca']}"
    )

    if csv_path:
        out = export_results_csv(results, Path(csv_path))
        console.print(f"[green]CSV:[/green] {out}")

    if html:
        report_path = generate_html_report(results, open_browser=False)
        console.print(f"[green]HTML report:[/green] {report_path}")

    db_info = {"run_id": None, "events_logged": 0}
    if persist and DB_LOG_ENABLED:
        try:
            db_info = log_watchlist_scan(report, source="cli")
            if db_info.get("run_id"):
                console.print(
                    f"[dim]DB: watchlist run #{db_info['run_id']} · "
                    f"{db_info['events_logged']} MEDIUM/HIGH event(s) → {DB_PATH.name}[/dim]"
                )
        except Exception as exc:
            console.print(f"[dim]DB log skipped: {exc}[/dim]")

    notify_info: dict = {}
    try:
        from services.notifications import notify_conjunction_events

        notify_info = notify_conjunction_events(report, source="cli")
        n_n = notify_info.get("notified") or notify_info.get("n") or 0
        if n_n and not notify_info.get("skipped"):
            console.print(
                f"[dim]Notify: queued {n_n} conjunction alert(s)[/dim]"
            )
    except Exception as exc:
        console.print(f"[dim]Notify skipped: {exc}[/dim]")

    log.append(
        {
            "action": "watchlist_scan",
            "watchlist": w.id,
            "hours": hours,
            "threshold_km": threshold,
            "pairs": report["pairs_scanned"],
            "n_results": summary["n_results"],
            "HIGH": summary["HIGH"],
            "MEDIUM": summary["MEDIUM"],
            "closest_km": summary["closest_km"],
            "closest_pair": summary["closest_pair"],
            "csv": csv_path,
            "db_run_id": db_info.get("run_id"),
            "db_events": db_info.get("events_logged"),
            "notify_n": notify_info.get("n"),
        }
    )


def _run_conj(
    *,
    name1: Optional[str],
    name2: Optional[str],
    group1: str,
    group2: str,
    hours: float,
    threshold: float,
    high_risk: float,
    steps: int,
    max_pairs: int,
    html: bool,
    open_html: bool,
    only_below: bool,
):
    """Pair or group-vs-group conjunction scan + optional HTML report."""
    path1 = _ensure_tles(group1)
    if path1 is None:
        return
    path2 = path1 if group2 == group1 else _ensure_tles(group2)
    if path2 is None:
        return

    with console.status("[bold cyan]Loading catalogs…"):
        sats1, _ = load_satellites(path1)
        sats2 = sats1 if path2 == path1 else load_satellites(path2)[0]

    # Mode A: named pair
    if name1 or name2:
        n1 = name1 or ("ISS" if group1 == "stations" else None)
        n2 = name2
        if not n1 or not n2:
            console.print(
                "[red]Pair mode needs both objects. "
                "Use --name1 ISS --name2 STARLINK-3005[/red]"
            )
            return
        sat1 = find_satellite_by_name(sats1, n1)
        sat2 = find_satellite_by_name(sats2, n2)
        if sat1 is None:
            console.print(f"[red]Not found in {group1}: {n1}[/red]")
            hits = search_satellites(sats1, n1, limit=8)
            for h in hits:
                console.print(f"  • {h.name}")
            return
        if sat2 is None:
            console.print(f"[red]Not found in {group2}: {n2}[/red]")
            hits = search_satellites(sats2, n2, limit=8)
            for h in hits:
                console.print(f"  • {h.name}")
            return

        with console.status(
            f"[bold cyan]Propagating {sat1.name} ↔ {sat2.name} ({hours:g}h)…"
        ):
            result = check_conjunction(
                sat1,
                sat2,
                hours=hours,
                threshold_km=threshold,
                high_risk_km=high_risk,
                steps=steps,
            )
        results = [result]
    else:
        # Mode B: group vs group (capped)
        # Prefer ISS as primary when stations is group1 and no names
        primary = list(sats1)
        if group1 == "stations":
            iss = find_satellite_by_name(sats1, "ISS")
            primary = [iss] if iss else primary[:3]
        else:
            primary = primary[: min(5, len(primary))]

        secondary = list(sats2)
        # Limit secondary for performance (Starlink catalogs are huge)
        secondary = secondary[: max(1, max_pairs // max(len(primary), 1))]

        console.print(
            f"[dim]Group scan: {len(primary)} × {len(secondary)} "
            f"(cap {max_pairs} pairs) over {hours:g}h · "
            f"threshold {threshold:g} km[/dim]"
        )
        with console.status("[bold cyan]Scanning conjunctions…"):
            results = scan_conjunctions(
                primary,
                secondary,
                hours=hours,
                threshold_km=threshold,
                high_risk_km=high_risk,
                steps=steps,
                max_pairs=max_pairs,
            )

    if only_below:
        results = [r for r in results if r.get("below_threshold")]

    if not results:
        console.print(
            "[yellow]No pairs to report "
            f"(try raising --threshold or --max_pairs, or disable --only_below).[/yellow]"
        )
        return

    # Terminal table
    table = Table(
        title="Conjunction Results",
        show_lines=False,
    )
    table.add_column("Object 1", style="cyan")
    table.add_column("Object 2", style="cyan")
    table.add_column("TCA (UTC)")
    table.add_column("Min dist", justify="right")
    table.add_column("Risk", justify="center")

    for r in results[:25]:
        tca = r["tca"]
        tca_s = tca.strftime("%Y-%m-%d %H:%M:%S") if hasattr(tca, "strftime") else str(tca)
        risk = r["risk"]
        table.add_row(
            r["sat1"],
            r["sat2"],
            tca_s,
            f"{r['min_dist_km']:.2f} km",
            f"[{_risk_style(risk)}]{risk}[/]",
        )
    console.print(table)

    best = results[0]
    console.print(
        f"\nClosest approach: [bold]{best['sat1']}[/bold] ↔ "
        f"[bold]{best['sat2']}[/bold] · "
        f"[{_risk_style(best['risk'])}]{best['risk']}[/] · "
        f"[bold]{best['min_dist_km']} km[/bold] at {best['tca']}"
    )

    report_path = None
    if html or open_html:
        # Always write report when html=True (default); open browser only if asked
        report_path = generate_html_report(
            results,
            open_browser=bool(open_html),
        )
        console.print(f"[green]HTML report:[/green] {report_path}")
        if not open_html:
            console.print(
                "[dim]Open with: python main.py html  "
                "(or conj … --open_html)[/dim]"
            )

    # Log compact summaries (not full time series)
    log.append(
        {
            "action": "conjunction_check",
            "mode": "pair" if (name1 or name2) else "group",
            "group1": group1,
            "group2": group2,
            "name1": name1,
            "name2": name2,
            "hours": hours,
            "threshold_km": threshold,
            "n_results": len(results),
            "closest_km": best["min_dist_km"],
            "closest_pair": f"{best['sat1']} / {best['sat2']}",
            "risk": best["risk"],
            "report": str(report_path) if report_path else None,
        }
    )


def main(
    action: str = "status",
    group: str = "stations",
    name: Optional[str] = None,
    hours: float = PASS_HOURS_AHEAD,
    min_el: float = PASS_MIN_ELEVATION,
    max_passes: int = 8,
    show: bool = True,
    search: Optional[str] = None,
    stargazer: bool = STARGAZER_DEFAULT,
    # Conjunction options
    name1: Optional[str] = None,
    name2: Optional[str] = None,
    group1: str = "stations",
    group2: str = "starlink",
    threshold: float = CONJ_THRESHOLD_KM,
    high_risk: float = CONJ_HIGH_RISK_KM,
    steps: int = CONJ_STEPS_DEFAULT,
    max_pairs: int = CONJ_MAX_PAIRS,
    html: bool = True,
    open_html: bool = False,
    only_below: bool = False,
    observer: str = DEFAULT_OBSERVER,
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    sort: str = "quality",
    min_score: float = 0,
    show_breakdown: bool = False,
    # Watchlist
    cmd: str = "list",
    wl: str = WATCHLIST_DEFAULT_ID,
    csv: Optional[str] = None,
    # History
    days: int = 7,
    object: Optional[str] = None,
    persist: bool = True,
    # Scheduler
    foreground: bool = True,
    immediately: bool = True,
    job: Optional[str] = None,
    # Export
    export_format: str = "pdf",
    output: Optional[str] = None,
):
    """StarShield Lite — personal orbital awareness CLI.

    USAGE
      python main.py <action> [options]

    ACTIONS
      status      System readiness, index size, SQLite summary, command hints
      fetch       Download TLEs  e.g.  --group stations|starlink|visual|active
      search      Multi-catalog search  e.g.  --search ISS
      passes      Predict + score passes
                    --name ISS --hours 168 --sort quality --show_breakdown
                    --stargazer=False --min_score 50
                    --observer "Cherry Springs, PA"  or  --lat/--lon
      map         Cartopy ground track  e.g.  --name ISS --hours 6 --show=False
      conj        One-shot pair/group conjunction check
                    --name1 ISS --name2 STARLINK-1008 --hours 24
      watchlist   Conjunction watchlists
                    --cmd list
                    --cmd scan --wl iss-starlink --hours 48 --csv data/out.csv
      history     SQLite history
                    --cmd summary|passes|conj|runs  --days 7  --object ISS
      export      PDF / ICS  --cmd passes|watchlist --export_format pdf|ics
      schedule    Background watchlist jobs
                    --cmd list|start|run  --job iss-starlink-12h
      notify      Webhook notifications
                    --cmd list|status|test|init
      debris      Debris catalogs & conjunctions
                    --cmd list|status|fetch|scan
                    --group debris|fengyun-1c-debris|iridium-33-debris
      api         FastAPI server (OpenAPI at /docs)
      dash        Streamlit dashboard
      tui         Textual terminal UI
      html        Open latest conjunction HTML report

    EXAMPLES
      python main.py status
      python main.py fetch --group stations
      python main.py passes --name ISS --hours 72 --sort quality
      python main.py watchlist --cmd scan --wl iss-starlink --hours 48
      python main.py history --cmd summary
      python main.py api
      docker compose up --build

    NOTES
      Stargazer (default on for passes): dark sky + sunlit satellite.
      Risk bands: HIGH < 10 km, MEDIUM < 50 km.
      DB logging: STARSHIELD_DB_LOG=0 off · --persist=False skip one run.
      Docs: README.md · docs/USAGE.md · docs/ARCHITECTURE.md · docs/DOCKER.md
    """
    obs = resolve_observer(profile=observer, lat=lat, lon=lon)

    if action == "tui":
        from tui import run_tui

        run_tui()
        return

    if action in ("dash", "dashboard", "web"):
        import subprocess
        import sys
        from pathlib import Path as _Path

        dash = _Path(__file__).parent / "dashboard.py"
        console.print("[cyan]Launching Streamlit dashboard…[/cyan]")
        console.print("[dim]Stop with Ctrl+C in this terminal.[/dim]")
        subprocess.run(
            [sys.executable, "-m", "streamlit", "run", str(dash), "--browser.gatherUsageStats=false"],
            check=False,
        )
        return

    if action in ("api", "serve", "uvicorn"):
        from config import API_HOST, API_PORT

        console.print(
            f"[cyan]Starting FastAPI on http://{API_HOST}:{API_PORT}[/cyan]\n"
            f"[dim]Docs: http://{API_HOST}:{API_PORT}/docs · Ctrl+C to stop[/dim]"
        )
        from api.main import run as run_api

        run_api(host=API_HOST, port=API_PORT, reload=False)
        return

    if action in ("schedule", "scheduler", "sched"):
        _run_schedule(
            cmd=cmd,
            job_id=job,
            foreground=foreground,
            immediately=immediately,
        )
        return

    if action in ("export", "exp"):
        _run_export(
            cmd=cmd if cmd and cmd != "list" else "passes",
            name=name,
            wl_id=wl,
            export_format=export_format,
            output=output,
            hours=hours,
            observer=obs,
            stargazer=stargazer,
            sort=sort,
            min_score=min_score,
            max_passes=max_passes,
            threshold=threshold,
            only_below=only_below,
            max_pairs=max_pairs,
        )
        return

    if action in ("apikey", "api-key", "keys"):
        _run_apikey(cmd=cmd)
        return

    if action in ("notify", "notification", "notifications", "webhook", "webhooks"):
        _run_notify(cmd=cmd)
        return

    if action in ("debris", "deb"):
        _run_debris(
            cmd=cmd,
            group=group,
            name=name,
            hours=hours,
            threshold=threshold,
            high_risk=high_risk,
            only_below=only_below,
            max_pairs=max_pairs,
            csv_path=csv,
            html=html,
            persist=persist,
        )
        return

    console.print(Panel("🚀 StarShield Lite", style="bold cyan"))

    if action == "fetch":
        if group not in TLE_URLS:
            console.print(
                f"[red]Unknown group '{group}'. "
                f"Choose from: {', '.join(TLE_URLS)}[/red]"
            )
            return
        path = fetch_tles(group)
        invalidate_index()
        log.append({"action": "fetch_tles", "group": group, "path": str(path)})
        console.print(f"[green]Done.[/green] Cached at {path}")

    elif action == "status":
        table = Table(title="System Status")
        table.add_column("Item", style="cyan")
        table.add_column("Value")
        table.add_row("Data dir", str(DATA_DIR))
        table.add_row("Observer", format_observer(obs))
        try:
            idx = get_index()
            st = idx.stats()
            table.add_row(
                "Object index",
                f"{st['objects']} objects · {', '.join(st['groups_loaded']) or 'none'}",
            )
        except Exception:
            table.add_row("Object index", "(unavailable)")
        table.add_row("TLE groups", ", ".join(TLE_URLS.keys()))
        table.add_row(
            "Pass defaults",
            f"{PASS_HOURS_AHEAD:g}h ahead, min elev {PASS_MIN_ELEVATION:g}°",
        )
        table.add_row(
            "Stargazer",
            f"default={'on' if STARGAZER_DEFAULT else 'off'}, "
            f"sun ≤ {STARGAZER_SUN_ALT_MAX:g}° at observer",
        )
        table.add_row(
            "Conjunction",
            f"warn < {CONJ_THRESHOLD_KM:g} km, high < {CONJ_HIGH_RISK_KM:g} km",
        )
        try:
            ensure_db()
            sdb = summary_stats(days=7)
            table.add_row(
                "SQLite (7d)",
                f"{'on' if DB_LOG_ENABLED else 'off'} · "
                f"passes={sdb['passes_logged']} · conj={sdb['conjunctions_logged']} · "
                f"runs={sdb['watchlist_runs']}",
            )
        except Exception:
            table.add_row("SQLite", str(DB_PATH))
        cached = list(DATA_DIR.glob("*_tles.txt"))
        table.add_row(
            "Cached TLEs",
            ", ".join(p.name for p in cached) if cached else "(none yet)",
        )
        report = DATA_DIR / CONJ_REPORT_FILE
        table.add_row(
            "Conj report",
            str(report) if report.exists() else "(none yet)",
        )
        try:
            from services.notifications import status_summary

            ns = status_summary()
            table.add_row(
                "Notifications",
                (
                    f"{'on' if ns['global_enabled'] else 'off'} · "
                    f"{ns['active_destinations']} active webhook(s)"
                ),
            )
        except Exception:
            table.add_row("Notifications", "optional")
        try:
            deb_st = get_index().stats()
            deb_g = deb_st.get("debris_groups_loaded") or []
            table.add_row(
                "Debris",
                (
                    f"{deb_st.get('debris_objects', 0)} tagged · "
                    f"groups={', '.join(deb_g) or 'none (optional)'}"
                ),
            )
        except Exception:
            table.add_row("Debris", "optional — python main.py debris --cmd fetch")
        console.print(table)

        # First-run guidance when catalogs are empty
        if not cached:
            console.print(
                Panel(
                    "[bold]First run[/bold]\n"
                    "1. [cyan]python main.py fetch --group stations[/cyan]\n"
                    "2. [cyan]python main.py fetch --group starlink[/cyan]\n"
                    "3. [cyan]python main.py passes --name ISS --hours 72 --sort quality[/cyan]\n"
                    "\nOr with Docker: [cyan]docker compose up --build[/cyan]",
                    title="Getting started",
                    border_style="green",
                )
            )
        else:
            console.print(
                "\n[bold]Quick commands[/bold]\n"
                "  [dim]# Catalog & passes[/dim]\n"
                "  python main.py fetch --group stations\n"
                "  python main.py search --search ISS\n"
                "  python main.py passes --name ISS --hours 168 --sort quality --show_breakdown\n"
                "\n"
                "  [dim]# Watchlist & history[/dim]\n"
                "  python main.py watchlist --cmd scan --wl iss-starlink --hours 48\n"
                "  python main.py history --cmd summary\n"
                "\n"
                "  [dim]# UIs & ops[/dim]\n"
                "  python main.py tui\n"
                "  python main.py dash\n"
                "  python main.py api          # → http://127.0.0.1:8000/docs\n"
                "  python main.py schedule --cmd list\n"
                "  python main.py notify --cmd list   # webhooks (optional)\n"
                "  python main.py debris --cmd fetch  # optional debris TLEs\n"
                "  python main.py watchlist --cmd scan --wl iss-debris --hours 24\n"
                "  docker compose up --build\n"
                "\n"
                "  [dim]Help: python main.py --help · Docs: docs/USAGE.md[/dim]"
            )

    elif action == "search":
        query = search or name
        if not query:
            console.print("[red]Provide --search or --name (substring / NORAD).[/red]")
            return
        # Prefer multi-catalog index; fall back to single group
        with console.status("[bold cyan]Searching object index…"):
            idx = get_index()
            hits = idx.search(query, limit=25)
        if hits:
            table = Table(
                title=f"Object index matches for '{query}' ({len(hits)} shown)"
            )
            table.add_column("#", style="dim")
            table.add_column("Name")
            table.add_column("NORAD")
            table.add_column("Groups")
            table.add_column("Epoch")
            for i, h in enumerate(hits, 1):
                table.add_row(
                    str(i),
                    h.name,
                    str(h.norad),
                    ",".join(sorted(h.groups)),
                    h.epoch.strftime("%Y-%m-%d") if h.epoch else "—",
                )
            console.print(table)
            console.print(
                f"[dim]Index: {idx.stats()['objects']} objects · "
                f"{', '.join(idx.stats()['groups_loaded'])}[/dim]"
            )
        else:
            path = _ensure_tles(group)
            if path is None:
                return
            sats, _ = load_satellites(path)
            legacy = search_satellites(sats, query, limit=25)
            table = Table(title=f"Matches for '{query}' in {group}")
            table.add_column("#", style="dim")
            table.add_column("Name")
            table.add_column("NORAD")
            for i, s in enumerate(legacy, 1):
                norad = getattr(getattr(s, "model", None), "satnum", "?")
                table.add_row(str(i), s.name, str(norad))
            if not legacy:
                console.print(f"[yellow]No matches for '{query}'.[/yellow]")
            else:
                console.print(table)

    elif action == "passes":
        from datetime import datetime as _dt
        from datetime import timezone as _tz

        mode_label = "Stargazer" if stargazer else "All geometric"
        geo_n = None
        vis_n = None
        passes = []
        sat = None
        with console.status(
            f"[bold cyan]Loading index & predicting passes ({mode_label})…"
        ):
            idx = get_index()
            qname = name or ("ISS" if group == "stations" else None)
            rec = None
            if qname:
                rec = idx.resolve(qname)
                sat = idx.get_satellite(rec, preferred_group=group) if rec else None
            if sat is None:
                path = _ensure_tles(group)
                if path is None:
                    return
                sats, _ = load_satellites(path)
                sat = _resolve_sat(sats, name, group)
            if sat is None:
                if not name:
                    console.print("[red]No satellites in catalog.[/red]")
                return
            if stargazer:
                console.print(
                    "[dim]Ephemeris: ensuring de421.bsp for sun/shadow checks…[/dim]"
                )
            # Fetch extra then score/filter so --min_score still has candidates
            raw_passes = predict_passes(
                sat,
                location=obs,
                hours_ahead=hours,
                min_elevation=min_el,
                max_passes=max(max_passes * 3, 20),
                stargazer=stargazer,
            )
            geo_n = getattr(raw_passes, "geometric_count", None)
            vis_n = getattr(raw_passes, "visible_count", None)
            sort_quality = str(sort).lower() in ("quality", "score", "best")
            passes = score_passes(
                raw_passes,
                location=obs,
                sat=sat,
                object_name=sat.name,
                min_score=float(min_score),
                sort=sort_quality,
            )
            if not sort_quality:
                passes.sort(
                    key=lambda p: (
                        p.get("culmination") or p.get("rise") or p.get("set") or {}
                    ).get("time")
                    or _dt.min.replace(tzinfo=_tz.utc)
                )
            passes = passes[:max_passes]

        filter_note = ""
        if stargazer and geo_n is not None:
            filter_note = (
                f"  ·  {vis_n}/{geo_n} geometric passes are naked-eye visible"
            )

        console.print(
            f"[dim]Observer: {format_observer(obs)}  ·  "
            f"min elev {min_el:g}°  ·  next {hours:g}h  ·  "
            f"mode={mode_label} · sort={sort} · min_score={min_score:g} "
            f"(sun ≤ {STARGAZER_SUN_ALT_MAX:g}°){filter_note}[/dim]\n"
        )

        title = (
            f"Best Passes — {sat.name}"
            if str(sort).lower() in ("quality", "score", "best")
            else (
                f"Visible Passes — {sat.name} (Stargazer)"
                if stargazer
                else f"All Passes — {sat.name}"
            )
        )
        table = Table(title=title, show_lines=False)
        table.add_column("Quality", justify="center")
        table.add_column("Rise (UTC)", style="green")
        table.add_column("Culmination (UTC)", style="bold yellow")
        table.add_column("Set (UTC)", style="red")
        table.add_column("Max El")
        table.add_column("Az @ Max")
        table.add_column("Duration")
        table.add_column("Sky", justify="center")

        if not passes:
            if stargazer:
                console.print(
                    f"[yellow]No naked-eye-visible passes of {sat.name} "
                    f"in the next {hours:g} hours "
                    f"(above {min_el:g}°, dark sky + sunlit sat).[/yellow]"
                )
                console.print(
                    "[dim]Try --stargazer=False, --hours longer, "
                    "or lower --min_score.[/dim]"
                )
            else:
                console.print(
                    f"[yellow]No passes of {sat.name} above {min_el:g}° "
                    f"in the next {hours:g} hours "
                    f"(or none ≥ min_score {min_score:g}).[/yellow]"
                )
        else:
            for p in passes:
                row = format_pass_row(p)
                q = p.get("quality") or {}
                grade = q.get("grade", "?")
                qcell = f"[{grade_style(grade)}]{row['quality']}[/]"
                table.add_row(
                    qcell,
                    row["rise"],
                    row["culmination"],
                    row["set"],
                    row["max_el"],
                    row["az_max"],
                    row["duration"],
                    row["sky"],
                )
            console.print(table)
            if show_breakdown and passes:
                console.print("\n[bold]Quality breakdown (best pass)[/bold]")
                best = passes[0].get("quality") or {}
                console.print(
                    f"  {best.get('grade')} {best.get('score')} — "
                    f"{format_quality_breakdown(best)}"
                )
            console.print(
                "[dim]Quality: elev 30% · duration 20% · darkness 25% · "
                "sunlit 15% · brightness proxy 10%. "
                "Sort: --sort quality|time · filter: --min_score 60[/dim]"
            )

        db_n = 0
        if persist and DB_LOG_ENABLED and passes:
            try:
                norad = getattr(getattr(sat, "model", None), "satnum", None)
                db_n = log_passes_batch(
                    passes,
                    object_name=sat.name,
                    norad=int(norad) if norad is not None else None,
                    location=obs,
                    stargazer=stargazer,
                    source="cli",
                )
                if db_n:
                    console.print(
                        f"[dim]DB: logged {db_n} high-quality pass(es) → {DB_PATH.name}[/dim]"
                    )
            except Exception as exc:
                console.print(f"[dim]DB log skipped: {exc}[/dim]")

        notify_n = 0
        if passes:
            try:
                from services.notifications import notify_high_quality_passes

                nres = notify_high_quality_passes(
                    passes,
                    object_name=sat.name,
                    location=obs,
                    source="cli",
                )
                notify_n = int(nres.get("notified") or nres.get("n") or 0)
                if notify_n and not nres.get("skipped"):
                    console.print(
                        f"[dim]Notify: queued {notify_n} high-quality pass alert(s)[/dim]"
                    )
            except Exception as exc:
                console.print(f"[dim]Notify skipped: {exc}[/dim]")

        log.append(
            {
                "action": "passes",
                "sat": sat.name,
                "group": group,
                "hours": hours,
                "min_el": min_el,
                "stargazer": stargazer,
                "sort": sort,
                "min_score": min_score,
                "n_passes": len(passes),
                "geometric_count": geo_n,
                "visible_count": vis_n,
                "best_score": (passes[0].get("quality_score") if passes else None),
                "db_logged": db_n,
                "notify_n": notify_n,
            }
        )

    elif action == "map":
        path = _ensure_tles(group)
        if path is None:
            return
        with console.status("[bold cyan]Propagating & rendering map…"):
            sats, _ = load_satellites(path)
            if (name and name.lower() == "multi") or (
                group == "starlink" and name is None
            ):
                subset = [
                    s for s in sats if "STARLINK" in s.name.upper()
                ][:8] or list(sats)[:8]
                out = map_multi_tracks(
                    subset,
                    hours=hours if hours != PASS_HOURS_AHEAD else 3,
                    show=show,
                )
                label = f"{len(subset)} sats"
            else:
                sat = _resolve_sat(sats, name, group)
                if sat is None:
                    if not name:
                        console.print("[red]No satellites in catalog.[/red]")
                    return
                out = map_ground_track(
                    sat,
                    hours=hours if hours != PASS_HOURS_AHEAD else 6,
                    show=show,
                )
                label = sat.name

        if out:
            console.print(f"[green]Map saved:[/green] {out}")
        log.append(
            {
                "action": "map",
                "target": label,
                "group": group,
                "path": str(out) if out else None,
            }
        )

    elif action == "conj":
        _run_conj(
            name1=name1,
            name2=name2,
            group1=group1,
            group2=group2,
            hours=hours,
            threshold=threshold,
            high_risk=high_risk,
            steps=steps,
            max_pairs=max_pairs,
            html=html,
            open_html=open_html,
            only_below=only_below,
        )

    elif action in ("watchlist", "wl"):
        _run_watchlist(
            cmd=cmd,
            wl_id=wl,
            hours=hours,
            threshold=threshold,
            high_risk=high_risk,
            only_below=only_below,
            max_pairs=max_pairs,
            csv_path=csv,
            html=html,
            persist=persist,
        )

    elif action in ("history", "hist", "db"):
        _run_history(
            cmd=cmd,
            days=days,
            object_name=object or name,
            wl_id=wl,
        )

    elif action == "html":
        path = open_latest_report()
        if path is None:
            console.print(
                f"[yellow]No report at data/{CONJ_REPORT_FILE}. "
                "Run a conj check first.[/yellow]"
            )
        else:
            console.print(f"[green]Opened:[/green] {path}")

    else:
        console.print(f"[yellow]Unknown action:[/yellow] {action}")
        console.print(
            "Try: status | fetch | passes | map | search | conj | watchlist | "
            "debris | history | export | schedule | notify | apikey | api | "
            "html | tui | dash"
        )


def cli_main():
    """Console script entry point: ``starshield``."""
    import fire

    fire.Fire(main)


if __name__ == "__main__":
    cli_main()

