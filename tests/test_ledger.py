from pathlib import Path
import importlib.util
import sys
import sqlite3

MODULE = Path(__file__).parents[1] / "custom_components" / "energy_cost_tracker" / "ledger.py"
spec = importlib.util.spec_from_file_location("ect_ledger", MODULE)
mod = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


def test_counter_reset_starts_new_segment(tmp_path):
    ledger = mod.Ledger(None, tmp_path / "ledger.db")
    ledger._initialize()
    first = ledger._observe_source("grid_import", "sensor.grid", 100.0, "2026-08-20T10:00:00+00:00")
    assert first["delta"] == 0.0
    normal = ledger._observe_source("grid_import", "sensor.grid", 100.5, "2026-08-20T10:01:00+00:00")
    assert normal["delta"] == 0.5
    reset = ledger._observe_source("grid_import", "sensor.grid", 0.2, "2026-08-20T10:02:00+00:00")
    assert reset["event"] == "counter_reset"
    assert reset["delta"] == 0.2


def test_negative_correction_is_not_huge_energy(tmp_path):
    ledger = mod.Ledger(None, tmp_path / "ledger.db")
    ledger._initialize()
    ledger._observe_source("grid_import", "sensor.grid", 100.0, "2026-08-20T10:00:00+00:00")
    corrected = ledger._observe_source("grid_import", "sensor.grid", 98.0, "2026-08-20T10:01:00+00:00")
    assert corrected["event"] == "negative_correction"
    assert corrected["delta"] == 0.0


def test_entity_replacement_sets_new_baseline(tmp_path):
    ledger = mod.Ledger(None, tmp_path / "ledger.db")
    ledger._initialize()
    ledger._observe_source("grid_import", "sensor.old", 12345.0, "2026-08-20T10:00:00+00:00")
    changed = ledger._observe_source("grid_import", "sensor.new", 321.0, "2026-08-20T10:01:00+00:00")
    assert changed["event"] == "source_changed"
    assert changed["delta"] == 0.0
    next_value = ledger._observe_source("grid_import", "sensor.new", 321.4, "2026-08-20T10:02:00+00:00")
    assert round(next_value["delta"], 6) == 0.4


def test_period_summary_prorates_boundary_crossing_row(tmp_path):
    ledger = mod.Ledger(None, tmp_path / "ledger.db")
    ledger._initialize()
    ledger._insert_interval(
        {
            "start_ts": "2026-08-20T23:59:00+00:00",
            "end_ts": "2026-08-21T00:01:00+00:00",
            "seconds": 120.0,
            "grid_import_kwh": 2.0,
            "import_cost": 1.0,
            "export_revenue": 0.0,
            "fixed_cost": 0.2,
            "net_cost": 1.2,
            "quality": "estimated",
        }
    )
    first = ledger._period_summary(
        "2026-08-20T00:00:00+00:00", "2026-08-21T00:00:00+00:00"
    )
    second = ledger._period_summary(
        "2026-08-21T00:00:00+00:00", "2026-08-22T00:00:00+00:00"
    )
    assert round(first["grid_import_kwh"], 6) == 1.0
    assert round(second["grid_import_kwh"], 6) == 1.0
    assert round(first["net_cost"], 6) == 0.6
    assert round(second["net_cost"], 6) == 0.6


def test_incomplete_cost_summary_does_not_look_like_zero(tmp_path):
    ledger = mod.Ledger(None, tmp_path / "ledger.db")
    ledger._initialize()
    ledger._insert_interval(
        {
            "start_ts": "2026-08-20T10:00:00+00:00",
            "end_ts": "2026-08-20T10:01:00+00:00",
            "seconds": 60.0,
            "grid_import_kwh": 0.5,
            "import_cost": None,
            "export_revenue": 0.0,
            "fixed_cost": 0.01,
            "net_cost": None,
            "quality": "missing_price",
        }
    )
    summary = ledger._period_summary(None, None)
    assert summary["net_cost"] is None
    assert summary["import_cost"] is None
    assert summary["incomplete_cost_intervals"] == 1


