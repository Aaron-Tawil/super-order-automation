"""
Timezone helpers for dashboard display.

Firestore timestamps are stored as UTC instants. These helpers convert them only
at the UI boundary, using the browser timezone when Streamlit exposes it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone, tzinfo
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import streamlit as st

DEFAULT_DASHBOARD_TIMEZONE = "Asia/Jerusalem"
DASHBOARD_DATETIME_FORMAT = "%Y-%m-%d %H:%M"


def _context_timezone_name() -> str | None:
    try:
        value = st.context.timezone
    except Exception:
        return None
    return value.strip() if isinstance(value, str) and value.strip() else None


def _context_timezone_offset() -> int | None:
    try:
        value = st.context.timezone_offset
    except Exception:
        return None
    return value if isinstance(value, int) else None


def get_dashboard_timezone() -> tzinfo:
    """
    Return the viewer's browser timezone, falling back to Asia/Jerusalem.

    Streamlit provides an IANA timezone name in normal browser sessions. The
    offset fallback is used only if the name is missing or invalid.
    """
    timezone_name = _context_timezone_name()
    if timezone_name:
        try:
            return ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            pass

    timezone_offset = _context_timezone_offset()
    if timezone_offset is not None:
        return timezone(-timedelta(minutes=timezone_offset))

    return ZoneInfo(DEFAULT_DASHBOARD_TIMEZONE)


def _coerce_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def to_dashboard_time(value: Any) -> datetime | None:
    timestamp = _coerce_datetime(value)
    if timestamp is None:
        return None
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    return timestamp.astimezone(get_dashboard_timezone())


def format_dashboard_dt(value: Any) -> str:
    timestamp = to_dashboard_time(value)
    if timestamp is None:
        return "-"
    return timestamp.strftime(DASHBOARD_DATETIME_FORMAT)
