"""Per-user access and sidebar visibility for Energy Cost Tracker."""
from __future__ import annotations

from typing import Any

from homeassistant.components.frontend.storage import async_user_store
from homeassistant.core import HomeAssistant

from .const import CONF_PANEL_ALLOWED_USERS, PANEL_URL


def configured_allowed_user_ids(runtime: Any) -> set[str]:
    """Return explicitly allowed non-admin user IDs."""
    raw = runtime.entry.options.get(CONF_PANEL_ALLOWED_USERS, []) or []
    if isinstance(raw, str):
        return {raw}
    return {str(user_id) for user_id in raw if user_id}


def user_can_access(runtime: Any, user: Any) -> bool:
    """Return whether a Home Assistant user may read the ECT panel API."""
    return bool(user and (user.is_admin or user.id in configured_allowed_user_ids(runtime)))


async def async_access_users(hass: HomeAssistant, runtime: Any) -> list[dict[str, Any]]:
    """Return human users and their effective panel access for the admin UI."""
    allowed = configured_allowed_user_ids(runtime)
    users = await hass.auth.async_get_users()
    result: list[dict[str, Any]] = []
    for user in users:
        if user.system_generated:
            continue
        result.append(
            {
                "id": user.id,
                "name": user.name or "User",
                "is_admin": bool(user.is_admin),
                "is_owner": bool(user.is_owner),
                "is_active": bool(user.is_active),
                "allowed": bool(user.is_admin or user.id in allowed),
            }
        )
    result.sort(key=lambda item: (not item["is_admin"], item["name"].casefold()))
    return result


async def async_sync_user_sidebar(
    hass: HomeAssistant, runtime: Any, user_id: str
) -> None:
    """Keep the ECT sidebar item aligned with the admin-managed access policy."""
    user = await hass.auth.async_get_user(user_id)
    if user is None or user.system_generated:
        return

    should_show = bool(user.is_active and user_can_access(runtime, user))
    store = await async_user_store(hass, user.id)
    sidebar = dict(store.data.get("sidebar") or {})
    panel_order = list(sidebar.get("panelOrder") or [])
    hidden_panels = list(sidebar.get("hiddenPanels") or [])

    before = (tuple(panel_order), tuple(hidden_panels))
    if should_show:
        hidden_panels = [item for item in hidden_panels if item != PANEL_URL]
        if PANEL_URL not in panel_order:
            panel_order.append(PANEL_URL)
    else:
        panel_order = [item for item in panel_order if item != PANEL_URL]
        if PANEL_URL not in hidden_panels:
            hidden_panels.append(PANEL_URL)

    after = (tuple(panel_order), tuple(hidden_panels))
    if before == after:
        return

    sidebar["panelOrder"] = panel_order
    sidebar["hiddenPanels"] = hidden_panels
    await store.async_set_item("sidebar", sidebar)


async def async_sync_all_sidebars(hass: HomeAssistant, runtime: Any) -> None:
    """Apply the panel visibility policy to all human users."""
    users = await hass.auth.async_get_users()
    for user in users:
        if not user.system_generated:
            await async_sync_user_sidebar(hass, runtime, user.id)


async def async_set_allowed_users(
    hass: HomeAssistant, runtime: Any, requested_ids: list[str]
) -> list[dict[str, Any]]:
    """Persist explicitly allowed non-admin users and synchronize sidebars."""
    users = await hass.auth.async_get_users()
    valid_non_admin = {
        user.id
        for user in users
        if not user.system_generated and user.is_active and not user.is_admin
    }
    allowed = sorted({str(user_id) for user_id in requested_ids if user_id in valid_non_admin})
    options = dict(runtime.entry.options)
    options[CONF_PANEL_ALLOWED_USERS] = allowed
    hass.config_entries.async_update_entry(runtime.entry, options=options)
    await async_sync_all_sidebars(hass, runtime)
    return await async_access_users(hass, runtime)


async def async_remove_stale_user(
    hass: HomeAssistant, runtime: Any, user_id: str
) -> None:
    """Remove deleted users from the persisted whitelist."""
    allowed = configured_allowed_user_ids(runtime)
    if user_id not in allowed:
        return
    allowed.discard(user_id)
    options = dict(runtime.entry.options)
    options[CONF_PANEL_ALLOWED_USERS] = sorted(allowed)
    hass.config_entries.async_update_entry(runtime.entry, options=options)


async def async_subscribe_sidebar_guard(
    hass: HomeAssistant, runtime: Any, user_id: str
):
    """Re-apply ECT sidebar policy whenever a user edits their sidebar."""
    user = await hass.auth.async_get_user(user_id)
    if user is None or user.system_generated:
        return None
    store = await async_user_store(hass, user.id)

    def _sidebar_changed() -> None:
        hass.async_create_task(async_sync_user_sidebar(hass, runtime, user.id))

    return store.async_subscribe("sidebar", _sidebar_changed)
