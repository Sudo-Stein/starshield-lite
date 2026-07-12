"""Export helpers: PDF reports and ICS calendar files.

Optional PDF dependency: ``fpdf2`` (``pip install fpdf2``).
ICS generation is pure Python (no extra deps).
"""

from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, Sequence, Union

PathLike = Union[str, Path]


class ExportError(RuntimeError):
    """Raised when an export cannot be completed."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_dt(val) -> Optional[datetime]:
    if val is None:
        return None
    if isinstance(val, datetime):
        if val.tzinfo is None:
            return val.replace(tzinfo=timezone.utc)
        return val
    if isinstance(val, str):
        try:
            # handle trailing Z
            s = val.replace("Z", "+00:00")
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            return None
    return None


def _fmt_dt(dt: Optional[datetime], local: bool = False) -> str:
    if dt is None:
        return "—"
    if local:
        return dt.astimezone().strftime("%Y-%m-%d %H:%M %Z")
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _observer_label(location: Optional[dict]) -> str:
    if not location:
        return "Unknown observer"
    name = location.get("name") or "Observer"
    lat = location.get("lat")
    lon = location.get("lon")
    if lat is None or lon is None:
        return str(name)
    ns = "N" if lat >= 0 else "S"
    ew = "E" if lon >= 0 else "W"
    return f"{name} ({abs(lat):g} deg {ns}, {abs(lon):g} deg {ew})"


def _pdf_text(text: str) -> str:
    """ASCII-safe text for core Helvetica fonts in fpdf2."""
    if text is None:
        return ""
    s = str(text)
    replacements = {
        "—": "-",
        "–": "-",
        "★": "*",
        "°": " deg",
        "·": "-",
        "↔": "<->",
        "≤": "<=",
        "≥": ">=",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
    }
    for a, b in replacements.items():
        s = s.replace(a, b)
    # Drop any remaining non-latin-1 chars
    return s.encode("latin-1", errors="replace").decode("latin-1")


def _pass_times(p: dict):
    rise = (p.get("rise") or {}).get("time")
    culm = (p.get("culmination") or {}).get("time")
    set_ = (p.get("set") or {}).get("time")
    return _as_dt(rise), _as_dt(culm), _as_dt(set_)


# ---------------------------------------------------------------------------
# ICS
# ---------------------------------------------------------------------------


def _ics_escape(text: str) -> str:
    return (
        str(text)
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def _ics_dt(dt: datetime) -> str:
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y%m%dT%H%M%SZ")


def passes_to_ics(
    passes: Sequence[dict],
    *,
    object_name: str = "Satellite",
    location: Optional[dict] = None,
    calendar_name: str = "StarShield Lite Passes",
) -> str:
    """Build an iCalendar (.ics) document for passes.

    Each pass becomes a VEVENT from rise→set (or culm ±2 min if incomplete).
    """
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//StarShield Lite//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_ics_escape(calendar_name)}",
    ]
    loc_label = _observer_label(location)
    now = _ics_dt(_utc_now())

    for i, p in enumerate(passes):
        rise, culm, set_ = _pass_times(p)
        if rise is None and culm is None and set_ is None:
            continue
        start = rise or culm or set_
        end = set_ or (
            (culm + timedelta(minutes=3)) if culm else (start + timedelta(minutes=5))
        )
        if end <= start:
            end = start + timedelta(minutes=5)

        max_el = p.get("max_elevation")
        q = p.get("quality") or {}
        grade = p.get("quality_grade") or q.get("grade")
        score = p.get("quality_score") or q.get("score")
        az_ev = p.get("culmination") or p.get("rise") or {}
        az = az_ev.get("az")
        direction = az_ev.get("direction")
        dur_s = p.get("duration_s")
        dur_m = f"{int(dur_s // 60)}m {int(dur_s % 60):02d}s" if dur_s else "—"

        title = f"{object_name} pass"
        if max_el is not None:
            title += f" · max {max_el:.0f}°"
        if grade:
            title += f" · {grade}"

        desc_parts = [
            f"Object: {object_name}",
            f"Observer: {loc_label}",
            f"Max elevation: {max_el:.1f}°" if max_el is not None else None,
            f"Duration: {dur_m}",
            f"Az @ max: {az:.0f}° {direction or ''}".strip() if az is not None else None,
            f"Quality: {grade} {score}" if grade else None,
            f"Sky: sunlit={p.get('sunlit')} dark={p.get('dark_sky')} visible={p.get('visible')}",
            "Generated by StarShield Lite",
        ]
        description = "\\n".join(_ics_escape(x) for x in desc_parts if x)

        uid = f"starshield-{object_name.replace(' ', '-')}-{i}-{_ics_dt(start)}@starshield.local"
        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:{uid}",
                f"DTSTAMP:{now}",
                f"DTSTART:{_ics_dt(start)}",
                f"DTEND:{_ics_dt(end)}",
                f"SUMMARY:{_ics_escape(title)}",
                f"DESCRIPTION:{description}",
                f"LOCATION:{_ics_escape(loc_label)}",
                "END:VEVENT",
            ]
        )

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def write_ics(content: str, path: PathLike) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# PDF (fpdf2)
# ---------------------------------------------------------------------------


def _require_fpdf():
    try:
        from fpdf import FPDF  # noqa: F401
    except ImportError as exc:
        raise ExportError(
            "PDF export requires fpdf2. Install with: pip install fpdf2"
        ) from exc


class _ReportPDF:
    """Thin wrapper around FPDF for simple tables."""

    def __init__(self, title: str):
        _require_fpdf()
        from fpdf import FPDF

        from fpdf.enums import XPos, YPos

        self.pdf = FPDF(orientation="P", unit="mm", format="A4")
        self.pdf.set_auto_page_break(auto=True, margin=15)
        self.pdf.add_page()
        self.pdf.set_font("Helvetica", "B", 16)
        self.pdf.cell(
            0,
            10,
            _pdf_text(title)[:80],
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )
        self.pdf.set_font("Helvetica", "", 10)
        self.pdf.set_text_color(80, 80, 80)
        self.pdf.cell(
            0,
            6,
            _pdf_text(
                f"Generated {_utc_now().strftime('%Y-%m-%d %H:%M UTC')} - StarShield Lite"
            ),
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )
        self.pdf.set_text_color(0, 0, 0)
        self.pdf.ln(4)

    def heading(self, text: str):
        from fpdf.enums import XPos, YPos

        self.pdf.set_font("Helvetica", "B", 12)
        self.pdf.cell(
            0, 8, _pdf_text(text), new_x=XPos.LMARGIN, new_y=YPos.NEXT
        )
        self.pdf.set_font("Helvetica", "", 10)

    def paragraph(self, text: str):
        self.pdf.multi_cell(0, 5, _pdf_text(text))
        self.pdf.ln(2)

    def kv(self, key: str, value: str):
        from fpdf.enums import XPos, YPos

        self.pdf.set_font("Helvetica", "B", 10)
        self.pdf.cell(40, 5, _pdf_text(key))
        self.pdf.set_font("Helvetica", "", 10)
        self.pdf.cell(
            0, 5, _pdf_text(value), new_x=XPos.LMARGIN, new_y=YPos.NEXT
        )

    def table(self, headers: List[str], rows: List[List[str]], col_widths: Optional[List[float]] = None):
        if not headers:
            return
        usable = self.pdf.w - self.pdf.l_margin - self.pdf.r_margin
        if col_widths is None:
            col_widths = [usable / len(headers)] * len(headers)
        # header
        self.pdf.set_fill_color(20, 40, 70)
        self.pdf.set_text_color(255, 255, 255)
        self.pdf.set_font("Helvetica", "B", 8)
        for w, h in zip(col_widths, headers):
            self.pdf.cell(w, 6, _pdf_text(str(h))[:40], border=1, fill=True)
        self.pdf.ln()
        self.pdf.set_text_color(0, 0, 0)
        self.pdf.set_font("Helvetica", "", 7)
        fill = False
        for row in rows:
            if self.pdf.get_y() > 270:
                self.pdf.add_page()
            if fill:
                self.pdf.set_fill_color(240, 244, 250)
            else:
                self.pdf.set_fill_color(255, 255, 255)
            for w, cell in zip(col_widths, row):
                self.pdf.cell(w, 5, _pdf_text(str(cell))[:48], border=1, fill=True)
            self.pdf.ln()
            fill = not fill
        self.pdf.ln(3)

    def output_bytes(self) -> bytes:
        out = self.pdf.output()
        if isinstance(out, (bytes, bytearray)):
            return bytes(out)
        return out.encode("latin-1")


def passes_to_pdf(
    passes: Sequence[dict],
    *,
    object_name: str = "Satellite",
    location: Optional[dict] = None,
    title: Optional[str] = None,
    stargazer: Optional[bool] = None,
    hours: Optional[float] = None,
) -> bytes:
    """Generate a PDF report for a list of scored/raw passes."""
    pdf = _ReportPDF(title or f"Pass Report - {object_name}")
    pdf.heading("Observer")
    pdf.kv("Location", _observer_label(location))
    if hours is not None:
        pdf.kv("Window", f"{hours:g} hours ahead")
    if stargazer is not None:
        pdf.kv("Stargazer filter", "on" if stargazer else "off")
    pdf.kv("Passes listed", str(len(passes)))
    pdf.paragraph("")

    headers = ["#", "Quality", "Rise UTC", "Culm UTC", "Set UTC", "Max El", "Dur", "Sky"]
    rows = []
    for i, p in enumerate(passes, 1):
        rise, culm, set_ = _pass_times(p)
        q = p.get("quality") or {}
        grade = p.get("quality_grade") or q.get("grade") or "—"
        score = p.get("quality_score") or q.get("score")
        qcell = f"{grade} {score}" if score is not None else str(grade)
        max_el = p.get("max_elevation")
        dur_s = p.get("duration_s")
        dur = f"{int(dur_s // 60)}m" if dur_s else "—"
        sky = "★" if p.get("visible") else (
            "day" if p.get("sunlit") and not p.get("dark_sky") else (
                "shadow" if p.get("dark_sky") and not p.get("sunlit") else "—"
            )
        )
        rows.append(
            [
                str(i),
                qcell,
                _fmt_dt(rise),
                _fmt_dt(culm),
                _fmt_dt(set_),
                f"{max_el:.1f} deg" if max_el is not None else "-",
                dur,
                sky,
            ]
        )

    pdf.heading("Passes")
    # widths sum ~190mm
    pdf.table(
        headers,
        rows,
        col_widths=[10, 18, 32, 32, 32, 18, 14, 18],
    )

    if passes:
        best = passes[0]
        q = best.get("quality") or {}
        pdf.heading("Top pass detail")
        pdf.kv("Quality", f"{q.get('grade', '—')} {q.get('score', '—')}")
        bd = q.get("breakdown") or {}
        if bd:
            pdf.paragraph(
                "Breakdown: "
                + ", ".join(f"{k}={v}" for k, v in bd.items())
            )
        pdf.paragraph(
            "Quality weights: elev 30% · duration 20% · darkness 25% · "
            "sunlit 15% · brightness proxy 10%."
        )

    pdf.paragraph(
        "Disclaimer: StarShield Lite is a personal awareness tool, "
        "not certified space-traffic coordination."
    )
    return pdf.output_bytes()


def watchlist_to_pdf(
    report: dict,
    *,
    title: Optional[str] = None,
    max_rows: int = 40,
) -> bytes:
    """Generate a PDF report for a watchlist scan result dict."""
    wl_name = report.get("watchlist_name") or report.get("watchlist_id") or "Watchlist"
    pdf = _ReportPDF(title or f"Watchlist Report - {wl_name}")
    summary = report.get("summary") or {}
    pdf.heading("Scan summary")
    pdf.kv("Watchlist", f"{report.get('watchlist_id')} ({wl_name})")
    pdf.kv("Window", f"{report.get('hours', '—')} hours")
    pdf.kv("Threshold", f"{report.get('threshold_km', '—')} km")
    pdf.kv("Pairs scanned", str(report.get("pairs_scanned", "—")))
    pdf.kv("Results", str(summary.get("n_results", len(report.get("results") or []))))
    pdf.kv(
        "Risk counts",
        f"HIGH={summary.get('HIGH', 0)}  MEDIUM={summary.get('MEDIUM', 0)}  "
        f"LOW={summary.get('LOW', 0)}",
    )
    if summary.get("closest_pair"):
        pdf.kv(
            "Closest",
            f"{summary.get('closest_pair')} · {summary.get('closest_km')} km",
        )

    results = list(report.get("results") or [])[:max_rows]
    headers = ["#", "Object 1", "Object 2", "TCA UTC", "Min km", "Rel v", "Risk"]
    rows = []
    for i, r in enumerate(results, 1):
        tca = _as_dt(r.get("tca"))
        rv = r.get("rel_velocity_kms")
        rows.append(
            [
                str(i),
                str(r.get("sat1") or "")[:22],
                str(r.get("sat2") or "")[:22],
                _fmt_dt(tca),
                f"{r.get('min_dist_km')}",
                f"{rv:.2f}" if rv is not None else "—",
                str(r.get("risk") or "—"),
            ]
        )
    pdf.heading("Close approaches")
    pdf.table(
        headers,
        rows,
        col_widths=[8, 35, 35, 36, 22, 18, 18],
    )
    pdf.paragraph(
        "Risk bands: HIGH < 10 km, MEDIUM < 50 km, LOW otherwise. "
        "Distances from SGP4/Skyfield propagation (approximate)."
    )
    return pdf.output_bytes()


def write_pdf(data: bytes, path: PathLike) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def write_bytes(data: bytes, path: PathLike) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path
