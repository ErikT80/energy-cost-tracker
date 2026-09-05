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
            "pv_direct_kwh": 0.15,
            "pv_export_kwh": 0.05,
            "pv_to_battery_kwh": 0.05,
            "battery_charge_kwh": 0.05,
            "battery_discharge_kwh": 0.02,
            "battery_charge_cost": 0.01,
            "battery_discharge_value": 0.008,
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
    assert round(first["pv_production_kwh"], 6) == 0.25
    assert round(first["pv_direct_kwh"], 6) == 0.15
    assert round(first["pv_export_kwh"], 6) == 0.05
    assert round(first["pv_to_battery_kwh"], 6) == 0.05
    assert round(first["battery_charge_kwh"], 6) == 0.05
    assert round(first["battery_discharge_kwh"], 6) == 0.02
    assert round(first["battery_charge_cost"], 6) == 0.01
    assert round(first["battery_discharge_value"], 6) == 0.008
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


def test_chart_series_exposes_energy_weighted_effective_prices(tmp_path):
    ledger = mod.Ledger(None, tmp_path / "ledger.db")
    ledger._initialize()
    ledger._insert_interval(
        {
            "start_ts": "2026-08-28T08:00:00+00:00",
            "end_ts": "2026-08-28T08:05:00+00:00",
            "seconds": 300.0,
            "grid_import_kwh": 0.1,
            "grid_export_kwh": 0.05,
            "import_price": 0.20,
            "export_price": 0.10,
            "import_cost": 0.02,
            "export_revenue": 0.005,
            "fixed_cost": 0.0,
            "net_cost": 0.015,
            "quality": "exact",
        }
    )
    ledger._insert_interval(
        {
            "start_ts": "2026-08-28T08:05:00+00:00",
            "end_ts": "2026-08-28T08:15:00+00:00",
            "seconds": 600.0,
            "grid_import_kwh": 0.2,
            "grid_export_kwh": 0.15,
            "import_price": 0.35,
            "export_price": 0.25,
            "import_cost": 0.07,
            "export_revenue": 0.0375,
            "fixed_cost": 0.0,
            "net_cost": 0.0325,
            "quality": "exact",
        }
    )

    result = ledger._chart_series(
        "2026-08-28T08:00:00+00:00",
        "2026-08-28T08:15:00+00:00",
        "quarter",
        "Europe/Amsterdam",
    )

    assert len(result["rows"]) == 1
    row = result["rows"][0]
    assert round(row["import_price"], 6) == 0.30
    assert round(row["export_price"], 6) == 0.2125
    # Chart tariff lines are time/tariff based rather than consumption weighted.
    assert round(row["import_tariff_price"], 6) == 0.30
    assert round(row["export_tariff_price"], 6) == 0.20
    assert round(result["averages"]["import_price"], 6) == 0.30
    assert round(result["averages"]["export_price"], 6) == 0.2125


def test_chart_detail_lines_keep_native_interval_prices(tmp_path):
    ledger = mod.Ledger(None, tmp_path / "ledger.db")
    ledger._initialize()
    for idx, price in enumerate((0.10, 0.20, 0.30, 0.40)):
        minute = idx * 15
        ledger._insert_interval(
            {
                "start_ts": f"2026-08-28T10:{minute:02d}:00+00:00",
                "end_ts": f"2026-08-28T10:{minute + 15:02d}:00+00:00" if minute < 45 else "2026-08-28T11:00:00+00:00",
                "seconds": 900.0,
                "grid_import_kwh": 0.25,
                "import_price": price,
                "export_price": price / 2,
                "import_cost": 0.25 * price,
                "export_revenue": 0.0,
                "fixed_cost": 0.0,
                "net_cost": 0.25 * price,
                "quality": "exact",
            }
        )
    result = ledger._chart_series(
        "2026-08-28T10:00:00+00:00",
        "2026-08-28T11:00:00+00:00",
        "hour",
        "Europe/Amsterdam",
    )
    assert len(result["rows"]) == 1
    assert len(result["line_rows"]) == 4
    assert [round(row["import_tariff_price"], 2) for row in result["line_rows"]] == [0.10, 0.20, 0.30, 0.40]
    assert result["line_detail_available"] is True


