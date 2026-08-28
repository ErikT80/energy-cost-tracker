# Changelog

All notable changes to Energy Cost Tracker are documented in this file.

The project follows [Semantic Versioning](https://semver.org/). While the integration is in the `0.x` series, configuration and ledger migrations may still change between releases.

## [Unreleased]

### Planned
- Explicit irregular first/last supplier billing periods.
- Named fixed-cost line items instead of aggregate daily/monthly/yearly fields.
- Historical backfill tooling.
- Independent multi-battery accounting.

## [0.1.0-alpha.5] - 2026-08-28

### Fixed
- Fixed Home Assistant backups failing when the SQLite `-shm` sidecar disappeared while the backup archive was being created.
- SQLite ledger helpers now explicitly close every connection; the previous transaction context manager committed correctly but did not itself close the connection.
- Added Home Assistant pre/post backup hooks that pause accounting, checkpoint WAL data and hold a database barrier for the duration of the backup.
- Energy accumulated while a backup runs is processed immediately after backup completion and is marked estimated when the gap is too long for exact interval attribution.

## [0.1.0-alpha.4] - 2026-08-27

### Added
- Interactive financial timeline on the Overview sidebar page.
- Default month-to-date chart with automatic day, hour and quarter-hour aggregation.
- Drill-down by tapping chart buckets, desktop wheel/drag zoom, zoom buttons and period navigation.
- Chart series for net energy cost, PV financial value and battery profit.
- Dedicated WebSocket chart endpoint that aggregates ledger data server-side for responsive mobile use.
- Incomplete ledger buckets remain visibly marked while known subtotals can still be graphed.

## [0.1.0-alpha.3] - 2026-08-27

### Changed
- Incomplete periods now expose known financial subtotals while keeping final invoice totals unknown.
- Sidebar overview, costs, solar and battery pages clearly mark partial values with missing-price warnings.
- Period sensor attributes expose incomplete-price counts and known subtotals for diagnostics and automations.

## [0.1.0-alpha.2] - 2026-08-25

### Fixed
- Fixed Config Flow number selector precision for Home Assistant versions that reject numeric steps below 0.001.
- Fixed CI dependency caching and hassfest manifest/config-entry-only validation.

## [0.1.0-alpha.1] - 2026-08-20

### Added
- UI-only Config Flow for grid, PV, battery, dynamic prices and billing settings.
- Persistent SQLite financial ledger.
- Cumulative-meter reset, rollover and entity-replacement handling.
- Data-quality labels for exact, reconstructed, estimated and incomplete intervals.
- Dynamic import/export tariff accounting, including negative prices.
- Fixed daily, monthly and annual charges plus annual rebate.
- Calendar and supplier billing periods.
- PV self-consumption, export and battery opportunity-cost valuation.
- Weighted-average battery inventory cost basis with solar/grid attribution.
- Sidebar panel with overview and searchable history.
- Diagnostics support.
- Dutch and English translations.
- HACS, hassfest and unit-test GitHub Actions.
