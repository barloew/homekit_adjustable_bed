"""Release notes for one version, taken from CHANGELOG.md.

Usage: python tools/release_notes.py 5.0.0 [--changelog CHANGELOG.md]

Prints the section "## 5.0.0" of the changelog as GitHub release notes. Subsections
("### What's New", "### Bug Fixes") become the release headings; a section without
subsections is published under "## What's New". Used by .github/workflows/release.yml.
Standard library only, so the workflow needs no dependencies.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def release_notes(changelog: str, version: str) -> str:
    """The notes of one version; ValueError when the changelog has no such section."""
    match = re.search(rf"^## {re.escape(version)}[ \t]*$", changelog, flags=re.MULTILINE)
    if not match:
        raise ValueError(f"CHANGELOG.md has no section '## {version}'")
    rest = changelog[match.end() :]
    following = re.search(r"^## ", rest, flags=re.MULTILINE)
    body = (rest[: following.start()] if following else rest).strip()
    if not body:
        raise ValueError(f"The section '## {version}' in CHANGELOG.md is empty")
    if re.search(r"^### ", body, flags=re.MULTILINE):
        return re.sub(r"^### ", "## ", body, flags=re.MULTILINE) + "\n"
    return f"## What's New\n{body}\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("version", help="version without the leading v, for example 5.0.0")
    parser.add_argument("--changelog", default=str(ROOT / "CHANGELOG.md"))
    args = parser.parse_args(argv)
    try:
        notes = release_notes(Path(args.changelog).read_text(), args.version.removeprefix("v"))
    except ValueError as err:
        print(err, file=sys.stderr)
        return 1
    sys.stdout.write(notes)
    return 0


if __name__ == "__main__":
    sys.exit(main())
