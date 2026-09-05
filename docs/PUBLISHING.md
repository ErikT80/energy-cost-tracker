# Publishing Energy Cost Tracker

Repository: `ErikT80/energy-cost-tracker`

## Repository prerequisites

Keep the repository public and ensure:

- GitHub Issues are enabled;
- repository description is populated;
- appropriate topics are configured (for example `home-assistant`, `hacs`, `energy`, `dynamic-tariffs`, `solar`, `battery`);
- `hacs.json` is valid;
- `manifest.json` is valid;
- HACS validation and Home Assistant hassfest are green;
- a real GitHub Release exists for the version being submitted.

## Release candidate

For `0.1.0-rc.1`:

```bash
git tag v0.1.0-rc.1
git push origin v0.1.0-rc.1
```

The release workflow verifies that the tag matches `manifest.json`, runs tests/import smoke, builds `energy_cost_tracker.zip` and creates a prerelease.

Release-candidate users should install the repository through HACS **Custom repositories** until the first stable release has been validated.

## First stable release

After every item in `docs/RELEASE_CHECKLIST.md` that is applicable has been completed:

1. Change the version in `manifest.json` and `const.py` to `0.1.0`.
2. Update `CHANGELOG.md`.
3. Merge through the protected `main` branch with all required checks green.
4. Tag and push `v0.1.0`.
5. Confirm the release workflow created a non-prerelease GitHub Release and attached `energy_cost_tracker.zip`.

## Request inclusion in the default HACS store

After `v0.1.0` exists as a GitHub Release:

1. Fork `hacs/default` to the maintainer's personal GitHub account.
2. Create a branch from its `master` branch.
3. Add `"ErikT80/energy-cost-tracker"` to the alphabetically sorted `integration` JSON list.
4. Open a pull request back to `hacs/default`.
5. Complete the HACS pull-request template and allow maintainer edits.
6. Resolve genuine validation failures; HACS maintainers perform the final review/merge.

Default-store review can take time. The custom-repository installation path remains usable while review is pending.

## Forks

Fork maintainers can use:

```bash
python scripts/set_github_owner.py NEW_OWNER
```

to update repository-owner metadata where supported by the script.
