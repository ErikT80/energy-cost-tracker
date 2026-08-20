"""WebSocket API for the Energy Cost Tracker sidebar panel."""
from __future__ import annotations

from datetime import datetime
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.util import dt as dt_util

from .const import DOMAIN


def _runtime(hass: HomeAssistant):
    data = hass.data.get(DOMAIN, {})
    for value in data.values():
        if hasattr(value, "ledger"):
            return value
    return None


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/summary"})
@websocket_api.async_response
async def websocket_summary(hass, connection, msg) -> None:
    runtime = _runtime(hass)
    if runtime is None:
        connection.send_error(msg["id"], "not_loaded", "Energy Cost Tracker is not loaded")
        return
    await runtime.async_refresh_summary()
    result = dict(runtime.summary)
    result["config"] = {
        "title": runtime.entry.title,
        "billing_month_start_day": runtime.config.get("billing_month_start_day", 1),
        "billing_year_start_month": runtime.config.get("billing_year_start_month", 1),
        "billing_year_start_day": runtime.config.get("billing_year_start_day", 1),
    }
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/ledger",
        vol.Optional("start"): str,
        vol.Optional("end"): str,
        vol.Optional("quality"): vol.In(["exact", "reconstructed", "estimated", "missing_price", "unknown_battery_basis"]),
        vol.Optional("activity"): vol.In(["grid_import", "grid_export", "pv", "battery_charge", "battery_discharge", "issues"]),
        vol.Optional("limit", default=250): vol.All(vol.Coerce(int), vol.Range(min=1, max=1000)),
        vol.Optional("offset", default=0): vol.All(vol.Coerce(int), vol.Range(min=0)),
    }
)
@websocket_api.async_response
async def websocket_ledger(hass, connection, msg) -> None:
    runtime = _runtime(hass)
    if runtime is None:
        connection.send_error(msg["id"], "not_loaded", "Energy Cost Tracker is not loaded")
        return
    result = await runtime.ledger.async_query_intervals(
        msg.get("start"),
        msg.get("end"),
        msg.get("quality"),
        msg.get("activity"),
        msg["limit"],
        msg["offset"],
    )
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/events", vol.Optional("limit", default=50): vol.All(vol.Coerce(int), vol.Range(min=1, max=500))})
@websocket_api.async_response
async def websocket_events(hass, connection, msg) -> None:
    runtime = _runtime(hass)
    if runtime is None:
        connection.send_error(msg["id"], "not_loaded", "Energy Cost Tracker is not loaded")
        return
    connection.send_result(msg["id"], await runtime.ledger.async_recent_events(msg["limit"]))


@callback
def async_register(hass: HomeAssistant) -> None:
    websocket_api.async_register_command(hass, websocket_summary)
    websocket_api.async_register_command(hass, websocket_ledger)
    websocket_api.async_register_command(hass, websocket_events)
