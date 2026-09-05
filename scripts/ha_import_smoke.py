"""Import-smoke the integration against the installed Home Assistant version."""
from __future__ import annotations

import importlib
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

MODULES = (
    "custom_components.energy_cost_tracker",
    "custom_components.energy_cost_tracker.access",
    "custom_components.energy_cost_tracker.accounting",
    "custom_components.energy_cost_tracker.accumulator",
    "custom_components.energy_cost_tracker.backup",
    "custom_components.energy_cost_tracker.config_flow",
    "custom_components.energy_cost_tracker.diagnostics",
    "custom_components.energy_cost_tracker.fixed_costs",
    "custom_components.energy_cost_tracker.ledger",
    "custom_components.energy_cost_tracker.migration",
    "custom_components.energy_cost_tracker.periods",
    "custom_components.energy_cost_tracker.runtime",
    "custom_components.energy_cost_tracker.sensor",
    "custom_components.energy_cost_tracker.websocket",
)


def main() -> None:
    import homeassistant  # noqa: F401

    loaded = [importlib.import_module(name) for name in MODULES]
    manifest = json.loads(
        (REPO_ROOT / "custom_components/energy_cost_tracker/manifest.json").read_text()
    )
    const = importlib.import_module("custom_components.energy_cost_tracker.const")
    flow = importlib.import_module("custom_components.energy_cost_tracker.config_flow")
    ledger = importlib.import_module("custom_components.energy_cost_tracker.ledger")

    assert manifest["domain"] == const.DOMAIN
    assert manifest["version"] == const.VERSION
    assert flow.EnergyCostTrackerConfigFlow.VERSION == const.CONFIG_ENTRY_VERSION
    assert ledger.SCHEMA_VERSION >= 2
    print(f"Imported {len(loaded)} ECT modules against Home Assistant successfully")


if __name__ == "__main__":
    main()
