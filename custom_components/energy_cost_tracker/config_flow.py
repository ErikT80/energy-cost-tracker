"""Config flow for Energy Cost Tracker."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.helpers import selector

from .const import *  # noqa: F403


def _entity_selector(multiple: bool = False) -> selector.EntitySelector:
    return selector.EntitySelector(
        selector.EntitySelectorConfig(
            filter=selector.EntityFilterSelectorConfig(domain="sensor"),
            multiple=multiple,
        )
    )


def _number(minimum: float, maximum: float, step: float = 0.01) -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=minimum,
            max=maximum,
            step=step,
            mode=selector.NumberSelectorMode.BOX,
        )
    )


def _optional_with_suggested(schema: dict, key: str, value: Any, field_selector) -> None:
    if value not in (None, "", []):
        schema[vol.Optional(key, description={"suggested_value": value})] = field_selector
    else:
        schema[vol.Optional(key)] = field_selector


class EnergyCostTrackerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):  # noqa: F405
    """Handle Energy Cost Tracker configuration."""

    VERSION = 1
    MINOR_VERSION = 0

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._data.update(user_input)
            await self.async_set_unique_id(DOMAIN)  # noqa: F405
            self._abort_if_unique_id_configured()
            return await self.async_step_grid()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_CURRENCY, default=self.hass.config.currency): selector.TextSelector(),  # noqa: F405
                }
            ),
        )

    async def async_step_grid(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_solar()
        return self.async_show_form(
            step_id="grid",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_GRID_IMPORT_ENERGY): _entity_selector(),  # noqa: F405
                    vol.Optional(CONF_GRID_EXPORT_ENERGY): _entity_selector(),  # noqa: F405
                    vol.Optional(CONF_GRID_POWER): _entity_selector(),  # noqa: F405
                }
            ),
        )

    async def async_step_solar(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_battery()
        return self.async_show_form(
            step_id="solar",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_PV_ENERGY, default=[]): _entity_selector(multiple=True),  # noqa: F405
                    vol.Optional(CONF_PV_POWER, default=[]): _entity_selector(multiple=True),  # noqa: F405
                }
            ),
        )

    async def async_step_battery(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_prices()
        return self.async_show_form(
            step_id="battery",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_BATTERY_CHARGE_ENERGY): _entity_selector(),  # noqa: F405
                    vol.Optional(CONF_BATTERY_DISCHARGE_ENERGY): _entity_selector(),  # noqa: F405
                    vol.Optional(CONF_BATTERY_POWER): _entity_selector(),  # noqa: F405
                    vol.Optional(CONF_BATTERY_SOC): _entity_selector(),  # noqa: F405
                    vol.Required(CONF_BATTERY_POWER_POSITIVE, default=DEFAULTS[CONF_BATTERY_POWER_POSITIVE]): selector.SelectSelector(  # noqa: F405
                        selector.SelectSelectorConfig(
                            options=[BATTERY_POSITIVE_CHARGING, BATTERY_POSITIVE_DISCHARGING],  # noqa: F405
                            mode=selector.SelectSelectorMode.DROPDOWN,
                            translation_key="battery_power_positive",
                        )
                    ),
                    vol.Required(CONF_BATTERY_EMPTY_SOC, default=DEFAULTS[CONF_BATTERY_EMPTY_SOC]): _number(0, 50, 1),  # noqa: F405
                }
            ),
        )

    async def async_step_prices(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_billing()
        return self.async_show_form(
            step_id="prices",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_IMPORT_PRICE): _entity_selector(),  # noqa: F405
                    vol.Optional(CONF_EXPORT_PRICE): _entity_selector(),  # noqa: F405
                    vol.Required(CONF_IMPORT_PRICE_MULTIPLIER, default=1.0): _number(-1000, 1000, 0.001),  # noqa: F405
                    vol.Required(CONF_IMPORT_PRICE_ADJUSTMENT, default=0.0): _number(-10, 10, 0.0001),  # noqa: F405
                    vol.Required(CONF_EXPORT_PRICE_MULTIPLIER, default=1.0): _number(-1000, 1000, 0.001),  # noqa: F405
                    vol.Required(CONF_EXPORT_PRICE_ADJUSTMENT, default=0.0): _number(-10, 10, 0.0001),  # noqa: F405
                }
            ),
        )

    async def async_step_billing(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._data.update(user_input)
            return self.async_create_entry(title=NAME, data=self._data)  # noqa: F405
        return self.async_show_form(
            step_id="billing",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_FIXED_DAILY, default=0.0): _number(-1000, 1000, 0.0001),  # noqa: F405
                    vol.Required(CONF_FIXED_MONTHLY, default=0.0): _number(-10000, 10000, 0.01),  # noqa: F405
                    vol.Required(CONF_FIXED_ANNUAL, default=0.0): _number(-100000, 100000, 0.01),  # noqa: F405
                    vol.Required(CONF_ANNUAL_REBATE, default=0.0): _number(0, 100000, 0.01),  # noqa: F405
                    vol.Required(CONF_BILLING_MONTH_START_DAY, default=1): _number(1, 31, 1),  # noqa: F405
                    vol.Required(CONF_BILLING_YEAR_START_MONTH, default=1): _number(1, 12, 1),  # noqa: F405
                    vol.Required(CONF_BILLING_YEAR_START_DAY, default=1): _number(1, 31, 1),  # noqa: F405
                }
            ),
        )

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        current = dict(entry.data)
        if user_input is not None:
            # Replace the full configuration so optional sensors can genuinely be
            # removed. The ledger is not replaced and survives all source changes.
            return self.async_update_reload_and_abort(entry, data=user_input)

        schema: dict[Any, Any] = {
            vol.Required(CONF_CURRENCY, default=current.get(CONF_CURRENCY, self.hass.config.currency)): selector.TextSelector(),  # noqa: F405
            vol.Required(CONF_GRID_IMPORT_ENERGY, default=current.get(CONF_GRID_IMPORT_ENERGY)): _entity_selector(),  # noqa: F405
        }
        for key in (CONF_GRID_EXPORT_ENERGY, CONF_GRID_POWER):  # noqa: F405
            _optional_with_suggested(schema, key, current.get(key), _entity_selector())
        _optional_with_suggested(schema, CONF_PV_ENERGY, current.get(CONF_PV_ENERGY, []), _entity_selector(True))  # noqa: F405
        _optional_with_suggested(schema, CONF_PV_POWER, current.get(CONF_PV_POWER, []), _entity_selector(True))  # noqa: F405
        for key in (CONF_BATTERY_CHARGE_ENERGY, CONF_BATTERY_DISCHARGE_ENERGY, CONF_BATTERY_POWER, CONF_BATTERY_SOC, CONF_IMPORT_PRICE, CONF_EXPORT_PRICE):  # noqa: F405
            _optional_with_suggested(schema, key, current.get(key), _entity_selector())

        schema.update(
            {
                vol.Required(CONF_BATTERY_POWER_POSITIVE, default=current.get(CONF_BATTERY_POWER_POSITIVE, BATTERY_POSITIVE_CHARGING)): selector.SelectSelector(  # noqa: F405
                    selector.SelectSelectorConfig(options=[BATTERY_POSITIVE_CHARGING, BATTERY_POSITIVE_DISCHARGING], mode=selector.SelectSelectorMode.DROPDOWN, translation_key="battery_power_positive")  # noqa: F405
                ),
                vol.Required(CONF_BATTERY_EMPTY_SOC, default=current.get(CONF_BATTERY_EMPTY_SOC, 5)): _number(0, 50, 1),  # noqa: F405
                vol.Required(CONF_IMPORT_PRICE_MULTIPLIER, default=current.get(CONF_IMPORT_PRICE_MULTIPLIER, 1.0)): _number(-1000, 1000, 0.001),  # noqa: F405
                vol.Required(CONF_IMPORT_PRICE_ADJUSTMENT, default=current.get(CONF_IMPORT_PRICE_ADJUSTMENT, 0.0)): _number(-10, 10, 0.0001),  # noqa: F405
                vol.Required(CONF_EXPORT_PRICE_MULTIPLIER, default=current.get(CONF_EXPORT_PRICE_MULTIPLIER, 1.0)): _number(-1000, 1000, 0.001),  # noqa: F405
                vol.Required(CONF_EXPORT_PRICE_ADJUSTMENT, default=current.get(CONF_EXPORT_PRICE_ADJUSTMENT, 0.0)): _number(-10, 10, 0.0001),  # noqa: F405
                vol.Required(CONF_FIXED_DAILY, default=current.get(CONF_FIXED_DAILY, 0.0)): _number(-1000, 1000, 0.0001),  # noqa: F405
                vol.Required(CONF_FIXED_MONTHLY, default=current.get(CONF_FIXED_MONTHLY, 0.0)): _number(-10000, 10000, 0.01),  # noqa: F405
                vol.Required(CONF_FIXED_ANNUAL, default=current.get(CONF_FIXED_ANNUAL, 0.0)): _number(-100000, 100000, 0.01),  # noqa: F405
                vol.Required(CONF_ANNUAL_REBATE, default=current.get(CONF_ANNUAL_REBATE, 0.0)): _number(0, 100000, 0.01),  # noqa: F405
                vol.Required(CONF_BILLING_MONTH_START_DAY, default=current.get(CONF_BILLING_MONTH_START_DAY, 1)): _number(1, 31, 1),  # noqa: F405
                vol.Required(CONF_BILLING_YEAR_START_MONTH, default=current.get(CONF_BILLING_YEAR_START_MONTH, 1)): _number(1, 12, 1),  # noqa: F405
                vol.Required(CONF_BILLING_YEAR_START_DAY, default=current.get(CONF_BILLING_YEAR_START_DAY, 1)): _number(1, 31, 1),  # noqa: F405
            }
        )
        return self.async_show_form(step_id="reconfigure", data_schema=vol.Schema(schema))