def test_chart_averages_include_solar_and_battery_realized_values(tmp_path):
    ledger = mod.Ledger(None, tmp_path / "ledger.db")
    ledger._initialize()
    ledger._insert_interval(
        {
            "start_ts": "2026-08-28T09:00:00+00:00",
            "end_ts": "2026-08-28T09:15:00+00:00",
            "seconds": 900.0,
            "pv_production_kwh": 1.0,
            "pv_export_kwh": 0.4,
            "export_price": 0.10,
            "pv_value": 0.20,
            "battery_charge_kwh": 0.5,
            "battery_charge_cost": 0.05,
            "battery_discharge_kwh": 0.4,
            "battery_discharge_value": 0.12,
            "import_cost": 0.0,
            "export_revenue": 0.04,
            "fixed_cost": 0.0,
            "net_cost": -0.04,
            "battery_profit": 0.04,
            "quality": "exact",
        }
    )
    ledger._insert_interval(
        {
            "start_ts": "2026-08-28T09:15:00+00:00",
            "end_ts": "2026-08-28T09:30:00+00:00",
            "seconds": 900.0,
            "pv_production_kwh": 2.0,
            "pv_export_kwh": 0.5,
            "export_price": 0.20,
            "pv_value": 0.70,
            "battery_charge_kwh": 0.5,
            "battery_charge_cost": 0.15,
            "battery_discharge_kwh": 0.6,
            "battery_discharge_value": 0.24,
            "import_cost": 0.0,
            "export_revenue": 0.10,
            "fixed_cost": 0.0,
            "net_cost": -0.10,
            "battery_profit": 0.09,
            "quality": "exact",
        }
    )

    result = ledger._chart_series(
        "2026-08-28T09:00:00+00:00",
        "2026-08-28T09:30:00+00:00",
        "quarter",
        "Europe/Amsterdam",
    )
    avg = result["averages"]
    first, second = result["rows"]
    assert round(first["pv_value_per_kwh"], 6) == 0.20
    assert round(first["pv_export_price"], 6) == 0.10
    assert round(first["battery_charge_cost_per_kwh"], 6) == 0.10
    assert round(first["battery_discharge_value_per_kwh"], 6) == 0.30
    assert round(second["pv_value_per_kwh"], 6) == 0.35
    assert round(second["pv_export_price"], 6) == 0.20
    assert round(second["battery_charge_cost_per_kwh"], 6) == 0.30
    assert round(second["battery_discharge_value_per_kwh"], 6) == 0.40
    assert round(avg["pv_value_per_kwh"], 6) == 0.3
    assert round(avg["pv_export_price"], 6) == round(0.14 / 0.9, 6)
    assert round(avg["battery_charge_cost_per_kwh"], 6) == 0.2
    assert round(avg["battery_discharge_value_per_kwh"], 6) == 0.36


def test_effective_average_ignores_unpriced_energy(tmp_path):
    ledger = mod.Ledger(None, tmp_path / "ledger.db")
    ledger._initialize()
    ledger._insert_interval(
        {
            "start_ts": "2026-08-28T10:00:00+00:00",
            "end_ts": "2026-08-28T10:15:00+00:00",
            "seconds": 900.0,
            "grid_import_kwh": 1.0,
            "import_price": 0.25,
            "import_cost": 0.25,
            "export_revenue": 0.0,
            "fixed_cost": 0.0,
            "net_cost": 0.25,
            "quality": "exact",
        }
    )
    ledger._insert_interval(
        {
            "start_ts": "2026-08-28T10:15:00+00:00",
            "end_ts": "2026-08-28T10:30:00+00:00",
            "seconds": 900.0,
            "grid_import_kwh": 2.0,
            "import_price": None,
            "import_cost": None,
            "export_revenue": 0.0,
            "fixed_cost": 0.0,
            "net_cost": None,
            "quality": "missing_price",
        }
    )
    summary = ledger._period_summary(None, None)
    assert round(summary["grid_import_kwh"], 6) == 3.0
    assert round(summary["priced_import_kwh"], 6) == 1.0
    assert summary["avg_import_price"] == 0.25


