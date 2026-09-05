"""Sensors for Energy Cost Tracker."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    CONF_BATTERY_CHARGE_ENERGY,
    CONF_BATTERY_DISCHARGE_ENERGY,
    CONF_BATTERY_POWER,
    CONF_PV_ENERGY,
    CONF_PV_POWER,
    DOMAIN,
)


def _entity_ids(value: Any) -> list[str]:
    """Normalize legacy single-entity and current multi-select config."""
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    return [str(entity_id) for entity_id in value if entity_id]


def _has_pv_config(config: dict[str, Any]) -> bool:
    return bool(_entity_ids(config.get(CONF_PV_ENERGY)) or _entity_ids(config.get(CONF_PV_POWER)))


def _has_battery_config(config: dict[str, Any]) -> bool:
    # SOC alone is only an optional technical helper and does not constitute a battery system.
    return any(
        _entity_ids(config.get(key))
        for key in (CONF_BATTERY_CHARGE_ENERGY, CONF_BATTERY_DISCHARGE_ENERGY, CONF_BATTERY_POWER)
    )


@dataclass(frozen=True, slots=True)
class SensorDescription:
    key: str
    translation_key: str
    path: tuple[str, ...]
    unit_kind: str = "money"
    icon: str | None = None
    asset: str = "core"  # core | pv | battery


SENSORS = (
    SensorDescription("cost_hour", "cost_hour", ("periods", "hour", "net_cost"), icon="mdi:clock-outline"),
    SensorDescription("cost_today", "cost_today", ("periods", "today", "net_cost"), icon="mdi:cash-clock"),
    SensorDescription("cost_week", "cost_week", ("periods", "week", "net_cost"), icon="mdi:calendar-week"),
    SensorDescription("cost_month", "cost_month", ("periods", "month", "net_cost"), icon="mdi:calendar-month"),
    SensorDescription("cost_year", "cost_year", ("periods", "year", "net_cost"), icon="mdi:calendar"),
    SensorDescription("cost_billing_month", "cost_billing_month", ("periods", "billing_month", "net_cost"), icon="mdi:receipt-text"),
    SensorDescription("cost_billing_year", "cost_billing_year", ("periods", "billing_year", "net_cost"), icon="mdi:file-document-outline"),
    SensorDescription("cost_total", "cost_total", ("periods", "total", "net_cost"), icon="mdi:cash-multiple"),
    SensorDescription("pv_value_today", "pv_value_today", ("periods", "today", "pv_value"), icon="mdi:solar-power", asset="pv"),
    SensorDescription("pv_value_month", "pv_value_month", ("periods", "month", "pv_value"), icon="mdi:solar-panel-large", asset="pv"),
    SensorDescription("battery_profit_today", "battery_profit_today", ("periods", "today", "battery_profit"), icon="mdi:battery-arrow-down", asset="battery"),
    SensorDescription("battery_profit_month", "battery_profit_month", ("periods", "month", "battery_profit"), icon="mdi:battery-sync", asset="battery"),
    SensorDescription("battery_stored_cost", "battery_stored_cost", ("battery_inventory", "cost_basis"), unit_kind="current_money", icon="mdi:battery-lock", asset="battery"),
    SensorDescription("battery_stored_energy", "battery_stored_energy", ("battery_inventory", "energy_kwh"), unit_kind="energy", icon="mdi:battery", asset="battery"),
    SensorDescription("battery_average_stored_price", "battery_average_stored_price", ("battery_inventory", "average_price"), unit_kind="price", icon="mdi:battery-clock", asset="battery"),
)


def _enabled_descriptions(config: dict[str, Any]) -> list[SensorDescription]:
    has_pv = _has_pv_config(config)
    has_battery = _has_battery_config(config)
    return [
        desc
        for desc in SENSORS
        if desc.asset == "core"
        or (desc.asset == "pv" and has_pv)
        or (desc.asset == "battery" and has_battery)
    ]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    runtime = entry.runtime_data
    enabled = _enabled_descriptions(runtime.config)
    enabled_keys = {desc.key for desc in enabled}

    # A reconfigure may remove PV/battery inputs. Remove their stale registry
    # entities rather than leaving unavailable historical shells behind. The
    # financial ledger itself is deliberately untouched.
    registry = er.async_get(hass)
    for desc in SENSORS:
        if desc.key in enabled_keys:
            continue
        unique_id = f"{entry.entry_id}_{desc.key}"
        entity_id = registry.async_get_entity_id("sensor", DOMAIN, unique_id)
        if entity_id is not None:
            registry.async_remove(entity_id)

    async_add_entities([EnergyCostSensor(entry, runtime, desc) for desc in enabled])


class EnergyCostSensor(SensorEntity):
    """A ledger-backed sensor."""

    _attr_has_entity_name = True

    def __init__(self, entry: ConfigEntry, runtime, description: SensorDescription) -> None:
        self.entry = entry
        self.runtime = runtime
        self.description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_translation_key = description.translation_key
        self._attr_icon = description.icon
        if description.unit_kind == "money":
            self._attr_device_class = SensorDeviceClass.MONETARY
            self._attr_state_class = SensorStateClass.TOTAL
        elif description.unit_kind == "current_money":
            # Current battery inventory valuation is not an accumulated total.
            pass
        elif description.unit_kind == "energy":
            self._attr_device_class = SensorDeviceClass.ENERGY_STORAGE
            self._attr_state_class = SensorStateClass.MEASUREMENT
            self._attr_native_unit_of_measurement = "kWh"
        elif description.unit_kind == "price":
            self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.entry.entry_id)},
            name=self.entry.title,
            manufacturer="Energy Cost Tracker",
            model="Local accounting engine",
        )

    def _value(self):
        data: Any = self.runtime.summary
        for part in self.description.path:
            if not isinstance(data, dict):
                return None
            data = data.get(part)
        return data

    def _period(self) -> dict[str, Any] | None:
        if self.description.path[:1] != ("periods",):
            return None
        return self.runtime.summary.get("periods", {}).get(self.description.path[1], {})

    def _known_period_value(self) -> Any:
        """Return the defensible known subtotal when the definitive total is incomplete."""
        period = self._period()
        if period is None:
            return self._value()
        field = self.description.path[2]
        fallback = {
            "net_cost": "known_net_cost",
            "pv_value": "known_pv_value",
            "battery_profit": "known_battery_profit",
        }.get(field)
        value = period.get(field)
        if value is not None or fallback is None:
            return value
        return period.get(fallback)

    @property
    def native_value(self):
        value = self._known_period_value()
        if value is None:
            return None
        return round(float(value), 6)

    @property
    def native_unit_of_measurement(self) -> str | None:
        if self.description.unit_kind in {"money", "current_money"}:
            return self.runtime.summary.get("currency", self.hass.config.currency)
        if self.description.unit_kind == "price":
            currency = self.runtime.summary.get("currency", self.hass.config.currency)
            return f"{currency}/kWh"
        return self._attr_native_unit_of_measurement

    @property
    def last_reset(self) -> datetime | None:
        """Expose the active period boundary for resettable monetary totals."""
        if self.description.unit_kind != "money":
            return None
        if self.description.path[:1] != ("periods",):
            return None
        period_name = self.description.path[1]
        if period_name == "total":
            return None
        raw = self.runtime.summary.get("periods", {}).get(period_name, {}).get("period_start")
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.description.path[:1] != ("periods",):
            if self.description.key.startswith("battery_"):
                return {
                    "basis_known": self.runtime.summary.get("battery_inventory", {}).get("basis_known")
                }
            return None
        period_name = self.description.path[1]
        period = self.runtime.summary.get("periods", {}).get(period_name, {})
        field = self.description.path[2]
        if field == "pv_value":
            complete = bool(period.get("pv_complete", True))
            incomplete_intervals = int(period.get("incomplete_pv_intervals", 0) or 0)
        elif field == "battery_profit":
            complete = bool(period.get("battery_complete", True))
            incomplete_intervals = int(period.get("incomplete_battery_intervals", 0) or 0)
        else:
            complete = bool(period.get("financial_complete", True))
            incomplete_intervals = int(period.get("incomplete_cost_intervals", 0) or 0)
        non_exact = int(period.get("non_exact_intervals", 0) or 0)
        data_quality = "incomplete" if not complete else ("non_exact" if non_exact else "exact")
        return {
            "period_start": period.get("period_start"),
            "period_end": period.get("period_end"),
            "intervals": period.get("intervals", 0),
            "data_quality": data_quality,
            "known_subtotal": not complete,
            "incomplete_intervals": incomplete_intervals,
            "incomplete_cost_intervals": period.get("incomplete_cost_intervals", 0),
            "incomplete_import_intervals": period.get("incomplete_import_intervals", 0),
            "incomplete_export_intervals": period.get("incomplete_export_intervals", 0),
            "incomplete_pv_intervals": period.get("incomplete_pv_intervals", 0),
            "incomplete_battery_intervals": period.get("incomplete_battery_intervals", 0),
            "non_exact_intervals": non_exact,
            "known_net_cost": period.get("known_net_cost"),
            "known_import_cost": period.get("known_import_cost"),
            "known_export_revenue": period.get("known_export_revenue"),
            "known_pv_value": period.get("known_pv_value"),
            "known_battery_profit": period.get("known_battery_profit"),
            "financial_complete": period.get("financial_complete", True),
            "pv_complete": period.get("pv_complete", True),
            "battery_complete": period.get("battery_complete", True),
        }

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self.runtime.async_add_listener(self._handle_update))

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()
