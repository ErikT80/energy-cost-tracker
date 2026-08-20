from pathlib import Path
import importlib.util
import sys

MODULE = Path(__file__).parents[1] / "custom_components" / "energy_cost_tracker" / "accounting.py"
spec = importlib.util.spec_from_file_location("ect_accounting", MODULE)
mod = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


def test_pv_direct_and_export_value():
    inv = mod.BatteryInventory(basis_known=True)
    result = mod.allocate_and_value(
        mod.EnergyFrame(grid_import=0, grid_export=1, pv_production=2, battery_charge=0, battery_discharge=0),
        mod.Prices(import_price=0.30, export_price=0.10),
        inv,
    )
    assert round(result.house_consumption, 6) == 1.0
    assert round(result.pv_direct, 6) == 1.0
    assert round(result.pv_export, 6) == 1.0
    assert round(result.pv_value, 6) == 0.40


def test_grid_battery_arbitrage_profit():
    inv = mod.BatteryInventory(basis_known=True)
    charge = mod.allocate_and_value(
        mod.EnergyFrame(grid_import=1, battery_charge=1),
        mod.Prices(import_price=0.10, export_price=0.05),
        inv,
    )
    assert round(charge.battery_charge_cost, 6) == 0.10
    discharge = mod.allocate_and_value(
        mod.EnergyFrame(battery_discharge=1),
        mod.Prices(import_price=0.40, export_price=0.05),
        inv,
    )
    assert round(discharge.battery_profit, 6) == 0.30


def test_solar_to_battery_uses_export_opportunity_cost():
    inv = mod.BatteryInventory(basis_known=True)
    charge = mod.allocate_and_value(
        mod.EnergyFrame(pv_production=1, battery_charge=1),
        mod.Prices(import_price=0.30, export_price=0.08),
        inv,
    )
    assert round(charge.battery_charge_cost, 6) == 0.08
    assert round(inv.cost_basis, 6) == 0.08


def test_negative_grid_price_cost_basis_survives_partial_discharge():
    inv = mod.BatteryInventory(basis_known=True)
    mod.allocate_and_value(
        mod.EnergyFrame(grid_import=2, battery_charge=2),
        mod.Prices(import_price=-0.10, export_price=0.05),
        inv,
    )
    assert round(inv.cost_basis, 6) == -0.20
    first = mod.allocate_and_value(
        mod.EnergyFrame(battery_discharge=1),
        mod.Prices(import_price=0.30, export_price=0.05),
        inv,
    )
    assert round(first.battery_discharge_cost_basis, 6) == -0.10
    assert round(first.battery_profit, 6) == 0.40
    assert round(inv.cost_basis, 6) == -0.10
    assert round(inv.energy_kwh, 6) == 1.0


def test_uncovered_discharge_invalidates_cost_basis_until_reconciled():
    inv = mod.BatteryInventory(energy_kwh=1.0, cost_basis=0.10, basis_known=True)
    result = mod.allocate_and_value(
        mod.EnergyFrame(battery_discharge=2.0),
        mod.Prices(import_price=0.30, export_price=0.05),
        inv,
    )
    assert result.battery_discharge_cost_basis is None
    assert result.battery_profit is None
    assert inv.basis_known is False
