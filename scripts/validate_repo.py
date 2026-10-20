# SPDX-License-Identifier: Apache-2.0
#!/usr/bin/env python3
"""Validate repository metadata, integration assets, and Python syntax."""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOMAIN = "whistle_assist"
INTEGRATION_DIR = ROOT / "custom_components" / DOMAIN


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as err:
        fail(f"invalid JSON in {path.relative_to(ROOT)}: {err}")


def main() -> int:
    if not INTEGRATION_DIR.is_dir():
        fail(f"missing integration directory: {INTEGRATION_DIR.relative_to(ROOT)}")

    manifest_path = INTEGRATION_DIR / "manifest.json"
    manifest = read_json(manifest_path)
    required = {
        "domain", "name", "codeowners", "config_flow", "dependencies",
        "documentation", "integration_type", "iot_class", "issue_tracker",
        "requirements", "version",
    }
    missing = sorted(required - manifest.keys())
    if missing:
        fail(f"manifest missing required fields: {', '.join(missing)}")
    if manifest["domain"] != DOMAIN:
        fail("manifest domain does not match its folder")
    if not re.fullmatch(r"\d+\.\d+\.\d+", manifest["version"]):
        fail("manifest version must use numeric semantic versioning (x.y.z)")
    if "cactus-needle==3.2.8" not in manifest["requirements"]:
        fail("manifest must pin cactus-needle==3.2.8 exactly")
    if not manifest["codeowners"] or any(
        not isinstance(item, str)
        or not re.fullmatch(r"@[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?", item)
        for item in manifest["codeowners"]
    ):
        fail("manifest codeowners must contain at least one configured GitHub username; run scripts/prepare_repo.py")
    for key in ("documentation", "issue_tracker"):
        value = manifest[key]
        if not isinstance(value, str) or not value.startswith("https://github.com/") or "YOUR_GITHUB_USERNAME" in value:
            fail(f"manifest {key} must be configured to the public GitHub repository; run scripts/prepare_repo.py")
    if list(manifest.keys()) != ["domain", "name"] + sorted(set(manifest) - {"domain", "name"}):
        fail("manifest keys are not sorted as required by Home Assistant Hassfest")

    hacs = read_json(ROOT / "hacs.json")
    if not isinstance(hacs.get("name"), str) or not hacs["name"].strip():
        fail("hacs.json must include a non-empty name")

    icon_path = INTEGRATION_DIR / "brand" / "icon.png"
    if not icon_path.is_file():
        fail("missing brand asset custom_components/whistle_assist/brand/icon.png")
    try:
        from PIL import Image
        with Image.open(icon_path) as icon:
            if icon.format != "PNG" or icon.size != (256, 256):
                fail("brand icon must be a 256x256 PNG")
    except ImportError:
        # Pillow is optional: validate the PNG signature if unavailable.
        if icon_path.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n":
            fail("brand icon has an invalid PNG signature")

    python_files = sorted((ROOT / "custom_components").rglob("*.py")) + sorted((ROOT / "scripts").rglob("*.py"))
    for path in python_files:
        if not path.read_text(encoding="utf-8").startswith("# SPDX-License-Identifier: Apache-2.0"):
            fail(f"missing SPDX license identifier: {path.relative_to(ROOT)}")
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as err:
            fail(f"Python syntax error in {path.relative_to(ROOT)}: {err}")

    for path in ROOT.rglob("*"):
        if path.is_file() and (path.suffix in {".pyc", ".pyo"} or "__pycache__" in path.parts):
            fail(f"generated Python cache file found: {path.relative_to(ROOT)}")

    placeholder_tokens = ("YOUR_GITHUB_USERNAME", "Copyright [yyyy]", "[name of copyright owner]")
    for path in ROOT.rglob("*"):
        if path.is_file() and path.parent != ROOT / "scripts" and ".git" not in path.parts and "__pycache__" not in path.parts:
            try:
                content = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            if any(token in content for token in placeholder_tokens):
                fail(f"unfilled repository placeholder found in {path.relative_to(ROOT)}")

    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    if "Apache License" not in license_text or "Version 2.0" not in license_text:
        fail("LICENSE must contain the Apache License 2.0 text")
    if "Copyright [yyyy]" in license_text or "[name of copyright owner]" in license_text:
        fail("LICENSE contains an unfilled copyright template")
    notice = (ROOT / "NOTICE").read_text(encoding="utf-8")
    if "cactus-needle==3.2.8" not in notice or "cactus-compute/needle" not in notice:
        fail("NOTICE must identify and link the upstream Needle dependency")

    print("Repository contract checks passed.")
    print(f"Checked manifest v{manifest['version']}, pinned Needle 3.2.8, HACS metadata, brand icon, licenses, and {len(python_files)} Python files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
