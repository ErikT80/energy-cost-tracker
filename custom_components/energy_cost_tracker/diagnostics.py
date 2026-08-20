"""Diagnostics support for Energy Cost Tracker."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry) -> dict:
    runtime = entry.runtime_data
    return {
        "config": dict(entry.data),
        "summary": runtime.summary,
        "source_states": await runtime.ledger.async_source_states(),
        "recent_events": await runtime.ledger.async_recent_events(50),
        "database_path": str(runtime.ledger.path),
    }
