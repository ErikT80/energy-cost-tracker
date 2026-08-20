"""Runtime accounting engine for Energy Cost Tracker."""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from homeassistant.const import UnitOfEnergy
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import EnergyConverter

from .accounting import BatteryInventory, EnergyFrame, Prices, allocate_and_value
from .const import (
    ACCOUNTING_INTERVAL_SECONDS,
    CONF_ANNUAL_REBATE,
    CONF_BATTERY_CHARGE_ENERGY,
    CONF_BATTERY_DISCHARGE_ENERGY,
    CONF_BATTERY_EMPTY_SOC,
    CONF_BATTERY_SOC,
    CONF_BILLING_MONTH_START_DAY,
    CONF_BILLING_YEAR_START_DAY,
    CONF_BILLING_YEAR_START_MONTH,
    CONF_EXPORT_PRICE,
    CONF_EXPORT_PRICE_ADJUSTMENT,
    CONF_EXPORT_PRICE_MULTIPLIER,
    CONF_FIXED_ANNUAL,
    CONF_FIXED_DAILY,
    CONF_FIXED_MONTHLY,
    CONF_GRID_EXPORT_ENERGY,
    CONF_GRID_IMPORT_ENERGY,
    CONF_GRID_POWER,
    CONF_IMPORT_PRICE,
    CONF_IMPORT_PRICE_ADJUSTMENT,
    CONF_IMPORT_PRICE_MULTIPLIER,
    CONF_PV_ENERGY,
    CONF_PV_POWER,
    CONF_BATTERY_POWER,
    CONF_BATTERY_POWER_POSITIVE,
    BATTERY_POSITIVE_CHARGING,
    DEFAULTS,
    QUALITY_ESTIMATED,
    QUALITY_EXACT,
    QUALITY_MISSING_PRICE,
    QUALITY_RECONSTRUCTED,
    QUALITY_UNKNOWN_BATTERY_BASIS,
)
from .ledger import Ledger
from .periods import standard_periods

_LOGGER = logging.getLogger(__name__)


def _float_state(state) -> float | None:
    if state is None or state.state in {"unknown", "unavailable", "none", ""}:
        return None
    try:
        return float(state.state)
    except (TypeError, ValueError):
        return None


def _energy_kwh(state) -> float | None:
    value = _float_state(state)
    if value is None or state is None:
        return None
    unit = state.attributes.get("unit_of_measurement")
    if unit not in EnergyConverter.VALID_UNITS:
        # Never silently interpret an unknown/unitless sensor as kWh: choosing a
        # power or percentage entity by mistake must suspend accounting, not create
        # plausible-looking but financially wrong history.
        return None
    try:
        converter = EnergyConverter.converter_factory(unit, UnitOfEnergy.KILO_WATT_HOUR)
        return float(converter(value))
    except (TypeError, ValueError):
        return None


def _price_per_kwh(state, multiplier: float, adjustment: float) -> float | None:
    value = _float_state(state)
    if value is None:
        return None
    unit = str(state.attributes.get("unit_of_measurement", "")).strip().lower().replace(" ", "")
    if "/mwh" in unit:
        value /= 1000.0
    elif any(token in unit for token in ("ct/kwh", "c/kwh", "cent/kwh", "p/kwh", "pence/kwh")):
        value /= 100.0
    return value * multiplier + adjustment


def _utc_iso(value: datetime) -> str:
    return dt_util.as_utc(value).isoformat()


