"""Runtime accounting engine for Energy Cost Tracker."""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from homeassistant.const import UnitOfEnergy
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.event import async_track_point_in_utc_time, async_track_state_change_event, async_track_time_interval
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import EnergyConverter

from .accounting import BatteryInventory, EnergyFrame, Prices, allocate_and_value
from .accumulator import IntervalAccumulator
from .const import (
    ACCOUNTING_INTERVAL_SECONDS,
    LEDGER_INTERVAL_SECONDS,
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
    CONF_FIXED_COST_PROFILES,
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
from .fixed_costs import fixed_cost_breakdown_for_interval, fixed_cost_for_interval, normalize_profiles
from .periods import billing_month_bounds, billing_month_segments, billing_year_bounds, standard_periods

_LOGGER = logging.getLogger(__name__)

_TARIFF_CHANGE_DEBOUNCE_SECONDS = 0.5
_POST_LEDGER_BOUNDARY_TARIFF_GRACE_SECONDS = 10.0


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


def _entity_ids(value: Any) -> list[str]:
    """Normalize legacy single-entity config and current multi-select config."""
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    return [str(entity_id) for entity_id in value if entity_id]


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
        self._process_lock = asyncio.Lock()
        self._backup_in_progress = False
        self._accounting_suspended = False
        self._unavailable_energy_sources: list[str] = []
        self._pending = IntervalAccumulator()
        self._ledger_boundary_unsub: Callable[[], None] | None = None
        self._tariff_change_task: asyncio.Task[Any] | None = None
        self._pending_tariff_change_at: datetime | None = None
        self._last_ledger_boundary: datetime | None = None

    async def async_start(self) -> None:
        await self.ledger.async_initialize()
        await self._async_load_inventory()
        await self._async_load_pending()
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
        self._schedule_next_ledger_boundary()
        await self.async_process_tick(initial=True)
        await self.async_refresh_summary()

    async def async_stop(self) -> None:
        while self._unsubs:
            self._unsubs.pop()()
        if self._ledger_boundary_unsub is not None:
            self._ledger_boundary_unsub()
            self._ledger_boundary_unsub = None
        if self._tariff_change_task is not None:
            self._tariff_change_task.cancel()
            self._tariff_change_task = None
            self._pending_tariff_change_at = None
        await self.async_process_tick()
        await self._async_flush_pending()
        await self._async_save_inventory()

    async def async_prepare_backup(self) -> None:
        """Pause accounting and make the ledger stable for a Home Assistant backup."""
        if self._backup_in_progress:
            return

        # Wait for a running accounting tick to finish, then hold the process lock
        # for the whole backup so source baselines and ledger rows remain coherent.
        await self._process_lock.acquire()
        self._backup_in_progress = True
        self._accounting_suspended = True
        try:
            await self._async_save_inventory()
            await self.ledger.async_prepare_backup()
            self._refresh_live()
        except Exception:
            await self.ledger.async_finish_backup()
            self._backup_in_progress = False
            self._accounting_suspended = False
            self._refresh_live()
            self._process_lock.release()
            raise

    async def async_resume_after_backup(self) -> None:
        """Resume accounting after Home Assistant completed a backup."""
        if not self._backup_in_progress:
            return
        try:
            await self.ledger.async_finish_backup()
        finally:
            self._backup_in_progress = False
            self._accounting_suspended = False
            self._refresh_live()
            self._process_lock.release()

        # Capture the cumulative meter delta that occurred while the backup was
        # running. A longer gap is automatically marked estimated by normal logic.
        await self.async_process_tick()

    def _configured_energy_entities(self) -> list[str]:
        """Return cumulative energy sources that must be sampled coherently."""
        entities: list[str] = []
        for key in (CONF_GRID_IMPORT_ENERGY, CONF_GRID_EXPORT_ENERGY):
            value = self.config.get(key)
            if value:
                entities.append(value)
        for key in (CONF_PV_ENERGY, CONF_BATTERY_CHARGE_ENERGY, CONF_BATTERY_DISCHARGE_ENERGY):
            entities.extend(_entity_ids(self.config.get(key)))
        return sorted(set(entities))

    def _unavailable_configured_energy_sources(self) -> list[str]:
        return [
            entity_id
            for entity_id in self._configured_energy_entities()
            if _energy_kwh(self.hass.states.get(entity_id)) is None
        ]

    def _all_configured_entities(self) -> list[str]:
        single_keys = (
            CONF_GRID_IMPORT_ENERGY,
            CONF_GRID_EXPORT_ENERGY,
            CONF_GRID_POWER,
            CONF_IMPORT_PRICE,
            CONF_EXPORT_PRICE,
        )
        entities: list[str] = []
        for key in single_keys:
            value = self.config.get(key)
            if value:
                entities.append(value)
        for key in (
            CONF_PV_ENERGY,
            CONF_PV_POWER,
            CONF_BATTERY_CHARGE_ENERGY,
            CONF_BATTERY_DISCHARGE_ENERGY,
            CONF_BATTERY_POWER,
        ):
            entities.extend(_entity_ids(self.config.get(key)))
        return sorted(set(entities))

    def _price_for_state(self, entity_id: str, state) -> float | None:
        """Return the configured effective tariff for one price entity state."""
        if entity_id == self.config.get(CONF_IMPORT_PRICE):
            return _price_per_kwh(
                state,
                float(
                    self.config.get(
                        CONF_IMPORT_PRICE_MULTIPLIER,
                        DEFAULTS[CONF_IMPORT_PRICE_MULTIPLIER],
                    )
                ),
                float(
                    self.config.get(
                        CONF_IMPORT_PRICE_ADJUSTMENT,
                        DEFAULTS[CONF_IMPORT_PRICE_ADJUSTMENT],
                    )
                ),
            )
        if entity_id == self.config.get(CONF_EXPORT_PRICE):
            return _price_per_kwh(
                state,
                float(
                    self.config.get(
                        CONF_EXPORT_PRICE_MULTIPLIER,
                        DEFAULTS[CONF_EXPORT_PRICE_MULTIPLIER],
                    )
                ),
                float(
                    self.config.get(
                        CONF_EXPORT_PRICE_ADJUSTMENT,
                        DEFAULTS[CONF_EXPORT_PRICE_ADJUSTMENT],
                    )
                ),
            )
        return None

    @callback
    def _state_changed(self, event: Event[EventStateChangedData]) -> None:
        self._refresh_live()
        entity_id = event.data["entity_id"]
        price_entities = {
            configured_entity
            for configured_entity in (
                self.config.get(CONF_IMPORT_PRICE),
                self.config.get(CONF_EXPORT_PRICE),
            )
            if configured_entity
        }
        if entity_id not in price_entities:
            return

        # Price integrations often update attributes without changing the numeric
        # tariff. Only an effective price change is a financial boundary.
        old_price = self._price_for_state(entity_id, event.data.get("old_state"))
        new_price = self._price_for_state(entity_id, event.data.get("new_state"))
        if old_price == new_price:
            return

        change_at = dt_util.as_utc(event.time_fired)
        if (
            self._pending_tariff_change_at is None
            or change_at < self._pending_tariff_change_at
        ):
            self._pending_tariff_change_at = change_at

        # Import and export sensors from one provider normally update back-to-back.
        # Debounce them into one accounting boundary so no intermediate mixed-price
        # interval is committed. The regular 60-second tick is held while pending.
        if self._tariff_change_task is not None and not self._tariff_change_task.done():
            return
        self._tariff_change_task = self.entry.async_create_task(
            self.hass,
            self._async_handle_tariff_change(),
            "Energy Cost Tracker tariff boundary",
        )

    async def _async_handle_tariff_change(self) -> None:
        try:
            await asyncio.sleep(_TARIFF_CHANGE_DEBOUNCE_SECONDS)
            change_at = self._pending_tariff_change_at or dt_util.utcnow()
            boundary = self._last_ledger_boundary
            if boundary is not None:
                seconds_after_boundary = (change_at - boundary).total_seconds()
                if 0 <= seconds_after_boundary <= _POST_LEDGER_BOUNDARY_TARIFF_GRACE_SECONDS:
                    # The aligned boundary has already sampled/closed the preceding
                    # quarter. A provider may publish the new quarter tariff a few
                    # seconds later. Updating only the stored tariff here keeps the
                    # next meter delta anchored at the aligned boundary and avoids a
                    # misleading tiny ledger row using the previous quarter's price.
                    current_prices = self._current_prices()
                    if current_prices.import_price is not None:
                        await self.ledger.async_set_meta(
                            "last_import_price", str(current_prices.import_price)
                        )
                    if current_prices.export_price is not None:
                        await self.ledger.async_set_meta(
                            "last_export_price", str(current_prices.export_price)
                        )
                    self._refresh_live()
                    if self.summary:
                        self.summary["live"] = dict(self.live)
                        for listener in list(self._listeners):
                            listener()
                    return

            await self.async_process_tick(force_flush=True)
        finally:
            self._pending_tariff_change_at = None
            self._tariff_change_task = None

    async def _scheduled_tick(self, now: datetime) -> None:
        # Do not let the normal accounting cadence split a debounced tariff pair.
        if self._tariff_change_task is not None and not self._tariff_change_task.done():
            return
        await self.async_process_tick()

    def _schedule_next_ledger_boundary(self) -> None:
        """Schedule an aligned persistent-ledger boundary."""
        if self._ledger_boundary_unsub is not None:
            self._ledger_boundary_unsub()
        now = dt_util.utcnow()
        next_epoch = (int(now.timestamp()) // LEDGER_INTERVAL_SECONDS + 1) * LEDGER_INTERVAL_SECONDS
        boundary = datetime.fromtimestamp(next_epoch, tz=timezone.utc)
        self._ledger_boundary_unsub = async_track_point_in_utc_time(
            self.hass, self._ledger_boundary_tick, boundary
        )

    async def _ledger_boundary_tick(self, now: datetime) -> None:
        boundary = dt_util.as_utc(now)
        self._last_ledger_boundary = boundary
        try:
            await self.async_process_tick(boundary=boundary)
        finally:
            self._schedule_next_ledger_boundary()

    def _refresh_live(self) -> None:
        def state_value(entity_id: str | None) -> float | None:
            return _float_state(self.hass.states.get(entity_id)) if entity_id else None

        battery_power_values = [
            value
            for entity in _entity_ids(self.config.get(CONF_BATTERY_POWER))
            if (value := state_value(entity)) is not None
        ]
        battery_power = sum(battery_power_values) if battery_power_values else None
        if (
            battery_power is not None
            and self.config.get(CONF_BATTERY_POWER_POSITIVE, BATTERY_POSITIVE_CHARGING)
            != BATTERY_POSITIVE_CHARGING
        ):
            battery_power *= -1

        current_prices = self._current_prices()
        self.live = {
            "grid_power": state_value(self.config.get(CONF_GRID_POWER)),
            "pv_power": sum(
                value
                for entity in _entity_ids(self.config.get(CONF_PV_POWER))
                if (value := state_value(entity)) is not None
            ),
            # Normalized convention in the panel/API: positive means charging.
            "battery_power": battery_power,
            # SOC is intentionally not a dashboard value. It is an optional technical
            # helper used only to reconcile an initially unknown battery cost basis.
            "import_price": current_prices.import_price,
            "export_price": current_prices.export_price,
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

    def _fixed_cost_profiles(self):
        """Return the legacy baseline plus all dated fixed-cost profiles."""
        return normalize_profiles(
            self.config,
            self.entry.options.get(CONF_FIXED_COST_PROFILES, []),
        )

    def _fixed_cost_for_interval(self, start: datetime, end: datetime) -> float:
        """Accrue the fixed-cost profile active on each local calendar date."""
        return fixed_cost_for_interval(
            start,
            end,
            self.hass.config.time_zone,
            self._fixed_cost_profiles(),
        )

    async def _async_recalculate_fixed_cost_history_locked(self) -> int:
        """Rebuild persisted fixed/net costs while the process lock is held."""
        profiles = self._fixed_cost_profiles()
        rows = await self.ledger.async_fixed_cost_rows()
        updates: list[tuple[float, float | None, int]] = []
        for row in rows:
            start = datetime.fromisoformat(str(row["start_ts"]).replace("Z", "+00:00"))
            end = datetime.fromisoformat(str(row["end_ts"]).replace("Z", "+00:00"))
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
            if end.tzinfo is None:
                end = end.replace(tzinfo=timezone.utc)
            fixed = fixed_cost_for_interval(
                start, end, self.hass.config.time_zone, profiles
            )
            import_cost = row.get("import_cost")
            export_revenue = row.get("export_revenue")
            net = (
                None
                if import_cost is None or export_revenue is None
                else float(import_cost) - float(export_revenue) + fixed
            )
            old_fixed = float(row.get("fixed_cost") or 0.0)
            old_net = row.get("net_cost")
            net_changed = (old_net is None) != (net is None) or (
                old_net is not None
                and net is not None
                and abs(float(old_net) - net) > 1e-10
            )
            if abs(old_fixed - fixed) <= 1e-10 and not net_changed:
                continue
            updates.append((fixed, net, int(row["id"])))
        return await self.ledger.async_apply_fixed_cost_updates(
            updates,
            {"profiles": [profile.as_dict() for profile in profiles]},
        )

    async def async_recalculate_fixed_cost_history(self) -> int:
        """Rebuild only fixed/net costs from the currently stored dated schedule."""
        await self._process_lock.acquire()
        try:
            changed = await self._async_recalculate_fixed_cost_history_locked()
        finally:
            self._process_lock.release()
        await self.async_refresh_summary()
        return changed

    async def async_set_fixed_cost_profiles(self, profiles: list[dict[str, Any]]) -> int:
        """Atomically switch schedule after closing the old active interval."""
        await self.async_process_tick(force_flush=True)
        await self._process_lock.acquire()
        try:
            options = dict(self.entry.options)
            options[CONF_FIXED_COST_PROFILES] = profiles
            self.hass.config_entries.async_update_entry(self.entry, options=options)
            changed = await self._async_recalculate_fixed_cost_history_locked()
        finally:
            self._process_lock.release()
        await self.async_refresh_summary()
        return changed

    async def async_process_tick(
        self, initial: bool = False, force_flush: bool = False, boundary: datetime | None = None
    ) -> None:
        if self._processing or self._backup_in_progress:
            return

        await self._process_lock.acquire()
        if self._processing or self._backup_in_progress:
            self._process_lock.release()
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
                # A tariff boundary may still safely commit already accumulated data.
                if boundary is not None and not self._pending.empty:
                    await self._async_flush_pending()
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
            # that tick. This avoids assigning a new tariff to energy measured before the tariff change.
            stored_import = await self.ledger.async_get_meta("last_import_price")
            stored_export = await self.ledger.async_get_meta("last_export_price")
            current_prices = self._current_prices()
            previous_prices = Prices(
                import_price=float(stored_import) if stored_import not in (None, "") else current_prices.import_price,
                export_price=float(stored_export) if stored_export not in (None, "") else current_prices.export_price,
            )

            gi, q_gi = await self._source_delta("grid_import", self.config.get(CONF_GRID_IMPORT_ENERGY), now)
            ge, q_ge = await self._source_delta("grid_export", self.config.get(CONF_GRID_EXPORT_ENERGY), now)
            pv, q_pv = await self._multi_source_delta("pv", _entity_ids(self.config.get(CONF_PV_ENERGY)), now)
            bc, q_bc = await self._multi_source_delta("battery_charge", _entity_ids(self.config.get(CONF_BATTERY_CHARGE_ENERGY)), now)
            bd, q_bd = await self._multi_source_delta("battery_discharge", _entity_ids(self.config.get(CONF_BATTERY_DISCHARGE_ENERGY)), now)

            await self.ledger.async_set_meta("last_tick", _utc_iso(now))
            if current_prices.import_price is not None:
                await self.ledger.async_set_meta("last_import_price", str(current_prices.import_price))
            if current_prices.export_price is not None:
                await self.ledger.async_set_meta("last_export_price", str(current_prices.export_price))

            # First-ever observation only establishes baselines.
            if last_tick_raw is None or initial and (now - last_tick).total_seconds() < 1:
                self._refresh_live()
                return

            seconds = max(0.0, (now - last_tick).total_seconds())
            if seconds <= 0:
                return

            qualities = [q_gi, q_ge, *q_bc, *q_bd, *q_pv]
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
            soc_entities = _entity_ids(self.config.get(CONF_BATTERY_SOC))
            soc_values = [
                value
                for entity_id in soc_entities
                if (value := _float_state(self.hass.states.get(entity_id))) is not None
            ]
            all_batteries_empty = bool(soc_entities) and len(soc_values) == len(soc_entities) and all(
                soc <= float(self.config.get(CONF_BATTERY_EMPTY_SOC, 5.0)) for soc in soc_values
            )
            loss_cost = 0.0
            if all_batteries_empty and bc <= 1e-6:
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

            sample_row = {
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
            self._pending.add(sample_row)
            await self._async_save_pending()

            should_flush = force_flush
            if boundary is not None and not self._pending.empty:
                try:
                    pending_start = datetime.fromisoformat(str(self._pending.start_ts))
                    if pending_start.tzinfo is None:
                        pending_start = pending_start.replace(tzinfo=timezone.utc)
                    should_flush = should_flush or pending_start.astimezone(timezone.utc) < dt_util.as_utc(boundary)
                except (TypeError, ValueError):
                    should_flush = True
            # A long recovery interval cannot be accurately assigned to a single
            # tariff bucket. Keep it as one explicit estimated row instead of
            # merging it with subsequent exact samples.
            if seconds > LEDGER_INTERVAL_SECONDS:
                should_flush = True
            if should_flush:
                await self._async_flush_pending()
            await self._async_save_inventory()
            self._refresh_live()
            await self.async_refresh_summary()
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Error processing Energy Cost Tracker interval")
        finally:
            self._processing = False
            self._process_lock.release()

    @property
    def pending_ledger_row(self) -> dict[str, Any] | None:
        return self._pending.to_ledger_row()

    async def _async_load_pending(self) -> None:
        self._pending = IntervalAccumulator.from_json(
            await self.ledger.async_get_meta("pending_interval")
        )

    async def _async_save_pending(self) -> None:
        if self._pending.empty:
            return
        await self.ledger.async_set_meta("pending_interval", self._pending.to_json())

    async def _async_flush_pending(self) -> None:
        row = self._pending.to_ledger_row()
        if row is None:
            return
        await self.ledger.async_commit_pending_interval(row)
        self._pending = IntervalAccumulator()

    async def async_chart_series(
        self, start: str, end: str, granularity: str, tz_name: str
    ) -> dict[str, Any]:
        return await self.ledger.async_chart_series(
            start, end, granularity, tz_name, self.pending_ledger_row
        )

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

    async def async_mark_battery_empty(self) -> dict[str, Any]:
        """Resolve an unknown initial battery inventory after user-confirmed empty state.

        This action exists only for installations without SOC helper sensors. It is
        intentionally one-way: once the cost basis is known, the action becomes a
        no-op so an established inventory cannot be accidentally erased.
        """
        if _entity_ids(self.config.get(CONF_BATTERY_SOC)):
            raise ValueError("soc_configured")
        if not any(
            _entity_ids(self.config.get(key))
            for key in (CONF_BATTERY_CHARGE_ENERGY, CONF_BATTERY_DISCHARGE_ENERGY, CONF_BATTERY_POWER)
        ):
            raise ValueError("battery_not_configured")

        # First capture all cumulative-meter movement up to the confirmation moment.
        await self.async_process_tick()

        async with self._process_lock:
            if self.inventory.basis_known:
                return {"changed": False, "basis_known": True}

            discarded_energy = float(self.inventory.energy_kwh)
            discarded_cost = float(self.inventory.cost_basis)
            self.inventory.mark_empty()
            await self._async_save_inventory()
            now = _utc_iso(dt_util.utcnow())
            await self.ledger.async_add_event(
                now,
                "battery_manual_empty",
                "battery_inventory",
                {
                    "discarded_virtual_energy_kwh": discarded_energy,
                    "discarded_unreconciled_cost_basis": discarded_cost,
                },
            )

        await self.async_refresh_summary()
        return {"changed": True, "basis_known": True}

    async def _async_fixed_cost_breakdown_for_period(
        self, start: datetime, end: datetime
    ) -> dict[str, float]:
        """Return fixed-cost components only for ledger-covered time.

        This intentionally follows the same persisted/open interval coverage as
        the public period summary. It therefore never invents fixed charges for
        time before ECT started tracking or for uncovered gaps.
        """
        start_utc = dt_util.as_utc(start)
        end_utc = dt_util.as_utc(end)
        start_iso = start_utc.isoformat()
        end_iso = end_utc.isoformat()
        bounds = await self.ledger.async_interval_bounds(start_iso, end_iso)
        profiles = self._fixed_cost_profiles()
        result = {"daily": 0.0, "monthly": 0.0, "annual": 0.0, "annual_rebate": 0.0, "total": 0.0}
        ranges: list[tuple[datetime, datetime]] = []

        def collect_slice(raw_start, raw_end) -> None:
            row_start = datetime.fromisoformat(str(raw_start).replace("Z", "+00:00"))
            row_end = datetime.fromisoformat(str(raw_end).replace("Z", "+00:00"))
            if row_start.tzinfo is None:
                row_start = row_start.replace(tzinfo=timezone.utc)
            if row_end.tzinfo is None:
                row_end = row_end.replace(tzinfo=timezone.utc)
            overlap_start = max(start_utc, row_start.astimezone(timezone.utc))
            overlap_end = min(end_utc, row_end.astimezone(timezone.utc))
            if overlap_end > overlap_start:
                ranges.append((overlap_start, overlap_end))

        for row in bounds:
            collect_slice(row["start_ts"], row["end_ts"])
        pending = self.pending_ledger_row
        if pending:
            collect_slice(pending["start_ts"], pending["end_ts"])

        # Most ledgers contain thousands of adjacent 15-minute rows. Merge only
        # truly contiguous/overlapping coverage before calculating the calendar
        # proration, so invoice-year views stay cheap without filling real gaps.
        merged: list[list[datetime]] = []
        for range_start, range_end in sorted(ranges, key=lambda item: item[0]):
            if merged and range_start <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], range_end)
            else:
                merged.append([range_start, range_end])
        for range_start, range_end in merged:
            part = fixed_cost_breakdown_for_interval(
                range_start, range_end, self.hass.config.time_zone, profiles
            )
            for key in result:
                result[key] += float(part[key])
        return result

    async def _async_invoice_period(
        self, start: datetime, end: datetime
    ) -> dict[str, Any]:
        summary = await self.ledger.async_period_summary(
            _utc_iso(start), _utc_iso(end), self.pending_ledger_row
        )
        summary["period_start"] = start.isoformat()
        summary["period_end"] = end.isoformat()
        summary["fixed_breakdown"] = await self._async_fixed_cost_breakdown_for_period(start, end)
        return summary

    async def async_invoice_breakdown(
        self, view: str, anchor_date: str | None = None
    ) -> dict[str, Any]:
        """Build billing-month/year invoice reconciliation data."""
        tz = dt_util.get_time_zone(self.hass.config.time_zone)
        if tz is None:
            tz = timezone.utc
        if anchor_date:
            try:
                anchor_day = datetime.strptime(anchor_date, "%Y-%m-%d").date()
            except ValueError as err:
                raise ValueError("anchor must be YYYY-MM-DD") from err
            anchor = datetime(anchor_day.year, anchor_day.month, anchor_day.day, 12, 0, tzinfo=tz)
        else:
            anchor = dt_util.now()

        month_day = int(self.config.get(CONF_BILLING_MONTH_START_DAY, 1))
        year_month = int(self.config.get(CONF_BILLING_YEAR_START_MONTH, 1))
        year_day = int(self.config.get(CONF_BILLING_YEAR_START_DAY, 1))
        if view == "month":
            start, end = billing_month_bounds(anchor, month_day)
        elif view == "year":
            start, end = billing_year_bounds(anchor, year_month, year_day)
        else:
            raise ValueError("view must be month or year")

        period = await self._async_invoice_period(start, end)
        result: dict[str, Any] = {
            "view": view,
            "anchor": anchor.date().isoformat(),
            "period_start": start.isoformat(),
            "period_end": end.isoformat(),
            "prev_anchor": (start - timedelta(days=1)).date().isoformat(),
            "next_anchor": end.date().isoformat(),
            "is_current": start <= dt_util.now() < end,
            "period": period,
            "months": [],
        }
        if view == "year":
            months = []
            for month_start, month_end in billing_month_segments(start, end, month_day):
                months.append(await self._async_invoice_period(month_start, month_end))
            result["months"] = months
        return result

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
            summary = await self.ledger.async_period_summary(
                _utc_iso(start), _utc_iso(end), self.pending_ledger_row
            )
            summary["period_start"] = start.isoformat()
            summary["period_end"] = end.isoformat()
            summaries[name] = summary
        summaries["total"] = await self.ledger.async_period_summary(
            None, None, self.pending_ledger_row
        )
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
