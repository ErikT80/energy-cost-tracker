#!/usr/bin/env bash
set -euo pipefail
python -m pytest -q
python -m compileall -q custom_components/energy_cost_tracker
node --check custom_components/energy_cost_tracker/frontend/energy-cost-tracker-panel.js
python - <<'PY'
import json
from pathlib import Path
for path in Path('custom_components/energy_cost_tracker').rglob('*.json'):
    json.loads(path.read_text())
json.loads(Path('hacs.json').read_text())
print('JSON validation OK')
PY
