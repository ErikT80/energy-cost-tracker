# v0.1.0 release checklist

The first stable release is intentionally gated on evidence, not additional features.

## Automated gates

- [ ] `Unit tests` is green.
- [ ] `HA import (minimum 2026.8.0)` is green.
- [ ] `HA import (latest stable)` is green.
- [ ] `Home Assistant hassfest` is green.
- [ ] `HACS validation` is green.
- [ ] Frontend `node --check` passes.
- [ ] Manifest, `const.py` and Git tag use the same version.
- [ ] English/Dutch translation key trees match.

## Maintainer Home Assistant validation

- [ ] Upgrade an existing alpha database/config entry to `v0.1.0-rc.1` and confirm history remains intact.
- [ ] Restart Home Assistant and confirm accounting resumes from correct baselines.
- [ ] Reconfigure PV sources from a combined template to individual counters without double booking.
- [ ] Add/remove an optional battery/PV configuration and confirm current entities change while historical sidebar data remains.
- [ ] Create a full Home Assistant backup while ECT is active.
- [ ] Restore that backup to a test instance and confirm the ledger, fixed-cost profiles, access settings and cost basis are present.
- [ ] Test English and Dutch sidebar UI.
- [ ] Test a non-admin user: hidden by default, visible when whitelisted, Settings unavailable.
- [ ] Test Android chart scrolling/tooltip/drill-down.
- [ ] Test iOS/iPadOS interaction if a device/tester is available.

## Financial reconciliation gate

Compare at least one complete real supplier statement with the ECT billing-period view:

- [ ] import kWh;
- [ ] export kWh;
- [ ] variable import cost;
- [ ] export revenue/credit;
- [ ] fixed daily/monthly/yearly costs;
- [ ] annual deduction/rebate allocation;
- [ ] final billing-period total;
- [ ] any difference is understood and documented (for example supplier rounding).

## External release-candidate validation

Target 3–5 installations if possible, including:

- [ ] grid-only/dynamic-price setup;
- [ ] grid + PV;
- [ ] multiple PV counters;
- [ ] PV + battery;
- [ ] multiple battery counters if available;
- [ ] at least one setup whose entity naming/units differ from the maintainer installation.

## Stable release

After the release candidate has no unresolved data-loss/accounting blockers:

1. Bump version from `0.1.0-rc.1` to `0.1.0`.
2. Run all required checks on `main`.
3. Tag `v0.1.0` and push the tag; `release.yml` creates the GitHub Release asset.
4. Verify HACS can install/update the stable release from the repository.
5. Submit the repository to `hacs/default` following `docs/PUBLISHING.md`.
