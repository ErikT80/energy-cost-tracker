"""Finalize RC2 version metadata, changelog and docs."""
from pathlib import Path
import json

VERSION = "0.1.0-rc.2"

manifest_path = Path("custom_components/energy_cost_tracker/manifest.json")
manifest = json.loads(manifest_path.read_text())
manifest["version"] = VERSION
manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")

const_path = Path("custom_components/energy_cost_tracker/const.py")
const = const_path.read_text()
old = 'VERSION = "0.1.0-rc.1"'
new = f'VERSION = "{VERSION}"'
if const.count(old) != 1:
    raise SystemExit("Expected RC1 VERSION exactly once in const.py")
const_path.write_text(const.replace(old, new, 1))

readme_path = Path("README.md")
readme = readme_path.read_text()
old = "**Release candidate: 0.1.0-rc.1.**"
new = f"**Release candidate: {VERSION}.**"
if readme.count(old) != 1:
    raise SystemExit("Expected RC1 release-candidate marker exactly once in README.md")
readme_path.write_text(readme.replace(old, new, 1))

changelog_path = Path("CHANGELOG.md")
changelog = changelog_path.read_text()
marker = "## [Unreleased]\n\n"
section = """## [0.1.0-rc.2] - 2026-10-03

### Fixed
- Ignore attribute-only updates from configured import/export tariff entities when their effective numeric price is unchanged, avoiding needless financial interval boundaries.
- Coalesce near-simultaneous import and export price changes for 0.5 seconds and hold the normal accounting tick while the pair is pending, so one provider update cannot create an intermediate mixed-price interval.
- Treat tariff publication shortly after an aligned 15-minute ledger boundary as the price for the new interval, updating the stored tariff without creating a tiny extra ledger row at the previous quarter's price.

### Changed
- Added permanent runtime regression tests for unchanged tariff states, paired import/export tariff changes, and a tariff update five seconds after a quarter boundary.
- Release automation now publishes the manifest version automatically after a version-changing merge to `main`: it creates the corresponding `v<version>` tag, builds `energy_cost_tracker.zip`, and marks alpha/beta/RC versions as GitHub prereleases. Existing tags are left untouched, so unrelated later merges do not republish the same version.

"""
if section in changelog:
    raise SystemExit("RC2 changelog section already exists")
if changelog.count(marker) != 1:
    raise SystemExit("Expected one Unreleased changelog marker")
changelog_path.write_text(changelog.replace(marker, marker + section, 1))
