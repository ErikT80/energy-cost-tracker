"""SQLite-backed immutable accounting ledger."""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import json
import sqlite3
from pathlib import Path
from typing import Any, TYPE_CHECKING
from zoneinfo import ZoneInfo


if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


SCHEMA_VERSION = 2


class Ledger:
    """Small dedicated SQLite ledger optimized for long-lived searchable history."""

    def __init__(self, hass: "HomeAssistant", path: Path) -> None:
        self.hass = hass
        self.path = path
        self._operation_lock = asyncio.Lock()
        self._backup_lock_held = False

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=20)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    @contextmanager
    def _connection(self):
        """Yield a transaction and always close the SQLite connection afterwards."""
        conn = self._connect()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT
                );
                CREATE TABLE IF NOT EXISTS source_state (
                    source_key TEXT PRIMARY KEY,
                    entity_id TEXT NOT NULL,
                    last_value REAL NOT NULL,
                    last_ts TEXT NOT NULL,
                    segment INTEGER NOT NULL DEFAULT 1,
                    reset_count INTEGER NOT NULL DEFAULT 0,
                    accumulated REAL NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS ledger (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    start_ts TEXT NOT NULL,
                    end_ts TEXT NOT NULL,
                    seconds REAL NOT NULL,
                    grid_import_kwh REAL NOT NULL DEFAULT 0,
                    grid_export_kwh REAL NOT NULL DEFAULT 0,
                    house_consumption_kwh REAL NOT NULL DEFAULT 0,
                    pv_production_kwh REAL NOT NULL DEFAULT 0,
                    battery_charge_kwh REAL NOT NULL DEFAULT 0,
                    battery_discharge_kwh REAL NOT NULL DEFAULT 0,
                    grid_to_house_kwh REAL NOT NULL DEFAULT 0,
                    grid_to_battery_kwh REAL NOT NULL DEFAULT 0,
                    pv_direct_kwh REAL NOT NULL DEFAULT 0,
                    pv_export_kwh REAL NOT NULL DEFAULT 0,
                    pv_to_battery_kwh REAL NOT NULL DEFAULT 0,
                    battery_to_house_kwh REAL NOT NULL DEFAULT 0,
                    battery_to_grid_kwh REAL NOT NULL DEFAULT 0,
                    flow_residual_kwh REAL NOT NULL DEFAULT 0,
                    import_price REAL,
                    export_price REAL,
                    import_cost REAL,
                    export_revenue REAL,
                    fixed_cost REAL NOT NULL DEFAULT 0,
                    net_cost REAL,
                    pv_value REAL,
                    battery_charge_cost REAL,
                    battery_discharge_value REAL,
                    battery_discharge_cost_basis REAL,
                    battery_profit REAL,
                    battery_loss_cost REAL NOT NULL DEFAULT 0,
                    quality TEXT NOT NULL,
                    notes TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_ledger_end_ts ON ledger(end_ts);
                CREATE INDEX IF NOT EXISTS idx_ledger_quality ON ledger(quality);
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    source_key TEXT,
                    details TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
                CREATE TABLE IF NOT EXISTS profiles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    effective_from TEXT NOT NULL,
                    config_hash TEXT NOT NULL,
                    config_json TEXT NOT NULL
                );
                """
            )
            row = conn.execute(
                "SELECT value FROM meta WHERE key = 'schema_version'"
            ).fetchone()
            if row is None:
                existing_rows = int(conn.execute("SELECT COUNT(*) FROM ledger").fetchone()[0])
                if existing_rows:
                    raise RuntimeError(
                        "Existing Energy Cost Tracker ledger has no schema version; "
                        "refusing to guess its format"
                    )
                # A genuinely fresh database already has the current table shape.
                conn.execute(
                    "INSERT INTO meta(key, value) VALUES('schema_version', ?)",
                    (str(SCHEMA_VERSION),),
                )
            else:
                self._migrate_schema(conn, int(row[0]))

    @staticmethod
    def _set_schema_version(conn: sqlite3.Connection, version: int) -> None:
        conn.execute(
            "UPDATE meta SET value = ? WHERE key = 'schema_version'",
            (str(version),),
        )

    def _migrate_schema(self, conn: sqlite3.Connection, current_version: int) -> None:
        """Migrate the dedicated ledger database forward transactionally."""
        if current_version > SCHEMA_VERSION:
            raise RuntimeError(
                f"Energy Cost Tracker database schema {current_version} is newer "
                f"than supported schema {SCHEMA_VERSION}"
            )

        version = current_version
        while version < SCHEMA_VERSION:
            if version == 1:
                # Schema 2 introduces the explicit forward-only migration framework.
                # The physical v1 table shape is already compatible, so this step is
                # intentionally data-preserving and has no DDL changes.
                version = 2
                self._set_schema_version(conn, version)
                continue
            raise RuntimeError(
                f"No ledger migration path from schema {version} to {SCHEMA_VERSION}"
            )

    async def _async_run(self, func, *args):
        """Run one database operation while respecting the backup barrier."""
        async with self._operation_lock:
            return await self.hass.async_add_executor_job(func, *args)

    def _prepare_backup(self) -> None:
        """Checkpoint WAL data and leave a single stable database file for backup."""
        if not self.path.exists():
            return

        # Checkpoint on one short-lived connection first. SQLite can reject a
        # journal-mode change on the same connection immediately after a WAL
        # checkpoint, so reopen before switching to DELETE mode.
        conn = sqlite3.connect(self.path, timeout=20)
        try:
            checkpoint = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            if checkpoint is not None and int(checkpoint[0]) != 0:
                raise RuntimeError("SQLite WAL checkpoint is busy")
        finally:
            conn.close()

        conn = sqlite3.connect(self.path, timeout=20)
        try:
            mode_row = conn.execute("PRAGMA journal_mode=DELETE").fetchone()
            mode = str(mode_row[0]).lower() if mode_row else ""
            if mode != "delete":
                raise RuntimeError(f"Could not switch SQLite journal mode for backup: {mode}")
        finally:
            conn.close()

        # In DELETE mode there must be no WAL shared-memory sidecars. Remove any
        # stale leftovers from an interrupted previous process only after the clean
        # checkpoint/journal-mode switch above has succeeded.
        for suffix in ("-wal", "-shm"):
            Path(f"{self.path}{suffix}").unlink(missing_ok=True)

    async def async_prepare_backup(self) -> None:
        """Block all ledger access and make SQLite safe for Home Assistant backup."""
        if self._backup_lock_held:
            return
        await self._operation_lock.acquire()
        try:
            await self.hass.async_add_executor_job(self._prepare_backup)
        except Exception:
            self._operation_lock.release()
            raise
        self._backup_lock_held = True

    async def async_finish_backup(self) -> None:
        """Release the database barrier after Home Assistant finished the backup."""
        if not self._backup_lock_held:
            return
        self._backup_lock_held = False
        self._operation_lock.release()

    async def async_initialize(self) -> None:
        await self._async_run(self._initialize)

    def _get_meta(self, key: str) -> str | None:
        with self._connection() as conn:
            row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
            return None if row is None else row["value"]

    async def async_get_meta(self, key: str) -> str | None:
        return await self._async_run(self._get_meta, key)

    def _set_meta(self, key: str, value: str) -> None:
        with self._connection() as conn:
            conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)", (key, value))

    async def async_set_meta(self, key: str, value: str) -> None:
        await self._async_run(self._set_meta, key, value)

    def _observe_source(
        self,
        source_key: str,
        entity_id: str,
        value: float,
        ts: str,
    ) -> dict[str, Any]:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM source_state WHERE source_key=?", (source_key,)
            ).fetchone()
            if row is None:
                conn.execute(
                    """INSERT INTO source_state
                       (source_key, entity_id, last_value, last_ts, segment, reset_count, accumulated)
                       VALUES (?, ?, ?, ?, 1, 0, 0)""",
                    (source_key, entity_id, value, ts),
                )
                return {"delta": 0.0, "quality": "baseline", "event": "baseline"}

            if row["entity_id"] != entity_id:
                details = json.dumps({"old_entity": row["entity_id"], "new_entity": entity_id})
                conn.execute(
                    "INSERT INTO events(ts,event_type,source_key,details) VALUES(?,?,?,?)",
                    (ts, "source_changed", source_key, details),
                )
                conn.execute(
                    """UPDATE source_state SET entity_id=?, last_value=?, last_ts=?,
                       segment=segment+1 WHERE source_key=?""",
                    (entity_id, value, ts, source_key),
                )
                return {"delta": 0.0, "quality": "reconstructed", "event": "source_changed"}

            previous = float(row["last_value"])
            delta = value - previous
            quality = "exact"
            event = None

            if delta < 0:
                drop = abs(delta)
                # A material drop is a reset/rollover. Tiny negative corrections are
                # accepted as a new baseline but never create negative energy.
                material = value <= previous * 0.20 or (value <= 0.05 and drop >= 0.05)
                if material:
                    delta = max(0.0, value)
                    quality = "reconstructed"
                    event = "counter_reset"
                    conn.execute(
                        "INSERT INTO events(ts,event_type,source_key,details) VALUES(?,?,?,?)",
                        (
                            ts,
                            event,
                            source_key,
                            json.dumps({"previous": previous, "current": value}),
                        ),
                    )
                    conn.execute(
                        """UPDATE source_state SET last_value=?, last_ts=?, segment=segment+1,
                           reset_count=reset_count+1, accumulated=accumulated+? WHERE source_key=?""",
                        (value, ts, delta, source_key),
                    )
                    return {"delta": delta, "quality": quality, "event": event}

                event = "negative_correction"
                quality = "reconstructed"
                delta = 0.0
                conn.execute(
                    "INSERT INTO events(ts,event_type,source_key,details) VALUES(?,?,?,?)",
                    (
                        ts,
                        event,
                        source_key,
                        json.dumps({"previous": previous, "current": value}),
                    ),
                )

            conn.execute(
                """UPDATE source_state SET last_value=?, last_ts=?, accumulated=accumulated+?
                   WHERE source_key=?""",
                (value, ts, delta, source_key),
            )
            return {"delta": delta, "quality": quality, "event": event}

    async def async_observe_source(
        self, source_key: str, entity_id: str, value: float, ts: str
    ) -> dict[str, Any]:
        return await self._async_run(
            self._observe_source, source_key, entity_id, value, ts
        )

    def _insert_interval(self, row: dict[str, Any]) -> int:
        columns = list(row)
        placeholders = ",".join("?" for _ in columns)
        sql = f"INSERT INTO ledger ({','.join(columns)}) VALUES ({placeholders})"
        with self._connection() as conn:
            cur = conn.execute(sql, [row[c] for c in columns])
            return int(cur.lastrowid)

    async def async_insert_interval(self, row: dict[str, Any]) -> int:
        return await self._async_run(self._insert_interval, row)

    def _commit_pending_interval(self, row: dict[str, Any]) -> int:
        """Atomically commit a pending interval and clear its crash checkpoint."""
        columns = list(row)
        placeholders = ",".join("?" for _ in columns)
        sql = f"INSERT INTO ledger ({','.join(columns)}) VALUES ({placeholders})"
        with self._connection() as conn:
            cur = conn.execute(sql, [row[c] for c in columns])
            conn.execute("DELETE FROM meta WHERE key='pending_interval'")
            return int(cur.lastrowid)

    async def async_commit_pending_interval(self, row: dict[str, Any]) -> int:
        return await self._async_run(self._commit_pending_interval, row)

    @staticmethod
    def _summary_raw_from_interval(
        row: dict[str, Any], start: str | None, end: str | None
    ) -> dict[str, Any]:
        """Build an unfinalized summary for one in-memory interval row."""
        row_start = datetime.fromisoformat(str(row["start_ts"]).replace("Z", "+00:00"))
        row_end = datetime.fromisoformat(str(row["end_ts"]).replace("Z", "+00:00"))
        if row_start.tzinfo is None:
            row_start = row_start.replace(tzinfo=timezone.utc)
        if row_end.tzinfo is None:
            row_end = row_end.replace(tzinfo=timezone.utc)
        row_start = row_start.astimezone(timezone.utc)
        row_end = row_end.astimezone(timezone.utc)
        period_start = (
            datetime.fromisoformat(start.replace("Z", "+00:00")).astimezone(timezone.utc)
            if start
            else row_start
        )
        period_end = (
            datetime.fromisoformat(end.replace("Z", "+00:00")).astimezone(timezone.utc)
            if end
            else row_end
        )
        overlap_start = max(row_start, period_start)
        overlap_end = min(row_end, period_end)
        seconds = float(row.get("seconds") or 0.0)
        overlap_seconds = max(0.0, (overlap_end - overlap_start).total_seconds())
        if seconds <= 0 or overlap_seconds <= 0:
            return {"intervals": 0}
        fraction = min(1.0, overlap_seconds / seconds)

        energy_fields = (
            "grid_import_kwh",
            "grid_export_kwh",
            "house_consumption_kwh",
            "pv_production_kwh",
            "battery_charge_kwh",
            "battery_discharge_kwh",
            "grid_to_house_kwh",
            "grid_to_battery_kwh",
            "pv_direct_kwh",
            "pv_export_kwh",
            "pv_to_battery_kwh",
            "battery_to_house_kwh",
            "battery_to_grid_kwh",
            "flow_residual_kwh",
        )
        money_fields = (
            "import_cost",
            "export_revenue",
            "fixed_cost",
            "net_cost",
            "pv_value",
            "battery_charge_cost",
            "battery_discharge_value",
            "battery_discharge_cost_basis",
            "battery_profit",
            "battery_loss_cost",
        )
        result: dict[str, Any] = {
            "intervals": 1,
            "covered_seconds": overlap_seconds,
            "first_ts": row.get("start_ts"),
            "last_ts": row.get("end_ts"),
        }
        for key in energy_fields:
            result[key] = float(row.get(key) or 0.0) * fraction
        for key in money_fields:
            value = row.get(key)
            result[key] = None if value is None else float(value) * fraction

        import_price = row.get("import_price")
        export_price = row.get("export_price")
        result["import_price_weighted_sum"] = (
            float(import_price) * overlap_seconds if import_price is not None else 0.0
        )
        result["import_price_seconds"] = overlap_seconds if import_price is not None else 0.0
        result["export_price_weighted_sum"] = (
            float(export_price) * overlap_seconds if export_price is not None else 0.0
        )
        result["export_price_seconds"] = overlap_seconds if export_price is not None else 0.0

        gi = float(row.get("grid_import_kwh") or 0.0)
        ge = float(row.get("grid_export_kwh") or 0.0)
        pv = float(row.get("pv_production_kwh") or 0.0)
        pv_export = float(row.get("pv_export_kwh") or 0.0)
        bc = float(row.get("battery_charge_kwh") or 0.0)
        bd = float(row.get("battery_discharge_kwh") or 0.0)

        # Energy denominators for effective, energy-weighted prices. Only include
        # energy whose matching monetary value is actually known. This keeps
        # incomplete price intervals from diluting the displayed average.
        result["priced_import_kwh"] = gi * fraction if row.get("import_cost") is not None else 0.0
        result["priced_export_kwh"] = ge * fraction if row.get("export_revenue") is not None else 0.0
        result["valued_pv_kwh"] = pv * fraction if row.get("pv_value") is not None else 0.0
        result["priced_pv_export_kwh"] = pv_export * fraction if export_price is not None else 0.0
        result["pv_export_revenue"] = (
            pv_export * float(export_price) * fraction if export_price is not None else 0.0
        )
        result["costed_battery_charge_kwh"] = (
            bc * fraction if row.get("battery_charge_cost") is not None else 0.0
        )
        result["valued_battery_discharge_kwh"] = (
            bd * fraction if row.get("battery_discharge_value") is not None else 0.0
        )
        result["incomplete_cost_intervals"] = int(row.get("net_cost") is None)
        result["incomplete_import_intervals"] = int(row.get("import_cost") is None and gi > 0)
        result["incomplete_export_intervals"] = int(row.get("export_revenue") is None and ge > 0)
        result["incomplete_pv_intervals"] = int(row.get("pv_value") is None and pv > 0)
        result["incomplete_battery_intervals"] = int(row.get("battery_profit") is None and bd > 0)
        result["non_exact_intervals"] = int(str(row.get("quality") or "exact") != "exact")
        return result

    @staticmethod
    def _combine_raw_summaries(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
        """Combine raw summaries while preserving SQL SUM(NULL) semantics."""
        if not int(extra.get("intervals") or 0):
            return dict(base)
        if not int(base.get("intervals") or 0):
            return dict(extra)

        result = dict(base)
        count_fields = (
            "intervals",
            "incomplete_cost_intervals",
            "incomplete_import_intervals",
            "incomplete_export_intervals",
            "incomplete_pv_intervals",
            "incomplete_battery_intervals",
            "non_exact_intervals",
        )
        additive_fields = (
            "covered_seconds",
            "grid_import_kwh",
            "grid_export_kwh",
            "house_consumption_kwh",
            "pv_production_kwh",
            "battery_charge_kwh",
            "battery_discharge_kwh",
            "grid_to_house_kwh",
            "grid_to_battery_kwh",
            "pv_direct_kwh",
            "pv_export_kwh",
            "pv_to_battery_kwh",
            "battery_to_house_kwh",
            "battery_to_grid_kwh",
            "flow_residual_kwh",
            "fixed_cost",
            "battery_loss_cost",
            "import_price_weighted_sum",
            "import_price_seconds",
            "export_price_weighted_sum",
            "export_price_seconds",
            "priced_import_kwh",
            "priced_export_kwh",
            "valued_pv_kwh",
            "priced_pv_export_kwh",
            "pv_export_revenue",
            "costed_battery_charge_kwh",
            "valued_battery_discharge_kwh",
        )
        optional_sum_fields = (
            "import_cost",
            "export_revenue",
            "net_cost",
            "pv_value",
            "battery_charge_cost",
            "battery_discharge_value",
            "battery_discharge_cost_basis",
            "battery_profit",
        )
        for key in count_fields:
            result[key] = int(base.get(key) or 0) + int(extra.get(key) or 0)
        for key in additive_fields:
            result[key] = float(base.get(key) or 0.0) + float(extra.get(key) or 0.0)
        for key in optional_sum_fields:
            values = [value for value in (base.get(key), extra.get(key)) if value is not None]
            result[key] = sum(float(value) for value in values) if values else None
        starts = [value for value in (base.get("first_ts"), extra.get("first_ts")) if value]
        ends = [value for value in (base.get("last_ts"), extra.get("last_ts")) if value]
        result["first_ts"] = min(starts) if starts else None
        result["last_ts"] = max(ends) if ends else None
        return result

    @staticmethod
    def _finalize_summary(raw: dict[str, Any]) -> dict[str, Any]:
        """Convert raw aggregate fields into the public period-summary contract."""
        result = dict(raw)
        intervals = int(result.get("intervals") or 0)
        count_fields = {
            "intervals",
            "incomplete_cost_intervals",
            "incomplete_import_intervals",
            "incomplete_export_intervals",
            "incomplete_pv_intervals",
            "incomplete_battery_intervals",
            "non_exact_intervals",
        }
        text_fields = {"first_ts", "last_ts"}
        for key in count_fields:
            result[key] = int(result.get(key) or 0)

        import_seconds = float(result.pop("import_price_seconds", 0.0) or 0.0)
        export_seconds = float(result.pop("export_price_seconds", 0.0) or 0.0)
        import_weighted = float(result.pop("import_price_weighted_sum", 0.0) or 0.0)
        export_weighted = float(result.pop("export_price_weighted_sum", 0.0) or 0.0)
        # Retain the old time-weighted tariff averages for diagnostics, but expose
        # avg_import/export_price as the price the installation actually paid or
        # received: monetary total divided by the energy that had a known price.
        result["avg_tariff_import_price"] = import_weighted / import_seconds if import_seconds > 0 else None
        result["avg_tariff_export_price"] = export_weighted / export_seconds if export_seconds > 0 else None

        priced_import_kwh = float(result.get("priced_import_kwh") or 0.0)
        priced_export_kwh = float(result.get("priced_export_kwh") or 0.0)
        valued_pv_kwh = float(result.get("valued_pv_kwh") or 0.0)
        priced_pv_export_kwh = float(result.get("priced_pv_export_kwh") or 0.0)
        costed_battery_charge_kwh = float(result.get("costed_battery_charge_kwh") or 0.0)
        valued_battery_discharge_kwh = float(result.get("valued_battery_discharge_kwh") or 0.0)
        known_import_cost = result.get("import_cost")
        known_export_revenue = result.get("export_revenue")
        known_pv_value = result.get("pv_value")
        battery_charge_cost = result.get("battery_charge_cost")
        battery_discharge_value = result.get("battery_discharge_value")

        result["avg_import_price"] = (
            float(known_import_cost) / priced_import_kwh
            if known_import_cost is not None and priced_import_kwh > 1e-12
            else None
        )
        result["avg_export_price"] = (
            float(known_export_revenue) / priced_export_kwh
            if known_export_revenue is not None and priced_export_kwh > 1e-12
            else None
        )
        result["avg_pv_value_per_kwh"] = (
            float(known_pv_value) / valued_pv_kwh
            if known_pv_value is not None and valued_pv_kwh > 1e-12
            else None
        )
        result["avg_pv_export_price"] = (
            float(result.get("pv_export_revenue") or 0.0) / priced_pv_export_kwh
            if priced_pv_export_kwh > 1e-12
            else None
        )
        result["avg_battery_charge_cost_per_kwh"] = (
            float(battery_charge_cost) / costed_battery_charge_kwh
            if battery_charge_cost is not None and costed_battery_charge_kwh > 1e-12
            else None
        )
        result["avg_battery_discharge_value_per_kwh"] = (
            float(battery_discharge_value) / valued_battery_discharge_kwh
            if battery_discharge_value is not None and valued_battery_discharge_kwh > 1e-12
            else None
        )

        for key, value in list(result.items()):
            if key in count_fields or key in text_fields:
                continue
            if value is None and intervals == 0:
                result[key] = 0.0

        result["known_import_cost"] = result.get("import_cost")
        result["known_export_revenue"] = result.get("export_revenue")
        result["known_pv_value"] = result.get("pv_value")
        result["known_battery_profit"] = result.get("battery_profit")
        if intervals == 0:
            result["known_net_cost"] = 0.0
        else:
            result["known_net_cost"] = (
                float(result.get("known_import_cost") or 0.0)
                - float(result.get("known_export_revenue") or 0.0)
                + float(result.get("fixed_cost") or 0.0)
            )

        result["financial_complete"] = result.get("incomplete_cost_intervals", 0) == 0
        result["pv_complete"] = result.get("incomplete_pv_intervals", 0) == 0
        result["battery_complete"] = result.get("incomplete_battery_intervals", 0) == 0
        if result.get("incomplete_import_intervals", 0):
            result["import_cost"] = None
        if result.get("incomplete_export_intervals", 0):
            result["export_revenue"] = None
        if result.get("incomplete_cost_intervals", 0):
            result["net_cost"] = None
        if result.get("incomplete_pv_intervals", 0):
            result["pv_value"] = None
        if result.get("incomplete_battery_intervals", 0):
            result["battery_profit"] = None
        return result

    def _period_summary_raw(self, start: str | None, end: str | None) -> dict[str, Any]:
        """Aggregate persisted ledger rows without applying completeness nulling."""
        where = []
        params: list[Any] = []
        if start is not None:
            where.append("end_ts > ?")
            params.append(start)
        if end is not None:
            where.append("start_ts < ?")
            params.append(end)
        where_sql = " WHERE " + " AND ".join(where) if where else ""
        factor_sql = """
            CASE WHEN seconds <= 0 THEN 0.0 ELSE
              MIN(1.0, MAX(0.0,
                (julianday(MIN(end_ts, COALESCE(?, end_ts))) -
                 julianday(MAX(start_ts, COALESCE(?, start_ts))))
                * 86400.0 / seconds
              ))
            END
        """
        cte_params = [end, start, *params]
        sql = f"""
            WITH selected AS (
              SELECT *, {factor_sql} AS fraction
              FROM ledger{where_sql}
            )
            SELECT
              COUNT(*) AS intervals,
              SUM(seconds * fraction) AS covered_seconds,
              SUM(grid_import_kwh * fraction) AS grid_import_kwh,
              SUM(grid_export_kwh * fraction) AS grid_export_kwh,
              SUM(house_consumption_kwh * fraction) AS house_consumption_kwh,
              SUM(pv_production_kwh * fraction) AS pv_production_kwh,
              SUM(battery_charge_kwh * fraction) AS battery_charge_kwh,
              SUM(battery_discharge_kwh * fraction) AS battery_discharge_kwh,
              SUM(grid_to_house_kwh * fraction) AS grid_to_house_kwh,
              SUM(grid_to_battery_kwh * fraction) AS grid_to_battery_kwh,
              SUM(pv_direct_kwh * fraction) AS pv_direct_kwh,
              SUM(pv_export_kwh * fraction) AS pv_export_kwh,
              SUM(pv_to_battery_kwh * fraction) AS pv_to_battery_kwh,
              SUM(battery_to_house_kwh * fraction) AS battery_to_house_kwh,
              SUM(battery_to_grid_kwh * fraction) AS battery_to_grid_kwh,
              SUM(flow_residual_kwh * fraction) AS flow_residual_kwh,
              SUM(import_cost * fraction) AS import_cost,
              SUM(export_revenue * fraction) AS export_revenue,
              SUM(fixed_cost * fraction) AS fixed_cost,
              SUM(net_cost * fraction) AS net_cost,
              SUM(pv_value * fraction) AS pv_value,
              SUM(battery_charge_cost * fraction) AS battery_charge_cost,
              SUM(battery_discharge_value * fraction) AS battery_discharge_value,
              SUM(battery_discharge_cost_basis * fraction) AS battery_discharge_cost_basis,
              SUM(battery_profit * fraction) AS battery_profit,
              SUM(battery_loss_cost * fraction) AS battery_loss_cost,
              SUM(CASE WHEN import_price IS NOT NULL THEN import_price * seconds * fraction ELSE 0 END)
                AS import_price_weighted_sum,
              SUM(CASE WHEN import_price IS NOT NULL THEN seconds * fraction ELSE 0 END)
                AS import_price_seconds,
              SUM(CASE WHEN export_price IS NOT NULL THEN export_price * seconds * fraction ELSE 0 END)
                AS export_price_weighted_sum,
              SUM(CASE WHEN export_price IS NOT NULL THEN seconds * fraction ELSE 0 END)
                AS export_price_seconds,
              SUM(CASE WHEN import_cost IS NOT NULL THEN grid_import_kwh * fraction ELSE 0 END)
                AS priced_import_kwh,
              SUM(CASE WHEN export_revenue IS NOT NULL THEN grid_export_kwh * fraction ELSE 0 END)
                AS priced_export_kwh,
              SUM(CASE WHEN pv_value IS NOT NULL THEN pv_production_kwh * fraction ELSE 0 END)
                AS valued_pv_kwh,
              SUM(CASE WHEN export_price IS NOT NULL THEN pv_export_kwh * fraction ELSE 0 END)
                AS priced_pv_export_kwh,
              SUM(CASE WHEN export_price IS NOT NULL THEN pv_export_kwh * export_price * fraction ELSE 0 END)
                AS pv_export_revenue,
              SUM(CASE WHEN battery_charge_cost IS NOT NULL THEN battery_charge_kwh * fraction ELSE 0 END)
                AS costed_battery_charge_kwh,
              SUM(CASE WHEN battery_discharge_value IS NOT NULL THEN battery_discharge_kwh * fraction ELSE 0 END)
                AS valued_battery_discharge_kwh,
              SUM(CASE WHEN net_cost IS NULL AND fraction > 0 THEN 1 ELSE 0 END) AS incomplete_cost_intervals,
              SUM(CASE WHEN import_cost IS NULL AND grid_import_kwh > 0 AND fraction > 0 THEN 1 ELSE 0 END) AS incomplete_import_intervals,
              SUM(CASE WHEN export_revenue IS NULL AND grid_export_kwh > 0 AND fraction > 0 THEN 1 ELSE 0 END) AS incomplete_export_intervals,
              SUM(CASE WHEN pv_value IS NULL AND pv_production_kwh > 0 AND fraction > 0 THEN 1 ELSE 0 END) AS incomplete_pv_intervals,
              SUM(CASE WHEN battery_profit IS NULL AND battery_discharge_kwh > 0 AND fraction > 0 THEN 1 ELSE 0 END) AS incomplete_battery_intervals,
              SUM(CASE WHEN quality != 'exact' AND fraction > 0 THEN 1 ELSE 0 END) AS non_exact_intervals,
              MIN(start_ts) AS first_ts,
              MAX(end_ts) AS last_ts
            FROM selected
            WHERE fraction > 0
        """
        with self._connection() as conn:
            row = conn.execute(sql, cte_params).fetchone()
        return dict(row) if row is not None else {"intervals": 0}

    def _period_summary(
        self, start: str | None, end: str | None, extra_row: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        raw = self._period_summary_raw(start, end)
        if extra_row:
            raw = self._combine_raw_summaries(
                raw, self._summary_raw_from_interval(extra_row, start, end)
            )
        return self._finalize_summary(raw)

    async def async_period_summary(
        self, start: str | None, end: str | None, extra_row: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return await self._async_run(self._period_summary, start, end, extra_row)

    @staticmethod
    def _chart_granularity(start: datetime, end: datetime, requested: str) -> str:
        """Pick a chart bucket size that gets finer as the visible range shrinks."""
        if requested != "auto":
            return requested
        span = max(0.0, (end - start).total_seconds())
        if span > 120 * 86400:
            return "month"
        if span > 72 * 3600:
            return "day"
        if span > 6 * 3600:
            return "hour"
        return "quarter"

    @staticmethod
    def _parse_chart_dt(value: str) -> datetime:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    @staticmethod
    def _chart_bucket_bounds(
        start: datetime, end: datetime, granularity: str, tz_name: str
    ) -> list[tuple[datetime, datetime]]:
        """Return aligned bucket boundaries covering a UTC range."""
        bounds: list[tuple[datetime, datetime]] = []
        if end <= start:
            return bounds

        if granularity in {"quarter", "hour"}:
            seconds = 900 if granularity == "quarter" else 3600
            first_epoch = int(start.timestamp()) // seconds * seconds
            cursor = datetime.fromtimestamp(first_epoch, tz=timezone.utc)
            while cursor < end:
                nxt = cursor + timedelta(seconds=seconds)
                bounds.append((max(cursor, start), min(nxt, end)))
                cursor = nxt
            return bounds

        tz = ZoneInfo(tz_name)
        local = start.astimezone(tz)
        if granularity == "month":
            cursor_local = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            while cursor_local.astimezone(timezone.utc) < end:
                if cursor_local.month == 12:
                    next_local = cursor_local.replace(
                        year=cursor_local.year + 1, month=1
                    )
                else:
                    next_local = cursor_local.replace(month=cursor_local.month + 1)
                bucket_start = cursor_local.astimezone(timezone.utc)
                bucket_end = next_local.astimezone(timezone.utc)
                bounds.append((max(bucket_start, start), min(bucket_end, end)))
                cursor_local = next_local
            return bounds

        cursor_local = local.replace(hour=0, minute=0, second=0, microsecond=0)
        while cursor_local.astimezone(timezone.utc) < end:
            next_local = cursor_local + timedelta(days=1)
            bucket_start = cursor_local.astimezone(timezone.utc)
            bucket_end = next_local.astimezone(timezone.utc)
            bounds.append((max(bucket_start, start), min(bucket_end, end)))
            cursor_local = next_local
        return bounds

    @staticmethod
    def _chart_detail_line_row(row: dict[str, Any]) -> dict[str, Any]:
        """Return native-interval per-kWh values for detailed chart lines."""
        def _num(key: str) -> float | None:
            value = row.get(key)
            if value is None:
                return None
            try:
                return float(value)
            except (TypeError, ValueError):
                return None

        pv = _num("pv_production_kwh") or 0.0
        pv_export = _num("pv_export_kwh") or 0.0
        charge = _num("battery_charge_kwh") or 0.0
        discharge = _num("battery_discharge_kwh") or 0.0
        pv_value = _num("pv_value")
        charge_cost = _num("battery_charge_cost")
        discharge_value = _num("battery_discharge_value")
        export_price = _num("export_price")
        return {
            "start": str(row.get("start_ts")),
            "end": str(row.get("end_ts")),
            "import_tariff_price": _num("import_price"),
            "export_tariff_price": export_price,
            "pv_value_per_kwh": pv_value / pv if pv_value is not None and pv > 1e-12 else None,
            "pv_export_price": export_price if export_price is not None and pv_export > 1e-12 else None,
            "battery_charge_cost_per_kwh": (
                charge_cost / charge if charge_cost is not None and charge > 1e-12 else None
            ),
            "battery_discharge_value_per_kwh": (
                discharge_value / discharge
                if discharge_value is not None and discharge > 1e-12
                else None
            ),
        }

    def _chart_tariff_rows(
        self, start_dt: datetime, end_dt: datetime, extra_row: dict[str, Any] | None
    ) -> list[dict[str, Any]]:
        """Return persisted import/export tariffs at native ledger resolution.

        Overview tariff lines must use the actual prices stored on each native
        financial interval. This payload is kept separate from realized-price KPIs
        and the Solar/Battery detail-line payload.
        """
        if (end_dt - start_dt).total_seconds() > 32 * 86400:
            return []
        start = start_dt.isoformat()
        end = end_dt.isoformat()
        with self._connection() as conn:
            rows = [dict(row) for row in conn.execute(
                "SELECT start_ts,end_ts,import_price,export_price "
                "FROM ledger WHERE end_ts > ? AND start_ts < ? ORDER BY start_ts",
                (start, end),
            ).fetchall()]
        if extra_row:
            extra_start = self._parse_chart_dt(str(extra_row.get("start_ts")))
            extra_end = self._parse_chart_dt(str(extra_row.get("end_ts")))
            if extra_end > start_dt and extra_start < end_dt:
                rows.append({
                    "start_ts": extra_row.get("start_ts"),
                    "end_ts": extra_row.get("end_ts"),
                    "import_price": extra_row.get("import_price"),
                    "export_price": extra_row.get("export_price"),
                })
                rows.sort(key=lambda row: str(row.get("start_ts") or ""))
        return [
            {
                "start": str(row.get("start_ts")),
                "end": str(row.get("end_ts")),
                "import_price": float(row["import_price"]) if row.get("import_price") is not None else None,
                "export_price": float(row["export_price"]) if row.get("export_price") is not None else None,
            }
            for row in rows
        ]

    def _chart_detail_line_rows(
        self, start_dt: datetime, end_dt: datetime, extra_row: dict[str, Any] | None
    ) -> list[dict[str, Any]]:
        """Return native ledger intervals for exact chart lines on practical ranges.

        A full year can contain ~35k quarter-hour intervals. Rendering that many
        points in a mobile SVG adds substantial payload/render cost and is not
        useful at year scale, so detailed lines are deliberately limited to 32 days.
        """
        if (end_dt - start_dt).total_seconds() > 32 * 86400:
            return []
        start = start_dt.isoformat()
        end = end_dt.isoformat()
        with self._connection() as conn:
            rows = [dict(row) for row in conn.execute(
                "SELECT start_ts,end_ts,import_price,export_price,pv_production_kwh,"
                "pv_export_kwh,pv_value,battery_charge_kwh,battery_discharge_kwh,"
                "battery_charge_cost,battery_discharge_value "
                "FROM ledger WHERE end_ts > ? AND start_ts < ? ORDER BY start_ts",
                (start, end),
            ).fetchall()]
        if extra_row:
            extra_start = self._parse_chart_dt(str(extra_row.get("start_ts")))
            extra_end = self._parse_chart_dt(str(extra_row.get("end_ts")))
            if extra_end > start_dt and extra_start < end_dt:
                rows.append(dict(extra_row))
                rows.sort(key=lambda row: str(row.get("start_ts") or ""))
        return [self._chart_detail_line_row(row) for row in rows]

    def _chart_series(
        self,
        start: str,
        end: str,
        granularity: str = "auto",
        tz_name: str = "UTC",
        extra_row: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build financial chart buckets from the immutable ledger.

        The graph deliberately uses known subtotals for incomplete buckets while
        exposing completeness flags. This mirrors the sidebar cards without ever
        turning a partial value into a definitive invoice total.
        """
        start_dt = self._parse_chart_dt(start)
        end_dt = self._parse_chart_dt(end)
        if end_dt <= start_dt:
            raise ValueError("chart end must be after start")

        selected = self._chart_granularity(start_dt, end_dt, granularity)
        buckets = self._chart_bucket_bounds(start_dt, end_dt, selected, tz_name)
        # Keep accidental huge requests bounded. Normal auto ranges are far below this.
        if len(buckets) > 500:
            raise ValueError("chart range produces too many buckets")

        period_summary = self._period_summary(start_dt.isoformat(), end_dt.isoformat(), extra_row)
        rows: list[dict[str, Any]] = []
        for bucket_start, bucket_end in buckets:
            summary = self._period_summary(
                bucket_start.isoformat(), bucket_end.isoformat(), extra_row
            )
            if int(summary.get("intervals") or 0) == 0:
                continue
            rows.append(
                {
                    "start": bucket_start.isoformat(),
                    "end": bucket_end.isoformat(),
                    "net_cost": summary.get("net_cost")
                    if summary.get("net_cost") is not None
                    else summary.get("known_net_cost"),
                    "pv_value": summary.get("pv_value")
                    if summary.get("pv_value") is not None
                    else summary.get("known_pv_value"),
                    "battery_profit": summary.get("battery_profit")
                    if summary.get("battery_profit") is not None
                    else summary.get("known_battery_profit"),
                    "import_cost": summary.get("import_cost")
                    if summary.get("import_cost") is not None
                    else summary.get("known_import_cost"),
                    "export_revenue": summary.get("export_revenue")
                    if summary.get("export_revenue") is not None
                    else summary.get("known_export_revenue"),
                    "fixed_cost": summary.get("fixed_cost"),
                    "pv_production_kwh": summary.get("pv_production_kwh"),
                    "pv_direct_kwh": summary.get("pv_direct_kwh"),
                    "pv_export_kwh": summary.get("pv_export_kwh"),
                    "pv_to_battery_kwh": summary.get("pv_to_battery_kwh"),
                    "battery_charge_kwh": summary.get("battery_charge_kwh"),
                    "battery_discharge_kwh": summary.get("battery_discharge_kwh"),
                    "battery_charge_cost": summary.get("battery_charge_cost"),
                    "battery_discharge_value": summary.get("battery_discharge_value"),
                    "battery_loss_cost": summary.get("battery_loss_cost"),
                    # Keep realized, energy-weighted prices for the period KPI,
                    # but expose tariff lines separately. The graph line must show
                    # the tariff that applied in the displayed bucket, independent
                    # of how much energy happened to be imported/exported.
                    "import_price": summary.get("avg_import_price"),
                    "export_price": summary.get("avg_export_price"),
                    "import_tariff_price": summary.get("avg_tariff_import_price"),
                    "export_tariff_price": summary.get("avg_tariff_export_price"),
                    "pv_value_per_kwh": summary.get("avg_pv_value_per_kwh"),
                    "pv_export_price": summary.get("avg_pv_export_price"),
                    "battery_charge_cost_per_kwh": summary.get("avg_battery_charge_cost_per_kwh"),
                    "battery_discharge_value_per_kwh": summary.get("avg_battery_discharge_value_per_kwh"),
                    "financial_complete": bool(summary.get("financial_complete")),
                    "pv_complete": bool(summary.get("pv_complete")),
                    "battery_complete": bool(summary.get("battery_complete")),
                    "incomplete_cost_intervals": int(
                        summary.get("incomplete_cost_intervals") or 0
                    ),
                    "incomplete_pv_intervals": int(
                        summary.get("incomplete_pv_intervals") or 0
                    ),
                    "incomplete_battery_intervals": int(
                        summary.get("incomplete_battery_intervals") or 0
                    ),
                    "non_exact_intervals": int(
                        summary.get("non_exact_intervals") or 0
                    ),
                }
            )

        tariff_rows = self._chart_tariff_rows(start_dt, end_dt, extra_row)
        detail_line_rows = self._chart_detail_line_rows(start_dt, end_dt, extra_row)
        return {
            "start": start_dt.isoformat(),
            "end": end_dt.isoformat(),
            "granularity": selected,
            "timezone": tz_name,
            "tariff_detail_available": bool(tariff_rows),
            "tariff_rows": tariff_rows,
            "line_detail_available": bool(detail_line_rows),
            "line_rows": detail_line_rows,
            "averages": {
                "import_price": period_summary.get("avg_import_price"),
                "export_price": period_summary.get("avg_export_price"),
                "pv_value_per_kwh": period_summary.get("avg_pv_value_per_kwh"),
                "pv_export_price": period_summary.get("avg_pv_export_price"),
                "battery_charge_cost_per_kwh": period_summary.get("avg_battery_charge_cost_per_kwh"),
                "battery_discharge_value_per_kwh": period_summary.get("avg_battery_discharge_value_per_kwh"),
                "grid_import_kwh": period_summary.get("grid_import_kwh"),
                "priced_import_kwh": period_summary.get("priced_import_kwh"),
                "grid_export_kwh": period_summary.get("grid_export_kwh"),
                "priced_export_kwh": period_summary.get("priced_export_kwh"),
                "pv_production_kwh": period_summary.get("pv_production_kwh"),
                "valued_pv_kwh": period_summary.get("valued_pv_kwh"),
                "pv_export_kwh": period_summary.get("pv_export_kwh"),
                "priced_pv_export_kwh": period_summary.get("priced_pv_export_kwh"),
                "battery_charge_kwh": period_summary.get("battery_charge_kwh"),
                "costed_battery_charge_kwh": period_summary.get("costed_battery_charge_kwh"),
                "battery_discharge_kwh": period_summary.get("battery_discharge_kwh"),
                "valued_battery_discharge_kwh": period_summary.get("valued_battery_discharge_kwh"),
            },
            "rows": rows,
        }

    async def async_chart_series(
        self,
        start: str,
        end: str,
        granularity: str = "auto",
        tz_name: str = "UTC",
        extra_row: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return await self._async_run(
            self._chart_series, start, end, granularity, tz_name, extra_row
        )

    def _query_intervals(
        self,
        start: str | None,
        end: str | None,
        quality: str | None,
        activity: str | None,
        limit: int,
        offset: int,
    ) -> dict[str, Any]:
        where = []
        params: list[Any] = []
        if start:
            where.append("end_ts > ?")
            params.append(start)
        if end:
            where.append("start_ts < ?")
            params.append(end)
        if quality:
            where.append("quality = ?")
            params.append(quality)
        activity_columns = {
            "grid_import": "grid_import_kwh",
            "grid_export": "grid_export_kwh",
            "pv": "pv_production_kwh",
            "battery_charge": "battery_charge_kwh",
            "battery_discharge": "battery_discharge_kwh",
        }
        if activity in activity_columns:
            where.append(f"{activity_columns[activity]} > 0.000000001")
        elif activity == "issues":
            where.append("quality != 'exact'")
        where_sql = " WHERE " + " AND ".join(where) if where else ""
        with self._connection() as conn:
            total = conn.execute(f"SELECT COUNT(*) AS c FROM ledger{where_sql}", params).fetchone()["c"]
            rows = conn.execute(
                f"SELECT * FROM ledger{where_sql} ORDER BY end_ts DESC LIMIT ? OFFSET ?",
                [*params, limit, offset],
            ).fetchall()
        return {"total": int(total), "rows": [dict(row) for row in rows]}

    async def async_query_intervals(
        self,
        start: str | None,
        end: str | None,
        quality: str | None,
        activity: str | None = None,
        limit: int = 250,
        offset: int = 0,
    ) -> dict[str, Any]:
        return await self._async_run(
            self._query_intervals,
            start,
            end,
            quality,
            activity,
            min(max(limit, 1), 1000),
            max(offset, 0),
        )

    def _interval_bounds(self, start: str, end: str) -> list[dict[str, str]]:
        """Return persisted interval bounds that overlap a requested period."""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT start_ts,end_ts FROM ledger WHERE end_ts > ? AND start_ts < ? ORDER BY start_ts",
                (start, end),
            ).fetchall()
        return [{"start_ts": str(row["start_ts"]), "end_ts": str(row["end_ts"])} for row in rows]

    async def async_interval_bounds(self, start: str, end: str) -> list[dict[str, str]]:
        return await self._async_run(self._interval_bounds, start, end)

    def _fixed_cost_rows(self) -> list[dict[str, Any]]:
        """Return only fields needed for deterministic fixed-cost repair."""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT id,start_ts,end_ts,import_cost,export_revenue,fixed_cost,net_cost FROM ledger ORDER BY id"
            ).fetchall()
        return [dict(row) for row in rows]

    async def async_fixed_cost_rows(self) -> list[dict[str, Any]]:
        return await self._async_run(self._fixed_cost_rows)

    def _apply_fixed_cost_updates(
        self, updates: list[tuple[float, float | None, int]], details: dict[str, Any]
    ) -> int:
        """Apply a controlled fixed/net-cost correction and add an audit event."""
        with self._connection() as conn:
            if updates:
                conn.executemany(
                    "UPDATE ledger SET fixed_cost=?, net_cost=? WHERE id=?", updates
                )
            event_details = dict(details)
            event_details["changed_intervals"] = len(updates)
            conn.execute(
                "INSERT INTO events(ts,event_type,source_key,details) VALUES(?,?,?,?)",
                (
                    datetime.now(timezone.utc).isoformat(),
                    "fixed_cost_schedule_recalculated",
                    None,
                    json.dumps(event_details),
                ),
            )
        return len(updates)

    async def async_apply_fixed_cost_updates(
        self, updates: list[tuple[float, float | None, int]], details: dict[str, Any]
    ) -> int:
        return await self._async_run(self._apply_fixed_cost_updates, updates, details)

    def _add_event(
        self,
        ts: str,
        event_type: str,
        source_key: str | None,
        details: dict[str, Any] | None,
    ) -> None:
        with self._connection() as conn:
            conn.execute(
                "INSERT INTO events(ts,event_type,source_key,details) VALUES(?,?,?,?)",
                (ts, event_type, source_key, json.dumps(details) if details is not None else None),
            )

    async def async_add_event(
        self,
        ts: str,
        event_type: str,
        source_key: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        await self._async_run(self._add_event, ts, event_type, source_key, details)

    def _recent_events(self, limit: int) -> list[dict[str, Any]]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM events ORDER BY ts DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]

    async def async_recent_events(self, limit: int = 50) -> list[dict[str, Any]]:
        return await self._async_run(self._recent_events, limit)

    def _ensure_profile(self, effective_from: str, config_hash: str, config: dict[str, Any]) -> None:
        with self._connection() as conn:
            row = conn.execute("SELECT config_hash FROM profiles ORDER BY id DESC LIMIT 1").fetchone()
            if row and row["config_hash"] == config_hash:
                return
            conn.execute(
                "INSERT INTO profiles(effective_from,config_hash,config_json) VALUES(?,?,?)",
                (effective_from, config_hash, json.dumps(config, sort_keys=True)),
            )

    async def async_ensure_profile(self, effective_from: str, config_hash: str, config: dict[str, Any]) -> None:
        await self._async_run(
            self._ensure_profile, effective_from, config_hash, config
        )

    def _source_states(self) -> list[dict[str, Any]]:
        with self._connection() as conn:
            rows = conn.execute("SELECT * FROM source_state ORDER BY source_key").fetchall()
        return [dict(row) for row in rows]

    async def async_source_states(self) -> list[dict[str, Any]]:
        return await self._async_run(self._source_states)
