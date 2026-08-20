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
SQLite immutable ledger
          │
          ├── HA monetary/energy sensors
          └── WebSocket query API → sidebar panel
```

## Invariants

1. Past ledger rows are never recomputed when current settings change.
2. Absolute meter readings are never added directly; only validated deltas are booked.
3. A source entity can change without requiring its absolute value to match the previous entity.
4. Negative cumulative deltas never become negative energy consumption.
5. Missing financial data is represented as `NULL` plus a quality status, not as zero.
6. PV value and battery profit are analytical values and are not added on top of invoice cost.
