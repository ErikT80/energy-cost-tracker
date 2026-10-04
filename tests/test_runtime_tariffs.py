"""Regression tests for tariff-boundary runtime coordination."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
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

    sys.modules.update(
        {
            "homeassistant": homeassistant,
            "homeassistant.const": const,
            "homeassistant.core": core,
            "homeassistant.helpers": helpers,
            "homeassistant.helpers.event": helpers_event,
            "homeassistant.util": util,
            "homeassistant.util.dt": dt_mod,
            "homeassistant.util.unit_conversion": conversion,
        }
    )


def _load_runtime_module():
    _install_homeassistant_stubs()
    package_name = "_ect_runtime_test"
    package = ModuleType(package_name)
    package.__path__ = [str(INTEGRATION)]
    sys.modules[package_name] = package
    module_name = f"{package_name}.runtime"
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(module_name, INTEGRATION / "runtime.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


RUNTIME = _load_runtime_module()


class FakeStates:
    def __init__(self, values):
        self.values = values

    def get(self, entity_id):
        return self.values.get(entity_id)


class FakeTask:
    def __init__(self):
        self.cancelled = False

    def done(self):
        return False

    def cancel(self):
        self.cancelled = True


class FakeEntry:
    def __init__(self, data):
        self.data = data
        self.options = {}
        self.created = []

    def async_create_task(self, _hass, coro, _name):
        self.created.append(coro)
        coro.close()
        return FakeTask()


class FakeLedger:
    def __init__(self):
        self.meta = {}

    async def async_set_meta(self, key, value):
        self.meta[key] = value


class FakeHass:
    def __init__(self, states):
        self.states = FakeStates(states)
        self.config = SimpleNamespace(time_zone="UTC", currency="EUR")


def _state(value, **attrs):
    return SimpleNamespace(state=str(value), attributes=attrs)


def _event(entity_id, old_state, new_state, when):
    return SimpleNamespace(
        data={
            "entity_id": entity_id,
            "old_state": old_state,
            "new_state": new_state,
        },
        time_fired=when,
    )


def _runtime(states):
    entry = FakeEntry(
        {
            RUNTIME.CONF_IMPORT_PRICE: "sensor.import_price",
            RUNTIME.CONF_EXPORT_PRICE: "sensor.export_price",
        }
    )
    runtime = RUNTIME.EnergyCostRuntime(FakeHass(states), entry, FakeLedger())
    runtime._refresh_live = lambda: None
    return runtime, entry


def test_attribute_only_price_update_does_not_create_tariff_boundary():
    now = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)
    old = _state(0.25, unit_of_measurement="EUR/kWh", source="old")
    new = _state(0.25, unit_of_measurement="EUR/kWh", source="new")
    runtime, entry = _runtime({"sensor.import_price": new})

    runtime._state_changed(_event("sensor.import_price", old, new, now))

    assert entry.created == []
    assert runtime._tariff_change_task is None


def test_near_simultaneous_import_export_changes_share_one_boundary_and_hold_tick():
    now = datetime(2026, 10, 3, 12, 15, tzinfo=timezone.utc)
    import_old = _state(0.20, unit_of_measurement="EUR/kWh")
    import_new = _state(0.25, unit_of_measurement="EUR/kWh")
    export_old = _state(0.10, unit_of_measurement="EUR/kWh")
    export_new = _state(0.15, unit_of_measurement="EUR/kWh")
    runtime, entry = _runtime(
        {
            "sensor.import_price": import_new,
            "sensor.export_price": export_new,
        }
    )

    runtime._state_changed(_event("sensor.import_price", import_old, import_new, now))
    runtime._state_changed(
        _event(
            "sensor.export_price",
            export_old,
            export_new,
            now + timedelta(milliseconds=200),
        )
    )

    assert len(entry.created) == 1

    processed = 0

    async def fake_process_tick(*_args, **_kwargs):
        nonlocal processed
        processed += 1

    runtime.async_process_tick = fake_process_tick
    asyncio.run(runtime._scheduled_tick(now + timedelta(milliseconds=300)))
    assert processed == 0


def test_price_update_five_seconds_after_quarter_boundary_updates_next_tariff_only():
    boundary = datetime(2026, 10, 3, 12, 30, tzinfo=timezone.utc)
    import_new = _state(0.31, unit_of_measurement="EUR/kWh")
    export_new = _state(0.18, unit_of_measurement="EUR/kWh")
    runtime, _entry = _runtime(
        {
            "sensor.import_price": import_new,
            "sensor.export_price": export_new,
        }
    )
    runtime._last_ledger_boundary = boundary
    runtime._pending_tariff_change_at = boundary + timedelta(seconds=5)

    processed = 0

    async def fake_process_tick(*_args, **_kwargs):
        nonlocal processed
        processed += 1

    async def immediate_sleep(_seconds):
        return None

    runtime.async_process_tick = fake_process_tick
    original_sleep = RUNTIME.asyncio.sleep
    RUNTIME.asyncio.sleep = immediate_sleep
    try:
        asyncio.run(runtime._async_handle_tariff_change())
    finally:
        RUNTIME.asyncio.sleep = original_sleep

    assert processed == 0
    assert runtime.ledger.meta == {
        "last_import_price": "0.31",
        "last_export_price": "0.18",
    }
