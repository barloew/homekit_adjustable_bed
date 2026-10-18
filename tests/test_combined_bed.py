"""Combined bed (parent "Ons Bed" with children per side)."""

from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.homekit_adjustable_bed.detection import _entity_key, detect_controls


def test_pair_unique_ids() -> None:
    assert _entity_key("pair_0a1b2c3d4e5f_preset_flat") == "preset_flat"
    assert _entity_key("AA:BB:CC:DD:EE:FF_back_position") == "back_position"
    assert _entity_key("pair_0a1b2c3d4e5f_stop") == "stop"


def _setup(hass):
    entry = MockConfigEntry(domain="adjustable_bed", title="Ons Bed")
    entry.add_to_hass(hass)
    devreg, reg = dr.async_get(hass), er.async_get(hass)
    parent = devreg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={("adjustable_bed", "pair_0a1b2c3d4e5f")},
        name="Ons Bed",
        manufacturer="Jensen",
        model="JMC400",
    )
    kids = {}
    for name, addr in (
        ("Barloew's bed", "AA:AA:AA:AA:AA:01"),
        ("Snork Maiden's bed", "AA:AA:AA:AA:AA:02"),
    ):
        # A real HA 2026.9 child device, as ha-adjustable-bed creates them.
        kid = devreg.async_get_or_create_child(
            config_entry_id=entry.entry_id,
            identifiers={("adjustable_bed", addr)},
            name=name,
            parent_device_id=parent.id,
        )
        kids[name] = kid.id
        for domain, key in (
            ("number", "back_position"),
            ("button", "preset_memory_1"),
            ("button", "preset_flat"),
        ):
            reg.async_get_or_create(
                domain,
                "adjustable_bed",
                f"{addr}_{key}",
                device_id=kid.id,
                config_entry=entry,
                suggested_object_id=f"{name[:5]}_{key}",
            )
    for domain, key in (
        ("button", "preset_flat"),
        ("button", "stop"),
        ("button", "preset_memory_1"),
        ("cover", "back"),
    ):
        reg.async_get_or_create(
            domain,
            "adjustable_bed",
            f"pair_0a1b2c3d4e5f_{key}",
            device_id=parent.id,
            config_entry=entry,
            suggested_object_id=f"ons_bed_{key}",
        )
    return parent.id, kids


async def test_parent_uses_only_its_own_controls(hass: HomeAssistant) -> None:
    parent, kids = _setup(hass)

    controls = detect_controls(hass, parent)  # real child devices
    entities = {c.entity_id for c in controls}
    assert entities == {
        "button.ons_bed_preset_flat",
        "button.ons_bed_stop",
        "button.ons_bed_preset_memory_1",
        "cover.ons_bed_back",
    }
    assert {c.control_id for c in controls if c.exposed} == {"flat", "stop", "memory_1", "back"}
    # A side keeps working on its own
    assert {c.control_id for c in detect_controls(hass, kids["Barloew's bed"]) if c.exposed} == {
        "back",
        "memory_1",
        "flat",
    }


async def test_combined_form_has_two_light_slots(hass: HomeAssistant, mock_async_zeroconf) -> None:

    parent, kids = _setup(hass)

    entry = MockConfigEntry(
        domain="homekit_adjustable_bed",
        version=2,
        data={"name": "Ons Bed", "port": 21070, "bed_device": parent},
        options={},
    )
    entry.add_to_hass(hass)
    with (
        patch("custom_components.homekit_adjustable_bed.async_setup_entry", return_value=True),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"next_step_id": "controls"}
        )
    lighting = next(v for k, v in result["data_schema"].schema.items() if str(k) == "lighting")
    fields = [str(k) for k in lighting.schema.schema]
    assert [f for f in fields if not f.startswith("color_")] == [
        "light_level_left",
        "light_level_right",
        "under_bed_light_level_left",
        "under_bed_light_level_right",
    ]
    presets = next(v for k, v in result["data_schema"].schema.items() if str(k) == "presets")
    assert {str(k) for k in presets.schema.schema} == {"flat", "memory_1", "stop"}  # no duplicates


def test_renamed_slots_migrate() -> None:
    from custom_components.homekit_adjustable_bed.controls import migrate_renamed

    old = {
        "entity_overrides": {"light_level_2": "light.hue"},
        "label_light_level_2": "Lamp Snork Maiden",
        "color_under_bed_light_level_2": False,
        "primary_control": "light_level_2",
    }
    assert migrate_renamed(old) == {
        "entity_overrides": {"light_level_right": "light.hue"},
        "label_light_level_right": "Lamp Snork Maiden",
        "color_under_bed_light_level_right": False,
        "primary_control": "light_level_right",
    }


async def test_hardware_info_of_real_child(hass: HomeAssistant, caplog) -> None:
    """Manufacturer/model come from the parent; the child is never asked."""
    from custom_components.homekit_adjustable_bed.devices import hardware_info

    _parent, kids = _setup(hass)
    assert hardware_info(hass, kids["Barloew's bed"]) == ("Jensen", "JMC400")
    assert "ChildDeviceEntry" not in caplog.text
