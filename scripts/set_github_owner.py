#!/usr/bin/env python3
"""Replace repository-owner placeholders before first publication."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLACEHOLDER = "REPLACE_WITH_GITHUB_USERNAME"
FILES = [
    ROOT / "README.md",
    ROOT / "custom_components" / "energy_cost_tracker" / "manifest.json",
    ROOT / ".github" / "CODEOWNERS",
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("github_username", help="GitHub username or organization owner")
    args = parser.parse_args()
    username = args.github_username.strip().lstrip("@")
    if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?", username):
        raise SystemExit("Invalid GitHub username/organization name")

    for path in FILES:
        text = path.read_text(encoding="utf-8")
        path.write_text(text.replace(PLACEHOLDER, username), encoding="utf-8")

    manifest_path = ROOT / "custom_components" / "energy_cost_tracker" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["codeowners"] = [f"@{username}"]
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Repository owner set to {username}")


if __name__ == "__main__":
    main()
