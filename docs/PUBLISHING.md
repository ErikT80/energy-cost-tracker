# Publishing to GitHub and HACS

## 1. Set the GitHub owner

Before the first commit, replace all repository-owner placeholders:

```bash
python scripts/set_github_owner.py YOUR_GITHUB_USERNAME
```

The intended repository name is `energy-cost-tracker`. If you choose another repository name, also update the `documentation` and `issue_tracker` URLs in `custom_components/energy_cost_tracker/manifest.json`.

## 2. Create the public repository

Create a public GitHub repository with:

- Name: `energy-cost-tracker`
- Issues: enabled
- Description: `Financial energy accounting for Home Assistant with dynamic tariffs, solar and battery valuation.`
- Suggested topics: `home-assistant`, `hacs`, `energy`, `dynamic-tariffs`, `solar`, `battery`, `smart-home`

HACS validates repository-level description, topics and issue availability in addition to committed files.

## 3. Push the repository

Example with Git:

```bash
git init -b main
git add .
git commit -m "Initial Energy Cost Tracker alpha"
git remote add origin git@github.com:YOUR_GITHUB_USERNAME/energy-cost-tracker.git
git push -u origin main
```

HTTPS is also fine if that is how Git/Codex is authenticated.

## 4. Check GitHub Actions

The `Validate` workflow runs:

- unit tests
- Python compile check
- Home Assistant hassfest
- HACS validation

Do not publish the first release until all applicable checks are green. HACS validation cannot fully succeed locally because some checks depend on the public GitHub repository metadata.

## 5. Create a release

The manifest currently uses `0.1.0-alpha.1`. After the validation workflow succeeds:

```bash
git tag v0.1.0-alpha.1
git push origin v0.1.0-alpha.1
```

The release workflow verifies that the tag matches `manifest.json`, runs tests, creates `energy_cost_tracker.zip` and publishes a GitHub prerelease.

## 6. Add as a custom HACS repository

During alpha testing, users can add the GitHub repository to HACS as a custom integration repository. This does not require acceptance into the HACS default store.

## 7. HACS default-store submission later

Do this only after the integration has been tested by multiple users and is no longer an early alpha. Current HACS publication guidance requires a public GitHub repository, passing HACS + hassfest actions, a release, suitable repository metadata and brand assets.
