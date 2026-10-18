"""Detection defaults per bed family (entity sets modelled on ha-adjustable-bed).

These are representative entity keys per family, not a dump of real beds:
they check that every structural pattern gets a sensible HomeKit default.
"""

import pytest
from homeassistant.core import HomeAssistant

from custom_components.homekit_adjustable_bed.detection import detect_controls

from .test_detection import _bed

FAMILIES = {
    # Okin / Keeson style: covers without position, many presets, buttons.
    "okin_keeson": (
        [
            ("cover", "back"),
            ("cover", "legs"),
            ("button", "stop"),
            ("button", "preset_flat"),
            ("button", "preset_zero_g"),
            ("button", "preset_anti_snore"),
            ("button", "preset_tv"),
            *[("button", f"preset_memory_{i}") for i in range(1, 5)],
            *[("button", f"program_memory_{i}") for i in range(1, 5)],
            ("button", "back_up"),
            ("button", "back_down"),
            ("button", "massage_head_toggle"),
            ("button", "massage_foot_toggle"),
            ("button", "massage_head_up"),
            ("button", "massage_mode_step"),
            ("button", "toggle_light"),
        ],
        {
            "back",
            "legs",
            "stop",
            "flat",
            "preset_zero_g",
            "preset_anti_snore",
            "preset_tv",
            "memory_1",
            "memory_2",
            "memory_3",
            "memory_4",
            "massage_head_toggle",
            "massage_foot_toggle",
            "light_toggle",
        },
    ),
    # Linak: four sections, real light, settings switch.
    "linak": (
        [
            ("cover", "back"),
            ("cover", "legs"),
            ("cover", "head"),
            ("cover", "feet"),
            ("button", "stop"),
            *[("button", f"preset_memory_{i}") for i in range(1, 5)],
            *[("button", f"program_memory_{i}") for i in range(1, 5)],
            ("light", "under_bed_lights"),
            ("switch", "linak_automatic_drive"),
            ("button", "toggle_light"),
        ],
        {
            "back",
            "legs",
            "head",
            "feet",
            "stop",
            "memory_1",
            "memory_2",
            "memory_3",
            "memory_4",
            "under_bed_light_level",
        },
    ),
    # Reverie / Octo style: position numbers next to covers, massage levels.
    "positions_and_massage": (
        [
            ("cover", "head"),
            ("cover", "feet"),
            ("number", "head_position"),
            ("number", "feet_position"),
            ("number", "massage_head_intensity"),
            ("number", "massage_foot_intensity"),
            ("button", "preset_flat"),
            ("button", "preset_zero_g"),
            ("button", "stop"),
        ],
        # head/feet position numbers take the ids of the head/foot section
        {"back", "legs", "head_massage", "foot_massage", "flat", "preset_zero_g", "stop"},
    ),
    # Jiecang split: left = back/legs, right = right_*, plus combined covers.
    "jiecang_split": (
        [
            ("cover", "back"),
            ("cover", "legs"),
            ("cover", "right_back"),
            ("cover", "right_legs"),
            ("cover", "both_backs"),
            ("cover", "both_legs"),
            ("cover", "both"),
            ("button", "preset_flat"),
            ("button", "stop"),
        ],
        {"back", "legs", "right_back", "right_legs", "flat", "stop"},
    ),
    # Single bed with a "Back + Legs" cover besides the separate ones.
    "combined_motor": (
        [
            ("cover", "back"),
            ("cover", "legs"),
            ("cover", "back_legs"),
            ("cover", "head_feet"),
            ("button", "preset_flat"),
        ],
        # head_feet stays: the bed has no separate head/feet section
        {"back", "legs", "head_feet", "flat"},
    ),
    # Only a combined cover: then it is the slider.
    "only_combined": (
        [("cover", "back_legs"), ("button", "preset_flat")],
        {"back_legs", "flat"},
    ),
    # Sleep Number split: sides, both-variants, firmness, climate, selects.
    "sleep_number_split": (
        [
            ("cover", "back_left"),
            ("cover", "back_right"),
            ("cover", "legs_left"),
            ("cover", "legs_right"),
            ("button", "preset_flat_left"),
            ("button", "preset_flat_right"),
            ("button", "preset_flat_both"),
            ("button", "stop_left"),
            ("button", "stop_right"),
            ("button", "stop_both"),
            ("number", "sleep_number_setting_left"),
            ("number", "sleep_number_setting_right"),
            ("climate", "sleep_number_thermal_climate_left"),
            ("climate", "sleep_number_thermal_climate_right"),
            ("climate", "footwarming_climate_left"),
            ("select", "foundation_preset_left"),
            ("select", "foundation_preset_right"),
            ("select", "thermal_timer_left"),
            ("light", "under_bed_lights"),
            ("button", "sync_positions"),
        ],
        {
            "back_left",
            "back_right",
            "legs_left",
            "legs_right",
            "preset_flat_both",
            "stop_both",
            "sleep_number_setting_left",
            "sleep_number_setting_right",
            "sleep_number_thermal_climate_left",
            "sleep_number_thermal_climate_right",
            "footwarming_climate_left",
            "foundation_preset_left",
            "foundation_preset_right",
            "under_bed_light_level",
        },
    ),
}


@pytest.mark.parametrize("family", sorted(FAMILIES))
async def test_family_defaults(hass: HomeAssistant, family: str) -> None:
    keys, expected = FAMILIES[family]
    device_id = _bed(hass, keys)
    controls = detect_controls(hass, device_id)
    shown = {c.control_id for c in controls if c.exposed}
    assert shown == expected, (family, shown ^ expected)
    # Never a maintenance action, never two sliders for one section and side.
    assert not any(
        c.key.startswith(("program_memory", "factory", "connect")) and c.exposed for c in controls
    )
    ids = [c.control_id for c in controls]
    assert len(ids) == len(set(ids))  # ids unique


@pytest.mark.parametrize("family", sorted(FAMILIES))
async def test_family_fields_have_names(hass: HomeAssistant, family: str) -> None:
    """Every detected control of every family has a name in the options form."""
    import json
    from pathlib import Path

    base = (
        Path(__file__).parents[1] / "custom_components" / "homekit_adjustable_bed" / "translations"
    )
    keys, _ = FAMILIES[family]
    device_id = _bed(hass, keys)
    for lang in ("en", "nl"):
        secs = json.loads((base / f"{lang}.json").read_text())["options"]["step"]["controls"][
            "sections"
        ]
        for c in detect_controls(hass, device_id):
            assert secs[c.group]["data"].get(c.control_id), (lang, family, c.group, c.control_id)
