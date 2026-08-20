# Contributing

Thanks for helping improve Energy Cost Tracker.

## Development principles

Energy Cost Tracker is a financial accounting integration. Changes that affect money, energy attribution, resets, billing boundaries or battery cost basis should include tests that show the intended accounting behaviour.

The project aims to remain supplier-independent. Provider-specific assumptions should not be embedded in the accounting core when the same result can be achieved through configuration or adapters.

## Local test run

The current unit tests exercise the pure accounting, ledger and billing-period modules and do not require a running Home Assistant instance.

```bash
python -m pip install -r requirements-test.txt
python -m pytest -q
python -m compileall -q custom_components/energy_cost_tracker
```

## Pull requests

Before opening a pull request:

1. Add or update tests for accounting behaviour that changes.
2. Update `CHANGELOG.md` under `Unreleased` when user-visible behaviour changes.
3. Keep existing ledger data compatible or document/migrate schema changes.
4. Do not silently convert unknown or incomplete energy data into `exact` financial values.
5. Run the local tests.

GitHub Actions also run Home Assistant hassfest and HACS repository validation.

## Release process

Releases use SemVer-style tags such as `v0.1.0-alpha.1`.

1. Move relevant entries from `Unreleased` to a dated version in `CHANGELOG.md`.
2. Set the same version without the leading `v` in `custom_components/energy_cost_tracker/manifest.json`.
3. Commit the release changes.
4. Create and push the matching Git tag.
5. The release workflow validates the tag/version match and creates a GitHub prerelease for versions containing `alpha`, `beta` or `rc`.
