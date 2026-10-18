"""Config flow with auto detection of ha-adjustable-bed entities."""

from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.homekit_adjustable_bed.config_flow import autodetect_entities
from custom_components.homekit_adjustable_bed.const import DOMAIN

ADDR = "AA:BB:CC:DD:EE:FF"


def _make_bed(hass: HomeAssistant) -> str:
    bed_entry = MockConfigEntry(domain="adjustable_bed", title="Jensen")
    bed_entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=bed_entry.entry_id,
        identifiers={("adjustable_bed", ADDR)},
        name="Jensen bed",
        manufacturer="Jensen",
        model="JMC400",
    )
    reg = er.async_get(hass)
    for domain, key in [
        ("number", "back_position"),
        ("number", "legs_position"),
        ("number", "massage_head_intensity"),
        ("number", "massage_foot_intensity"),
        ("number", "massage_wave_intensity"),
        ("button", "preset_flat"),
        ("button", "preset_memory_1"),
        ("button", "preset_memory_2"),
        ("button", "preset_memory_3"),
        ("button", "preset_memory_4"),
        ("button", "program_memory_1"),
        ("cover", "back"),
        ("cover", "tilt"),
        ("number", "light_level"),
        ("number", "fan_level"),
        ("light", "under_bed_lights"),
        ("button", "stop"),
        ("button", "massage_all_toggle"),
        ("button", "toggle_light"),
    ]:
        reg.async_get_or_create(
            domain,
            "adjustable_bed",
            f"{ADDR}_{key}",
            device_id=device.id,
            config_entry=bed_entry,
            suggested_object_id=f"jensen_bed_{key}",
        )
    return device.id


async def test_autodetect(hass: HomeAssistant) -> None:
    device_id = _make_bed(hass)
    found = autodetect_entities(hass, device_id)
    assert found == {
        "back": "number.jensen_bed_back_position",
        "legs": "number.jensen_bed_legs_position",
        "head_massage": "number.jensen_bed_massage_head_intensity",
        "foot_massage": "number.jensen_bed_massage_foot_intensity",
        "wave_massage": "number.jensen_bed_massage_wave_intensity",
        "flat": "button.jensen_bed_preset_flat",
        "memory_1": "button.jensen_bed_preset_memory_1",
        "memory_2": "button.jensen_bed_preset_memory_2",
        "memory_3": "button.jensen_bed_preset_memory_3",
        "memory_4": "button.jensen_bed_preset_memory_4",
        "tilt": "cover.jensen_bed_tilt",
        "light_level": "number.jensen_bed_light_level",
        "fan_level": "number.jensen_bed_fan_level",
        "under_bed_light_level": "light.jensen_bed_under_bed_lights",
        "stop": "button.jensen_bed_stop",
        "massage_toggle": "button.jensen_bed_massage_all_toggle",
        "light_toggle": "button.jensen_bed_toggle_light",
        "under_bed_light_toggle": "light.jensen_bed_under_bed_lights",
    }


async def test_full_flow(hass: HomeAssistant, mock_async_zeroconf) -> None:
    device_id = _make_bed(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    from custom_components.homekit_adjustable_bed.vol import vol

    for marker in result["data_schema"].schema:
        if marker == "bed_device":
            assert marker.default is vol.UNDEFINED
            assert marker.description == {"suggested_value": device_id}
    with patch(
        "custom_components.homekit_adjustable_bed.config_flow.async_port_is_free",
        return_value=True,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"name": "Bed", "bed_device": device_id, "port": 21070},
        )
    # A detected bed gets the same grouped form as the options.
    assert result["step_id"] == "bed_controls"
    assert result["description_placeholders"]["name"] == "Bed"
    from .test_unified_form import _sections, _submit_unchanged

    secs = _sections(result)
    assert "back" in secs["positions"] and "stop" in secs["presets"]
    with patch("custom_components.homekit_adjustable_bed.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], _submit_unchanged(result)
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["port"] == 21070
    assert result["options"]["hidden_controls"] == []  # detection defaults
    assert result["options"]["label_back"] in ("Head section", "Rugdeel")
    assert "label_lumbar" not in result["options"]  # not on this bed: no caption


async def test_no_controls_error(hass: HomeAssistant, mock_async_zeroconf) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with patch(
        "custom_components.homekit_adjustable_bed.config_flow.async_port_is_free",
        return_value=True,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"name": "Bed", "port": 21071}
        )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"positions": {}, "comfort": {}, "switches": {}}
    )
    assert result["errors"] == {"base": "no_controls"}


async def test_migrate_v1(hass: HomeAssistant, tmp_path) -> None:
    """v1 single 'memory' becomes memory_1 and the old pairing is dropped."""
    from custom_components.homekit_adjustable_bed import async_migrate_entry
    from custom_components.homekit_adjustable_bed.server import legacy_persist_file_path

    entry = MockConfigEntry(
        domain=DOMAIN,
        version=1,
        data={"name": "Bed", "port": 21070},
        options={
            "back": "number.a",
            "legs": "number.b",
            "memory": "button.m",
            "label_memory": "Memory positie",
        },
    )
    entry.add_to_hass(hass)
    legacy = legacy_persist_file_path(hass, entry.entry_id)
    import os

    os.makedirs(os.path.dirname(legacy), exist_ok=True)
    with open(legacy, "w") as file:
        file.write("{}")
    assert await async_migrate_entry(hass, entry)
    assert entry.version == 2
    assert entry.options["memory_1"] == "button.m"
    assert "memory" not in entry.options
    assert entry.options["label_memory_1"] == "Memory 1"
    assert not os.path.exists(legacy)


async def test_options_preview(hass: HomeAssistant, mock_async_zeroconf) -> None:
    """Options show the expected grid and only save after the preview."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        data={"name": "Bed", "port": 21070},
        options={
            "back": "number.a",
            "legs": "number.b",
            "flat": "button.f",
            "label_back": "Hoofdeinde",
            "label_legs": "Voeteinde",
            "label_flat": "Bed vlak",
        },
    )
    entry.add_to_hass(hass)
    with patch("custom_components.homekit_adjustable_bed.async_setup_entry", return_value=True):
        await hass.config_entries.async_setup(entry.entry_id)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "controls"}
    )
    assert "| Hoofdeinde | Bed vlak |" in result["description_placeholders"]["preview"]
    new = {
        "positions": {"back": "number.a", "legs": "number.b"},
        "comfort": {},
        "switches": {"flat": "button.f"},
        "captions": {"label_back": "Rug", "label_legs": "Benen", "label_flat": "Vlak"},
        "layout": {"primary_control": "back", "enforce_captions": True},
    }
    result = await hass.config_entries.options.async_configure(result["flow_id"], new)
    assert result["step_id"] == "preview"
    assert "| Rug | Benen |\n| Vlak |  |" in result["description_placeholders"]["preview"]
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"save": False})
    assert result["step_id"] == "controls"
    result = await hass.config_entries.options.async_configure(result["flow_id"], new)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"save": True})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["label_back"] == "Rug"
    assert "positions" not in entry.options  # sections are flattened
