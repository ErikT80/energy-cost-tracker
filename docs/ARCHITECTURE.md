# Architecture

```text
Home Assistant entities
  grid / PV / battery / prices
          │
          ▼
60 s synchronized sampler + tariff boundaries
          │
          ├── coherent pause/recovery on unavailable sources
          ├── reset & source-change segmentation
          ▼
Energy frame (kWh deltas)
          │
          ▼
Flow allocation + financial valuation
          │
          ├── invoice: import - export + fixed costs
          ├── PV economic value
          └── battery weighted-average cost basis / profit
          │
          ▼
In-memory financial accumulator
          │
          ├── crash-safe pending checkpoint
          ├── commit on 15-minute boundary
          └── immediate commit on tariff change / shutdown
          │
          ▼
SQLite immutable ledger
          │
          ├── HA monetary/energy sensors
          └── WebSocket query API → sidebar panel
```

## Invariants

1. Measured energy, dynamic prices, PV value and battery accounting in past ledger rows are not rewritten by normal configuration changes. The only supported historical repair is the explicit dated fixed-cost repair, which changes `fixed_cost` and dependent `net_cost` only.
2. Absolute meter readings are never added directly; only validated deltas are booked.
3. A source entity can change without requiring its absolute value to match the previous entity.
4. Negative cumulative deltas never become negative energy consumption.
5. Missing financial data is represented as `NULL` plus a quality status, not as zero.
6. PV value and battery profit are analytical values and are not added on top of invoice cost.
7. Frequent meter samples do not create immutable history rows; normally one ledger row is committed per 15-minute financial interval.


## Upgrade safety

Energy Cost Tracker has two independent forward-only version domains:

- Home Assistant config-entry version (`CONFIG_ENTRY_VERSION`).
- Dedicated SQLite ledger schema (`SCHEMA_VERSION`).

Config migration normalizes old multi-source entity fields without touching ledger history. Database initialization reads the persisted schema version and applies explicit migrations one version at a time. A database with a newer schema is refused rather than downgraded; an existing non-empty unversioned ledger is also refused rather than guessed.

The first release candidate migrates config entries from v1 to v2 and ledger schema v1 to v2. Both migrations are intentionally data-preserving.

## Validation layers

The fast pytest suite deliberately imports the pure accounting/ledger modules without Home Assistant, keeping financial regression tests deterministic and quick. CI adds a separate Home Assistant import-smoke matrix for the minimum supported Core version and latest stable, plus hassfest and HACS validation. Real backup/restore and supplier-invoice reconciliation remain explicit manual stable-release gates.
