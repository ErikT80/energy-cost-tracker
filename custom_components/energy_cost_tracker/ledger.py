"""SQLite-backed immutable accounting ledger."""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
import json
import sqlite3
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


SCHEMA_VERSION = 1


class Ledger:
    """Small dedicated SQLite ledger optimized for long-lived searchable history."""

    def __init__(self, hass: "HomeAssistant", path: Path) -> None:
        self.hass = hass
        self.path = path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=20)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
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
            conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )

    async def async_initialize(self) -> None:
        await self.hass.async_add_executor_job(self._initialize)

    def _get_meta(self, key: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
            return None if row is None else row["value"]

    async def async_get_meta(self, key: str) -> str | None:
        return await self.hass.async_add_executor_job(self._get_meta, key)

    def _set_meta(self, key: str, value: str) -> None:
        with self._connect() as conn:
            conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)", (key, value))

    async def async_set_meta(self, key: str, value: str) -> None:
        await self.hass.async_add_executor_job(self._set_meta, key, value)

    def _observe_source(
        self,
        source_key: str,
        entity_id: str,
        value: float,
        ts: str,
    ) -> dict[str, Any]:
        with self._connect() as conn:
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
        return await self.hass.async_add_executor_job(
            self._observe_source, source_key, entity_id, value, ts
        )

    def _insert_interval(self, row: dict[str, Any]) -> int:
        columns = list(row)
        placeholders = ",".join("?" for _ in columns)
        sql = f"INSERT INTO ledger ({','.join(columns)}) VALUES ({placeholders})"
        with self._connect() as conn:
            cur = conn.execute(sql, [row[c] for c in columns])
            return int(cur.lastrowid)

    async def async_insert_interval(self, row: dict[str, Any]) -> int:
        return await self.hass.async_add_executor_job(self._insert_interval, row)

    def _period_summary(self, start: str | None, end: str | None) -> dict[str, Any]:
        """Aggregate a period and prorate rows that cross its boundaries.

        Normal rows are short, but a Home Assistant/source outage can intentionally
        create a longer estimated row. Prorating prevents such a row from being
        counted in full in two adjacent billing/calendar periods.
        """
        where = []
        params: list[Any] = []
        if start is not None:
            where.append("end_ts > ?")
            params.append(start)
        if end is not None:
            where.append("start_ts < ?")
            params.append(end)
        where_sql = " WHERE " + " AND ".join(where) if where else ""

        # All ledger timestamps are normalized to UTC ISO-8601, so lexical MAX/MIN
        # is safe before julianday() converts the overlap to seconds.
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
              SUM(grid_import_kwh * fraction) AS grid_import_kwh,
              SUM(grid_export_kwh * fraction) AS grid_export_kwh,
              SUM(house_consumption_kwh * fraction) AS house_consumption_kwh,
              SUM(pv_production_kwh * fraction) AS pv_production_kwh,
              SUM(battery_charge_kwh * fraction) AS battery_charge_kwh,
              SUM(battery_discharge_kwh * fraction) AS battery_discharge_kwh,
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
        with self._connect() as conn:
            row = conn.execute(sql, cte_params).fetchone()

        result = dict(row) if row is not None else {}
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
        for key, value in list(result.items()):
            if key in count_fields or key in text_fields:
                continue
            if value is None and intervals == 0:
                result[key] = 0.0

        # Never present a partial financial total as if it were complete.
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

    async def async_period_summary(self, start: str | None, end: str | None) -> dict[str, Any]:
        return await self.hass.async_add_executor_job(self._period_summary, start, end)

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
        with self._connect() as conn:
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
        return await self.hass.async_add_executor_job(
            self._query_intervals,
            start,
            end,
            quality,
            activity,
            min(max(limit, 1), 1000),
            max(offset, 0),
        )

    def _recent_events(self, limit: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM events ORDER BY ts DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]

    async def async_recent_events(self, limit: int = 50) -> list[dict[str, Any]]:
        return await self.hass.async_add_executor_job(self._recent_events, limit)

    def _ensure_profile(self, effective_from: str, config_hash: str, config: dict[str, Any]) -> None:
        with self._connect() as conn:
            row = conn.execute("SELECT config_hash FROM profiles ORDER BY id DESC LIMIT 1").fetchone()
            if row and row["config_hash"] == config_hash:
                return
            conn.execute(
                "INSERT INTO profiles(effective_from,config_hash,config_json) VALUES(?,?,?)",
                (effective_from, config_hash, json.dumps(config, sort_keys=True)),
            )

    async def async_ensure_profile(self, effective_from: str, config_hash: str, config: dict[str, Any]) -> None:
        await self.hass.async_add_executor_job(
            self._ensure_profile, effective_from, config_hash, config
        )

    def _source_states(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM source_state ORDER BY source_key").fetchall()
        return [dict(row) for row in rows]

    async def async_source_states(self) -> list[dict[str, Any]]:
        return await self.hass.async_add_executor_job(self._source_states)
