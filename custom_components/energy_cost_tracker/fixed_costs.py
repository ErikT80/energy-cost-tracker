"""Dated fixed-cost schedules for Energy Cost Tracker.

This module is deliberately Home-Assistant independent so the calendar/proration
rules can be tested without a HA runtime.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable
from zoneinfo import ZoneInfo


@dataclass(frozen=True, slots=True)
class FixedCostProfile:
    """One complete fixed-cost profile, active from a local calendar date."""

    effective_from: date | None
    daily: float = 0.0
    monthly: float = 0.0
    annual: float = 0.0
    annual_rebate: float = 0.0

    @property
    def net_annual(self) -> float:
        return self.annual - self.annual_rebate

    def as_dict(self) -> dict[str, Any]:
        return {
            "effective_from": self.effective_from.isoformat() if self.effective_from else None,
            "daily": self.daily,
            "monthly": self.monthly,
            "annual": self.annual,
            "annual_rebate": self.annual_rebate,
        }


def _float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def normalize_profiles(
    base: dict[str, Any] | FixedCostProfile,
    scheduled: Iterable[dict[str, Any]] | None = None,
) -> list[FixedCostProfile]:
    """Return a baseline plus sorted, de-duplicated dated profiles.

    The baseline has ``effective_from=None`` and therefore applies before the first
    dated profile. If multiple schedule entries use the same date, the last one wins.
    """
    if isinstance(base, FixedCostProfile):
        baseline = FixedCostProfile(
            effective_from=None,
            daily=base.daily,
            monthly=base.monthly,
            annual=base.annual,
            annual_rebate=base.annual_rebate,
        )
    else:
        baseline = FixedCostProfile(
            effective_from=None,
            daily=_float(base.get("fixed_daily")),
            monthly=_float(base.get("fixed_monthly")),
            annual=_float(base.get("fixed_annual")),
            annual_rebate=_float(base.get("annual_rebate")),
        )

    by_date: dict[date, FixedCostProfile] = {}
    for raw in scheduled or []:
        if not isinstance(raw, dict):
            continue
        raw_date = raw.get("effective_from")
        if not raw_date:
            continue
        try:
            effective = date.fromisoformat(str(raw_date))
        except ValueError:
            continue
        by_date[effective] = FixedCostProfile(
            effective_from=effective,
            daily=_float(raw.get("daily")),
            monthly=_float(raw.get("monthly")),
            annual=_float(raw.get("annual")),
            annual_rebate=_float(raw.get("annual_rebate")),
        )
    return [baseline, *(by_date[key] for key in sorted(by_date))]


def active_profile(profiles: list[FixedCostProfile], local_date: date) -> FixedCostProfile:
    """Return the profile effective on ``local_date``."""
    active = profiles[0]
    for profile in profiles[1:]:
        if profile.effective_from is None or profile.effective_from > local_date:
            break
        active = profile
    return active


def fixed_cost_breakdown_for_interval(
    start: datetime,
    end: datetime,
    tz_name: str,
    profiles: list[FixedCostProfile],
) -> dict[str, float]:
    """Accrue fixed-charge components over an aware UTC interval.

    ``annual_rebate`` is returned as a positive deduction amount. ``total`` is
    therefore ``daily + monthly + annual - annual_rebate``. The proration rules
    are intentionally identical to :func:`fixed_cost_for_interval`.
    """
    result = {
        "daily": 0.0,
        "monthly": 0.0,
        "annual": 0.0,
        "annual_rebate": 0.0,
        "total": 0.0,
    }
    if end <= start:
        return result
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    start = start.astimezone(timezone.utc)
    end = end.astimezone(timezone.utc)
    tz = ZoneInfo(tz_name)

    cursor = start
    while cursor < end:
        local = cursor.astimezone(tz)
        day_start_local = local.replace(hour=0, minute=0, second=0, microsecond=0)
        next_day_local = day_start_local + timedelta(days=1)
        next_day_utc = next_day_local.astimezone(timezone.utc)
        slice_end = min(end, next_day_utc)
        seconds = (slice_end - cursor).total_seconds()
        if seconds <= 0:
            break

        profile = active_profile(profiles, local.date())

        month_start_local = day_start_local.replace(day=1)
        if month_start_local.month == 12:
            next_month_local = month_start_local.replace(year=month_start_local.year + 1, month=1)
        else:
            next_month_local = month_start_local.replace(month=month_start_local.month + 1)

        year_start_local = day_start_local.replace(month=1, day=1)
        next_year_local = year_start_local.replace(year=year_start_local.year + 1)

        day_seconds = (next_day_utc - day_start_local.astimezone(timezone.utc)).total_seconds()
        month_seconds = (
            next_month_local.astimezone(timezone.utc) - month_start_local.astimezone(timezone.utc)
        ).total_seconds()
        year_seconds = (
            next_year_local.astimezone(timezone.utc) - year_start_local.astimezone(timezone.utc)
        ).total_seconds()

        result["daily"] += profile.daily * seconds / day_seconds
        result["monthly"] += profile.monthly * seconds / month_seconds
        result["annual"] += profile.annual * seconds / year_seconds
        result["annual_rebate"] += profile.annual_rebate * seconds / year_seconds
        cursor = slice_end

    result["total"] = (
        result["daily"]
        + result["monthly"]
        + result["annual"]
        - result["annual_rebate"]
    )
    return result


def fixed_cost_for_interval(
    start: datetime,
    end: datetime,
    tz_name: str,
    profiles: list[FixedCostProfile],
) -> float:
    """Accrue the net fixed cost over an aware UTC interval."""
    return fixed_cost_breakdown_for_interval(start, end, tz_name, profiles)["total"]
