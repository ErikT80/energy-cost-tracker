# Energy Cost Tracker for Home Assistant

Energy Cost Tracker is a local-first Home Assistant custom integration for detailed electricity cost accounting. It combines cumulative grid/PV/battery meters with dynamic import/export prices, dated fixed costs and supplier billing periods, and stores the resulting financial history in a dedicated local SQLite ledger.

> **Release candidate: 0.1.0-rc.1.** The feature set is frozen for the first public release. This release candidate is intended for backup/restore, invoice-reconciliation and multi-installation validation before `v0.1.0`.

## Highlights

- Provider-independent Config Flow: select existing Home Assistant entities instead of connecting to one energy supplier.
- Dynamic import and export prices, including negative prices and common `currency/kWh`, `currency/MWh` and cent/pence units.
- Calendar hour/day/week/month/year plus configurable supplier billing month and billing year.
- Invoice-style Costs page with separate grid import cost, export revenue, fixed charges/deductions and billing-period total.
- Dated fixed-cost schedules: enter a future tariff change now and ECT activates it automatically on the effective date.
- Multiple PV meters and multiple battery meters; batteries are accounted as one combined financial inventory.
- Solar economic value, direct self-consumption, export, PV-to-battery attribution and self-consumption percentage.
- Battery weighted-average cost basis and realized battery profit without double-counting solar value.
- Year / Month / Day / Day 15 min charts with mobile scrolling, drill-down, tooltips and automatic focus on the relevant part of the period.
- Realized average-price KPIs are weighted by the energy you actually imported/exported/charged/discharged.
- Dedicated searchable local ledger with data-quality flags instead of silently inventing missing prices.
- English and Dutch sidebar UI.
- Admin-managed sidebar whitelist: admins always have access; regular users are hidden by default.
- Backup-aware SQLite handling for Home Assistant backups.

## Requirements

- Home Assistant **2026.8.0 or newer**.
- At minimum one cumulative grid-import energy entity.
- Dynamic price entities are optional, but financial intervals that require an unavailable price are marked incomplete.

For best results, cumulative energy entities should expose a valid energy unit such as kWh, Wh or MWh. Optional live power sensors are used only for live display and do not replace cumulative energy accounting.

## Installation

### HACS custom repository (recommended for the release candidate)

1. In HACS, open the menu and choose **Custom repositories**.
2. Add `https://github.com/ErikT80/energy-cost-tracker` as type **Integration**.
3. Install **Energy Cost Tracker**.
4. Restart Home Assistant.
5. Go to **Settings → Devices & services → Add integration** and search for **Energy Cost Tracker**.

### Manual

1. Copy `custom_components/energy_cost_tracker` to `/config/custom_components/energy_cost_tracker`.
2. Restart Home Assistant.
3. Add **Energy Cost Tracker** from **Settings → Devices & services**.

No YAML configuration is required.

## Source configuration

### Grid

- Grid import energy — required cumulative counter.
- Grid export energy — optional but recommended when exporting.
- Grid power — optional live power.

### Solar

One or more cumulative PV-production counters and optionally one or more PV power sensors can be selected. Multiple selected systems are combined for accounting; old combined/template history can remain in the ledger when switching to individual source sensors because new sources start from a baseline rather than booking their lifetime total again.

Do not configure both a combined template counter and the individual counters that make up that template at the same time, or production will be counted twice.

### Battery

One or more cumulative charge counters, discharge counters and live power sensors can be selected. They are intentionally treated as one combined battery system with one weighted-average cost basis.

SOC is optional and is **not** used to measure energy or calculate profit. It is only a helper for determining when the initial unknown stored-energy inventory has become empty. Without SOC, an admin can perform the one-time **Battery is empty now** confirmation in Settings when the whole configured battery system is physically empty.

## Financial model

The invoice and asset-value accounting are deliberately separated:

- **Grid import cost** = imported kWh × effective import price.
- **Grid export revenue** = exported kWh × effective export price.
- **Invoice/net cost** = import cost − export revenue + fixed costs/deductions.
- **Direct PV value** = avoided grid import cost.
- **PV export value** = actual export revenue.
- **PV → battery value** = foregone export revenue (opportunity cost).
- **Grid → battery cost basis** = actual grid import cost.
- **Battery profit** = discharge value − weighted-average cost basis of discharged energy.

Because PV energy stored in the battery enters the battery at its opportunity cost, PV value and battery profit can be added without counting the same value twice.

