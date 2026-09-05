"""WebSocket API for the Energy Cost Tracker sidebar panel."""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.util import dt as dt_util

from .access import async_access_users, async_set_allowed_users, user_can_access
from .const import (
    CONF_BATTERY_CHARGE_ENERGY,
    CONF_BATTERY_INVESTMENT,
    CONF_BATTERY_DISCHARGE_ENERGY,
    CONF_BATTERY_POWER,
    CONF_BATTERY_SOC,
    CONF_EXPORT_PRICE,
    CONF_EXPORT_PRICE_ADJUSTMENT,
    CONF_EXPORT_PRICE_MULTIPLIER,
    CONF_FIXED_ANNUAL,
    CONF_FIXED_COST_PROFILES,
    CONF_FIXED_DAILY,
    CONF_FIXED_MONTHLY,
    CONF_ANNUAL_REBATE,
    CONF_IMPORT_PRICE,
    CONF_IMPORT_PRICE_ADJUSTMENT,
    CONF_IMPORT_PRICE_MULTIPLIER,
    CONF_PV_ENERGY,
    CONF_PV_INVESTMENT,
    CONF_PV_POWER,
    DEFAULTS,
    DOMAIN,
)


def _entity_ids(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    return [str(entity_id) for entity_id in value if entity_id]


def _runtime(hass: HomeAssistant):
    data = hass.data.get(DOMAIN, {})
    for value in data.values():
        if hasattr(value, "ledger"):
            return value
    return None


def _authorized_runtime(hass: HomeAssistant, connection, msg):
    """Return the runtime only when the current user may access the panel."""
    runtime = _runtime(hass)
    if runtime is None:
        connection.send_error(msg["id"], "not_loaded", "Energy Cost Tracker is not loaded")
        return None
    if not user_can_access(runtime, connection.user):
        connection.send_error(msg["id"], "unauthorized", "Energy Cost Tracker panel access is not enabled for this user")
        return None
    return runtime


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/summary"})
@websocket_api.async_response
async def websocket_summary(hass, connection, msg) -> None:
    runtime = _authorized_runtime(hass, connection, msg)
    if runtime is None:
        return
    await runtime.async_refresh_summary()
    result = dict(runtime.summary)
    result["config"] = {
        "title": runtime.entry.title,
        "billing_month_start_day": runtime.config.get("billing_month_start_day", 1),
        "billing_year_start_month": runtime.config.get("billing_year_start_month", 1),
        "billing_year_start_day": runtime.config.get("billing_year_start_day", 1),
        "import_price": runtime.config.get(CONF_IMPORT_PRICE),
        "export_price": runtime.config.get(CONF_EXPORT_PRICE),
        "import_price_multiplier": runtime.config.get(
            CONF_IMPORT_PRICE_MULTIPLIER, DEFAULTS[CONF_IMPORT_PRICE_MULTIPLIER]
        ),
        "export_price_multiplier": runtime.config.get(
            CONF_EXPORT_PRICE_MULTIPLIER, DEFAULTS[CONF_EXPORT_PRICE_MULTIPLIER]
        ),
        "import_price_adjustment": runtime.config.get(
            CONF_IMPORT_PRICE_ADJUSTMENT, DEFAULTS[CONF_IMPORT_PRICE_ADJUSTMENT]
        ),
        "export_price_adjustment": runtime.config.get(
            CONF_EXPORT_PRICE_ADJUSTMENT, DEFAULTS[CONF_EXPORT_PRICE_ADJUSTMENT]
        ),
        "has_pv": bool(
            (runtime.config.get(CONF_PV_ENERGY) or [])
            or runtime.config.get(CONF_PV_POWER)
        ),
        "has_pv_power": bool(runtime.config.get(CONF_PV_POWER)),
        "has_battery": any(
            runtime.config.get(key)
            for key in (
                CONF_BATTERY_CHARGE_ENERGY,
                CONF_BATTERY_DISCHARGE_ENERGY,
                CONF_BATTERY_POWER,
            )
        ),
        "has_battery_power": bool(_entity_ids(runtime.config.get(CONF_BATTERY_POWER))),
        "has_battery_soc": bool(_entity_ids(runtime.config.get(CONF_BATTERY_SOC))),
        "pv_investment": float(runtime.entry.options.get(CONF_PV_INVESTMENT, 0.0) or 0.0),
        "battery_investment": float(runtime.entry.options.get(CONF_BATTERY_INVESTMENT, 0.0) or 0.0),
        "fixed_cost_base": {
            "daily": float(runtime.config.get(CONF_FIXED_DAILY, 0.0) or 0.0),
            "monthly": float(runtime.config.get(CONF_FIXED_MONTHLY, 0.0) or 0.0),
            "annual": float(runtime.config.get(CONF_FIXED_ANNUAL, 0.0) or 0.0),
            "annual_rebate": float(runtime.config.get(CONF_ANNUAL_REBATE, 0.0) or 0.0),
        },
        "fixed_cost_profiles": list(runtime.entry.options.get(CONF_FIXED_COST_PROFILES, []) or []),
    }
    total = result.get("periods", {}).get("total", {})
    result["config"]["has_pv_history"] = bool(
        abs(float(total.get("pv_production_kwh") or 0.0)) > 1e-9
        or abs(float(total.get("known_pv_value") or 0.0)) > 1e-9
        or int(total.get("incomplete_pv_intervals") or 0) > 0
    )
    result["config"]["has_battery_history"] = bool(
        abs(float(total.get("battery_charge_kwh") or 0.0)) > 1e-9
        or abs(float(total.get("battery_discharge_kwh") or 0.0)) > 1e-9
        or abs(float(total.get("known_battery_profit") or 0.0)) > 1e-9
        or int(total.get("incomplete_battery_intervals") or 0) > 0
    )
    result["access"] = {
        "is_admin": bool(connection.user.is_admin),
        "can_manage": bool(connection.user.is_admin),
    }
    first_ts = result.get("periods", {}).get("total", {}).get("first_ts")
    if first_ts:
        try:
            first_dt = datetime.fromisoformat(str(first_ts).replace("Z", "+00:00"))
            if first_dt.tzinfo is None:
                first_dt = first_dt.replace(tzinfo=timezone.utc)
            result["config"]["tracking_start_date"] = dt_util.as_local(first_dt).date().isoformat()
        except (TypeError, ValueError):
            result["config"]["tracking_start_date"] = dt_util.now().date().isoformat()
    else:
        result["config"]["tracking_start_date"] = dt_util.now().date().isoformat()
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/settings/update",
        vol.Optional("pv_investment"): vol.All(
            vol.Coerce(float), vol.Range(min=0, max=1_000_000_000)
        ),
        vol.Optional("battery_investment"): vol.All(
            vol.Coerce(float), vol.Range(min=0, max=1_000_000_000)
        ),
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_update_settings(hass, connection, msg) -> None:
    """Persist non-accounting sidebar settings without rewriting ledger history."""
    runtime = _runtime(hass)
    if runtime is None:
        connection.send_error(msg["id"], "not_loaded", "Energy Cost Tracker is not loaded")
        return

    options = dict(runtime.entry.options)
    if "pv_investment" in msg:
        options[CONF_PV_INVESTMENT] = float(msg["pv_investment"])
    if "battery_investment" in msg:
        options[CONF_BATTERY_INVESTMENT] = float(msg["battery_investment"])
    hass.config_entries.async_update_entry(runtime.entry, options=options)
    await runtime.async_refresh_summary()
    connection.send_result(
        msg["id"],
        {
            "pv_investment": float(options.get(CONF_PV_INVESTMENT, 0.0) or 0.0),
            "battery_investment": float(options.get(CONF_BATTERY_INVESTMENT, 0.0) or 0.0),
        },
    )


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/battery/mark_empty"})
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_mark_battery_empty(hass, connection, msg) -> None:
    """Confirm that an SOC-less combined battery system is physically empty."""
    runtime = _runtime(hass)
    if runtime is None:
        connection.send_error(msg["id"], "not_loaded", "Energy Cost Tracker is not loaded")
        return
    try:
        result = await runtime.async_mark_battery_empty()
    except ValueError as err:
        code = str(err)
        messages = {
            "soc_configured": "Manual empty confirmation is disabled while SOC helpers are configured",
            "battery_not_configured": "No battery system is configured",
        }
        connection.send_error(msg["id"], code, messages.get(code, code))
        return
    connection.send_result(msg["id"], result)


_FIXED_COST_PROFILE_SCHEMA = vol.Schema(
    {
        vol.Required("effective_from"): str,
        vol.Required("daily"): vol.All(vol.Coerce(float), vol.Range(min=-1000, max=1000)),
        vol.Required("monthly"): vol.All(vol.Coerce(float), vol.Range(min=-10000, max=10000)),
        vol.Required("annual"): vol.All(vol.Coerce(float), vol.Range(min=-100000, max=100000)),
        vol.Required("annual_rebate"): vol.All(vol.Coerce(float), vol.Range(min=0, max=100000)),
    }
)


def _sanitize_fixed_cost_profiles(raw_profiles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Validate, sort and de-duplicate schedule rows by effective date."""
    by_date: dict[str, dict[str, Any]] = {}
    for raw in raw_profiles:
        effective = str(raw["effective_from"])
        # ISO parsing also rejects impossible dates such as 2027-02-31.
        parsed = date.fromisoformat(effective)
        key = parsed.isoformat()
        by_date[key] = {
            "effective_from": key,
            "daily": float(raw["daily"]),
            "monthly": float(raw["monthly"]),
            "annual": float(raw["annual"]),
            "annual_rebate": float(raw["annual_rebate"]),
        }
    return [by_date[key] for key in sorted(by_date)]


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/fixed_costs/update",
        vol.Required("profiles"): vol.All([_FIXED_COST_PROFILE_SCHEMA], vol.Length(max=100)),
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_update_fixed_costs(hass, connection, msg) -> None:
    """Persist a dated fixed-cost schedule and deterministically repair history."""
    runtime = _runtime(hass)
    if runtime is None:
        connection.send_error(msg["id"], "not_loaded", "Energy Cost Tracker is not loaded")
        return
    try:
        profiles = _sanitize_fixed_cost_profiles(msg["profiles"])
    except (TypeError, ValueError, KeyError) as err:
        connection.send_error(msg["id"], "invalid_fixed_cost_schedule", str(err))
        return

    # Runtime closes the open interval under the old schedule, switches profiles
    # under its accounting lock, then repairs only fixed/net historical fields.
    changed = await runtime.async_set_fixed_cost_profiles(profiles)
    connection.send_result(
        msg["id"],
        {"profiles": profiles, "changed_intervals": changed},
    )


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/access/users"})
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_access_users(hass, connection, msg) -> None:
    """Return Home Assistant users and effective ECT panel access."""
    runtime = _runtime(hass)
    if runtime is None:
        connection.send_error(msg["id"], "not_loaded", "Energy Cost Tracker is not loaded")
        return
    connection.send_result(msg["id"], {"users": await async_access_users(hass, runtime)})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/access/update",
        vol.Required("allowed_user_ids"): [str],
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_update_access(hass, connection, msg) -> None:
    """Persist the non-admin panel whitelist and synchronize sidebar visibility."""
    runtime = _runtime(hass)
    if runtime is None:
        connection.send_error(msg["id"], "not_loaded", "Energy Cost Tracker is not loaded")
        return
    users = await async_set_allowed_users(hass, runtime, msg["allowed_user_ids"])
    connection.send_result(msg["id"], {"users": users})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/invoice",
        vol.Required("view"): vol.In(["month", "year"]),
        vol.Optional("anchor"): str,
    }
)
@websocket_api.async_response
async def websocket_invoice(hass, connection, msg) -> None:
    """Return invoice-style reconciliation for one billing month or year."""
    runtime = _authorized_runtime(hass, connection, msg)
    if runtime is None:
        return
    try:
        result = await runtime.async_invoice_breakdown(msg["view"], msg.get("anchor"))
    except ValueError as err:
        connection.send_error(msg["id"], "invalid_invoice_period", str(err))
        return
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
    runtime = _authorized_runtime(hass, connection, msg)
    if runtime is None:
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


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/chart",
        vol.Required("start"): str,
        vol.Required("end"): str,
        vol.Optional("granularity", default="auto"): vol.In(
            ["auto", "month", "day", "hour", "quarter"]
        ),
    }
)
@websocket_api.async_response
async def websocket_chart(hass, connection, msg) -> None:
    runtime = _authorized_runtime(hass, connection, msg)
    if runtime is None:
        return
    try:
        result = await runtime.async_chart_series(
            msg["start"],
            msg["end"],
            msg["granularity"],
            hass.config.time_zone,
        )
    except (ValueError, OverflowError) as err:
        connection.send_error(msg["id"], "invalid_range", str(err))
        return
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/events", vol.Optional("limit", default=50): vol.All(vol.Coerce(int), vol.Range(min=1, max=500))})
@websocket_api.async_response
async def websocket_events(hass, connection, msg) -> None:
    runtime = _authorized_runtime(hass, connection, msg)
    if runtime is None:
        return
    connection.send_result(msg["id"], await runtime.ledger.async_recent_events(msg["limit"]))


@callback
def async_register(hass: HomeAssistant) -> None:
    websocket_api.async_register_command(hass, websocket_summary)
    websocket_api.async_register_command(hass, websocket_invoice)
    websocket_api.async_register_command(hass, websocket_ledger)
    websocket_api.async_register_command(hass, websocket_chart)
    websocket_api.async_register_command(hass, websocket_events)
    websocket_api.async_register_command(hass, websocket_update_settings)
    websocket_api.async_register_command(hass, websocket_update_fixed_costs)
    websocket_api.async_register_command(hass, websocket_mark_battery_empty)
    websocket_api.async_register_command(hass, websocket_access_users)
    websocket_api.async_register_command(hass, websocket_update_access)
