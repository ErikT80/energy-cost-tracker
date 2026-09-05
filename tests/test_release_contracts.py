"""Static release contracts that catch packaging/frontend regressions cheaply."""
from __future__ import annotations

import json
from pathlib import Path
import re

ROOT = Path(__file__).parents[1]
INTEGRATION = ROOT / "custom_components" / "energy_cost_tracker"


def _key_tree(value):
    if isinstance(value, dict):
        return {key: _key_tree(child) for key, child in value.items()}
    return None


def test_manifest_and_const_versions_match():
    manifest = json.loads((INTEGRATION / "manifest.json").read_text())
    const_text = (INTEGRATION / "const.py").read_text()
    match = re.search(r'^VERSION = "([^"]+)"$', const_text, re.MULTILINE)
    assert match is not None
    assert manifest["version"] == match.group(1)


def test_translation_key_trees_match():
    en = json.loads((INTEGRATION / "translations" / "en.json").read_text())
    nl = json.loads((INTEGRATION / "translations" / "nl.json").read_text())
    assert _key_tree(en) == _key_tree(nl)


def test_frontend_keeps_localized_axis_titles_and_mobile_tap_contract():
    js = (INTEGRATION / "frontend" / "energy-cost-tracker-panel.js").read_text()
    assert 'this.tr("€ per periode", "€ per period")' in js
    assert 'this.tr("kWh per periode","kWh per period")' in js
    # One-tap tooltip / second-tap drill-down depends on the remembered touch bucket.
    assert "_touchTooltipIndex" in js
    assert "_touchTooltipAt" in js
    assert "matchMedia" in js


def test_hacs_minimum_version_is_declared():
    hacs = json.loads((ROOT / "hacs.json").read_text())
    assert hacs["homeassistant"] == "2026.8.0"
