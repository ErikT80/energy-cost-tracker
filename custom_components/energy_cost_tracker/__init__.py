"""Energy Cost Tracker integration."""
from __future__ import annotations

from pathlib import Path

from homeassistant.auth import EVENT_USER_ADDED, EVENT_USER_REMOVED, EVENT_USER_UPDATED
from homeassistant.components import frontend
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import config_validation as cv

from .access import (
    async_remove_stale_user,
    async_subscribe_sidebar_guard,
    async_sync_all_sidebars,
    async_sync_user_sidebar,
)
from .const import (
    CONFIG_ENTRY_MINOR_VERSION,
    CONFIG_ENTRY_VERSION,
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
from .migration import migrate_config_data
from .runtime import EnergyCostRuntime
from .websocket import async_register as async_register_websocket


CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up integration-level APIs and static frontend."""
    hass.data.setdefault(DOMAIN, {})
    frontend_dir = Path(__file__).parent / "frontend"
    await hass.http.async_register_static_paths(
        [StaticPathConfig(FRONTEND_URL, str(frontend_dir / "energy-cost-tracker-panel.js"), False)]
    )
    async_register_websocket(hass)
    return True


def _register_panel(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Register a custom panel that is hidden by default for new users."""
    if frontend.async_panel_exists(hass, PANEL_URL):
        return
    # panel_custom.async_register_panel does not expose sidebar_default_visible.
    # This mirrors its _panel_custom payload but lets ECT opt into Home
    # Assistant's default-hidden panel behavior. Admin/whitelist visibility is
    # then stored in each user's frontend sidebar data.
    frontend.async_register_built_in_panel(
        hass,
        component_name="custom",
        sidebar_title=PANEL_TITLE,
        sidebar_icon=PANEL_ICON,
        sidebar_default_visible=False,
        frontend_url_path=PANEL_URL,
        config={
            "domain": DOMAIN,
            "entry_id": entry.entry_id,
            "_panel_custom": {
                "name": PANEL_COMPONENT,
                "embed_iframe": False,
                "trust_external": False,
                "handle_safe_area": False,
                "module_url": FRONTEND_URL,
            },
        },
        require_admin=False,
    )


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate older config entries forward without touching ledger history."""
    if entry.version > CONFIG_ENTRY_VERSION:
        return False
    if (entry.version, entry.minor_version) == (
        CONFIG_ENTRY_VERSION,
        CONFIG_ENTRY_MINOR_VERSION,
    ):
        return True

    try:
        data = migrate_config_data(entry.data, entry.version)
    except (TypeError, ValueError):
        return False

    hass.config_entries.async_update_entry(
        entry,
        data=data,
        version=CONFIG_ENTRY_VERSION,
        minor_version=CONFIG_ENTRY_MINOR_VERSION,
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Energy Cost Tracker from a config entry."""
    ledger = Ledger(hass, Path(hass.config.path(".storage", DB_FILENAME)))
    runtime = EnergyCostRuntime(hass, entry, ledger)
    entry.runtime_data = runtime
    hass.data[DOMAIN][entry.entry_id] = runtime
    await runtime.async_start()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    _register_panel(hass, entry)
    await async_sync_all_sidebars(hass, runtime)

    sidebar_guards: dict[str, object] = {}

    async def _ensure_sidebar_guard(user_id: str) -> None:
        if user_id in sidebar_guards:
            return
        unsubscribe = await async_subscribe_sidebar_guard(hass, runtime, user_id)
        if unsubscribe is not None:
            sidebar_guards[user_id] = unsubscribe

    for user in await hass.auth.async_get_users():
        if not user.system_generated:
            await _ensure_sidebar_guard(user.id)

    @callback
    def _cleanup_sidebar_guards() -> None:
        for unsubscribe in list(sidebar_guards.values()):
            unsubscribe()
        sidebar_guards.clear()

    entry.async_on_unload(_cleanup_sidebar_guards)

    @callback
    def _handle_user_change(event: Event) -> None:
        user_id = str(event.data.get("user_id") or "")
        if not user_id:
            return

        async def _sync() -> None:
            if event.event_type == EVENT_USER_REMOVED:
                unsubscribe = sidebar_guards.pop(user_id, None)
                if unsubscribe is not None:
                    unsubscribe()
                await async_remove_stale_user(hass, runtime, user_id)
                return
            await _ensure_sidebar_guard(user_id)
            await async_sync_user_sidebar(hass, runtime, user_id)

        hass.async_create_task(_sync())

    for event_type in (EVENT_USER_ADDED, EVENT_USER_UPDATED, EVENT_USER_REMOVED):
        entry.async_on_unload(hass.bus.async_listen(event_type, _handle_user_change))
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
