"""Repository requirements of HACS and hassfest that the code does not otherwise exercise."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).parents[1]
INTEGRATION = ROOT / "custom_components" / "homekit_adjustable_bed"


@pytest.mark.parametrize(
    ("name", "size"),
    [
        ("icon.png", 256),
        ("icon@2x.png", 512),
        ("dark_icon.png", 256),
        ("dark_icon@2x.png", 512),
    ],
)
def test_brand_images(name: str, size: int) -> None:
    """HACS needs brand/icon.png; Home Assistant 2026.3+ shows these images."""
    with Image.open(INTEGRATION / "brand" / name) as image:
        assert image.format == "PNG"
        assert image.size == (size, size)
        assert image.mode == "RGBA"  # transparent background
        # trimmed: the drawing touches at least two opposite edges
        left, top, right, bottom = image.getbbox() or (0, 0, 0, 0)
        assert (left, right) == (0, size) or (top, bottom) == (0, size)


def test_hacs_json() -> None:
    data = json.loads((ROOT / "hacs.json").read_text())
    allowed = {
        "content_in_root",
        "country",
        "filename",
        "hacs",
        "hide_default_branch",
        "homeassistant",
        "persistent_directory",
        "render_readme",
        "zip_release",
        "name",
    }
    assert data["name"]
    assert set(data) <= allowed
    assert data.get("content_in_root") is False


def test_manifest_requirements_are_not_pinned() -> None:
    """Hassfest rejects pins of packages Home Assistant itself depends on."""
    manifest = json.loads((INTEGRATION / "manifest.json").read_text())
    assert all("==" not in req for req in manifest["requirements"])
    for key in ("codeowners", "documentation", "issue_tracker", "version"):
        assert key in manifest


def test_license_is_mit() -> None:
    assert (ROOT / "LICENSE").read_text().startswith("MIT License")
