from datetime import datetime
from pathlib import Path
import importlib.util
import sys
from zoneinfo import ZoneInfo

MODULE = Path(__file__).parents[1] / "custom_components" / "energy_cost_tracker" / "periods.py"
spec = importlib.util.spec_from_file_location("ect_periods", MODULE)
mod = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


def test_billing_month_non_calendar_start():
    tz = ZoneInfo("Europe/Amsterdam")
    now = datetime(2026, 8, 20, 12, 0, tzinfo=tz)
    start, end = mod.billing_month_bounds(now, 18)
    assert start == datetime(2026, 8, 18, tzinfo=tz)
    assert end == datetime(2026, 9, 18, tzinfo=tz)


def test_billing_month_day_31_clamps():
    tz = ZoneInfo("Europe/Amsterdam")
    now = datetime(2026, 2, 28, 12, 0, tzinfo=tz)
    start, end = mod.billing_month_bounds(now, 31)
    assert start == datetime(2026, 2, 28, tzinfo=tz)
    assert end == datetime(2026, 3, 31, tzinfo=tz)


def test_billing_year_non_calendar_start():
    tz = ZoneInfo("Europe/Amsterdam")
    now = datetime(2026, 8, 20, 12, 0, tzinfo=tz)
    start, end = mod.billing_year_bounds(now, 10, 12)
    assert start == datetime(2025, 10, 12, tzinfo=tz)
    assert end == datetime(2026, 10, 12, tzinfo=tz)


def test_standard_periods_include_current_hour():
    tz = ZoneInfo("Europe/Amsterdam")
    now = datetime(2026, 8, 20, 18, 37, 12, tzinfo=tz)
    start, end = mod.standard_periods(now, 1, 1, 1)["hour"]
    assert start == datetime(2026, 8, 20, 18, 0, 0, tzinfo=tz)
    assert end == datetime(2026, 8, 20, 19, 0, 0, tzinfo=tz)
