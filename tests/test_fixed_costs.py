from datetime import datetime, timezone
from pathlib import Path
import importlib.util
import sys

MODULE = Path(__file__).parents[1] / "custom_components" / "energy_cost_tracker" / "fixed_costs.py"
spec = importlib.util.spec_from_file_location("ect_fixed_costs", MODULE)
mod = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


def test_future_profile_switches_at_local_midnight():
    profiles = mod.normalize_profiles(
        {"fixed_daily": 1.0, "fixed_monthly": 0, "fixed_annual": 0, "annual_rebate": 0},
        [{"effective_from": "2027-01-01", "daily": 2.0, "monthly": 0, "annual": 0, "annual_rebate": 0}],
    )
    # Amsterdam is UTC+1 on Jan 1. This spans 23:30 Dec 31 to 00:30 Jan 1 local.
    start = datetime(2026, 12, 31, 22, 30, tzinfo=timezone.utc)
    end = datetime(2026, 12, 31, 23, 30, tzinfo=timezone.utc)
    value = mod.fixed_cost_for_interval(start, end, "Europe/Amsterdam", profiles)
    # Half an hour at EUR 1/day + half an hour at EUR 2/day.
    assert abs(value - ((0.5 / 24) * 1 + (0.5 / 24) * 2)) < 1e-9


def test_dated_annual_profile_is_used_after_effective_date():
    profiles = mod.normalize_profiles(
        {"fixed_daily": 0, "fixed_monthly": 0, "fixed_annual": 0, "annual_rebate": 0},
        [{"effective_from": "2026-08-01", "daily": 0, "monthly": 0, "annual": 365, "annual_rebate": 0}],
    )
    start = datetime(2026, 8, 10, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 8, 11, 0, 0, tzinfo=timezone.utc)
    value = mod.fixed_cost_for_interval(start, end, "UTC", profiles)
    assert abs(value - 1.0) < 1e-9


def test_last_duplicate_date_wins_and_schedule_is_sorted():
    profiles = mod.normalize_profiles(
        {},
        [
            {"effective_from": "2027-01-01", "daily": 2, "monthly": 0, "annual": 0, "annual_rebate": 0},
            {"effective_from": "2026-10-01", "daily": 1, "monthly": 0, "annual": 0, "annual_rebate": 0},
            {"effective_from": "2027-01-01", "daily": 3, "monthly": 0, "annual": 0, "annual_rebate": 0},
        ],
    )
    assert [p.effective_from.isoformat() for p in profiles[1:]] == ["2026-10-01", "2027-01-01"]
    assert profiles[-1].daily == 3


def test_dst_day_still_accrues_exact_daily_amount():
    profiles = mod.normalize_profiles(
        {"fixed_daily": 1, "fixed_monthly": 0, "fixed_annual": 0, "annual_rebate": 0}, []
    )
    # Europe/Amsterdam DST starts Mar 29 2026: local day is 23 actual hours.
    start = datetime(2026, 3, 28, 23, 0, tzinfo=timezone.utc)
    end = datetime(2026, 3, 29, 22, 0, tzinfo=timezone.utc)
    value = mod.fixed_cost_for_interval(start, end, "Europe/Amsterdam", profiles)
    assert abs(value - 1.0) < 1e-9


def test_fixed_cost_breakdown_matches_existing_total():
    profiles = mod.normalize_profiles(
        {"fixed_daily": 0.24, "fixed_monthly": 6.25, "fixed_annual": 475.84, "annual_rebate": 629.0}, []
    )
    start = datetime(2026, 8, 1, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 9, 1, 0, 0, tzinfo=timezone.utc)
    breakdown = mod.fixed_cost_breakdown_for_interval(start, end, "UTC", profiles)
    total = mod.fixed_cost_for_interval(start, end, "UTC", profiles)
    assert abs(breakdown["total"] - total) < 1e-12
    assert abs(
        breakdown["daily"]
        + breakdown["monthly"]
        + breakdown["annual"]
        - breakdown["annual_rebate"]
        - breakdown["total"]
    ) < 1e-12
    assert breakdown["annual_rebate"] > 0


def test_fixed_cost_breakdown_switches_profile_mid_invoice_period():
    profiles = mod.normalize_profiles(
        {"fixed_daily": 1.0, "fixed_monthly": 0, "fixed_annual": 0, "annual_rebate": 0},
        [{"effective_from": "2027-01-01", "daily": 2.0, "monthly": 0, "annual": 0, "annual_rebate": 0}],
    )
    start = datetime(2026, 12, 31, 0, 0, tzinfo=timezone.utc)
    end = datetime(2027, 1, 2, 0, 0, tzinfo=timezone.utc)
    breakdown = mod.fixed_cost_breakdown_for_interval(start, end, "UTC", profiles)
    assert abs(breakdown["daily"] - 3.0) < 1e-9
    assert abs(breakdown["total"] - 3.0) < 1e-9
