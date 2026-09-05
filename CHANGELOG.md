# Changelog

All notable changes to Energy Cost Tracker are documented in this file.

The project follows [Semantic Versioning](https://semver.org/). While the integration is in the `0.x` series, configuration and ledger migrations may still change between releases.

## [Unreleased]

## [0.1.0-rc.1] - 2026-09-03

### Fixed
- HA import smoke test now explicitly adds the repository root to `sys.path`, so `custom_components.energy_cost_tracker` can be imported when the script is executed from `scripts/` in GitHub Actions.

### Changed
- Froze the feature set for the first public release candidate and refreshed the README/documentation around current accounting, chart, access, backup and HACS behavior.
- Updated GitHub Actions to `actions/checkout@v7` and `actions/setup-python@v7`; CI now uses Python 3.14. Dependabot now groups GitHub Actions updates into one maintenance PR.
- Added CI import-smoke checks against both the minimum supported Home Assistant 2026.8.0 and latest stable Home Assistant.
- Added frontend JavaScript syntax, translation parity, packaging/version and release-contract checks.

### Added
- Added explicit forward-only Home Assistant config-entry migration support (v1 → v2), normalizing historical single/multiple PV and battery source fields without touching ledger history.
- Added explicit forward-only SQLite schema migrations (v1 → v2) and refusal of newer/unknown non-empty ledger schemas instead of silently guessing or downgrading them.
- Added a maintainer release checklist covering real backup/restore, invoice reconciliation, access control, mobile interaction and external release-candidate validation.
- Added dedicated testing documentation and a Home Assistant import-smoke script.

### Fixed
- Corrected architecture/documentation statements that implied every ledger field was immutable; dated fixed-cost repair is now explicitly documented as the only controlled historical rewrite and is limited to `fixed_cost`/`net_cost`.

## [0.1.0-alpha.33] - 2026-09-03

### Changed
- Solar Day and Day 15 min charts now focus on the daylight window: 30 minutes before historical sunrise through 30 minutes after historical sunset, rounded outward to whole hours using the Home Assistant location.
- All chart tabs and all views now auto-focus the horizontally scrollable chart on the relevant point in time: the current month/day/time for current periods, the anchor position for historical periods, and the selected bucket after drill-down.
- Switching between Overview, Solar and Battery restores the relevant temporal focus without affecting ordinary in-place re-renders or manual scrolling.
- Solar daylight cropping only affects visualization; accounting and period KPI calculations continue to use the complete ledger period.

## [0.1.0-alpha.32] - 2026-09-02

### Fixed
- Localized the Overview financial Y-axis title so English dashboards show `€ per period` instead of the hardcoded Dutch `€ per periode`.
- Restored reliable mobile/coarse-pointer chart interaction across Android WebViews: one tap pins the tooltip and a second tap on the same period drills down.
- Mobile tap handling no longer depends solely on `pointerType === "touch"`; narrow/coarse input and fallback click events are handled consistently while swipes remain native horizontal scrolling.

## [0.1.0-alpha.31] - 2026-09-02

### Changed
- Day chart X-axis labels now snap to fixed 3-hour clock boundaries instead of arbitrary evenly sampled timestamps.
- Day 15 min X-axis labels now snap to fixed 2-hour clock boundaries.
- The same clock-axis behavior is used consistently by Overview, Solar and Battery charts.

## [0.1.0-alpha.30] - 2026-09-02

### Changed
- Overview graph lines now show the time-weighted import/export tariff for each displayed chart bucket, independent of how much energy was actually imported or exported in that bucket.
- Overview line granularity remains aligned with the graph view: monthly tariff in Year, daily tariff in Month, hourly tariff in Day, and quarter-hour tariff in Day 15 min.
- Renamed Overview line labels to “Import tariff” / “Export tariff” to distinguish them from the realized average-price KPIs.
- The Overview KPIs remain action-weighted realized prices over the entire selected view (`import cost / priced import kWh` and `export revenue / priced export kWh`).
- Solar KPIs remain action-weighted by actual PV destinations: total PV value per valued produced kWh and actual PV export revenue per exported PV kWh.
- Battery KPIs remain action-weighted by actual battery activity: actual charge cost per charged kWh and actual discharge value per discharged kWh.
- Solar and Battery €-per-period graph lines remain unchanged.

## [0.1.0-alpha.29] - 2026-09-02

### Changed
- Overview import/export price lines now follow the selected chart granularity: monthly averages in Year, daily averages in Month, hourly averages in Day, and native quarter-hour prices in Day 15 min.
- Price-line values are realized energy-weighted prices (`cost / priced kWh` and `revenue / priced kWh`) for each displayed bucket.
- The period-average KPIs above the chart remain calculated across the entire selected visible period.
- Overview price-line legend and tooltip labels now use “Import price” / “Export price” rather than implying a native tariff at coarser granularities.
- Solar and Battery financial lines remain unchanged from their alpha.23-style €-per-period behavior.

## [0.1.0-alpha.28] - 2026-09-02

### Fixed
- Overview tariff lines now read `import_price` and `export_price` directly from every native ledger interval.
- Removed the synthetic live tariff segment from the chart; missing persisted prices now create an explicit gap instead of a potentially misleading continuation.
- Solar and Battery financial line toggles now remain available in every view, including Year.
- Added persisted import/export tariff columns to History for direct diagnostics.
- Added a regression test that verifies exact tariff points remain present through the end of the requested chart range.

## [0.1.0-alpha.27] - 2026-09-02

### Fixed
- Use one real time axis for bars, labels and tariff lines, so partial current months/days no longer spread only the available buckets across the entire chart.
- Position chart drill-down, tooltips and mobile auto-scroll on timestamps instead of array indexes.
- Extend the current import/export tariff line from the configured price entity's `last_changed` timestamp while its current state is valid; genuinely missing tariff history remains a visible gap instead of being guessed.

## [0.1.0-alpha.26] - 2026-09-02

### Changed
- Restored the Solar chart financial line from alpha.23: Solar value in EUR per chart period.
- Restored the Battery chart financial lines from alpha.23: charge cost, discharge value, and battery profit in EUR per chart period.
- Kept the period-wide effective average price/value KPIs above Solar and Battery charts from alpha.24/25.
- The Overview chart keeps the detailed actual import/export tariff lines introduced in alpha.25.

## [0.1.0-alpha.25] - 2026-09-02

### Changed
- Kept the period KPI values above charts as realized, energy-weighted averages.
- Changed Overview chart price lines back to tariff-based import/export prices so line shape no longer depends on how much energy was consumed or exported.
- For Month, Day and Day 15 min views, price/value lines now use the native ledger interval (normally 15-minute) values even when the bars are aggregated to days or hours.
- Detailed price/value lines are intentionally hidden in Year view to avoid rendering roughly 35,000 quarter-hour points; the realized period-average KPIs remain available.
- Changed Solar chart financial lines to solar value per kWh and actual solar export price per kWh.
- Changed Battery chart financial lines to charge cost price per kWh and discharge value per kWh; total battery profit remains available in KPI/tooltip data rather than sharing an incompatible per-kWh axis.
- Updated chart legends, secondary axes and tooltips to clearly distinguish period averages from native-interval tariff/value lines.

## [0.1.0-alpha.24] - 2026-09-02

### Added
- Added energy-weighted effective price KPIs for the complete visible chart period: actual average grid import price and grid export price.
- Added Solar chart KPIs for average value per produced solar kWh and average realized price per exported solar kWh.
- Added Battery chart KPIs for average charge cost per kWh and average discharge value per kWh.
- Chart responses now expose priced/valued energy coverage so averages with incomplete price history are clearly marked.

### Changed
- Overview import/export price lines now use realized energy-weighted prices per bucket instead of time-weighted tariff averages.
- Reworked the large cards below Overview, Solar and Battery charts into compact, ordered KPI strips: four columns on desktop and a two-column layout on mobile.
- Moved live power and battery inventory details into compact secondary rows and reduced the investment section to one progress row.


## [0.1.0-alpha.23] - 2026-08-31

### Changed
- Home Assistant PV and battery entities are now created only when the corresponding asset is currently configured; stale asset entities are removed from the entity registry after reconfiguration.
- Period monetary entities now expose the defensible known subtotal as their numeric state when price data is incomplete, with explicit completeness and data-quality attributes instead of remaining `unknown`.
- Solar and Battery sidebar tabs remain available when retained ledger history exists after the live asset configuration is removed.
- Historical Solar/Battery tabs now show an all-time summary and a compact retained-history notice while live-only inventory/power elements stay hidden.
- History filters and financial chart series remain available for retained PV/battery history.

## [0.1.0-alpha.22] - 2026-08-31

### Added
- Reworked the Costs tab into an invoice-reconciliation view for billing months and billing years.
- Added separate invoice rows for grid import energy/cost, grid export energy/revenue, daily/monthly/annual fixed costs, annual deductions, total fixed costs and total billing-period cost.
- Added previous/current/next navigation for billing periods.
- Billing-year view now includes clickable billing-month rows with import, export, fixed/deduction and total amounts.
- Added a fixed-cost component breakdown that uses the same dated fixed-cost schedule and proration logic as ledger accounting.

### Changed
- The previous general Costs table remains available as a collapsed Period overview below the invoice reconciliation.
- Incomplete price history is shown as known subtotals with an explicit invoice warning instead of being presented as definitive.

## [0.1.0-alpha.21] - 2026-08-31

### Added
- Added admin-managed per-user access to the Energy Cost Tracker side panel.
- Added an Access section in Settings where admins can whitelist regular Home Assistant users.

### Security
- All panel write WebSocket commands now require a Home Assistant admin user server-side.
- Read WebSocket commands now require either an admin user or an explicitly whitelisted regular user.
- New regular users do not see the panel by default; admins are always granted panel access.

### Changed
- Panel visibility is synchronized through Home Assistant's per-user frontend sidebar storage, including user creation and admin-role changes.
- The Settings tab is admin-only.

## [0.1.0-alpha.20] - 2026-08-31

### Added
- Dated fixed-cost profiles in the sidebar Settings tab. A complete daily/monthly/yearly/rebate profile can be entered now with a future effective date.
- Edit and delete controls for fixed-cost schedule rows.
- Automatic historical repair when a fixed-cost profile is added, edited or deleted with a date that affects existing ledger intervals.

### Changed
- Runtime fixed-cost accrual now selects the profile active on each local calendar date and switches automatically at local midnight.
- Historical fixed-cost repair only changes `fixed_cost` and dependent `net_cost`; measured energy, dynamic prices, PV value and battery accounting remain untouched.
- Fixed-cost changes after initial setup are managed from the sidebar Settings tab rather than the Home Assistant reconfigure form.

## [0.1.0-alpha.19] - 2026-08-30

### Changed
- Treat battery SOC exclusively as an optional technical helper for detecting an empty initial battery inventory.
- Removed SOC values/ranges from the sidebar dashboard and battery chart header.
- A configured SOC sensor no longer makes a battery system appear configured by itself.
- Clarified in the configuration flow that SOC is not used to calculate energy or battery profit.

### Added
- Added a guarded **Battery is empty now** action in Settings for systems without SOC while the initial battery cost basis is still unknown.
- Manual empty confirmation is persisted and audited in the integration event log; once the basis is known, the action can no longer erase it.

## [0.1.0-alpha.18] - 2026-08-29

### Added
- Native multi-battery input support for cumulative charge energy, cumulative discharge energy, live power and SOC sensors.
- Multiple battery sources are aggregated into one financial battery inventory/cost basis, matching the existing combined investment model.
- When multiple SOC sensors are configured, the panel shows the live SOC range instead of a potentially misleading unweighted average.

### Changed
- Reconfigure now accepts multiple battery entities while remaining backwards compatible with existing single-entity entries.
- Combined battery inventory is only reconciled as empty when every configured SOC sensor is available and below the empty threshold.

## [0.1.0-alpha.17] - 2026-08-29

### Added
- Added one optional aggregate investment amount for Solar and one for Battery in the central Settings tab.
- Solar and Battery pages now show the configured investment, the existing ledger-derived value/profit since tracking began, the percentage relative to the investment, and a compact progress bar.

### Design
- Investment amounts are stored as Home Assistant config-entry options and do not alter accounting profiles or historical ledger bookings.
- No payback-time or payback-date forecast is calculated, because Energy Cost Tracker may have been installed long after the physical system was commissioned.
- Investment progress reuses the existing `pv_value` and `battery_profit` definitions, preserving the existing no-double-counting model.

## [0.1.0-alpha.16] - 2026-08-29

### Added
- Added a central Settings tab for chart appearance; chart theme selection is no longer repeated above every chart.
- Added solar self-consumption percentage to the Solar period cards and chart tooltip. Self-consumption is calculated as direct PV use plus PV sent to the battery, divided by total PV production.

### Changed
- Increased visual differentiation between the Home Assistant, Electric, Ocean, Sunset, Forest and Monochrome chart palettes.
- Removed the long instructional text below the Overview, Solar and Battery charts.
- Removed the long explanatory Solar-value paragraph below the Solar cards.

## [0.1.0-alpha.15] - 2026-08-29

### Added
- Added interactive Year / Month / Day / Day 15 min charts to the Solar and Battery sidebar tabs, using the same navigation, mobile scrolling, persistent tooltips and drill-down behaviour as the Overview chart.
- Solar chart shows PV production, direct self-consumption, grid export and PV-to-battery energy as kWh bars, with PV financial value on a separate euro axis.
- Battery chart shows charge/discharge energy as kWh bars, with charge cost, discharge value and battery profit on a separate euro axis.
- Added a persistent chart-theme selector with Home Assistant, Energy, Ocean, Sunset, Forest and Monochrome palettes. The selected palette applies consistently to all chart series and is stored locally in the browser.

### Changed
- Extended the chart WebSocket payload with solar-flow and battery-flow/financial fields needed by the new asset charts.

## [0.1.0-alpha.14] - 2026-08-29

### Changed
- Renamed chart views to describe the visible range: Year, Month, Day and Day 15 min (with Dutch equivalents).
- Drill-down now preserves the selected time context and automatically scrolls the next view around the selected period.
- Improved mobile chart interaction: swiping scrolls without flashing the tooltip; one tap shows a persistent tooltip and a second tap on the same period drills down.

## [0.1.0-alpha.13] - 2026-08-29

### Changed
- Changed the overlapping financial bars so all enabled bar series keep the same width.
- Bars are still drawn in descending absolute value order per period, so the largest value is behind and smaller values are rendered in front.
- Added a subtle outline/opacity tweak so overlapping bars remain distinguishable without varying their widths.

## [0.1.0-alpha.12] - 2026-08-29

### Changed
- The custom sidebar panel now follows the Home Assistant interface language and is fully available in Dutch and English.
- Tabs, charts, tooltips, cards, cost tables, history filters, quality labels, hints, loading states and navigation controls are localized.
- Currency, number, date, time, weekday and month formatting now follow the selected panel locale instead of the browser default.
- Changing the Home Assistant interface language while the panel is open triggers an immediate re-render in the new language.

## [0.1.0-alpha.11] - 2026-08-29

### Changed
- Financial chart bars now overlap from the shared zero baseline instead of stacking, so each bar endpoint represents the actual value of that series.
- For each time bucket, bars are ordered dynamically by absolute magnitude: the largest bar is drawn widest and behind, intermediate bars are progressively narrower, and the smallest bar is drawn last/in front so every enabled series remains visible.
- The financial Y-axis now scales from the individual series values instead of stacked totals.

## [0.1.0-alpha.10] - 2026-08-29

### Changed
- Ledger history is now committed per 15-minute financial interval instead of creating one immutable ledger row every minute. Meter sampling remains frequent for accurate PV/battery flow attribution, while a small pending checkpoint preserves crash recovery.
- Tariff changes still close the active financial interval immediately, and long recovered gaps remain explicit estimated rows.
- Current open-interval values are included in sensors and chart summaries before the interval is committed.
- Mobile finance charts now support native horizontal swipe/scroll and automatically start at the latest data for the current hour/quarter view.


### Planned
- Explicit irregular first/last supplier billing periods.
- Named fixed-cost line items instead of aggregate daily/monthly/yearly fields.
- Historical backfill tooling.
- Independent multi-battery accounting.

## [0.1.0-alpha.9] - 2026-08-28

### Changed
- Sidebar PV features are now hidden entirely when no PV entities are configured: the Solar tab, Overview PV card, chart series/toggle, tooltip field, History filters/columns and live PV power are omitted.
- Sidebar battery features are now hidden entirely when no battery entities are configured: the Battery tab, Overview battery cards, chart series/toggle, tooltip field, History filters/columns and battery-specific quality filter are omitted.
- Live PV power, battery power and battery SOC are shown independently only when their corresponding live entity is configured.
- If PV or battery configuration is removed while its tab/filter is active, the panel automatically falls back to a valid view/filter.

## [0.1.0-alpha.8] - 2026-08-28

### Changed
- Aligned the financial and tariff Y axes to one shared horizontal zero baseline, so `€0` and `€0/kWh` always render at exactly the same height.
- The tariff axis now expands around zero when necessary while preserving all price data, including negative dynamic tariffs.
- Added fixed-domain tariff ticks that keep the shared zero line exact instead of re-rounding the secondary axis after alignment.

## [0.1.0-alpha.7] - 2026-08-28

### Changed
- Changed financial bars from grouped to stacked bars, with positive and negative values stacked independently around zero.
- Reworked chart sizing so SVG text is rendered at native pixel scale instead of being stretched with the chart viewport.
- Added rounded “nice” Y-axis ranges and tick steps for both financial values and tariff prices.
- Reduced tariff-axis precision for clearer labels and dynamically spaces X-axis ticks based on available chart width.
- Chart tooltips now show the full interval start and end; an hourly `17:00` bucket is explicitly shown as `17:00–18:00`, and a quarter-hour bucket as `17:00–17:15`.
- Clarified in the chart hint that X-axis timestamps represent the start of each bucket.

## [0.1.0-alpha.6] - 2026-08-28

### Changed
- Reworked the Overview financial visualization into a grouped bar chart for net cost, PV value and battery profit.
- Replaced wheel/drag zoom with explicit Month, Day, Hour and Quarter aggregation views plus previous/next/now controls.
- Month shows months of the selected year, Day shows days of the selected month, Hour shows hours of the selected day and Quarter shows 15-minute buckets of the selected day; tapping a bar still drills down.

### Added
- Current effective import and export prices in the chart header.
- Optional historical import/export tariff overlays using a separate price axis and time-weighted bucket averages.
- Per-series toggles for net cost, PV value, battery profit, import price and export price; selections persist in browser storage.

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
