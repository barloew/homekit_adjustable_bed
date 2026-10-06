"""One version everywhere (release process in AGENTS.md)."""

import json
import tomllib
from pathlib import Path

from custom_components.homekit_bed.const import VERSION

ROOT = Path(__file__).parents[1]


def test_versions_match() -> None:
    manifest = json.loads((ROOT / "custom_components/homekit_bed/manifest.json").read_text())
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    assert manifest["version"] == project["version"] == VERSION


def test_requirements_match() -> None:
    """manifest.json requirements are the runtime dependencies in pyproject.toml."""
    manifest = json.loads((ROOT / "custom_components/homekit_bed/manifest.json").read_text())
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    assert sorted(manifest["requirements"]) == sorted(project["dependencies"])
