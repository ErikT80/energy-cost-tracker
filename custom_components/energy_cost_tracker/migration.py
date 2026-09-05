"""Pure helpers for forward-only Energy Cost Tracker config migrations."""
from __future__ import annotations

from typing import Any, Mapping

from .const import (
    BATTERY_POSITIVE_CHARGING,
    CONF_BATTERY_CHARGE_ENERGY,
    CONF_BATTERY_DISCHARGE_ENERGY,
    CONF_BATTERY_EMPTY_SOC,
    CONF_BATTERY_POWER,
    CONF_BATTERY_POWER_POSITIVE,
    CONF_BATTERY_SOC,
    CONF_EXPORT_PRICE_ADJUSTMENT,
    CONF_EXPORT_PRICE_MULTIPLIER,
    CONF_IMPORT_PRICE_ADJUSTMENT,
    CONF_IMPORT_PRICE_MULTIPLIER,
    CONF_PV_ENERGY,
    CONF_PV_POWER,
    CONFIG_ENTRY_VERSION,
    DEFAULTS,
)

_MULTI_ENTITY_KEYS = (
    CONF_PV_ENERGY,
    CONF_PV_POWER,
    CONF_BATTERY_CHARGE_ENERGY,
    CONF_BATTERY_DISCHARGE_ENERGY,
    CONF_BATTERY_POWER,
    CONF_BATTERY_SOC,
)


def _as_entity_list(value: Any) -> list[str]:
    """Normalize an old single/multiple entity field to a clean list."""
    if value in (None, "", []):
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if item not in (None, "")]
    return [str(value)]


def migrate_config_data(data: Mapping[str, Any], from_version: int) -> dict[str, Any]:
    """Return migrated config-entry data without mutating the input mapping."""
    if from_version > CONFIG_ENTRY_VERSION:
        raise ValueError(
            f"Config entry version {from_version} is newer than supported version "
            f"{CONFIG_ENTRY_VERSION}"
        )

    migrated = dict(data)
    version = int(from_version)

    if version < 2:
        # Early alpha releases accepted a mix of one entity string and multiple
        # entity lists. Version 2 makes the multi-source contract explicit so a
        # future migration can rely on one stable representation.
        for key in _MULTI_ENTITY_KEYS:
            migrated[key] = _as_entity_list(migrated.get(key))

        migrated.setdefault(
            CONF_BATTERY_POWER_POSITIVE,
            DEFAULTS.get(CONF_BATTERY_POWER_POSITIVE, BATTERY_POSITIVE_CHARGING),
        )
        migrated.setdefault(
            CONF_BATTERY_EMPTY_SOC,
            DEFAULTS[CONF_BATTERY_EMPTY_SOC],
        )
        migrated.setdefault(
            CONF_IMPORT_PRICE_MULTIPLIER,
            DEFAULTS[CONF_IMPORT_PRICE_MULTIPLIER],
        )
        migrated.setdefault(
            CONF_EXPORT_PRICE_MULTIPLIER,
            DEFAULTS[CONF_EXPORT_PRICE_MULTIPLIER],
        )
        migrated.setdefault(
            CONF_IMPORT_PRICE_ADJUSTMENT,
            DEFAULTS[CONF_IMPORT_PRICE_ADJUSTMENT],
        )
        migrated.setdefault(
            CONF_EXPORT_PRICE_ADJUSTMENT,
            DEFAULTS[CONF_EXPORT_PRICE_ADJUSTMENT],
        )
        version = 2

    if version != CONFIG_ENTRY_VERSION:
        raise ValueError(f"No config migration path to version {CONFIG_ENTRY_VERSION}")
    return migrated
