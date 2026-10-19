"""Release notes taken from CHANGELOG.md (tools/release_notes.py)."""

from __future__ import annotations

from pathlib import Path

import pytest

from custom_components.homekit_adjustable_bed.const import VERSION
from tools.release_notes import main, release_notes

ROOT = Path(__file__).parents[1]

CHANGELOG = """# Changelog

## Unreleased
- Pending.

## 2.0.0
### What's New
- New thing.

### Bug Fixes
- Fixed thing.

## 1.0.0
- First.
"""


def test_subsections_become_release_headings() -> None:
    assert release_notes(CHANGELOG, "2.0.0") == (
        "## What's New\n- New thing.\n\n## Bug Fixes\n- Fixed thing.\n"
    )


def test_plain_section_is_whats_new() -> None:
    assert release_notes(CHANGELOG, "1.0.0") == "## What's New\n- First.\n"


@pytest.mark.parametrize("version", ["3.0.0", "2.0"])
def test_unknown_version_is_an_error(version: str) -> None:
    with pytest.raises(ValueError):
        release_notes(CHANGELOG, version)


def test_cli_accepts_a_tag(tmp_path, capsys) -> None:
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(CHANGELOG)
    assert main(["v1.0.0", "--changelog", str(changelog)]) == 0
    assert capsys.readouterr().out == "## What's New\n- First.\n"
    assert main(["9.9.9", "--changelog", str(changelog)]) == 1


def test_current_version_has_release_notes() -> None:
    """A tag of the current version must find its notes, or the release workflow fails."""
    notes = release_notes((ROOT / "CHANGELOG.md").read_text(), VERSION)
    assert "## What's New" in notes
