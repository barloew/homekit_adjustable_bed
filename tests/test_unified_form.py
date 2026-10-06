"""Linked bed: one list of HomeKit controls; removing/adding moves between lists."""

import json
from pathlib import Path
from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import section
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.homekit_bed.const import DOMAIN
from custom_components.homekit_bed.controls import effective_controls, normalize_options
from custom_components.homekit_bed.detection import detect_controls

from .test_detection import ADDR, JENSEN, _bed

BASE = Path(__file__).parents[1] / "custom_components" / "homekit_bed"
LANGS = {p.stem: json.loads(p.read_text()) for p in (BASE / "translations").glob("*.json")}


def _sections(result) -> dict[str, list[str]]:
    out = {}
    for marker, value in result["data_schema"].schema.items():
        if isinstance(value, section):
            out[str(marker)] = [str(k) for k in value.schema.schema]
    return out


def _add_options(result) -> list[str]:
    for marker, value in result["data_schema"].schema.items():
        if str(marker) == "add":
            sel = value.schema.schema[next(iter(value.schema.schema))]
            return [o["value"] for o in sel.config["options"]]
    return []


def _submit_unchanged(result, **changes):
    """What the frontend sends back: every shown field with its value."""
    data = {}
    for marker, value in result["data_schema"].schema.items():
        if not isinstance(value, section):
            continue
        part = {}
        for key in value.schema.schema:
            suggested = (key.description or {}).get("suggested_value")
            default = key.default() if callable(key.default) else None
            val = suggested if suggested is not None else default
            if val not in (None, "", []):
                part[str(key)] = val
        data[str(marker)] = part
    for path, val in changes.items():
        sec, key = path.split("__")
        if val is None:
            data[sec].pop(key, None)
        else:
            data[sec][key] = val
    return data


async def _open(hass, options):
    device_id = _bed(hass, JENSEN)
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        data={"name": "Bed", "port": 21070, "bed_device": device_id},
        options=options,
    )
    entry.add_to_hass(hass)
    with patch("custom_components.homekit_bed.async_setup_entry", return_value=True):
        await hass.config_entries.async_setup(entry.entry_id)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "controls"}
    )
    return entry, device_id, result


async def test_remove_and_add_move_between_lists(hass: HomeAssistant, mock_async_zeroconf) -> None:
    entry, device_id, result = await _open(
        hass,
        {
            "auto_register": True,
            "under_bed_light_level": "light.hue_strip",
            "label_under_bed_light_level": "Onderbedlicht",
            "label_back": "Hoofdeinde",
        },
    )
    secs = _sections(result)
    assert "memory_1" in secs["presets"] and "back" in secs["positions"]
    assert "under_bed_light_level" in secs["lighting"]  # the Hue lamp
    assert "memory_1" not in _add_options(result)
    assert "program_memory_1" in _add_options(result)  # available, not in HomeKit

    # Clear Memory 1 -> it leaves Presets and appears under "add"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], _submit_unchanged(result, presets__memory_1=None)
    )
    assert result["step_id"] == "controls"
    assert "memory_1" not in _sections(result)["presets"]
    assert "memory_1" in _add_options(result)

    # Add it back plus "Save to Memory 1" -> both appear in Presets
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        _submit_unchanged(result, add__add_controls=["memory_1", "program_memory_1"]),
    )
    presets = _sections(result)["presets"]
    assert "memory_1" in presets and "program_memory_1" in presets
    assert "memory_1" not in _add_options(result)

    # Submit without changes -> preview -> save
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], _submit_unchanged(result)
    )
    assert result["step_id"] == "preview"
    await hass.config_entries.options.async_configure(result["flow_id"], {"save": True})
    o = entry.options
    assert o["hidden_controls"] == [] and o["added_controls"] == ["program_memory_1"]
    assert o["entity_overrides"] == {"under_bed_light_level": "light.hue_strip"}
    assert "auto_register" not in o and "auto_controls" not in o  # legacy keys gone
    assert o["label_back"] == "Hoofdeinde"


async def test_other_entity_is_stored_as_override(hass: HomeAssistant, mock_async_zeroconf) -> None:
    entry, _, result = await _open(hass, {"auto_register": True})
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], _submit_unchanged(result, presets__flat="script.my_flat")
    )
    assert result["step_id"] == "preview"
    await hass.config_entries.options.async_configure(result["flow_id"], {"save": True})
    assert entry.options["entity_overrides"] == {"flat": "script.my_flat"}


async def test_new_detected_control_follows_defaults(hass: HomeAssistant) -> None:
    """Only exceptions are stored: a control detected later just appears."""
    device_id = _bed(hass, JENSEN)
    options = {"hidden_controls": ["memory_4"], "added_controls": [], "entity_overrides": {}}
    ids = {c.id for c in effective_controls(hass, {"bed_device": device_id}, options, {})}
    assert "memory_4" not in ids and "memory_5" not in ids
    reg = er.async_get(hass)
    bed_entry = hass.config_entries.async_entries("adjustable_bed")[0]
    reg.async_get_or_create(
        "button",
        "adjustable_bed",
        f"{ADDR}_preset_memory_5",
        device_id=device_id,
        config_entry=bed_entry,
        suggested_object_id="bed_preset_memory_5",
    )
    ids = {c.id for c in effective_controls(hass, {"bed_device": device_id}, options, {})}
    assert "memory_5" in ids and "memory_4" not in ids


async def test_legacy_manual_options_keep_homekit_as_it_was(hass: HomeAssistant) -> None:
    device_id = _bed(hass, JENSEN)
    legacy = {
        "back": "number.bed_back_position",
        "memory_1": "button.bed_preset_memory_1",
        "under_bed_light_level": "light.hue_strip",
    }
    model = normalize_options(detect_controls(hass, device_id), legacy)
    ids = {c.id for c in effective_controls(hass, {"bed_device": device_id}, model, {})}
    assert ids == {"back", "memory_1", "under_bed_light_level"}


async def test_every_field_translated(hass: HomeAssistant, mock_async_zeroconf) -> None:
    every = [{"auto_register": True, "added_controls": [d.control_id for d in []]}]
    entry, device_id, result = await _open(hass, every[0])
    # add everything that is available, so all fields are rendered
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], _submit_unchanged(result, add__add_controls=_add_options(result))
    )
    for name, lang in LANGS.items():
        secs = lang["options"]["step"]["controls"]["sections"]
        for sec, fields in _sections(result).items():
            assert secs[sec]["name"], (name, sec)
            for field in fields:
                assert secs[sec]["data"].get(field), (name, sec, field)


async def test_legacy_auto_untick_is_respected(hass: HomeAssistant) -> None:
    """4.1 options: Memory 1 unticked in the list but still linked by hand -> stays out."""
    device_id = _bed(hass, JENSEN)
    legacy = {
        "auto_register": True,
        "auto_controls": ["back", "legs", "flat"],
        "memory_1": "button.bed_preset_memory_1",
        "under_bed_light_level": "light.hue_strip",
    }
    model = normalize_options(detect_controls(hass, device_id), legacy)
    ids = {c.id for c in effective_controls(hass, {"bed_device": device_id}, model, {})}
    assert ids == {"back", "legs", "flat", "under_bed_light_level"}
    assert "memory_1" in model["hidden_controls"]
