"""Regression tests for source-availability classification."""
from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

ROOT = Path(__file__).parents[1]
INTEGRATION = ROOT / "custom_components" / "energy_cost_tracker"


def _install_homeassistant_stubs() -> None:
    homeassistant = ModuleType("homeassistant")
    const = ModuleType("homeassistant.const")
    core = ModuleType("homeassistant.core")
    helpers = ModuleType("homeassistant.helpers")
    helpers_event = ModuleType("homeassistant.helpers.event")
    util = ModuleType("homeassistant.util")
    dt_mod = ModuleType("homeassistant.util.dt")
    conversion = ModuleType("homeassistant.util.unit_conversion")

    class UnitOfEnergy:
        KILO_WATT_HOUR = "kWh"

    class EnergyConverter:
        VALID_UNITS = {"Wh", "kWh", "MWh"}

        @staticmethod
        def converter_factory(_from, _to):
            return lambda value: value

    const.UnitOfEnergy = UnitOfEnergy
    core.Event = object
    core.EventStateChangedData = object
    core.HomeAssistant = object
    core.callback = lambda func: func
    helpers_event.async_track_point_in_utc_time = lambda *args, **kwargs: None
    helpers_event.async_track_state_change_event = lambda *args, **kwargs: None
    helpers_event.async_track_time_interval = lambda *args, **kwargs: None
    dt_mod.utcnow = lambda: datetime.now(timezone.utc)
    dt_mod.now = lambda: datetime.now(timezone.utc)
    dt_mod.as_utc = lambda value: value.astimezone(timezone.utc)
    dt_mod.get_time_zone = lambda _name: timezone.utc
    conversion.EnergyConverter = EnergyConverter
    util.dt = dt_mod

    sys.modules.update({
        "homeassistant": homeassistant,
        "homeassistant.const": const,
        "homeassistant.core": core,
        "homeassistant.helpers": helpers,
        "homeassistant.helpers.event": helpers_event,
        "homeassistant.util": util,
        "homeassistant.util.dt": dt_mod,
        "homeassistant.util.unit_conversion": conversion,
    })


def _load_runtime_module():
    _install_homeassistant_stubs()
    package_name = "_ect_source_availability_test"
    package = ModuleType(package_name)
    package.__path__ = [str(INTEGRATION)]
    sys.modules[package_name] = package
    module_name = f"{package_name}.runtime"
    spec = importlib.util.spec_from_file_location(module_name, INTEGRATION / "runtime.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


RUNTIME = _load_runtime_module()


def _runtime():
    entry = SimpleNamespace(
        data={
            RUNTIME.CONF_GRID_IMPORT_ENERGY: "sensor.grid_import",
            RUNTIME.CONF_GRID_EXPORT_ENERGY: "sensor.grid_export",
            RUNTIME.CONF_BATTERY_CHARGE_ENERGY: ["sensor.bat1_charge", "sensor.bat2_charge"],
            RUNTIME.CONF_BATTERY_DISCHARGE_ENERGY: ["sensor.bat1_discharge", "sensor.bat2_discharge"],
            RUNTIME.CONF_BATTERY_POWER: ["sensor.bat1_power", "sensor.bat2_power"],
        },
        options={},
    )
    hass = SimpleNamespace(config=SimpleNamespace(time_zone="UTC", currency="EUR"))
    return RUNTIME.EnergyCostRuntime(hass, entry, SimpleNamespace())


def test_battery_energy_unavailability_is_degraded_not_critical():
    runtime = _runtime()
    critical, degraded = runtime._split_unavailable_energy_sources(
        ["sensor.bat1_charge", "sensor.grid_export"]
    )
    assert critical == ["sensor.grid_export"]
    assert degraded == ["sensor.bat1_charge"]


def test_battery_power_sensors_are_not_cumulative_accounting_sources():
    runtime = _runtime()
    configured = runtime._configured_energy_entities()
    assert "sensor.bat1_power" not in configured
    assert "sensor.bat2_power" not in configured
    assert "sensor.bat1_charge" in configured
    assert "sensor.bat1_discharge" in configured
