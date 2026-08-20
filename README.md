# Energy Cost Tracker for Home Assistant

Energy Cost Tracker is a local-first Home Assistant custom integration for financial energy accounting with dynamic electricity tariffs, fixed charges, supplier billing periods, solar value and home-battery cost basis/profit.

> **Status: 0.1.0-alpha.1.** The data model and ledger are intentionally designed for long-term history, but this release should be validated against real meters and invoices before relying on it for financial decisions.

## Core design

- UI-only setup through a Home Assistant Config Flow.
- Supplier-independent: choose existing Home Assistant entities instead of connecting to a specific energy company.
- Dedicated searchable SQLite ledger stored at `.storage/energy_cost_tracker.db`.
- Immutable interval bookings: changing a sensor or tariff does not rewrite past rows.
- Cumulative meter resets are detected and start a new internal segment.
- Replacing an entity creates a new baseline; old ledger history remains intact.
- Configured cumulative sources are sampled coherently; if one is unavailable, accounting baselines pause until recovery and the recovered span is marked `estimated`.
- Recurring billing month and billing year can differ from calendar periods.
- Multiple PV production entities can be selected.
- Battery charging can have a mixed solar/grid cost basis using a weighted-average inventory model.
- Sidebar panel with overview, cost, PV, battery and searchable history pages (date, activity and quality filters).

## Install manually

1. Copy `custom_components/energy_cost_tracker` to `/config/custom_components/energy_cost_tracker`.
2. Restart Home Assistant.
3. Go to **Settings → Devices & services → Add integration**.
4. Search for **Energy Cost Tracker**.
5. Select your entities in the Config Flow.

No YAML is required.

## Source expectations

For the best accuracy use cumulative energy entities (kWh/Wh/MWh):

- grid import (required)
- grid export (optional but recommended)
- one or more PV production counters
- battery charge counter
- battery discharge counter

Power and SOC sensors are optional and are currently used mainly for live display and battery cost-basis reconciliation. Dynamic price entities can be left blank until a dynamic contract is active.

Price units `currency/kWh`, `currency/MWh`, `ct/kWh`, `c/kWh`, `p/kWh` and `pence/kWh` are automatically normalized where possible. A multiplier and per-kWh adjustment are available for provider-specific price representations.

## Financial definitions

- Grid import cost = imported kWh × effective import price.
- Grid export revenue = exported kWh × effective export price.
- PV direct-use value = avoided import price.
- PV export value = export price.
- PV sent to battery enters the battery at the foregone export price (opportunity cost).
- Grid energy sent to battery enters at the import price.
- Battery profit = value when discharged − weighted-average stored cost basis.
- Fixed daily/monthly/yearly charges and annual rebates accrue over wall-clock time.

PV value and battery profit are **analytical asset values**. They are not added to invoice cost again, avoiding double counting.

## Quality states

Each ledger interval carries one of these states:

- `exact` – normal meter progression with a normal accounting interval.
- `reconstructed` – a counter reset or small negative meter correction was handled.
- `estimated` – source data was unavailable or a long HA gap spans the interval.
- `missing_price` – energy was measured but a required price was unavailable.
- `unknown_battery_basis` – discharge value exists but the initial stored-energy cost basis is not yet known.

After a configured battery SOC reaches the "empty" threshold, the remaining virtual inventory is reconciled and subsequent battery cost basis can become known.

## Billing periods

The integration exposes calendar periods and recurring supplier periods:

- current hour / today / week / calendar month / calendar year
- billing month with configurable start day (1–31; invalid dates clamp to month-end)
- billing year with configurable start month and day

A future version will add explicit one-off irregular first/last statement periods in addition to recurring anchors.

## Sensor changes and resets

The ledger stores a baseline for each logical source. If a cumulative sensor drops materially, it is treated as a reset/rollover. If the configured entity changes, a new source segment starts at the new entity's current value. Historical kWh and money remain in the ledger.

## Sidebar panel

The integration automatically registers `/energy-cost-tracker` in the Home Assistant sidebar. The panel uses Home Assistant WebSockets to query the local ledger and supports date and quality filtering.

## GitHub / HACS publication

This repository is prepared for public GitHub and HACS use. Before the first push, replace the owner placeholder once:

```bash
python scripts/set_github_owner.py ErikT80
```

Then create a public GitHub repository named `energy-cost-tracker`, enable **Issues**, add a short repository description and add topics such as `home-assistant`, `hacs`, `energy`, `dynamic-tariffs`, `solar` and `battery`. HACS checks these repository-level settings in addition to the files committed here.

The repository contains GitHub Actions for unit tests, Home Assistant hassfest and HACS validation. A tag such as `v0.1.0-alpha.1` triggers the release workflow and produces a manual-install `energy_cost_tracker.zip` asset.

The included brand icon is intentionally generic and can be replaced later without changing the integration domain.

## Known alpha limitations

- Normal accounting uses a 60-second cadence and closes an interval immediately on a detected tariff state change. A long HA/source outage spanning tariff changes cannot be reconstructed exactly from cumulative meters alone and is therefore marked `estimated`.
- PV/battery flow allocation assumes PV serves house load first, then battery, then export; battery discharge serves house load before export. A residual is stored when asynchronously updating meters do not balance.
- Battery loss accounting is reconciled when the configured empty-SOC threshold is observed. Battery systems with a permanent reserve need validation. Negative energy prices are supported in the weighted cost basis.
- Multiple batteries are not yet exposed as independent assets in the Config Flow; the internal schema is ready to evolve, but 0.1.0 accepts one aggregate battery.
- Explicit irregular first billing-period start/end dates are planned for the next iteration.
- No automatic historical backfill is attempted before the integration's first baseline.

## License

MIT