def test_period_summary_includes_uncommitted_pending_row(tmp_path):
    ledger = mod.Ledger(None, tmp_path / "ledger.db")
    ledger._initialize()
    ledger._insert_interval(
        {
            "start_ts": "2026-08-29T10:00:00+00:00",
            "end_ts": "2026-08-29T10:15:00+00:00",
            "seconds": 900.0,
            "grid_import_kwh": 1.0,
            "import_price": 0.20,
            "import_cost": 0.20,
            "export_revenue": 0.0,
            "fixed_cost": 0.0,
            "net_cost": 0.20,
            "quality": "exact",
        }
    )
    pending = {
        "start_ts": "2026-08-29T10:15:00+00:00",
        "end_ts": "2026-08-29T10:20:00+00:00",
        "seconds": 300.0,
        "grid_import_kwh": 0.5,
        "grid_export_kwh": 0.0,
        "house_consumption_kwh": 0.5,
        "pv_production_kwh": 0.0,
        "battery_charge_kwh": 0.0,
        "battery_discharge_kwh": 0.0,
        "import_price": 0.30,
        "export_price": 0.10,
        "import_cost": 0.15,
        "export_revenue": 0.0,
        "fixed_cost": 0.0,
        "net_cost": 0.15,
        "pv_value": 0.0,
        "battery_charge_cost": 0.0,
        "battery_discharge_value": 0.0,
        "battery_discharge_cost_basis": 0.0,
        "battery_profit": 0.0,
        "battery_loss_cost": 0.0,
        "quality": "exact",
    }
    summary = ledger._period_summary(None, None, pending)
    assert round(summary["grid_import_kwh"], 6) == 1.5
    assert round(summary["net_cost"], 6) == 0.35
    assert summary["intervals"] == 2
    assert round(summary["avg_import_price"], 6) == round(0.35 / 1.5, 6)


