# Testing

Energy Cost Tracker uses a layered test strategy so pure accounting remains fast while Home Assistant API compatibility is checked in CI.

## Local fast checks

```bash
python -m pip install -r requirements-test.txt
python -m pytest -q
python -m compileall -q custom_components/energy_cost_tracker
node --check custom_components/energy_cost_tracker/frontend/energy-cost-tracker-panel.js
```

The pure test suite covers accounting, source reset/replacement behavior, fixed-cost schedules, chart aggregation, billing periods, SQLite backup behavior, schema migrations, config migration helpers, translation parity and release contracts.

## Home Assistant compatibility smoke test

CI installs both the minimum supported Home Assistant (`2026.8.0`) and the latest stable Home Assistant on Python 3.14, then imports all integration modules with:

```bash
python scripts/ha_import_smoke.py
```

This deliberately catches changed Home Assistant imports/APIs without making the fast local unit suite depend on the very large Home Assistant test environment.

Import smoke is not a replacement for real runtime tests. The release checklist therefore requires actual setup/reconfigure/backup/restore testing in Home Assistant before `v0.1.0`.

## Required regression coverage

Bug fixes should include a regression test whenever the behavior can be isolated. In particular, keep coverage for:

- incomplete/missing price periods and known subtotals;
- tariff aggregation versus realized average prices;
- sensor reset and replacement baselines;
- multiple PV/battery source normalization;
- fixed-cost effective-date repair;
- SQLite WAL backup handling;
- config/database forward migrations;
- frontend translation/touch interaction release contracts.

## Manual mobile checks

Before a release candidate or stable release, test at minimum:

- Android Home Assistant Companion app;
- iOS/iPadOS Safari or Home Assistant Companion app when available;
- horizontal chart swipe;
- one tap = persistent tooltip;
- second tap on the same bucket = drill-down;
- automatic focus for Year/Month/Day/Day 15 min;
- Solar daylight-window behavior.
