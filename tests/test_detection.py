"""Feature detection -> HomeKit controls, and automatic registration."""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pyhap.accessory_driver import AccessoryDriver
from pyhap.loader import get_loader
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.homekit_bed.accessory import BedAccessory
from custom_components.homekit_bed.const import DOMAIN
from custom_components.homekit_bed.controls import effective_controls
from custom_components.homekit_bed.detection import classify, detect_controls

ADDR = "AA:BB:CC:00:11:22"

JENSEN = [  # what ha-adjustable-bed creates for a JMC400 (app-stored memories)
    ("number", "back_position"),
    ("number", "legs_position"),
    ("cover", "back"),
    ("cover", "legs"),
    ("number", "massage_head_intensity"),
    ("number", "massage_foot_intensity"),
    ("number", "massage_wave_intensity"),
    ("number", "light_level"),
    ("number", "fan_level"),
    ("button", "preset_flat"),
    ("button", "stop"),
    *[("button", f"preset_memory_{i}") for i in range(1, 5)],
    *[("button", f"program_memory_{i}") for i in range(1, 5)],
    ("button", "back_up"),
    ("button", "back_down"),
    ("button", "legs_up"),
    ("button", "legs_down"),
    ("button", "massage_all_toggle"),
    ("button", "massage_head_toggle"),
    ("button", "massage_foot_toggle"),
    ("button", "toggle_light"),
    ("button", "factory_reset"),
    ("button", "connect"),
    ("sensor", "back_angle"),
    ("binary_sensor", "ble_connection"),
]


def _bed(hass, keys, name="Barloew's bed") -> str:
    bed_entry = MockConfigEntry(domain="adjustable_bed", title="Bed")
    bed_entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=bed_entry.entry_id, identifiers={("adjustable_bed", ADDR)}, name=name
    )
    reg = er.async_get(hass)
    for domain, key in keys:
        reg.async_get_or_create(
            domain,
            "adjustable_bed",
            f"{ADDR}_{key}",
            device_id=device.id,
            config_entry=bed_entry,
            suggested_object_id=f"bed_{key}",
            original_name=key.replace("_", " ").capitalize(),
        )
    return device.id


async def test_jensen_defaults(hass: HomeAssistant) -> None:
    device_id = _bed(hass, JENSEN)
    controls = {c.key: c for c in detect_controls(hass, device_id)}
    shown = {k for k, c in controls.items() if c.exposed}
    assert shown == {
        "back_position",
        "legs_position",
        "stop",
        "preset_flat",
        "preset_memory_1",
        "preset_memory_2",
        "preset_memory_3",
        "preset_memory_4",
        "massage_head_intensity",
        "massage_foot_intensity",
        "massage_wave_intensity",
        "massage_all_toggle",
        "massage_head_toggle",
        "massage_foot_toggle",
        "light_level",
        "fan_level",
    }
    # One slider per section; save/reset/connect never shown by default.
    assert not controls["back"].exposed and not controls["back_up"].exposed
    assert not controls["program_memory_1"].exposed
    assert not controls["factory_reset"].exposed and not controls["connect"].exposed
    assert not controls["toggle_light"].exposed  # light level slider covers it
    assert "back_angle" not in controls  # read-only sensors are not controls
    # Legacy ids keep HomeKit identity and captions of existing setups.
    assert controls["back_position"].control_id == "back"
    assert controls["preset_memory_3"].control_id == "memory_3"
    assert controls["massage_all_toggle"].control_id == "massage_toggle"
    assert controls["fan_level"].hk_type == "fan" and controls["light_level"].hk_type == "light"


async def test_cover_only_bed_and_split_sides(hass: HomeAssistant) -> None:
    device_id = _bed(
        hass,
        [
            ("cover", "back_left"),
            ("cover", "back_right"),
            ("cover", "tilt"),
            ("button", "back_up_left"),
            ("button", "preset_zero_g_both"),
            ("light", "under_bed_lights"),
            ("switch", "under_bed_lights"),
            ("select", "foundation_preset_left"),
            ("select", "massage_timer"),
            ("switch", "synchro_mode"),
            ("button", "some_vendor_action"),
        ],
    )
    c = {x.key: x for x in detect_controls(hass, device_id)}
    assert c["back_left"].exposed and c["back_right"].exposed and c["tilt"].exposed
    assert c["back_left"].side == "left" and c["back_left"].control_id == "back_left"
    assert not c["back_up_left"].exposed  # the cover is the slider
    assert c["preset_zero_g_both"].exposed
    assert c["under_bed_lights"].hk_type in ("light", "switch")
    lights = [x for x in detect_controls(hass, device_id) if x.base == "under_bed_lights"]
    assert [x.domain for x in lights if x.exposed] == ["light"]  # switch is redundant
    assert c["foundation_preset_left"].hk_type == "select" and c["foundation_preset_left"].exposed
    assert not c["massage_timer"].exposed and not c["synchro_mode"].exposed
    assert c["some_vendor_action"].hk_type == "momentary" and not c["some_vendor_action"].exposed


