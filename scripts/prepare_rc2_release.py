"""Finalize RC2 version metadata, changelog, docs and release-on-merge workflow."""
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

Path(".github/workflows/release.yml").write_text(r'''name: Release

on:
  push:
    branches:
      - main
    tags:
      - "v*"

permissions:
  contents: write

jobs:
  release:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v7
        with:
          fetch-depth: 0

      - name: Set up Python
        uses: actions/setup-python@v7
        with:
          python-version: "3.14"
          cache: pip
          cache-dependency-path: requirements-test.txt

      - name: Resolve release version
        id: release_version
        shell: bash
        run: |
          manifest_version="$(python - <<'PY'
          import json
          from pathlib import Path
          print(json.loads(Path('custom_components/energy_cost_tracker/manifest.json').read_text())['version'])
          PY
          )"

          if [ "$GITHUB_REF_TYPE" = "tag" ]; then
            tag_name="$GITHUB_REF_NAME"
            tag_version="${tag_name#v}"
            if [ "$manifest_version" != "$tag_version" ]; then
              echo "Tag version $tag_version does not match manifest version $manifest_version"
              exit 1
            fi
            publish=true
          else
            tag_name="v${manifest_version}"
            if git ls-remote --exit-code --tags origin "refs/tags/${tag_name}" >/dev/null 2>&1; then
              echo "Tag ${tag_name} already exists; nothing to publish for this main push."
              publish=false
            else
              publish=true
            fi
          fi

          echo "version=${manifest_version}" >> "$GITHUB_OUTPUT"
          echo "tag=${tag_name}" >> "$GITHUB_OUTPUT"
          echo "publish=${publish}" >> "$GITHUB_OUTPUT"

      - name: Install test dependencies
        if: steps.release_version.outputs.publish == 'true'
        run: python -m pip install -r requirements-test.txt

      - name: Run release checks
        if: steps.release_version.outputs.publish == 'true'
        shell: bash
        run: |
          python -m pytest -q
          python -m compileall -q custom_components/energy_cost_tracker
          node --check custom_components/energy_cost_tracker/frontend/energy-cost-tracker-panel.js

      - name: Install minimum supported Home Assistant
        if: steps.release_version.outputs.publish == 'true'
        run: python -m pip install "homeassistant==2026.8.0"

      - name: Import-smoke integration on minimum Home Assistant
        if: steps.release_version.outputs.publish == 'true'
        run: python scripts/ha_import_smoke.py

      - name: Build manual-install archive
        if: steps.release_version.outputs.publish == 'true'
        shell: bash
        run: |
          mkdir -p dist
          cd custom_components
          zip -r "../dist/energy_cost_tracker.zip" energy_cost_tracker -x "*/__pycache__/*" "*.pyc"

      - name: Create version tag after main merge
        if: steps.release_version.outputs.publish == 'true' && github.ref_type != 'tag'
        env:
          TAG_NAME: ${{ steps.release_version.outputs.tag }}
        shell: bash
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git tag "$TAG_NAME" "$GITHUB_SHA"
          git push origin "$TAG_NAME"

      - name: Determine release type
        if: steps.release_version.outputs.publish == 'true'
        id: release_type
        env:
          TAG_NAME: ${{ steps.release_version.outputs.tag }}
        shell: bash
        run: |
          if [[ "$TAG_NAME" == *alpha* || "$TAG_NAME" == *beta* || "$TAG_NAME" == *rc* ]]; then
            echo "prerelease=true" >> "$GITHUB_OUTPUT"
          else
            echo "prerelease=false" >> "$GITHUB_OUTPUT"
          fi

      - name: Create GitHub release
        if: steps.release_version.outputs.publish == 'true'
        env:
          GH_TOKEN: ${{ github.token }}
          TAG_NAME: ${{ steps.release_version.outputs.tag }}
        shell: bash
        run: |
          args=("$TAG_NAME" "dist/energy_cost_tracker.zip" --generate-notes --title "$TAG_NAME")
          if [ "${{ steps.release_type.outputs.prerelease }}" = "true" ]; then
            args+=(--prerelease)
          fi
          gh release create "${args[@]}"
''')