def test_commit_pending_interval_clears_checkpoint_atomically(tmp_path):
    ledger = mod.Ledger(None, tmp_path / "ledger.db")
    ledger._initialize()
    ledger._set_meta("pending_interval", '{"pending":true}')
    ledger._commit_pending_interval(
        {
            "start_ts": "2026-08-29T10:00:00+00:00",
            "end_ts": "2026-08-29T10:15:00+00:00",
            "seconds": 900.0,
            "grid_import_kwh": 0.1,
            "import_cost": 0.02,
            "export_revenue": 0.0,
            "fixed_cost": 0.0,
            "net_cost": 0.02,
            "quality": "exact",
        }
    )
    assert ledger._get_meta("pending_interval") is None
    with sqlite3.connect(ledger.path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM ledger").fetchone()[0] == 1


def test_multiple_battery_sources_keep_independent_baselines(tmp_path):
    ledger = mod.Ledger(None, tmp_path / "ledger.db")
    ledger._initialize()
    ledger._observe_source("battery_charge:sensor.battery_a_charge", "sensor.battery_a_charge", 10.0, "2026-08-29T20:00:00+00:00")
    ledger._observe_source("battery_charge:sensor.battery_b_charge", "sensor.battery_b_charge", 20.0, "2026-08-29T20:00:00+00:00")
    a = ledger._observe_source("battery_charge:sensor.battery_a_charge", "sensor.battery_a_charge", 10.3, "2026-08-29T20:01:00+00:00")
    b = ledger._observe_source("battery_charge:sensor.battery_b_charge", "sensor.battery_b_charge", 20.4, "2026-08-29T20:01:00+00:00")
    assert round(a["delta"] + b["delta"], 6) == 0.7


def test_manual_battery_empty_event_is_auditable(tmp_path):
    ledger = mod.Ledger(None, tmp_path / "ledger.db")
    ledger._initialize()
    ledger._add_event(
        "2026-08-30T04:00:00+00:00",
        "battery_manual_empty",
        "battery_inventory",
        {"discarded_virtual_energy_kwh": 0.4},
    )
    events = ledger._recent_events(10)
    assert events[0]["event_type"] == "battery_manual_empty"
    assert events[0]["source_key"] == "battery_inventory"
    assert '0.4' in events[0]["details"]


def test_controlled_fixed_cost_update_only_changes_fixed_and_net(tmp_path):
    ledger = mod.Ledger(None, tmp_path / "ledger.db")
    ledger._initialize()
    row_id = ledger._insert_interval(
        {
            "start_ts": "2026-08-20T10:00:00+00:00",
            "end_ts": "2026-08-20T10:15:00+00:00",
            "seconds": 900.0,
            "grid_import_kwh": 1.25,
            "pv_production_kwh": 0.7,
            "import_cost": 0.30,
            "export_revenue": 0.05,
            "fixed_cost": 0.01,
            "net_cost": 0.26,
            "pv_value": 0.16,
            "battery_profit": 0.04,
            "quality": "exact",
        }
    )
    changed = ledger._apply_fixed_cost_updates(
        [(0.02, 0.27, row_id)], {"profiles": [{"effective_from": "2026-08-20"}]}
    )
    assert changed == 1
    row = ledger._query_intervals(None, None, None, None, 10, 0)["rows"][0]
    assert row["fixed_cost"] == 0.02
    assert row["net_cost"] == 0.27
    assert row["grid_import_kwh"] == 1.25
    assert row["pv_value"] == 0.16
    assert row["battery_profit"] == 0.04
    events = ledger._recent_events(5)
    assert events[0]["event_type"] == "fixed_cost_schedule_recalculated"


def test_interval_bounds_returns_only_overlapping_rows(tmp_path):
    ledger = mod.Ledger(None, tmp_path / "ledger.db")
    ledger._initialize()
    for hour in (9, 10, 11):
        ledger._insert_interval(
            {
                "start_ts": f"2026-08-20T{hour:02d}:00:00+00:00",
                "end_ts": f"2026-08-20T{hour + 1:02d}:00:00+00:00",
                "seconds": 3600.0,
                "fixed_cost": 0.0,
                "net_cost": 0.0,
                "quality": "exact",
            }
        )
    rows = ledger._interval_bounds("2026-08-20T09:30:00+00:00", "2026-08-20T11:00:00+00:00")
    assert len(rows) == 2
    assert rows[0]["start_ts"].startswith("2026-08-20T09:00")
    assert rows[1]["start_ts"].startswith("2026-08-20T10:00")


def test_chart_tariff_rows_keep_all_exact_prices_through_end_of_range(tmp_path):
    ledger = mod.Ledger(None, tmp_path / "ledger.db")
    ledger._initialize()
    prices = [0.31, 0.32, 0.33, 0.34, 0.35, 0.36]
    for idx, price in enumerate(prices):
        minute = idx * 15
        hour = 17 + minute // 60
        mm = minute % 60
        end_minute = minute + 15
        end_hour = 17 + end_minute // 60
        end_mm = end_minute % 60
        ledger._insert_interval({
            "start_ts": f"2026-09-02T{hour:02d}:{mm:02d}:00+00:00",
            "end_ts": f"2026-09-02T{end_hour:02d}:{end_mm:02d}:00+00:00",
            "seconds": 900.0,
            "grid_import_kwh": 0.1,
            "grid_export_kwh": 0.2,
            "import_price": price,
            "export_price": price / 2,
            "import_cost": 0.1 * price,
            "export_revenue": 0.2 * price / 2,
            "fixed_cost": 0.0,
            "net_cost": 0.0,
            "quality": "exact",
        })
    result = ledger._chart_series(
        "2026-09-02T17:00:00+00:00",
        "2026-09-02T19:00:00+00:00",
        "quarter",
        "Europe/Amsterdam",
    )
    assert result["tariff_detail_available"] is True
    assert len(result["tariff_rows"]) == len(prices)
    assert [round(row["import_price"], 2) for row in result["tariff_rows"]] == prices
    assert round(result["tariff_rows"][-1]["export_price"], 3) == round(prices[-1] / 2, 3)


def test_chart_price_rows_follow_bucket_granularity(tmp_path):
    ledger = mod.Ledger(None, tmp_path / "ledger.db")
    ledger._initialize()
    # Four quarter-hours in one hour with deliberately unequal energy volumes.
    # The visible hourly line must be the realized, energy-weighted price for
    # that hour, not four native tariff points and not a simple mean.
    imports = [1.0, 2.0, 1.0, 0.5]
    exports = [0.5, 0.0, 1.5, 1.0]
    prices = [0.10, 0.20, 0.40, 0.60]
    export_prices = [0.05, 0.10, 0.20, 0.30]
    for idx in range(4):
        minute = idx * 15
        end = minute + 15
        ledger._insert_interval({
            "start_ts": f"2026-09-02T10:{minute:02d}:00+00:00",
            "end_ts": "2026-09-02T11:00:00+00:00" if end == 60 else f"2026-09-02T10:{end:02d}:00+00:00",
            "seconds": 900.0,
            "grid_import_kwh": imports[idx],
            "grid_export_kwh": exports[idx],
            "import_price": prices[idx],
            "export_price": export_prices[idx],
            "import_cost": imports[idx] * prices[idx],
            "export_revenue": exports[idx] * export_prices[idx],
            "fixed_cost": 0.0,
            "net_cost": imports[idx] * prices[idx] - exports[idx] * export_prices[idx],
            "quality": "exact",
        })

    result = ledger._chart_series(
        "2026-09-02T10:00:00+00:00",
        "2026-09-02T11:00:00+00:00",
        "hour",
        "UTC",
    )
    assert len(result["rows"]) == 1
    row = result["rows"][0]
    expected_import = sum(e * p for e, p in zip(imports, prices)) / sum(imports)
    expected_export = sum(e * p for e, p in zip(exports, export_prices)) / sum(exports)
    assert round(row["import_price"], 9) == round(expected_import, 9)
    assert round(row["export_price"], 9) == round(expected_export, 9)


def test_chart_tariff_bucket_is_independent_from_realized_import_weighting(tmp_path):
    ledger = mod.Ledger(None, tmp_path / "ledger.db")
    ledger._initialize()
    prices = (0.10, 0.20, 0.30, 0.40)
    imports = (0.10, 0.10, 0.10, 0.70)
    for idx, (price, imported) in enumerate(zip(prices, imports, strict=True)):
        start_minute = idx * 15
        end_minute = (idx + 1) * 15
        start = f"2026-08-28T17:{start_minute:02d}:00+00:00"
        end = (
            f"2026-08-28T17:{end_minute:02d}:00+00:00"
            if end_minute < 60
            else "2026-08-28T18:00:00+00:00"
        )
        ledger._insert_interval(
            {
                "start_ts": start,
                "end_ts": end,
                "seconds": 900.0,
                "grid_import_kwh": imported,
                "grid_export_kwh": 0.0,
                "import_price": price,
                "export_price": 0.05,
                "import_cost": imported * price,
                "export_revenue": 0.0,
                "fixed_cost": 0.0,
                "net_cost": imported * price,
                "quality": "exact",
            }
        )

    result = ledger._chart_series(
        "2026-08-28T17:00:00+00:00",
        "2026-08-28T18:00:00+00:00",
        "hour",
        "UTC",
    )
    row = result["rows"][0]
    # Graph tariff line: mean tariff over time, independent from imported volume.
    assert round(row["import_tariff_price"], 6) == 0.25
    # Period KPI: actual price paid, weighted by the imported kWh.
    assert round(result["averages"]["import_price"], 6) == 0.34


def test_solar_and_battery_period_kpis_are_weighted_by_actual_activity(tmp_path):
    ledger = mod.Ledger(None, tmp_path / "ledger.db")
    ledger._initialize()
    rows = [
        {
            "start_ts": "2026-08-28T10:00:00+00:00",
            "end_ts": "2026-08-28T10:15:00+00:00",
            "seconds": 900.0,
            "pv_production_kwh": 1.0,
            "pv_export_kwh": 0.25,
            "export_price": 0.10,
            "pv_value": 0.15,
            "battery_charge_kwh": 0.25,
            "battery_charge_cost": 0.025,
            "battery_discharge_kwh": 0.25,
            "battery_discharge_value": 0.05,
            "import_cost": 0.0,
            "export_revenue": 0.025,
            "fixed_cost": 0.0,
            "net_cost": -0.025,
            "battery_profit": 0.025,
            "quality": "exact",
        },
        {
            "start_ts": "2026-08-28T10:15:00+00:00",
            "end_ts": "2026-08-28T10:30:00+00:00",
            "seconds": 900.0,
            "pv_production_kwh": 3.0,
            "pv_export_kwh": 1.0,
            "export_price": 0.30,
            "pv_value": 0.90,
            "battery_charge_kwh": 0.75,
            "battery_charge_cost": 0.225,
            "battery_discharge_kwh": 0.75,
            "battery_discharge_value": 0.30,
            "import_cost": 0.0,
            "export_revenue": 0.30,
            "fixed_cost": 0.0,
            "net_cost": -0.30,
            "battery_profit": 0.075,
            "quality": "exact",
        },
    ]
    for row in rows:
        ledger._insert_interval(row)
    result = ledger._chart_series(
        "2026-08-28T10:00:00+00:00",
        "2026-08-28T10:30:00+00:00",
        "quarter",
        "UTC",
    )
    averages = result["averages"]
    assert round(averages["pv_value_per_kwh"], 6) == round(1.05 / 4.0, 6)
    assert round(averages["pv_export_price"], 6) == round(0.325 / 1.25, 6)
    assert round(averages["battery_charge_cost_per_kwh"], 6) == round(0.25 / 1.0, 6)
    assert round(averages["battery_discharge_value_per_kwh"], 6) == round(0.35 / 1.0, 6)


def test_schema_v1_is_migrated_forward_without_losing_rows(tmp_path):
    path = tmp_path / "ledger.db"
    ledger = mod.Ledger(None, path)
    ledger._initialize()
    ledger._insert_interval(
        {
            "start_ts": "2026-08-20T10:00:00+00:00",
            "end_ts": "2026-08-20T10:15:00+00:00",
            "seconds": 900.0,
            "grid_import_kwh": 0.25,
            "import_cost": 0.05,
            "export_revenue": 0.0,
            "fixed_cost": 0.01,
            "net_cost": 0.06,
            "quality": "exact",
        }
    )
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE meta SET value='1' WHERE key='schema_version'")
        conn.commit()

    ledger._initialize()

    with sqlite3.connect(path) as conn:
        version = conn.execute(
            "SELECT value FROM meta WHERE key='schema_version'"
        ).fetchone()[0]
        count = conn.execute("SELECT COUNT(*) FROM ledger").fetchone()[0]
    assert version == str(mod.SCHEMA_VERSION)
    assert count == 1


def test_newer_schema_is_refused(tmp_path):
    path = tmp_path / "ledger.db"
    ledger = mod.Ledger(None, path)
    ledger._initialize()
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE meta SET value='999' WHERE key='schema_version'")
        conn.commit()

    try:
        ledger._initialize()
    except RuntimeError as err:
        assert "newer" in str(err)
    else:
        raise AssertionError("newer database schema must not be opened")


def test_existing_unversioned_ledger_is_refused(tmp_path):
    path = tmp_path / "ledger.db"
    ledger = mod.Ledger(None, path)
    ledger._initialize()
    ledger._insert_interval(
        {
            "start_ts": "2026-08-20T10:00:00+00:00",
            "end_ts": "2026-08-20T10:15:00+00:00",
            "seconds": 900.0,
            "fixed_cost": 0.0,
            "net_cost": 0.0,
            "quality": "exact",
        }
    )
    with sqlite3.connect(path) as conn:
        conn.execute("DELETE FROM meta WHERE key='schema_version'")
        conn.commit()

    try:
        ledger._initialize()
    except RuntimeError as err:
        assert "no schema version" in str(err)
    else:
        raise AssertionError("existing unversioned ledger must not be guessed")
