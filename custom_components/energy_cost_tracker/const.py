"""Constants for Energy Cost Tracker."""
from __future__ import annotations

DOMAIN = "energy_cost_tracker"
NAME = "Energy Cost Tracker"
VERSION = "0.1.0"
PLATFORMS = ["sensor"]

PANEL_URL = "energy-cost-tracker"
PANEL_COMPONENT = "energy-cost-tracker-panel"
PANEL_TITLE = "Energy Costs"
PANEL_ICON = "mdi:cash-multiple"
FRONTEND_URL = f"/{DOMAIN}/energy-cost-tracker-panel.js"

DB_FILENAME = f"{DOMAIN}.db"
ACCOUNTING_INTERVAL_SECONDS = 60

CONF_CURRENCY = "currency"

CONF_GRID_IMPORT_ENERGY = "grid_import_energy"
CONF_GRID_EXPORT_ENERGY = "grid_export_energy"
CONF_GRID_POWER = "grid_power"

CONF_PV_ENERGY = "pv_energy"
CONF_PV_POWER = "pv_power"

CONF_BATTERY_CHARGE_ENERGY = "battery_charge_energy"
CONF_BATTERY_DISCHARGE_ENERGY = "battery_discharge_energy"
CONF_BATTERY_POWER = "battery_power"
CONF_BATTERY_SOC = "battery_soc"
CONF_BATTERY_USABLE_CAPACITY = "battery_usable_capacity"
CONF_BATTERY_POWER_POSITIVE = "battery_power_positive"
CONF_BATTERY_EMPTY_SOC = "battery_empty_soc"
BATTERY_POSITIVE_CHARGING = "charging"
BATTERY_POSITIVE_DISCHARGING = "discharging"

CONF_IMPORT_PRICE = "import_price"
CONF_EXPORT_PRICE = "export_price"
CONF_IMPORT_PRICE_MULTIPLIER = "import_price_multiplier"
CONF_EXPORT_PRICE_MULTIPLIER = "export_price_multiplier"
CONF_IMPORT_PRICE_ADJUSTMENT = "import_price_adjustment"
CONF_EXPORT_PRICE_ADJUSTMENT = "export_price_adjustment"

CONF_FIXED_DAILY = "fixed_daily"
CONF_FIXED_MONTHLY = "fixed_monthly"
CONF_FIXED_ANNUAL = "fixed_annual"
CONF_ANNUAL_REBATE = "annual_rebate"

CONF_BILLING_MONTH_START_DAY = "billing_month_start_day"
CONF_BILLING_YEAR_START_MONTH = "billing_year_start_month"
CONF_BILLING_YEAR_START_DAY = "billing_year_start_day"

QUALITY_EXACT = "exact"
QUALITY_RECONSTRUCTED = "reconstructed"
QUALITY_ESTIMATED = "estimated"
QUALITY_MISSING_PRICE = "missing_price"
QUALITY_UNKNOWN_BATTERY_BASIS = "unknown_battery_basis"

DEFAULTS = {
    CONF_IMPORT_PRICE_MULTIPLIER: 1.0,
    CONF_EXPORT_PRICE_MULTIPLIER: 1.0,
    CONF_IMPORT_PRICE_ADJUSTMENT: 0.0,
    CONF_EXPORT_PRICE_ADJUSTMENT: 0.0,
    CONF_FIXED_DAILY: 0.0,
    CONF_FIXED_MONTHLY: 0.0,
    CONF_FIXED_ANNUAL: 0.0,
    CONF_ANNUAL_REBATE: 0.0,
    CONF_BILLING_MONTH_START_DAY: 1,
    CONF_BILLING_YEAR_START_MONTH: 1,
    CONF_BILLING_YEAR_START_DAY: 1,
    CONF_BATTERY_POWER_POSITIVE: BATTERY_POSITIVE_CHARGING,
    CONF_BATTERY_EMPTY_SOC: 5.0,
}
