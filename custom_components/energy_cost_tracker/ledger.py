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


SCHEMA_VERSION = 1


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
            conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES('schema_version', ?)",
                (str(SCHEMA_VERSION),),
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
              SUM(CASE WHEN import_price IS NOT NULL THEN import_price * seconds * fraction ELSE 0 END)
                / NULLIF(SUM(CASE WHEN import_price IS NOT NULL THEN seconds * fraction ELSE 0 END), 0)
                AS avg_import_price,
              SUM(CASE WHEN export_price IS NOT NULL THEN export_price * seconds * fraction ELSE 0 END)
                / NULLIF(SUM(CASE WHEN export_price IS NOT NULL THEN seconds * fraction ELSE 0 END), 0)
                AS avg_export_price,
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

        # Preserve known financial subtotals before complete-period fields are
        # intentionally nulled below. SQLite SUM ignores NULL values, so these
        # values represent only ledger rows for which the relevant amount is known.
        result["known_import_cost"] = result.get("import_cost")
        result["known_export_revenue"] = result.get("export_revenue")
        result["known_pv_value"] = result.get("pv_value")
        result["known_battery_profit"] = result.get("battery_profit")

        # Fixed costs are deterministic even when an energy price is missing.
        # Include them in the known net subtotal so the UI can show useful partial
        # information without presenting it as a final invoice amount.
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
        return await self._async_run(self._period_summary, start, end)

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

    def _chart_series(
        self,
        start: str,
        end: str,
        granularity: str = "auto",
        tz_name: str = "UTC",
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

        rows: list[dict[str, Any]] = []
        for bucket_start, bucket_end in buckets:
            summary = self._period_summary(
                bucket_start.isoformat(), bucket_end.isoformat()
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
                    "import_price": summary.get("avg_import_price"),
                    "export_price": summary.get("avg_export_price"),
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

        return {
            "start": start_dt.isoformat(),
            "end": end_dt.isoformat(),
            "granularity": selected,
            "timezone": tz_name,
            "rows": rows,
        }

    async def async_chart_series(
        self,
        start: str,
        end: str,
        granularity: str = "auto",
        tz_name: str = "UTC",
    ) -> dict[str, Any]:
        return await self._async_run(
            self._chart_series, start, end, granularity, tz_name
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
