"""Pure accounting logic for Energy Cost Tracker.

This module intentionally has no Home Assistant imports, which makes the financial
model easy to unit test and reuse.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(slots=True)
class EnergyFrame:
    """Energy deltas for one accounting interval, all in kWh."""

    grid_import: float = 0.0
    grid_export: float = 0.0
    pv_production: float = 0.0
    battery_charge: float = 0.0
    battery_discharge: float = 0.0


@dataclass(slots=True)
class Prices:
    """Effective all-in prices in currency/kWh."""

    import_price: Optional[float] = None
    export_price: Optional[float] = None


@dataclass(slots=True)
class BatteryInventory:
    """Weighted-average cost-basis inventory for energy stored in a battery."""

    energy_kwh: float = 0.0
    cost_basis: float = 0.0
    basis_known: bool = False

    @property
    def average_price(self) -> Optional[float]:
        if self.energy_kwh <= 1e-9:
            return None
        return self.cost_basis / self.energy_kwh

    def add(self, energy_kwh: float, cost: Optional[float]) -> None:
        if energy_kwh <= 0:
            return
        self.energy_kwh += energy_kwh
        if cost is None:
            self.basis_known = False
            return
        self.cost_basis += cost

    def withdraw(self, energy_kwh: float) -> tuple[Optional[float], float]:
        """Withdraw energy and return (cost_basis, uncovered_energy).

        If the initial battery inventory is unknown, the cost basis remains unknown
        until the battery has been observed empty and subsequently charged.
        """
        if energy_kwh <= 0:
            return 0.0, 0.0
        if self.energy_kwh <= 1e-9:
            if energy_kwh > 1e-9:
                self.basis_known = False
            return None, energy_kwh

        covered = min(energy_kwh, self.energy_kwh)
        uncovered = max(0.0, energy_kwh - covered)
        avg = self.cost_basis / self.energy_kwh if self.energy_kwh > 0 else 0.0
        cost = covered * avg
        self.energy_kwh -= covered
        self.cost_basis -= cost
        if abs(self.cost_basis) <= 1e-12:
            self.cost_basis = 0.0
        if self.energy_kwh <= 1e-9:
            self.energy_kwh = 0.0
            self.cost_basis = 0.0

        if uncovered > 1e-9:
            self.basis_known = False
        if not self.basis_known:
            return None, uncovered
        return cost, uncovered

    def mark_empty(self) -> float:
        """Mark the physical battery empty and return stranded cost as loss."""
        loss = self.cost_basis
        self.energy_kwh = 0.0
        self.cost_basis = 0.0
        self.basis_known = True
        return loss


@dataclass(slots=True)
class AccountingResult:
    house_consumption: float
    grid_to_house: float
    grid_to_battery: float
    pv_direct: float
    pv_export: float
    pv_to_battery: float
    battery_to_house: float
    battery_to_grid: float
    flow_residual: float
    import_cost: Optional[float]
    export_revenue: Optional[float]
    pv_value: Optional[float]
    battery_charge_cost: Optional[float]
    battery_discharge_value: Optional[float]
    battery_discharge_cost_basis: Optional[float]
    battery_profit: Optional[float]
    battery_uncovered_discharge: float


def _money(energy: float, price: Optional[float]) -> Optional[float]:
    if energy <= 1e-12:
        return 0.0
    if price is None:
        return None
    return energy * price


def _sum_optional(*values: Optional[float]) -> Optional[float]:
    if any(value is None for value in values):
        return None
    return sum(value or 0.0 for value in values)


def allocate_and_value(
    frame: EnergyFrame,
    prices: Prices,
    inventory: BatteryInventory,
) -> AccountingResult:
    """Allocate measured energy flows and calculate financial values.

    The allocation is deterministic and conservative. It treats PV as serving the
    home first, then battery charging, then export. Battery discharge serves the
    remaining home demand first and exports only the excess. The measured grid and
    battery totals remain authoritative; a residual quantifies inconsistent sensor
    timing or topology.
    """
    gi = max(0.0, frame.grid_import)
    ge = max(0.0, frame.grid_export)
    pv = max(0.0, frame.pv_production)
    bc = max(0.0, frame.battery_charge)
    bd = max(0.0, frame.battery_discharge)

    # AC-side energy balance. Negative values can occur with asynchronously updating
    # meters; clamp to zero and preserve the mismatch as residual below.
    house = max(0.0, gi + pv + bd - ge - bc)

    pv_direct = min(pv, house)
    remaining_house = max(0.0, house - pv_direct)

    battery_to_house = min(bd, remaining_house)
    remaining_house = max(0.0, remaining_house - battery_to_house)
    battery_to_grid = max(0.0, bd - battery_to_house)

    pv_after_direct = max(0.0, pv - pv_direct)
    pv_to_battery = min(bc, pv_after_direct)
    grid_to_battery = max(0.0, bc - pv_to_battery)
    pv_export = max(0.0, pv_after_direct - pv_to_battery)
    grid_to_house = remaining_house

    allocated_export = pv_export + battery_to_grid
    allocated_import = grid_to_house + grid_to_battery
    residual = abs(ge - allocated_export) + abs(gi - allocated_import)

    import_cost = _money(gi, prices.import_price)
    export_revenue = _money(ge, prices.export_price)

    pv_direct_value = _money(pv_direct, prices.import_price)
    pv_export_value = _money(pv_export, prices.export_price)
    pv_battery_value = _money(pv_to_battery, prices.export_price)
    pv_value = _sum_optional(pv_direct_value, pv_export_value, pv_battery_value)

    solar_charge_cost = _money(pv_to_battery, prices.export_price)
    grid_charge_cost = _money(grid_to_battery, prices.import_price)
    battery_charge_cost = _sum_optional(solar_charge_cost, grid_charge_cost)
    inventory.add(bc, battery_charge_cost)

    battery_house_value = _money(battery_to_house, prices.import_price)
    battery_grid_value = _money(battery_to_grid, prices.export_price)
    discharge_value = _sum_optional(battery_house_value, battery_grid_value)
    discharge_basis, uncovered = inventory.withdraw(bd)
    if discharge_value is None or discharge_basis is None:
        battery_profit = None
    else:
        battery_profit = discharge_value - discharge_basis

    return AccountingResult(
        house_consumption=house,
        grid_to_house=grid_to_house,
        grid_to_battery=grid_to_battery,
        pv_direct=pv_direct,
        pv_export=pv_export,
        pv_to_battery=pv_to_battery,
        battery_to_house=battery_to_house,
        battery_to_grid=battery_to_grid,
        flow_residual=residual,
        import_cost=import_cost,
        export_revenue=export_revenue,
        pv_value=pv_value,
        battery_charge_cost=battery_charge_cost,
        battery_discharge_value=discharge_value,
        battery_discharge_cost_basis=discharge_basis,
        battery_profit=battery_profit,
        battery_uncovered_discharge=uncovered,
    )
