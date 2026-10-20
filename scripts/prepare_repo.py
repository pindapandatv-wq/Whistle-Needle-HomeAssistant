# SPDX-License-Identifier: Apache-2.0
#!/usr/bin/env python3
"""Fill GitHub-specific metadata in a Whistle Assist repository template."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OWNER_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", default="pindapandatv-wq", help="GitHub user or organization name (default: pindapandatv-wq)")
    parser.add_argument("--repo", default="Whistle-Needle-HomeAssistant", help="GitHub repository name (default: Whistle-Needle-HomeAssistant)")
    args = parser.parse_args()

    if not OWNER_RE.fullmatch(args.owner):
        parser.error("--owner must be a GitHub username or organization slug (letters, digits, hyphens; no leading/trailing hyphen)")
    if not REPO_RE.fullmatch(args.repo) or args.repo in {".", ".."}:
        parser.error("--repo must be a valid GitHub repository name")

    manifest_path = ROOT / "custom_components" / "whistle_assist" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    base_url = f"https://github.com/{args.owner}/{args.repo}"
    manifest["codeowners"] = [f"@{args.owner}"]
    manifest["documentation"] = base_url
    manifest["issue_tracker"] = f"{base_url}/issues"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    for relative in ("README.md", ".github/CODEOWNERS", "PUBLISHING.md"):
        path = ROOT / relative
        text = path.read_text(encoding="utf-8")
        text = text.replace("YOUR_GITHUB_USERNAME", args.owner)
        text = text.replace("ha-cactus-assist", args.repo)
        path.write_text(text, encoding="utf-8")

    print(f"Configured repository metadata for {args.owner}/{args.repo}.")
    print("Review the diff, run scripts/validate_repo.py, then push the repository yourself.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