def test_history_activity_filter(tmp_path):
    ledger = mod.Ledger(None, tmp_path / "ledger.db")
    ledger._initialize()
    for minute, pv, quality in [(0, 0.0, "exact"), (1, 1.0, "exact"), (2, 0.0, "estimated")]:
        ledger._insert_interval(
            {
                "start_ts": f"2026-08-20T10:0{minute}:00+00:00",
                "end_ts": f"2026-08-20T10:0{minute + 1}:00+00:00",
                "seconds": 60.0,
                "pv_production_kwh": pv,
                "fixed_cost": 0.0,
                "net_cost": 0.0,
                "quality": quality,
            }
        )
    pv_rows = ledger._query_intervals(None, None, None, "pv", 100, 0)
    issue_rows = ledger._query_intervals(None, None, None, "issues", 100, 0)
    assert pv_rows["total"] == 1
    assert issue_rows["total"] == 1


def test_small_counter_negative_correction_is_not_reset(tmp_path):
    ledger = mod.Ledger(None, tmp_path / "ledger.db")
    ledger._initialize()
    ledger._observe_source("daily_meter", "sensor.daily", 0.5, "2026-08-20T10:00:00+00:00")
    corrected = ledger._observe_source("daily_meter", "sensor.daily", 0.4, "2026-08-20T10:01:00+00:00")
    assert corrected["event"] == "negative_correction"
    assert corrected["delta"] == 0.0


def test_incomplete_period_keeps_known_subtotals(tmp_path):
    ledger = mod.Ledger(None, tmp_path / "ledger.db")
    ledger._initialize()

    ledger._insert_interval(
        {
            "start_ts": "2026-08-25T16:00:00+00:00",
            "end_ts": "2026-08-25T16:01:00+00:00",
            "seconds": 60.0,
            "grid_export_kwh": 0.1,
            "pv_production_kwh": 0.1,
            "import_cost": 0.0,
            "export_revenue": None,
            "fixed_cost": 0.01,
            "net_cost": None,
            "pv_value": None,
            "quality": "missing_price",
        }
    )
    ledger._insert_interval(
        {
            "start_ts": "2026-08-25T16:01:00+00:00",
            "end_ts": "2026-08-25T16:02:00+00:00",
            "seconds": 60.0,
            "grid_import_kwh": 0.2,
            "pv_production_kwh": 0.1,
            "import_cost": 0.05,
            "export_revenue": 0.0,
            "fixed_cost": 0.01,
            "net_cost": 0.06,
            "pv_value": 0.03,
            "quality": "exact",
        }
    )

    summary = ledger._period_summary(None, None)

    assert summary["net_cost"] is None
    assert summary["pv_value"] is None
    assert summary["known_import_cost"] == 0.05
    assert summary["known_export_revenue"] == 0.0
    assert summary["known_pv_value"] == 0.03
    assert round(summary["known_net_cost"], 6) == 0.07
    assert summary["incomplete_cost_intervals"] == 1
    assert summary["incomplete_pv_intervals"] == 1
    assert summary["financial_complete"] is False
    assert summary["pv_complete"] is False


def test_chart_auto_granularity_drills_down_with_range():
    from datetime import datetime, timezone

    start = datetime(2026, 8, 1, tzinfo=timezone.utc)
    assert mod.Ledger._chart_granularity(start, datetime(2026, 8, 31, tzinfo=timezone.utc), "auto") == "day"
    assert mod.Ledger._chart_granularity(start, datetime(2026, 8, 2, tzinfo=timezone.utc), "auto") == "hour"
    assert mod.Ledger._chart_granularity(start, datetime(2026, 8, 1, 2, tzinfo=timezone.utc), "auto") == "quarter"


