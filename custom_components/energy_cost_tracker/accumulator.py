"""In-memory aggregation for persistent financial ledger intervals.

The runtime may sample cumulative meters frequently to keep flow attribution and
battery cost basis accurate. Those samples are accumulated here and only one
immutable ledger row is committed per tariff interval (or other financial
boundary such as a tariff change or clean shutdown).
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any


SUM_FIELDS = (
    "grid_import_kwh",
    "grid_export_kwh",
    "house_consumption_kwh",
    "pv_production_kwh",
    "battery_charge_kwh",
    "battery_discharge_kwh",
    "grid_to_house_kwh",
    "grid_to_battery_kwh",
    "pv_direct_kwh",
    "pv_export_kwh",
    "pv_to_battery_kwh",
    "battery_to_house_kwh",
    "battery_to_grid_kwh",
    "flow_residual_kwh",
    "fixed_cost",
    "battery_loss_cost",
)

OPTIONAL_SUM_FIELDS = (
    "import_cost",
    "export_revenue",
    "net_cost",
    "pv_value",
    "battery_charge_cost",
    "battery_discharge_value",
    "battery_discharge_cost_basis",
    "battery_profit",
)

QUALITY_RANK = {
    "exact": 0,
    "reconstructed": 1,
    "unknown_battery_basis": 2,
    "estimated": 3,
    "missing_price": 4,
}


@dataclass(slots=True)
class IntervalAccumulator:
    """Accumulate accounting samples into one persistent ledger interval."""

    start_ts: str | None = None
    end_ts: str | None = None
    seconds: float = 0.0
    sums: dict[str, float] = field(default_factory=dict)
    optional_sums: dict[str, float] = field(default_factory=dict)
    optional_complete: dict[str, bool] = field(default_factory=dict)
    import_price_weighted: float = 0.0
    import_price_seconds: float = 0.0
    export_price_weighted: float = 0.0
    export_price_seconds: float = 0.0
    quality: str = "exact"
    notes: set[str] = field(default_factory=set)

    @property
    def empty(self) -> bool:
        return self.start_ts is None or self.end_ts is None or self.seconds <= 0

    def add(self, row: dict[str, Any]) -> None:
        """Add one already-valued runtime sample."""
        seconds = max(0.0, float(row.get("seconds") or 0.0))
        if seconds <= 0:
            return

        if self.start_ts is None:
            self.start_ts = str(row["start_ts"])
        self.end_ts = str(row["end_ts"])
        self.seconds += seconds

        for key in SUM_FIELDS:
            self.sums[key] = self.sums.get(key, 0.0) + float(row.get(key) or 0.0)

        for key in OPTIONAL_SUM_FIELDS:
            if key not in self.optional_complete:
                self.optional_complete[key] = True
                self.optional_sums[key] = 0.0
            value = row.get(key)
            if value is None:
                self.optional_complete[key] = False
            else:
                self.optional_sums[key] += float(value)

        import_price = row.get("import_price")
        if import_price is not None:
            self.import_price_weighted += float(import_price) * seconds
            self.import_price_seconds += seconds
        export_price = row.get("export_price")
        if export_price is not None:
            self.export_price_weighted += float(export_price) * seconds
            self.export_price_seconds += seconds

        row_quality = str(row.get("quality") or "exact")
        if QUALITY_RANK.get(row_quality, 1) > QUALITY_RANK.get(self.quality, 1):
            self.quality = row_quality

        raw_notes = row.get("notes")
        if raw_notes:
            self.notes.update(note for note in str(raw_notes).split(",") if note)

    def to_ledger_row(self) -> dict[str, Any] | None:
        """Return one immutable ledger row, or ``None`` when empty."""
        if self.empty:
            return None
        row: dict[str, Any] = {
            "start_ts": self.start_ts,
            "end_ts": self.end_ts,
            "seconds": self.seconds,
            **{key: self.sums.get(key, 0.0) for key in SUM_FIELDS},
        }
        for key in OPTIONAL_SUM_FIELDS:
            row[key] = (
                self.optional_sums.get(key, 0.0)
                if self.optional_complete.get(key, True)
                else None
            )
        row["import_price"] = (
            self.import_price_weighted / self.import_price_seconds
            if self.import_price_seconds > 0
            else None
        )
        row["export_price"] = (
            self.export_price_weighted / self.export_price_seconds
            if self.export_price_seconds > 0
            else None
        )
        row["quality"] = self.quality
        row["notes"] = ",".join(sorted(self.notes)) if self.notes else None
        return row

    def to_json(self) -> str:
        """Serialize the pending checkpoint for crash-safe continuation."""
        return json.dumps(
            {
                "start_ts": self.start_ts,
                "end_ts": self.end_ts,
                "seconds": self.seconds,
                "sums": self.sums,
                "optional_sums": self.optional_sums,
                "optional_complete": self.optional_complete,
                "import_price_weighted": self.import_price_weighted,
                "import_price_seconds": self.import_price_seconds,
                "export_price_weighted": self.export_price_weighted,
                "export_price_seconds": self.export_price_seconds,
                "quality": self.quality,
                "notes": sorted(self.notes),
            },
            separators=(",", ":"),
            sort_keys=True,
        )

    @classmethod
    def from_json(cls, raw: str | None) -> "IntervalAccumulator":
        """Restore a pending checkpoint; invalid data starts a fresh interval."""
        if not raw:
            return cls()
        try:
            data = json.loads(raw)
            return cls(
                start_ts=data.get("start_ts"),
                end_ts=data.get("end_ts"),
                seconds=float(data.get("seconds", 0.0)),
                sums={str(k): float(v) for k, v in (data.get("sums") or {}).items()},
                optional_sums={
                    str(k): float(v) for k, v in (data.get("optional_sums") or {}).items()
                },
                optional_complete={
                    str(k): bool(v) for k, v in (data.get("optional_complete") or {}).items()
                },
                import_price_weighted=float(data.get("import_price_weighted", 0.0)),
                import_price_seconds=float(data.get("import_price_seconds", 0.0)),
                export_price_weighted=float(data.get("export_price_weighted", 0.0)),
                export_price_seconds=float(data.get("export_price_seconds", 0.0)),
                quality=str(data.get("quality") or "exact"),
                notes=set(str(v) for v in (data.get("notes") or [])),
            )
        except (TypeError, ValueError, json.JSONDecodeError):
            return cls()