class EnergyCostRuntime:
    """Coordinates source meters, immutable ledger, summaries and entity updates."""

    def __init__(self, hass: HomeAssistant, entry, ledger: Ledger) -> None:
        self.hass = hass
        self.entry = entry
        self.ledger = ledger
        self.config = dict(entry.data)
        self.inventory = BatteryInventory()
        self.summary: dict[str, Any] = {}
        self.live: dict[str, Any] = {}
        self._listeners: list[Callable[[], None]] = []
        self._unsubs: list[Callable[[], None]] = []
        self._processing = False
        self._accounting_suspended = False
        self._unavailable_energy_sources: list[str] = []

    async def async_start(self) -> None:
        await self.ledger.async_initialize()
        await self._async_load_inventory()
        profile_json = json.dumps(self.config, sort_keys=True, default=str)
        await self.ledger.async_ensure_profile(
            _utc_iso(dt_util.utcnow()), hashlib.sha256(profile_json.encode()).hexdigest(), self.config
        )

        tracked = self._all_configured_entities()
        if tracked:
            self._unsubs.append(async_track_state_change_event(self.hass, tracked, self._state_changed))
        self._unsubs.append(
            async_track_time_interval(
                self.hass, self._scheduled_tick, timedelta(seconds=ACCOUNTING_INTERVAL_SECONDS)
            )
        )
        await self.async_process_tick(initial=True)
        await self.async_refresh_summary()

    async def async_stop(self) -> None:
        while self._unsubs:
            self._unsubs.pop()()
        await self._async_save_inventory()

    def _configured_energy_entities(self) -> list[str]:
        """Return cumulative energy sources that must be sampled coherently."""
        entities: list[str] = []
        for key in (
            CONF_GRID_IMPORT_ENERGY,
            CONF_GRID_EXPORT_ENERGY,
            CONF_BATTERY_CHARGE_ENERGY,
            CONF_BATTERY_DISCHARGE_ENERGY,
        ):
            value = self.config.get(key)
            if value:
                entities.append(value)
        entities.extend(self.config.get(CONF_PV_ENERGY, []) or [])
        return sorted(set(entities))

    def _unavailable_configured_energy_sources(self) -> list[str]:
        return [
            entity_id
            for entity_id in self._configured_energy_entities()
            if _energy_kwh(self.hass.states.get(entity_id)) is None
        ]

    def _all_configured_entities(self) -> list[str]:
        keys = (
            CONF_GRID_IMPORT_ENERGY,
            CONF_GRID_EXPORT_ENERGY,
            CONF_GRID_POWER,
            CONF_BATTERY_CHARGE_ENERGY,
            CONF_BATTERY_DISCHARGE_ENERGY,
            CONF_BATTERY_POWER,
    CONF_BATTERY_POWER_POSITIVE,
    BATTERY_POSITIVE_CHARGING,
            CONF_BATTERY_SOC,
            CONF_IMPORT_PRICE,
            CONF_EXPORT_PRICE,
        )
        entities: list[str] = []
        for key in keys:
            value = self.config.get(key)
            if value:
                entities.append(value)
        for key in (CONF_PV_ENERGY, CONF_PV_POWER):
            entities.extend(self.config.get(key, []) or [])
        return sorted(set(entities))

    @callback
    def _state_changed(self, event: Event[EventStateChangedData]) -> None:
        self._refresh_live()
        # Close the financial interval immediately when a tariff changes. The stored
        # previous tariff is then applied only to energy observed before this boundary.
        if event.data["entity_id"] in {
            self.config.get(CONF_IMPORT_PRICE),
            self.config.get(CONF_EXPORT_PRICE),
        }:
            self.entry.async_create_task(
                self.hass,
                self.async_process_tick(),
                "Energy Cost Tracker tariff boundary",
            )

    async def _scheduled_tick(self, now: datetime) -> None:
        await self.async_process_tick()

    def _refresh_live(self) -> None:
        def state_value(entity_id: str | None) -> float | None:
            return _float_state(self.hass.states.get(entity_id)) if entity_id else None

        battery_power = state_value(self.config.get(CONF_BATTERY_POWER))
        if (
            battery_power is not None
            and self.config.get(CONF_BATTERY_POWER_POSITIVE, BATTERY_POSITIVE_CHARGING)
            != BATTERY_POSITIVE_CHARGING
        ):
            battery_power *= -1

        self.live = {
            "grid_power": state_value(self.config.get(CONF_GRID_POWER)),
            "pv_power": sum(
                value
                for entity in self.config.get(CONF_PV_POWER, []) or []
                if (value := state_value(entity)) is not None
            ),
            # Normalized convention in the panel/API: positive means charging.
            "battery_power": battery_power,
            "battery_soc": state_value(self.config.get(CONF_BATTERY_SOC)),
            "accounting_suspended": self._accounting_suspended,
            "unavailable_energy_sources": list(self._unavailable_energy_sources),
        }

    async def _source_delta(self, source_key: str, entity_id: str | None, now: datetime) -> tuple[float, str]:
        if not entity_id:
            return 0.0, QUALITY_EXACT
        state = self.hass.states.get(entity_id)
        value = _energy_kwh(state)
        if value is None:
            return 0.0, QUALITY_ESTIMATED
        result = await self.ledger.async_observe_source(source_key, entity_id, value, _utc_iso(now))
        quality = result["quality"]
        if quality == "baseline":
            quality = QUALITY_EXACT
        return float(result["delta"]), quality

    async def _multi_source_delta(self, prefix: str, entity_ids: list[str], now: datetime) -> tuple[float, list[str]]:
        total = 0.0
        qualities: list[str] = []
        for entity_id in entity_ids:
            delta, quality = await self._source_delta(f"{prefix}:{entity_id}", entity_id, now)
            total += delta
            qualities.append(quality)
        return total, qualities

    def _current_prices(self) -> Prices:
        import_state = self.hass.states.get(self.config.get(CONF_IMPORT_PRICE)) if self.config.get(CONF_IMPORT_PRICE) else None
        export_state = self.hass.states.get(self.config.get(CONF_EXPORT_PRICE)) if self.config.get(CONF_EXPORT_PRICE) else None
        import_price = _price_per_kwh(
            import_state,
            float(self.config.get(CONF_IMPORT_PRICE_MULTIPLIER, DEFAULTS[CONF_IMPORT_PRICE_MULTIPLIER])),
            float(self.config.get(CONF_IMPORT_PRICE_ADJUSTMENT, DEFAULTS[CONF_IMPORT_PRICE_ADJUSTMENT])),
        ) if import_state else None
        export_price = _price_per_kwh(
            export_state,
            float(self.config.get(CONF_EXPORT_PRICE_MULTIPLIER, DEFAULTS[CONF_EXPORT_PRICE_MULTIPLIER])),
            float(self.config.get(CONF_EXPORT_PRICE_ADJUSTMENT, DEFAULTS[CONF_EXPORT_PRICE_ADJUSTMENT])),
        ) if export_state else None
        return Prices(import_price=import_price, export_price=export_price)

    def _fixed_cost_for_interval(self, start: datetime, end: datetime) -> float:
        """Accrue configured fixed charges over local calendar periods.

        Actual UTC durations are used for local days/months/years, so DST changes
        do not make a daily or monthly charge drift.
        """
        if end <= start:
            return 0.0
        total = 0.0
        cursor = start
        daily = float(self.config.get(CONF_FIXED_DAILY, 0.0))
        monthly = float(self.config.get(CONF_FIXED_MONTHLY, 0.0))
        annual = float(self.config.get(CONF_FIXED_ANNUAL, 0.0)) - float(
            self.config.get(CONF_ANNUAL_REBATE, 0.0)
        )

        while cursor < end:
            local = dt_util.as_local(cursor)
            day_start_local = local.replace(hour=0, minute=0, second=0, microsecond=0)
            next_day_local = day_start_local + timedelta(days=1)

            month_start_local = day_start_local.replace(day=1)
            if month_start_local.month == 12:
                next_month_local = month_start_local.replace(
                    year=month_start_local.year + 1, month=1
                )
            else:
                next_month_local = month_start_local.replace(month=month_start_local.month + 1)

            year_start_local = day_start_local.replace(month=1, day=1)
            next_year_local = year_start_local.replace(year=year_start_local.year + 1)

            next_day_utc = dt_util.as_utc(next_day_local)
            slice_end = min(end, next_day_utc)
            seconds = (slice_end - cursor).total_seconds()
            if seconds <= 0:
                break

            day_seconds = (next_day_utc - dt_util.as_utc(day_start_local)).total_seconds()
            month_seconds = (
                dt_util.as_utc(next_month_local) - dt_util.as_utc(month_start_local)
            ).total_seconds()
            year_seconds = (
                dt_util.as_utc(next_year_local) - dt_util.as_utc(year_start_local)
            ).total_seconds()

            total += daily * seconds / day_seconds
            total += monthly * seconds / month_seconds
            total += annual * seconds / year_seconds
            cursor = slice_end
        return total

    async def async_process_tick(self, initial: bool = False) -> None:
        if self._processing:
            return
        self._processing = True
        try:
            now = dt_util.utcnow()
            unavailable = self._unavailable_configured_energy_sources()
            self._unavailable_energy_sources = unavailable
            self._accounting_suspended = bool(unavailable)
            if unavailable:
                # Do not advance any cumulative baseline while one configured energy
                # source is unavailable. On recovery all deltas therefore cover the
                # same elapsed window, which is booked as an estimated long interval.
                self._refresh_live()
                if self.summary:
                    self.summary["live"] = dict(self.live)
                    for listener in list(self._listeners):
                        listener()
                return

            last_tick_raw = await self.ledger.async_get_meta("last_tick")
            if last_tick_raw is None:
                last_tick = now
            else:
                try:
                    last_tick = datetime.fromisoformat(last_tick_raw)
                except ValueError:
                    last_tick = now

            # Use the price sampled at the previous tick for the energy elapsed since
            # that tick. This avoids assigning the new tariff to the minute just ended.
            stored_import = await self.ledger.async_get_meta("last_import_price")
            stored_export = await self.ledger.async_get_meta("last_export_price")
            current_prices = self._current_prices()
            previous_prices = Prices(
                import_price=float(stored_import) if stored_import not in (None, "") else current_prices.import_price,
                export_price=float(stored_export) if stored_export not in (None, "") else current_prices.export_price,
            )

            gi, q_gi = await self._source_delta("grid_import", self.config.get(CONF_GRID_IMPORT_ENERGY), now)
            ge, q_ge = await self._source_delta("grid_export", self.config.get(CONF_GRID_EXPORT_ENERGY), now)
            pv, q_pv = await self._multi_source_delta("pv", self.config.get(CONF_PV_ENERGY, []) or [], now)
            bc, q_bc = await self._source_delta("battery_charge", self.config.get(CONF_BATTERY_CHARGE_ENERGY), now)
            bd, q_bd = await self._source_delta("battery_discharge", self.config.get(CONF_BATTERY_DISCHARGE_ENERGY), now)

            await self.ledger.async_set_meta("last_tick", _utc_iso(now))
            await self.ledger.async_set_meta("last_import_price", "" if current_prices.import_price is None else str(current_prices.import_price))
            await self.ledger.async_set_meta("last_export_price", "" if current_prices.export_price is None else str(current_prices.export_price))

            # First-ever observation only establishes baselines.
            if last_tick_raw is None or initial and (now - last_tick).total_seconds() < 1:
                self._refresh_live()
                return

            seconds = max(0.0, (now - last_tick).total_seconds())
            if seconds <= 0:
                return

            qualities = [q_gi, q_ge, q_bc, q_bd, *q_pv]
            quality = QUALITY_EXACT
            if any(q == QUALITY_RECONSTRUCTED for q in qualities):
                quality = QUALITY_RECONSTRUCTED
            if seconds > ACCOUNTING_INTERVAL_SECONDS * 2.5 or any(q == QUALITY_ESTIMATED for q in qualities):
                quality = QUALITY_ESTIMATED

            frame = EnergyFrame(gi, ge, pv, bc, bd)
            result = allocate_and_value(frame, previous_prices, self.inventory)

            # Reconcile stranded stored cost only when the battery is observed empty
            # and is not charging in the same sampled interval. This avoids deleting
            # freshly charged energy while SOC still sits around the empty threshold.
            soc_entity = self.config.get(CONF_BATTERY_SOC)
            soc = _float_state(self.hass.states.get(soc_entity)) if soc_entity else None
            loss_cost = 0.0
            if (
                soc is not None
                and soc <= float(self.config.get(CONF_BATTERY_EMPTY_SOC, 5.0))
                and bc <= 1e-6
            ):
                if self.inventory.energy_kwh > 1e-6:
                    basis_was_known = self.inventory.basis_known
                    stranded = self.inventory.mark_empty()
                    if basis_was_known:
                        loss_cost = stranded
                else:
                    self.inventory.basis_known = True

            import_price_needed = any(
                value > 1e-9
                for value in (gi, result.pv_direct, result.grid_to_battery, result.battery_to_house)
            )
            export_price_needed = any(
                value > 1e-9
                for value in (ge, result.pv_export, result.pv_to_battery, result.battery_to_grid)
            )
            import_price_missing = import_price_needed and previous_prices.import_price is None
            export_price_missing = export_price_needed and previous_prices.export_price is None
            if import_price_missing or export_price_missing:
                quality = QUALITY_MISSING_PRICE

            fixed_cost = self._fixed_cost_for_interval(last_tick, now)
            if result.import_cost is None or result.export_revenue is None:
                net_cost = None
            else:
                net_cost = result.import_cost - result.export_revenue + fixed_cost

            battery_profit = result.battery_profit
            if battery_profit is not None:
                battery_profit -= loss_cost
            if bd > 1e-9 and battery_profit is None and quality not in {QUALITY_MISSING_PRICE, QUALITY_ESTIMATED}:
                quality = QUALITY_UNKNOWN_BATTERY_BASIS

            notes = []
            if bc > 1e-9 and bd > 1e-9:
                notes.append("simultaneous_battery_charge_discharge")
                if quality == QUALITY_EXACT:
                    quality = QUALITY_RECONSTRUCTED
            if result.flow_residual > 0.02:
                notes.append("flow_residual")
            if result.battery_uncovered_discharge > 1e-6:
                notes.append("battery_cost_basis_incomplete")

            await self.ledger.async_insert_interval(
                {
                    "start_ts": _utc_iso(last_tick),
                    "end_ts": _utc_iso(now),
                    "seconds": seconds,
                    "grid_import_kwh": gi,
                    "grid_export_kwh": ge,
                    "house_consumption_kwh": result.house_consumption,
                    "pv_production_kwh": pv,
                    "battery_charge_kwh": bc,
                    "battery_discharge_kwh": bd,
                    "grid_to_house_kwh": result.grid_to_house,
                    "grid_to_battery_kwh": result.grid_to_battery,
                    "pv_direct_kwh": result.pv_direct,
                    "pv_export_kwh": result.pv_export,
                    "pv_to_battery_kwh": result.pv_to_battery,
                    "battery_to_house_kwh": result.battery_to_house,
                    "battery_to_grid_kwh": result.battery_to_grid,
                    "flow_residual_kwh": result.flow_residual,
                    "import_price": previous_prices.import_price,
                    "export_price": previous_prices.export_price,
                    "import_cost": result.import_cost,
                    "export_revenue": result.export_revenue,
                    "fixed_cost": fixed_cost,
                    "net_cost": net_cost,
                    "pv_value": result.pv_value,
                    "battery_charge_cost": result.battery_charge_cost,
                    "battery_discharge_value": result.battery_discharge_value,
                    "battery_discharge_cost_basis": result.battery_discharge_cost_basis,
                    "battery_profit": battery_profit,
                    "battery_loss_cost": loss_cost,
                    "quality": quality,
                    "notes": ",".join(notes) if notes else None,
                }
            )
            await self._async_save_inventory()
            self._refresh_live()
            await self.async_refresh_summary()
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Error processing Energy Cost Tracker interval")
        finally:
            self._processing = False

    async def _async_load_inventory(self) -> None:
        raw = await self.ledger.async_get_meta("battery_inventory")
        if not raw:
            self.inventory = BatteryInventory(basis_known=False)
            return
        try:
            data = json.loads(raw)
            self.inventory = BatteryInventory(
                energy_kwh=float(data.get("energy_kwh", 0.0)),
                cost_basis=float(data.get("cost_basis", 0.0)),
                basis_known=bool(data.get("basis_known", False)),
            )
        except (ValueError, TypeError, json.JSONDecodeError):
            self.inventory = BatteryInventory(basis_known=False)

    async def _async_save_inventory(self) -> None:
        await self.ledger.async_set_meta(
            "battery_inventory",
            json.dumps(
                {
                    "energy_kwh": self.inventory.energy_kwh,
                    "cost_basis": self.inventory.cost_basis,
                    "basis_known": self.inventory.basis_known,
                }
            ),
        )

    async def async_refresh_summary(self) -> None:
        now = dt_util.now()
        periods = standard_periods(
            now,
            int(self.config.get(CONF_BILLING_MONTH_START_DAY, 1)),
            int(self.config.get(CONF_BILLING_YEAR_START_MONTH, 1)),
            int(self.config.get(CONF_BILLING_YEAR_START_DAY, 1)),
        )
        summaries: dict[str, Any] = {}
        for name, (start, end) in periods.items():
            summary = await self.ledger.async_period_summary(_utc_iso(start), _utc_iso(end))
            summary["period_start"] = start.isoformat()
            summary["period_end"] = end.isoformat()
            summaries[name] = summary
        summaries["total"] = await self.ledger.async_period_summary(None, None)
        self.summary = {
            "periods": summaries,
            "battery_inventory": {
                "energy_kwh": self.inventory.energy_kwh,
                "cost_basis": self.inventory.cost_basis,
                "average_price": self.inventory.average_price,
                "basis_known": self.inventory.basis_known,
            },
            "live": self.live,
            "currency": self.config.get("currency", self.hass.config.currency),
            "updated_at": now.isoformat(),
        }
        for listener in list(self._listeners):
            listener()

    @callback
    def async_add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(listener)

        @callback
        def remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return remove
