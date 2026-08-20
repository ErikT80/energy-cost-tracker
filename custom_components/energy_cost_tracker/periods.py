"""Billing-period helpers."""
from __future__ import annotations

import calendar
from datetime import datetime, timedelta


def _clamped_datetime(year: int, month: int, day: int, tzinfo) -> datetime:
    day = min(max(1, day), calendar.monthrange(year, month)[1])
    return datetime(year, month, day, tzinfo=tzinfo)


def _add_month(year: int, month: int) -> tuple[int, int]:
    if month == 12:
        return year + 1, 1
    return year, month + 1


def billing_month_bounds(now: datetime, start_day: int) -> tuple[datetime, datetime]:
    """Return the current recurring billing-month bounds [start, end)."""
    candidate = _clamped_datetime(now.year, now.month, start_day, now.tzinfo)
    if now >= candidate:
        start = candidate
        ny, nm = _add_month(now.year, now.month)
        end = _clamped_datetime(ny, nm, start_day, now.tzinfo)
    else:
        py, pm = (now.year - 1, 12) if now.month == 1 else (now.year, now.month - 1)
        start = _clamped_datetime(py, pm, start_day, now.tzinfo)
        end = candidate
    return start, end


def billing_year_bounds(
    now: datetime, start_month: int, start_day: int
) -> tuple[datetime, datetime]:
    """Return the current recurring billing-year bounds [start, end)."""
    start_month = min(max(1, start_month), 12)
    candidate = _clamped_datetime(now.year, start_month, start_day, now.tzinfo)
    if now >= candidate:
        start = candidate
        end = _clamped_datetime(now.year + 1, start_month, start_day, now.tzinfo)
    else:
        start = _clamped_datetime(now.year - 1, start_month, start_day, now.tzinfo)
        end = candidate
    return start, end


def standard_periods(now: datetime, billing_month_day: int, billing_year_month: int, billing_year_day: int) -> dict[str, tuple[datetime, datetime]]:
    """Return standard and billing periods."""
    hour = now.replace(minute=0, second=0, microsecond=0)
    next_hour = hour + timedelta(hours=1)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow = today + timedelta(days=1)
    week = today - timedelta(days=today.weekday())
    month = today.replace(day=1)
    if month.month == 12:
        next_month = month.replace(year=month.year + 1, month=1)
    else:
        next_month = month.replace(month=month.month + 1)
    year = today.replace(month=1, day=1)
    next_year = year.replace(year=year.year + 1)
    bill_month = billing_month_bounds(now, billing_month_day)
    bill_year = billing_year_bounds(now, billing_year_month, billing_year_day)
    return {
        "hour": (hour, next_hour),
        "today": (today, tomorrow),
        "week": (week, week + timedelta(days=7)),
        "month": (month, next_month),
        "year": (year, next_year),
        "billing_month": bill_month,
        "billing_year": bill_year,
    }