def test_every_known_key_is_classified_or_ignored() -> None:
    """All entity keys of ha-adjustable-bed get a HomeKit type (or are sensors/climate)."""
    for domain, key in [
        ("button", "preset_memory_6_right"),
        ("cover", "malouf_full_tilt"),
        ("number", "sleep_number_setting_left"),
        ("select", "thermal_timer_both"),
        ("switch", "linak_automatic_drive"),
    ]:
        assert classify(domain, key) is not None
    climate = classify("climate", "sleep_number_thermal_climate_left")
    assert climate.hk_type == "climate_fan" and climate.exposed and climate.side == "left"
    assert classify("climate", "footwarming_climate").exposed
    assert classify("sensor", "head_angle") is None


async def test_auto_registration_merges_manual_lamp(hass: HomeAssistant) -> None:
    device_id = _bed(hass, JENSEN)
    hass.config.language = "en"
    options = {
        "auto_register": True,
        "under_bed_light_level": "light.hue_strip",
        "label_under_bed_light_level": "Onderbedlicht",
        "label_back": "Hoofdeinde",
    }
    labels = {
        "back": "Head section",
        "under_bed_light_level": "Under bed light",
        "memory_1": "Memory 1",
        "flat": "Flat",
    }
    controls = effective_controls(hass, {"bed_device": device_id}, options, labels)
    ids = [c.id for c in controls]
    assert "back" in ids and "memory_4" in ids and "under_bed_light_level" in ids
    back = next(c for c in controls if c.id == "back")
    assert back.caption == "Hoofdeinde" and back.motor and back.hk_type == "cover"
    lamp = next(c for c in controls if c.id == "under_bed_light_level")
    assert lamp.entity_id == "light.hue_strip" and lamp.hk_type == "light"
    # Selection overrides the defaults
    options["auto_controls"] = ["back", "flat"]
    ids = {c.id for c in effective_controls(hass, {"bed_device": device_id}, options, labels)}
    assert ids == {"back", "flat", "under_bed_light_level"}
    # Manual mode ignores detection
    ids = {
        c.id
        for c in effective_controls(hass, {"bed_device": device_id}, {"back": "number.x"}, labels)
    }
    assert ids == {"back"}


async def test_select_as_switch_group(hass: HomeAssistant, tmp_path) -> None:
    hass.states.async_set("select.preset", "Flat", {"options": ["Flat", "Zero G", "Read"]})
    calls = []

    async def _select_option(call) -> None:
        calls.append(dict(call.data))

    hass.services.async_register("select", "select_option", _select_option)
    entry = MockConfigEntry(domain=DOMAIN, title="Bed")
    entry.add_to_hass(hass)
    loader = await hass.async_add_executor_job(get_loader)
    driver = AccessoryDriver(
        loop=hass.loop, address="127.0.0.1", port=0, persist_file=str(tmp_path / "s"), loader=loader
    )
    acc = BedAccessory(
        hass,
        driver,
        entry,
        "Bed",
        [],
        [("stop", "Stop", "button.s")],
        manufacturer="J",
        model="M",
        serial="s",
        firmware="f",
        selects=[("foundation_preset_left", "Voorkeur", "select.preset")],
    )
    acc.async_attach()
    group = acc.selects[0]
    assert [c.value for c in group.chars.values()] == [True, False, False]
    group.chars["Zero G"].client_update_value(True)
    await hass.async_block_till_done()
    assert calls == [{"entity_id": "select.preset", "option": "Zero G"}]
    assert group.chars["Flat"].value is False
    names = [s.get_characteristic("ConfiguredName").value for s in group.services]
    assert names == ["Voorkeur Flat", "Voorkeur Zero G", "Voorkeur Read"]
    acc.async_detach()


