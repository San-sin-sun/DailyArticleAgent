from __future__ import annotations

from datetime import UTC, date, datetime

from dailyarticleagent.service import local_today, previous_complete_week_end, weekly_window


def test_weekly_window_normalizes_to_sunday() -> None:
    start, end = weekly_window(date(2026, 6, 10))

    assert start == date(2026, 6, 8)
    assert end == date(2026, 6, 14)


def test_previous_complete_week_end_uses_today_when_sunday() -> None:
    assert previous_complete_week_end(date(2026, 6, 14)) == date(2026, 6, 14)


def test_previous_complete_week_end_uses_previous_sunday_midweek() -> None:
    assert previous_complete_week_end(date(2026, 6, 10)) == date(2026, 6, 7)


def test_local_today_uses_configured_timezone(monkeypatch) -> None:
    monkeypatch.setenv("DAA_TIMEZONE", "Europe/Berlin")

    assert local_today(datetime(2026, 6, 8, 22, 30, tzinfo=UTC)) == date(2026, 6, 9)