The sidebar can optionally store one aggregate PV investment amount and one aggregate battery investment amount. ECT shows the ledger-derived value/profit since tracking began as a percentage of those amounts. It intentionally does **not** forecast a payback time.

## Average prices and chart lines

On the Overview chart, tariff lines describe the tariff of each displayed time bucket independently of how much energy you used:

- Year → time-weighted tariff per month.
- Month → time-weighted tariff per day.
- Day → time-weighted tariff per hour.
- Day 15 min → tariff per quarter-hour.

The KPIs above the chart answer a different question: what you actually paid/received over the whole selected view. They are energy-weighted using only energy for which the required price is known.

Solar KPIs are weighted by actual PV production/export. Battery KPIs are weighted by actual charged/discharged energy. Solar and Battery financial chart lines remain expressed as value/cost in currency per displayed period.

## Fixed costs and billing periods

Initial fixed daily/monthly/yearly charges and an annual deduction can be entered during setup. Later changes are managed in **Settings → Fixed costs by effective date**.

A complete cost profile can be scheduled in advance, for example for 1 January. If a past effective date is edited, ECT deterministically recalculates only historical `fixed_cost` and dependent `net_cost`; measured energy, dynamic prices, solar value and battery accounting are not rewritten.

The Costs page supports:

- configurable billing-month start day;
- configurable billing-year start month/day;
- separate import kWh/cost and export kWh/revenue;
- fixed-cost/deduction breakdown;
- billing-year summary with clickable billing-month rows.

## Data quality

Every ledger interval has a quality state:

- `exact` — normal meter progression with all required financial inputs.
- `reconstructed` — reset or small negative counter correction was handled.
- `estimated` — an outage/gap prevented exact time allocation.
- `missing_price` — measured energy required a price that was unavailable.
- `unknown_battery_basis` — discharge occurred while initial stored-energy cost basis was still unknown.

For an incomplete period, financial Home Assistant entities expose the defensible **known subtotal** as a numeric state and include completeness attributes. ECT does not fill missing historical prices with the current price.

## Persistence, upgrades and backups

The ledger is stored in `.storage/energy_cost_tracker.db`. Source baselines, interval history and battery cost basis survive normal integration reloads and Home Assistant restarts.

The integration implements explicit forward-only migrations for both the Home Assistant config entry and the dedicated database. A database created by a newer unsupported ECT schema is refused rather than guessed or downgraded.

During a Home Assistant backup, ECT pauses database access, checkpoints SQLite WAL data and switches to a stable single-file state. Existing financial history is not deleted when PV/battery sources are removed from the current configuration.

Removing the config entry or uninstalling the custom integration does not currently provide an in-product destructive “delete all ledger history” action. Back up `.storage/energy_cost_tracker.db` before manually removing stored history.

## Sidebar access

Home Assistant administrators always have access to the side panel and its Settings page. Regular Home Assistant users do not see ECT by default. An admin can whitelist individual users under **Settings → Side panel access**.

Read WebSocket APIs enforce the same whitelist server-side. Settings/write APIs are admin-only; hiding the sidebar is not the security boundary.

## Development and validation

The repository validates:

- unit/accounting/database migration tests;
- release/package contracts and translation-key parity;
- Python compilation;
- frontend JavaScript syntax;
- import compatibility against Home Assistant 2026.8.0 and latest stable;
- Home Assistant hassfest;
- HACS validation.

See [Testing](docs/TESTING.md), [Architecture](docs/ARCHITECTURE.md) and the [Release checklist](docs/RELEASE_CHECKLIST.md).

## Known limitations

- No historical backfill is attempted before ECT established its first source baselines.
- Multiple batteries are combined into one financial inventory; per-device battery profit/cost basis is not separated.
- PV/battery flow attribution necessarily infers flows from aggregate counters. Residual flow is retained when asynchronously updating meters cannot balance perfectly.
- Long source outages that span multiple tariff periods cannot always be reconstructed exactly from cumulative energy alone and are marked accordingly.
- Recurring billing anchors are supported; one-off irregular first/last supplier statement boundaries are not separately configurable.
- This project performs local financial accounting and is useful for invoice reconciliation, but supplier rounding/tax rules can still create small differences from an official invoice.

## Release candidate testing

Before `v0.1.0`, the maintainer is explicitly validating a real Home Assistant backup/restore, at least one real supplier invoice and a small set of external installations. See [RELEASE_CHECKLIST.md](docs/RELEASE_CHECKLIST.md).

## License

MIT