def test_chart_series_returns_quarter_financial_buckets(tmp_path):
    ledger = mod.Ledger(None, tmp_path / "ledger.db")
    ledger._initialize()
    ledger._insert_interval(
        {
            "start_ts": "2026-08-25T16:00:00+00:00",
            "end_ts": "2026-08-25T16:15:00+00:00",
            "seconds": 900.0,
            "grid_import_kwh": 0.5,
            "pv_production_kwh": 0.25,
            "import_cost": 0.15,
            "export_revenue": 0.0,
            "fixed_cost": 0.01,
            "net_cost": 0.16,
            "pv_value": 0.08,
            "battery_profit": 0.02,
            "quality": "exact",
        }
    )
    ledger._insert_interval(
        {
            "start_ts": "2026-08-25T16:15:00+00:00",
            "end_ts": "2026-08-25T16:30:00+00:00",
            "seconds": 900.0,
            "grid_export_kwh": 0.4,
            "pv_production_kwh": 0.5,
            "import_cost": 0.0,
            "export_revenue": None,
            "fixed_cost": 0.01,
            "net_cost": None,
            "pv_value": None,
            "battery_profit": 0.0,
            "quality": "missing_price",
        }
    )

    result = ledger._chart_series(
        "2026-08-25T16:00:00+00:00",
        "2026-08-25T16:30:00+00:00",
        "quarter",
        "Europe/Amsterdam",
    )

    assert result["granularity"] == "quarter"
    assert len(result["rows"]) == 2
    first, second = result["rows"]
    assert round(first["net_cost"], 6) == 0.16
    assert round(first["pv_value"], 6) == 0.08
    assert round(first["battery_profit"], 6) == 0.02
    assert first["financial_complete"] is True
    assert round(second["net_cost"], 6) == 0.01
    assert second["financial_complete"] is False
    assert second["pv_complete"] is False


def test_prepare_backup_removes_wal_sidecars_and_preserves_data(tmp_path):
    ledger = mod.Ledger(None, tmp_path / "ledger.db")
    ledger._initialize()
    ledger._insert_interval(
        {
            "start_ts": "2026-08-28T04:00:00+00:00",
            "end_ts": "2026-08-28T04:01:00+00:00",
            "seconds": 60.0,
            "grid_import_kwh": 0.1,
            "import_cost": 0.03,
            "export_revenue": 0.0,
            "fixed_cost": 0.0,
            "net_cost": 0.03,
            "quality": "exact",
        }
    )

    # Exercise a normal WAL connection before backup preparation.
    conn = ledger._connect()
    conn.execute("SELECT 1").fetchone()
    conn.close()

    ledger._prepare_backup()

    assert ledger.path.exists()
    assert not Path(f"{ledger.path}-wal").exists()
    assert not Path(f"{ledger.path}-shm").exists()

    with sqlite3.connect(ledger.path) as verify:
        assert verify.execute("PRAGMA journal_mode").fetchone()[0].lower() == "delete"
        assert verify.execute("SELECT COUNT(*) FROM ledger").fetchone()[0] == 1


def test_normal_connection_can_restore_wal_after_backup(tmp_path):
    ledger = mod.Ledger(None, tmp_path / "ledger.db")
    ledger._initialize()
    ledger._prepare_backup()

    with ledger._connect() as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"


def test_ledger_operations_close_sqlite_connections(tmp_path):
    ledger = mod.Ledger(None, tmp_path / "ledger.db")
    ledger._initialize()
    ledger._set_meta("test", "value")
    assert ledger._get_meta("test") == "value"

    # WAL sidecars may exist while a connection is open, but all ledger helpers
    # must close their connection before returning. Otherwise Home Assistant can
    # enumerate a transient -shm file and then fail when it disappears mid-backup.
    assert not Path(f"{ledger.path}-wal").exists()
    assert not Path(f"{ledger.path}-shm").exists()


def test_async_backup_barrier_blocks_database_access(tmp_path):
    import asyncio

    class FakeHass:
        async def async_add_executor_job(self, func, *args):
            return await asyncio.to_thread(func, *args)

    async def scenario():
        ledger = mod.Ledger(FakeHass(), tmp_path / "ledger.db")
        await ledger.async_initialize()
        await ledger.async_set_meta("before_backup", "ok")

        await ledger.async_prepare_backup()
        pending_read = asyncio.create_task(ledger.async_get_meta("before_backup"))
        await asyncio.sleep(0.02)
        assert not pending_read.done()

        await ledger.async_finish_backup()
        assert await asyncio.wait_for(pending_read, timeout=1) == "ok"

    asyncio.run(scenario())
