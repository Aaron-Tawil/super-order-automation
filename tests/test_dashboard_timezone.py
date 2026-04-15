from datetime import UTC, datetime

from src.dashboard import timezone_utils


def test_format_dashboard_dt_uses_browser_timezone(monkeypatch):
    monkeypatch.setattr(timezone_utils, "_context_timezone_name", lambda: "America/New_York")
    monkeypatch.setattr(timezone_utils, "_context_timezone_offset", lambda: None)

    value = datetime(2026, 4, 15, 10, 0, tzinfo=UTC)

    assert timezone_utils.format_dashboard_dt(value) == "2026-04-15 06:00"


def test_format_dashboard_dt_falls_back_to_jerusalem(monkeypatch):
    monkeypatch.setattr(timezone_utils, "_context_timezone_name", lambda: None)
    monkeypatch.setattr(timezone_utils, "_context_timezone_offset", lambda: None)

    value = datetime(2026, 1, 15, 10, 0, tzinfo=UTC)

    assert timezone_utils.format_dashboard_dt(value) == "2026-01-15 12:00"


def test_to_dashboard_time_uses_offset_when_timezone_name_is_invalid(monkeypatch):
    monkeypatch.setattr(timezone_utils, "_context_timezone_name", lambda: "Not/AZone")
    monkeypatch.setattr(timezone_utils, "_context_timezone_offset", lambda: -180)

    value = datetime(2026, 4, 15, 10, 0, tzinfo=UTC)

    assert timezone_utils.format_dashboard_dt(value) == "2026-04-15 13:00"


def test_to_dashboard_time_converts_date_for_filtering(monkeypatch):
    monkeypatch.setattr(timezone_utils, "_context_timezone_name", lambda: "America/New_York")
    monkeypatch.setattr(timezone_utils, "_context_timezone_offset", lambda: None)

    value = datetime(2026, 4, 15, 1, 0, tzinfo=UTC)

    assert timezone_utils.to_dashboard_time(value).date().isoformat() == "2026-04-14"
