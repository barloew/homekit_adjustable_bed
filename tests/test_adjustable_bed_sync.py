"""HomeKit Bed against the Adjustable Bed release in tests/fixtures/adjustable_bed.json.

The fixture is written by tools/sync_adjustable_bed.py. These tests fail when the integration
falls behind that release: an entity without a HomeKit type or form name, a timed_move motor
HomeKit Bed does not offer, or documentation that no longer matches.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from custom_components.homekit_bed.const import TIMED_MOTORS
from custom_components.homekit_bed.detection import (
    _CATALOG_IDS,
    DETECTION_GROUPS,
    G_FIRMNESS,
    G_LIGHTING,
    G_MASSAGE,
    G_POSITIONS,
    G_SETTINGS,
    classify,
)
from tools import sync_adjustable_bed as sync

ROOT = Path(__file__).parents[1]
FIXTURE = json.loads((ROOT / "tests" / "fixtures" / "adjustable_bed.json").read_text())
ENTITIES = [
    (domain, key, name)
    for domain, entries in FIXTURE["entities"].items()
    for key, name in entries.items()
]


def _form_names(lang: str) -> dict[str, str]:
    data = json.loads(
        (ROOT / "custom_components" / "homekit_bed" / "translations" / f"{lang}.json").read_text()
    )
    sections = data["options"]["step"]["controls"]["sections"]
    return {
        key: name
        for group in DETECTION_GROUPS
        for key, name in sections.get(group, {}).get("data", {}).items()
    } | sections["captions"]["data"]


def test_fixture_is_a_real_release() -> None:
    assert FIXTURE["ref"].startswith("v")
    assert len(FIXTURE["commit"]) == 40
    assert len(FIXTURE["bed_types"]) > 50
    assert len(ENTITIES) > 500


def test_every_entity_gets_a_homekit_type() -> None:
    missing = [(d, k) for d, k, _ in ENTITIES if classify(d, k) is None]
    assert missing == []


@pytest.mark.parametrize("lang", ["en", "nl"])
def test_every_entity_has_a_form_and_caption_name(lang: str) -> None:
    names = _form_names(lang)
    missing = []
    for domain, key, _ in ENTITIES:
        control = classify(domain, key)
        assert control is not None
        ids = {key, f"{domain}_{key}"} if key in _CATALOG_IDS else {key}
        if not ids & names.keys() or not {f"label_{i}" for i in ids} & names.keys():
            missing.append(f"{domain}.{key}")
    assert missing == [], "run tools/sync_adjustable_bed.py --offline"


def test_every_entity_is_named_in_its_own_group() -> None:
    data = json.loads(
        (ROOT / "custom_components" / "homekit_bed" / "translations" / "en.json").read_text()
    )
    sections = data["options"]["step"]["controls"]["sections"]
    for domain, key, _ in ENTITIES:
        control = classify(domain, key)
        assert control is not None
        if key in _CATALOG_IDS:
            continue
        assert key in sections[control.group]["data"], f"{domain}.{key} not in {control.group}"


def test_timed_motors_follow_the_timed_move_action() -> None:
    assert list(TIMED_MOTORS) == FIXTURE["timed_motors"]


def test_supported_beds_doc_is_current() -> None:
    doc = (ROOT / "docs" / "SUPPORTED_BEDS.md").read_text()
    assert doc == sync.render_beds_doc(FIXTURE), "run tools/sync_adjustable_bed.py --offline"
    for bed_type in FIXTURE["bed_types"]:
        assert f"`{bed_type}`" in doc


def test_readme_names_the_checked_release() -> None:
    readme = (ROOT / "README.md").read_text()
    assert f"checked against v{FIXTURE['version']}" in readme


def test_maintenance_never_on_by_default() -> None:
    for domain, key, _ in ENTITIES:
        control = classify(domain, key)
        assert control is not None
        if control.source != "rule":
            assert not control.exposed, f"{domain}.{key}"


@pytest.mark.parametrize(
    ("domain", "key", "group"),
    [
        ("button", "vmatbasic_massage_back", G_MASSAGE),
        ("button", "vmatbasic_massage_program_1", G_MASSAGE),
        ("number", "richmat_mh_head_massage_intensity", G_MASSAGE),
        ("select", "richmat_mh_waist_left_heat", G_MASSAGE),
        ("button", "vibradorm_app_mood_toggle", G_LIGHTING),
        ("number", "starcode_abm5_4_light_level", G_LIGHTING),
        ("button", "logicdata_air_pump_inflate", G_FIRMNESS),
        ("button", "vmatbasic_all_up", G_POSITIONS),
        ("button", "starcode_save_zero_g", G_SETTINGS),
        ("button", "ore_comfort_program_flat", G_SETTINGS),
        ("button", "logicdata_air_pump_save_memory", G_SETTINGS),
        ("button", "remacro_led_brightness_save", G_SETTINGS),
        ("button", "sleeptracker_refresh", G_SETTINGS),
    ],
)
def test_vendor_controls_grouped_by_keyword(domain: str, key: str, group: str) -> None:
    control = classify(domain, key)
    assert control is not None
    assert (control.group, control.source, control.exposed) == (group, "keyword", False)


def test_compare_reports_beds_entities_and_renames() -> None:
    old = {
        "version": "1.0.0",
        "bed_types": {"a": "Bed A", "b": "Bed B"},
        "entities": {"button": {"old_key": "Flat", "same": "Same"}},
        "timed_motors": ["back"],
        "services": ["stop_all"],
    }
    new = {
        "version": "1.1.0",
        "bed_types": {"a": "Bed A v2", "c": "Bed C"},
        "entities": {"button": {"new_key": "Flat", "same": "Same", "extra": "Extra"}},
        "timed_motors": ["back", "tilt"],
        "services": ["stop_all", "timed_move"],
    }
    diff = sync.compare(old, new)
    assert diff["beds_added"] == {"c": "Bed C"}
    assert diff["beds_removed"] == {"b": "Bed B"}
    assert diff["beds_renamed"] == {"a": ("Bed A", "Bed A v2")}
    assert diff["entities_added"] == ["button.extra", "button.new_key"]
    assert diff["entities_removed"] == ["button.old_key"]
    assert diff["entities_renamed"] == [("button.old_key", "button.new_key")]
    assert diff["motors_added"] == ["tilt"]
    assert diff["services_added"] == ["timed_move"]


def test_changelog_entry_is_replaced_not_stacked(tmp_path, monkeypatch) -> None:
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("# Changelog\n\n## 1.0.0\n- Old.\n")
    monkeypatch.setattr(sync, "CHANGELOG", changelog)
    sync.update_changelog(["- Synced with Adjustable Bed v1.", "  - New bed types: A."], None)
    sync.update_changelog(["- Synced with Adjustable Bed v2."], None)
    text = changelog.read_text()
    assert text.count("Synced with") == 1
    assert "v2." in text and "New bed types" not in text
    assert text.index("## Unreleased") < text.index("## 1.0.0")
