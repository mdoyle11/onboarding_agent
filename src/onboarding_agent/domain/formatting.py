"""Shared formatting helpers used across workflow domains."""

from __future__ import annotations

from datetime import date, datetime


def format_date(value: str) -> str:
    """Normalise ISO / Excel-serial dates to MM/DD/YYYY for display."""
    raw = str(value or "").strip()
    if not raw:
        return ""

    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            parsed = datetime.strptime(raw, fmt).date()
            return parsed.strftime("%m/%d/%Y")
        except ValueError:
            continue

    try:
        excel_serial = float(raw)
        excel_epoch = date(1899, 12, 30)
        parsed = excel_epoch.fromordinal(excel_epoch.toordinal() + int(excel_serial))
        return parsed.strftime("%m/%d/%Y")
    except ValueError:
        return raw
