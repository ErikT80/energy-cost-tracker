"""Contract test for in-place entity ID changes on Home Assistant 2026.11+."""
from __future__ import annotations

import ast
from pathlib import Path
from textwrap import indent

SENSOR_PATH = (
    Path(__file__).parents[1]
    / "custom_components"
    / "energy_cost_tracker"
    / "sensor.py"
)


def test_entity_id_change_keeps_existing_runtime_subscription():
    """The rename hook must delegate to HA without re-subscribing listeners."""
    tree = ast.parse(SENSOR_PATH.read_text())
    sensor_class = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "EnergyCostSensor"
    )
    hook = next(
        node for node in sensor_class.body
        if isinstance(node, ast.FunctionDef) and node.name == "async_entity_id_changed"
    )

    class Base:
        def async_entity_id_changed(self, old_entity_id):
            self.base_calls.append((old_entity_id, self.entity_id))

    namespace = {"Base": Base, "callback": lambda fn: fn}
    exec(
        "class TestSensor(Base):\n" + indent(ast.unparse(hook), "    "),
        namespace,
    )
    sensor = namespace["TestSensor"]()
    sensor.entity_id = "sensor.energy_cost_renamed"
    sensor.base_calls = []
    sensor.async_entity_id_changed("sensor.energy_cost_original")

    assert sensor.base_calls == [
        ("sensor.energy_cost_original", "sensor.energy_cost_renamed")
    ]
    # Runtime listeners are not keyed to entity_id and remain active across renames.
    assert "async_add_listener" not in ast.unparse(hook)