async def test_sleep_number_climate_as_fan(hass: HomeAssistant, tmp_path) -> None:
    hass.states.async_set(
        "climate.thermal",
        "cool",
        {
            "hvac_modes": ["off", "cool", "heat"],
            "preset_mode": "medium",
            "preset_modes": ["low", "medium", "high", "boost"],
        },
    )
    hass.states.async_set(
        "climate.feet",
        "off",
        {
            "hvac_modes": ["off", "heat"],
            "preset_mode": None,
            "preset_modes": ["low", "medium", "high"],
        },
    )
    calls = []

    async def _rec(call):
        calls.append((call.service, dict(call.data)))

    for service in ("turn_on", "turn_off", "set_preset_mode", "set_hvac_mode"):
        hass.services.async_register("climate", service, _rec)
    entry = MockConfigEntry(domain=DOMAIN, title="Bed")
    entry.add_to_hass(hass)
    loader = await hass.async_add_executor_job(get_loader)
    driver = AccessoryDriver(
        loop=hass.loop, address="127.0.0.1", port=0, persist_file=str(tmp_path / "s"), loader=loader
    )
    acc = BedAccessory(
        hass,
        driver,
        entry,
        "Bed",
        [],
        [],
        manufacturer="S",
        model="N",
        serial="s",
        firmware="f",
        climates=[
            ("thermal", "Klimaat", "climate.thermal"),
            ("feet", "Voetverwarming", "climate.feet"),
        ],
        mode_names={"cool": "Koelen", "heat": "Verwarmen"},
    )
    acc.async_attach()
    thermal, feet = acc.climates
    # On, cooling, medium of 4 presets (with boost) -> 50 %
    assert thermal.char_active.value == 1 and thermal.char_speed.value == 50
    assert thermal.mode_chars["cool"].value is True and thermal.mode_chars["heat"].value is False
    names = [
        s.get_characteristic("ConfiguredName").value
        for s in acc.services
        if s.display_name == "Switch"
    ]
    assert names == ["Klimaat Koelen", "Klimaat Verwarmen"]
    # Footwarming is heat only: a fan without mode switches, off
    assert feet.mode_chars == {} and feet.char_active.value == 0

    thermal.char_speed.client_update_value(30)  # ceil(30*4/100)=2 -> "medium"
    feet.char_speed.client_update_value(100)  # -> "high", turns it on
    from datetime import timedelta

    from homeassistant.util import dt as dt_util
    from pytest_homeassistant_custom_component.common import async_fire_time_changed

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=1))
    await hass.async_block_till_done()
    assert ("set_preset_mode", {"entity_id": "climate.thermal", "preset_mode": "medium"}) in calls
    assert ("set_preset_mode", {"entity_id": "climate.feet", "preset_mode": "high"}) in calls

    calls.clear()
    thermal.mode_chars["heat"].client_update_value(True)
    await hass.async_block_till_done()
    assert calls == [("set_hvac_mode", {"entity_id": "climate.thermal", "hvac_mode": "heat"})]
    assert thermal.mode_chars["cool"].value is False

    calls.clear()
    thermal.char_active.client_update_value(0)
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=3))
    await hass.async_block_till_done()
    assert calls == [("turn_off", {"entity_id": "climate.thermal"})]

    # State from the bed: heating, low (3 presets without boost) -> 33 %
    hass.states.async_set(
        "climate.thermal",
        "heat",
        {
            "hvac_modes": ["off", "cool", "heat"],
            "preset_mode": "low",
            "preset_modes": ["low", "medium", "high"],
        },
    )
    await hass.async_block_till_done()
    assert thermal.char_speed.value == 33 and thermal.mode_chars["heat"].value is True
    acc.async_detach()


async def test_sleep_number_detection(hass: HomeAssistant) -> None:
    device_id = _bed(
        hass,
        [
            ("climate", "sleep_number_thermal_climate_left"),
            ("climate", "footwarming_climate_left"),
            ("number", "sleep_number_setting_left"),
            ("select", "thermal_timer_left"),
        ],
    )
    c = {x.key: x for x in detect_controls(hass, device_id)}
    assert c["sleep_number_thermal_climate_left"].hk_type == "climate_fan"
    assert c["footwarming_climate_left"].exposed
    assert c["sleep_number_setting_left"].hk_type == "cover"  # firmness
    assert not c["thermal_timer_left"].exposed


async def test_translation_key_wins_over_unique_id(hass: HomeAssistant) -> None:
    """Entities are recognised by translation_key, whatever the unique_id looks like."""
    bed_entry = MockConfigEntry(domain="adjustable_bed", title="Bed")
    bed_entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=bed_entry.entry_id, identifiers={("adjustable_bed", "x")}, name="Bed"
    )
    reg = er.async_get(hass)
    for domain, key in (("number", "back_position"), ("button", "preset_memory_2")):
        reg.async_get_or_create(
            domain,
            "adjustable_bed",
            f"opaque-{key}-id",
            device_id=device.id,
            config_entry=bed_entry,
            translation_key=key,
            suggested_object_id=f"bed_{key}",
        )
    ids = {c.control_id for c in detect_controls(hass, device.id) if c.exposed}
    assert ids == {"back", "memory_2"}
