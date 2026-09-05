from pathlib import Path
import importlib.util
import sys

MODULE = Path(__file__).parents[1] / "custom_components" / "energy_cost_tracker" / "accumulator.py"
spec = importlib.util.spec_from_file_location("ect_accumulator", MODULE)
mod = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


def sample(start, end, *, seconds=60, import_price=0.2, import_cost=0.02, quality="exact"):
    return {
        "start_ts": start,
        "end_ts": end,
        "seconds": seconds,
        "grid_import_kwh": 0.1,
        "grid_export_kwh": 0.0,
        "house_consumption_kwh": 0.1,
        "pv_production_kwh": 0.0,
        "battery_charge_kwh": 0.0,
        "battery_discharge_kwh": 0.0,
        "grid_to_house_kwh": 0.1,
        "grid_to_battery_kwh": 0.0,
        "pv_direct_kwh": 0.0,
        "pv_export_kwh": 0.0,
        "pv_to_battery_kwh": 0.0,
        "battery_to_house_kwh": 0.0,
        "battery_to_grid_kwh": 0.0,
        "flow_residual_kwh": 0.0,
        "import_price": import_price,
        "export_price": 0.1,
        "import_cost": import_cost,
        "export_revenue": 0.0,
        "fixed_cost": 0.001,
        "net_cost": None if import_cost is None else import_cost + 0.001,
        "pv_value": 0.0,
        "battery_charge_cost": 0.0,
        "battery_discharge_value": 0.0,
        "battery_discharge_cost_basis": 0.0,
        "battery_profit": 0.0,
        "battery_loss_cost": 0.0,
        "quality": quality,
        "notes": None,
    }


def test_accumulator_creates_one_row_for_many_samples():
    acc = mod.IntervalAccumulator()
    acc.add(sample("2026-08-29T10:00:00+00:00", "2026-08-29T10:01:00+00:00"))
    acc.add(sample("2026-08-29T10:01:00+00:00", "2026-08-29T10:02:00+00:00", import_price=0.4, import_cost=0.04))
    row = acc.to_ledger_row()
    assert row is not None
    assert row["start_ts"] == "2026-08-29T10:00:00+00:00"
    assert row["end_ts"] == "2026-08-29T10:02:00+00:00"
    assert row["seconds"] == 120
    assert round(row["grid_import_kwh"], 6) == 0.2
    assert round(row["import_cost"], 6) == 0.06
    assert round(row["import_price"], 6) == 0.3


def test_accumulator_preserves_incomplete_financial_field():
    acc = mod.IntervalAccumulator()
    acc.add(sample("2026-08-29T10:00:00+00:00", "2026-08-29T10:01:00+00:00"))
    acc.add(sample("2026-08-29T10:01:00+00:00", "2026-08-29T10:02:00+00:00", import_price=None, import_cost=None, quality="missing_price"))
    row = acc.to_ledger_row()
    assert row is not None
    assert row["import_cost"] is None
    assert row["net_cost"] is None
    assert row["quality"] == "missing_price"


def test_accumulator_checkpoint_roundtrip():
    acc = mod.IntervalAccumulator()
    acc.add(sample("2026-08-29T10:00:00+00:00", "2026-08-29T10:01:00+00:00"))
    restored = mod.IntervalAccumulator.from_json(acc.to_json())
    assert restored.to_ledger_row() == acc.to_ledger_row()
