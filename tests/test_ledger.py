from pathlib import Path
import importlib.util
import sys

MODULE = Path(__file__).parents[1] / "custom_components" / "energy_cost_tracker" / "ledger.py"
spec = importlib.util.spec_from_file_location("ect_ledger", MODULE)
mod = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


def test_counter_reset_starts_new_segment(tmp_path):
    ledger = mod.Ledger(None, tmp_path / "ledger.db")
    ledger._initialize()
    first = ledger._observe_source("grid_import", "sensor.grid", 100.0, "2026-08-20T10:00:00+00:00")
    assert first["delta"] == 0.0
    normal = ledger._observe_source("grid_import", "sensor.grid", 100.5, "2026-08-20T10:01:00+00:00")
    assert normal["delta"] == 0.5
    reset = ledger._observe_source("grid_import", "sensor.grid", 0.2, "2026-08-20T10:02:00+00:00")
    assert reset["event"] == "counter_reset"
    assert reset["delta"] == 0.2


def test_negative_correction_is_not_huge_energy(tmp_path):
    ledger = mod.Ledger(None, tmp_path / "ledger.db")
    ledger._initialize()
    ledger._observe_source("grid_import", "sensor.grid", 100.0, "2026-08-20T10:00:00+00:00")
    corrected = ledger._observe_source("grid_import", "sensor.grid", 98.0, "2026-08-20T10:01:00+00:00")
    assert corrected["event"] == "negative_correction"
    assert corrected["delta"] == 0.0


def test_entity_replacement_sets_new_baseline(tmp_path):
    ledger = mod.Ledger(None, tmp_path / "ledger.db")
    ledger._initialize()
    ledger._observe_source("grid_import", "sensor.old", 12345.0, "2026-08-20T10:00:00+00:00")
    changed = ledger._observe_source("grid_import", "sensor.new", 321.0, "2026-08-20T10:01:00+00:00")
    assert changed["event"] == "source_changed"
    assert changed["delta"] == 0.0
    next_value = ledger._observe_source("grid_import", "sensor.new", 321.4, "2026-08-20T10:02:00+00:00")
    assert round(next_value["delta"], 6) == 0.4


def test_period_summary_prorates_boundary_crossing_row(tmp_path):
    ledger = mod.Ledger(None, tmp_path / "ledger.db")
    ledger._initialize()
    ledger._insert_interval(
        {
            "start_ts": "2026-08-20T23:59:00+00:00",
            "end_ts": "2026-08-21T00:01:00+00:00",
            "seconds": 120.0,
            "grid_import_kwh": 2.0,
            "import_cost": 1.0,
            "export_revenue": 0.0,
            "fixed_cost": 0.2,
            "net_cost": 1.2,
            "quality": "estimated",
        }
    )
    first = ledger._period_summary(
        "2026-08-20T00:00:00+00:00", "2026-08-21T00:00:00+00:00"
    )
    second = ledger._period_summary(
        "2026-08-21T00:00:00+00:00", "2026-08-22T00:00:00+00:00"
    )
    assert round(first["grid_import_kwh"], 6) == 1.0
    assert round(second["grid_import_kwh"], 6) == 1.0
    assert round(first["net_cost"], 6) == 0.6
    assert round(second["net_cost"], 6) == 0.6


def test_incomplete_cost_summary_does_not_look_like_zero(tmp_path):
    ledger = mod.Ledger(None, tmp_path / "ledger.db")
    ledger._initialize()
    ledger._insert_interval(
        {
            "start_ts": "2026-08-20T10:00:00+00:00",
            "end_ts": "2026-08-20T10:01:00+00:00",
            "seconds": 60.0,
            "grid_import_kwh": 0.5,
            "import_cost": None,
            "export_revenue": 0.0,
            "fixed_cost": 0.01,
            "net_cost": None,
            "quality": "missing_price",
        }
    )
    summary = ledger._period_summary(None, None)
    assert summary["net_cost"] is None
    assert summary["import_cost"] is None
    assert summary["incomplete_cost_intervals"] == 1


def test_history_activity_filter(tmp_path):
    ledger = mod.Ledger(None, tmp_path / "ledger.db")
    ledger._initialize()
    for minute, pv, quality in [(0, 0.0, "exact"), (1, 1.0, "exact"), (2, 0.0, "estimated")]:
        ledger._insert_interval(
            {
                "start_ts": f"2026-08-20T10:0{minute}:00+00:00",
                "end_ts": f"2026-08-20T10:0{minute + 1}:00+00:00",
                "seconds": 60.0,
                "pv_production_kwh": pv,
                "fixed_cost": 0.0,
                "net_cost": 0.0,
                "quality": quality,
            }
        )
    pv_rows = ledger._query_intervals(None, None, None, "pv", 100, 0)
    issue_rows = ledger._query_intervals(None, None, None, "issues", 100, 0)
    assert pv_rows["total"] == 1
    assert issue_rows["total"] == 1


def test_small_counter_negative_correction_is_not_reset(tmp_path):
    ledger = mod.Ledger(None, tmp_path / "ledger.db")
    ledger._initialize()
    ledger._observe_source("daily_meter", "sensor.daily", 0.5, "2026-08-20T10:00:00+00:00")
    corrected = ledger._observe_source("daily_meter", "sensor.daily", 0.4, "2026-08-20T10:01:00+00:00")
    assert corrected["event"] == "negative_correction"
    assert corrected["delta"] == 0.0
