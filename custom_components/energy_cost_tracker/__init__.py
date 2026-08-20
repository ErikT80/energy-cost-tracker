"""Energy Cost Tracker integration."""
from __future__ import annotations

from pathlib import Path

from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    DB_FILENAME,
    DOMAIN,
    FRONTEND_URL,
    PANEL_COMPONENT,
    PANEL_ICON,
    PANEL_TITLE,
    PANEL_URL,
    PLATFORMS,
)
from .ledger import Ledger
from .runtime import EnergyCostRuntime
from .websocket import async_register as async_register_websocket


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up integration-level APIs and static frontend."""
    hass.data.setdefault(DOMAIN, {})
    frontend_dir = Path(__file__).parent / "frontend"
    await hass.http.async_register_static_paths(
        [StaticPathConfig(FRONTEND_URL, str(frontend_dir / "energy-cost-tracker-panel.js"), False)]
    )
    async_register_websocket(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Energy Cost Tracker from a config entry."""
    ledger = Ledger(hass, Path(hass.config.path(".storage", DB_FILENAME)))
    runtime = EnergyCostRuntime(hass, entry, ledger)
    entry.runtime_data = runtime
    hass.data[DOMAIN][entry.entry_id] = runtime
    await runtime.async_start()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    if not frontend.async_panel_exists(hass, PANEL_URL):
        await panel_custom.async_register_panel(
            hass,
            frontend_url_path=PANEL_URL,
            webcomponent_name=PANEL_COMPONENT,
            sidebar_title=PANEL_TITLE,
            sidebar_icon=PANEL_ICON,
            module_url=FRONTEND_URL,
            config={"domain": DOMAIN, "entry_id": entry.entry_id},
        )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry without deleting its financial history."""
    runtime = entry.runtime_data
    await runtime.async_stop()
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    if frontend.async_panel_exists(hass, PANEL_URL):
        frontend.async_remove_panel(hass, PANEL_URL)
    return unload_ok
