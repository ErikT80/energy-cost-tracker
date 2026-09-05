"""Tests for the pure config-entry migration helpers."""
from pathlib import Path
import importlib.util
import sys
import types

ROOT = Path(__file__).parents[1] / "custom_components" / "energy_cost_tracker"
PKG = "ect_migration_test"
pkg = types.ModuleType(PKG)
pkg.__path__ = [str(ROOT)]
sys.modules[PKG] = pkg


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(f"{PKG}.{name}", ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


const = _load("const", "const.py")
migration = _load("migration", "migration.py")


def test_v1_single_entities_are_normalized_to_lists():
    data = {
        const.CONF_PV_ENERGY: "sensor.pv_total",
        const.CONF_BATTERY_CHARGE_ENERGY: "sensor.battery_charge",
        const.CONF_BATTERY_DISCHARGE_ENERGY: None,
    }
    result = migration.migrate_config_data(data, 1)
    assert result[const.CONF_PV_ENERGY] == ["sensor.pv_total"]
    assert result[const.CONF_BATTERY_CHARGE_ENERGY] == ["sensor.battery_charge"]
    assert result[const.CONF_BATTERY_DISCHARGE_ENERGY] == []
    assert result[const.CONF_IMPORT_PRICE_MULTIPLIER] == 1.0
    assert result[const.CONF_BATTERY_EMPTY_SOC] == 5.0


def test_current_config_migration_is_idempotent():
    data = {const.CONF_PV_ENERGY: ["sensor.one", "sensor.two"]}
    assert migration.migrate_config_data(data, const.CONFIG_ENTRY_VERSION) == data


def test_future_config_version_is_refused():
    try:
        migration.migrate_config_data({}, const.CONFIG_ENTRY_VERSION + 1)
    except ValueError as err:
        assert "newer" in str(err)
    else:
        raise AssertionError("future config versions must be refused")
