# Changelog

All notable changes to Energy Cost Tracker are documented in this file.

The project follows [Semantic Versioning](https://semver.org/). While the integration is in the `0.x` series, configuration and ledger migrations may still change between releases.

## [Unreleased]

### Planned
- Explicit irregular first/last supplier billing periods.
- Named fixed-cost line items instead of aggregate daily/monthly/yearly fields.
- Historical backfill tooling.
- Independent multi-battery accounting.
- Richer charts and drill-down views in the sidebar panel.

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
