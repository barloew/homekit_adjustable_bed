"""Detected-only forms, colour lights and stable IIDs."""

from datetime import timedelta
from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.data_entry_flow import section
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pyhap.accessory_driver import AccessoryDriver
from pyhap.loader import get_loader
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.homekit_bed.accessory import BedAccessory
from custom_components.homekit_bed.config_flow import offered_keys
from custom_components.homekit_bed.const import ALL_KEYS, DOMAIN
from custom_components.homekit_bed.iids import StableIIDManager

ADDR = "11:22:33:44:55:66"
POS = {"min": 0, "max": 100, "step": 1}


def _jensen_like(hass) -> str:
    """A bed that only has back/legs, two massages, flat and memory 1."""
    bed_entry = MockConfigEntry(domain="adjustable_bed", title="Jensen")
    bed_entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=bed_entry.entry_id,
        identifiers={("adjustable_bed", ADDR)},
        name="Barloew's bed",
    )
    reg = er.async_get(hass)
    for domain, key in [
        ("number", "back_position"),
        ("number", "legs_position"),
        ("number", "massage_head_intensity"),
        ("number", "massage_foot_intensity"),
        ("button", "preset_flat"),
        ("button", "preset_memory_1"),
    ]:
        reg.async_get_or_create(
            domain,
            "adjustable_bed",
            f"{ADDR}_{key}",
            device_id=device.id,
            config_entry=bed_entry,
            suggested_object_id=f"bed_{key}",
        )
    return device.id


def _fields(schema) -> set[str]:
    out = set()
    for value in schema.schema.values():
        if isinstance(value, section):
            out |= {str(k) for k in value.schema.schema}
    return out


async def test_only_detected_controls_and_lights_are_offered(hass: HomeAssistant) -> None:
    device_id = _jensen_like(hass)
    keys = offered_keys(hass, device_id, {})
    assert keys == [
        "back",
        "legs",
        "head_massage",
        "foot_massage",
        "light_level",
        "under_bed_light_level",
        "flat",
        "memory_1",
    ]
    # Already configured controls stay visible so they can be removed.
    assert "stop" in offered_keys(hass, device_id, {"stop": "script.x"})
    # Without a bed device: everything.
    assert offered_keys(hass, None, {}) == list(ALL_KEYS)


async def test_config_flow_shows_detected_only(hass: HomeAssistant, mock_async_zeroconf) -> None:
    device_id = _jensen_like(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with patch("custom_components.homekit_bed.config_flow.async_port_is_free", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"name": "Bed", "bed_device": device_id, "port": 21070}
        )
    fields = _fields(result["data_schema"])
    assert "tilt" not in fields and "fan_level" not in fields and "memory_2" not in fields
    assert {"back", "light_level", "under_bed_light_level", "memory_1"} <= fields


async def _driver(hass, tmp_path):
    loader = await hass.async_add_executor_job(get_loader)
    return AccessoryDriver(
        loop=hass.loop, address="127.0.0.1", port=0, persist_file=str(tmp_path / "s"), loader=loader
    )


def _later(hass, s):
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=s))


async def test_hue_light_gets_colour(hass: HomeAssistant, tmp_path) -> None:
    hass.states.async_set(
        "light.strip",
        "on",
        {
            "brightness": 255,
            "supported_color_modes": ["xy", "color_temp"],
            "color_mode": "xy",
            "hs_color": [200.0, 80.0],
            "color_temp_kelvin": None,
            "min_color_temp_kelvin": 2000,
            "max_color_temp_kelvin": 6535,
        },
    )
    hass.states.async_set(
        "light.lamp", "on", {"brightness": 128, "supported_color_modes": ["brightness"]}
    )
    calls = []

    async def _rec(call: ServiceCall) -> None:
        calls.append((call.service, dict(call.data)))

    hass.services.async_register("light", "turn_on", _rec)
    hass.services.async_register("light", "turn_off", _rec)
    entry = MockConfigEntry(domain=DOMAIN, title="Bed")
    entry.add_to_hass(hass)
    acc = BedAccessory(
        hass,
        await _driver(hass, tmp_path),
        entry,
        "Bed",
        [
            ("under_bed_light_level", "Onderbed", "light.strip", False),
            ("light_level", "Lamp", "light.lamp", False),
        ],
        [],
        manufacturer="J",
        model="M",
        serial="s",
        firmware="f",
    )
    acc.async_attach()
    strip, lamp = acc.sliders
    assert strip.char_hue.value == 200.0 and strip.char_sat.value == 80.0
    assert strip.char_ct.properties["minValue"] == 153  # 6535 K
    assert strip.char_ct.properties["maxValue"] == 500  # 2000 K
    assert lamp.char_hue is None and lamp.char_ct is None  # plain dimmable lamp

    strip.char_hue.client_update_value(30)
    strip.char_sat.client_update_value(100)
    _later(hass, 1)
    await hass.async_block_till_done()
    assert (
        "turn_on",
        {"entity_id": "light.strip", "brightness_pct": 100, "hs_color": [30.0, 100.0]},
    ) in calls
    calls.clear()
    strip.char_ct.client_update_value(370)
    _later(hass, 2)
    await hass.async_block_till_done()
    assert calls[-1][1]["color_temp_kelvin"] == 2703
    acc.async_detach()


async def test_colour_known_while_light_unavailable(hass: HomeAssistant, tmp_path) -> None:
    """Registry capabilities keep colour after a start with the lamp offline."""
    reg = er.async_get(hass)
    reg.async_get_or_create(
        "light",
        "hue",
        "strip1",
        suggested_object_id="strip",
        capabilities={"supported_color_modes": ["xy"]},
    )
    hass.states.async_set("light.strip", "unavailable")
    entry = MockConfigEntry(domain=DOMAIN, title="Bed")
    entry.add_to_hass(hass)
    acc = BedAccessory(
        hass,
        await _driver(hass, tmp_path),
        entry,
        "Bed",
        [("light_level", "Lamp", "light.strip", False)],
        [],
        manufacturer="J",
        model="M",
        serial="s",
        firmware="f",
    )
    assert acc.sliders[0].char_hue is not None


# --------------------------------------------------------------------- IIDs
def _iids(acc) -> dict[str, int]:
    out = {}
    for svc in acc.services:
        sk = f"{svc.type_id}|{svc.unique_id}"
        out[sk] = acc.iid_manager.get_iid(svc)
        for c in svc.characteristics:
            out[f"{sk}|{c.type_id}"] = acc.iid_manager.get_iid(c)
    return out


async def test_iids_stable_when_controls_and_colour_are_added(
    hass: HomeAssistant, tmp_path
) -> None:
    for e, v in [("number.a", "0"), ("number.b", "0"), ("number.t", "0")]:
        hass.states.async_set(e, v, POS)
    hass.states.async_set("button.f", "unknown")
    hass.states.async_set(
        "light.l", "on", {"brightness": 10, "supported_color_modes": ["brightness"]}
    )
    entry = MockConfigEntry(domain=DOMAIN, title="Bed")
    entry.add_to_hass(hass)
    common = {"manufacturer": "J", "model": "M", "serial": "s", "firmware": "f"}

    # 3.2 layout with pyhap's default (counting) manager
    old = BedAccessory(
        hass,
        await _driver(hass, tmp_path),
        entry,
        "Bed",
        [
            ("back", "Rug", "number.a", True),
            ("legs", "Benen", "number.b", True),
            ("light_level", "Lamp", "light.l", False),
        ],
        [("flat", "Vlak", "button.f")],
        **common,
    )
    # First 3.3 start: no stored map -> must reproduce the same IIDs
    mgr = StableIIDManager({})
    seeded = BedAccessory(
        hass,
        await _driver(hass, tmp_path),
        entry,
        "Bed",
        [
            ("back", "Rug", "number.a", True),
            ("legs", "Benen", "number.b", True),
            ("light_level", "Lamp", "light.l", False),
        ],
        [("flat", "Vlak", "button.f")],
        iid_manager=mgr,
        **common,
    )
    assert _iids(seeded) == _iids(old)

    # Later: tilt added in the middle and the lamp became a colour lamp
    hass.states.async_set(
        "light.l", "on", {"brightness": 10, "supported_color_modes": ["hs"], "hs_color": [10, 10]}
    )
    newer = BedAccessory(
        hass,
        await _driver(hass, tmp_path),
        entry,
        "Bed",
        [
            ("back", "Rug", "number.a", True),
            ("legs", "Benen", "number.b", True),
            ("tilt", "Kussen", "number.t", True),
            ("light_level", "Lamp", "light.l", False),
        ],
        [("flat", "Vlak", "button.f")],
        iid_manager=StableIIDManager(mgr.map),
        **common,
    )
    before, after = _iids(old), _iids(newer)
    assert all(after[k] == v for k, v in before.items())  # nothing moved
    new_ids = [v for k, v in after.items() if k not in before]
    assert new_ids and min(new_ids) > max(before.values())  # new ones appended


async def test_colour_can_be_turned_off_per_light(hass: HomeAssistant, tmp_path) -> None:
    """Colour off: plain dimmable light, other IIDs untouched, colour IIDs reused."""
    hass.states.async_set(
        "light.strip",
        "on",
        {"brightness": 255, "supported_color_modes": ["xy"], "hs_color": [1, 2]},
    )
    hass.states.async_set("button.f", "unknown")
    entry = MockConfigEntry(domain=DOMAIN, title="Bed")
    entry.add_to_hass(hass)
    common = {"manufacturer": "J", "model": "M", "serial": "s", "firmware": "f"}
    sliders = [("under_bed_light_level", "Onderbedlicht", "light.strip", False)]
    actions = [("flat", "Vlak", "button.f")]

    mgr = StableIIDManager({})
    with_color = BedAccessory(
        hass,
        await _driver(hass, tmp_path),
        entry,
        "Bed",
        sliders,
        actions,
        iid_manager=mgr,
        **common,
    )
    assert with_color.sliders[0].char_hue is not None
    before = _iids(with_color)

    without = BedAccessory(
        hass,
        await _driver(hass, tmp_path),
        entry,
        "Bed",
        sliders,
        actions,
        iid_manager=StableIIDManager(mgr.map),
        color_off={"under_bed_light_level"},
        **common,
    )
    assert without.sliders[0].char_hue is None and without.sliders[0].char_ct is None
    after = _iids(without)
    assert all(before[k] == v for k, v in after.items())

    again = BedAccessory(
        hass,
        await _driver(hass, tmp_path),
        entry,
        "Bed",
        sliders,
        actions,
        iid_manager=StableIIDManager(mgr.map),
        **common,
    )
    assert _iids(again) == before  # colour back on: same IIDs as before


async def _controls_form(hass, options):
    entry = MockConfigEntry(
        domain=DOMAIN, version=2, data={"name": "Bed", "port": 21070}, options=options
    )
    entry.add_to_hass(hass)
    with patch("custom_components.homekit_bed.async_setup_entry", return_value=True):
        await hass.config_entries.async_setup(entry.entry_id)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["menu_options"] == ["controls", "pairing"]
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "controls"}
    )
    return entry, result


async def test_colour_and_inverted_in_controls_form(
    hass: HomeAssistant, mock_async_zeroconf
) -> None:
    entry, result = await _controls_form(
        hass,
        {
            "back": "number.a",
            "under_bed_light_level": "light.bed",
            "flat": "button.f",
            "label_back": "Hoofdeinde",
            "label_under_bed_light_level": "Onderbedlicht",
            "label_flat": "Vlak",
        },
    )
    schema = result["data_schema"].schema
    comfort = [str(k) for k in next(v for k, v in schema.items() if k == "comfort").schema.schema]
    assert comfort[comfort.index("under_bed_light_level") + 1] == "color_under_bed_light_level"
    layout = next(v for k, v in schema.items() if k == "layout").schema.schema
    inv = layout[next(k for k in layout if k == "inverted")]
    assert [o["value"] for o in inv.config["options"]] == ["back"]  # blinds only
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "positions": {"back": "number.a"},
            "comfort": {"under_bed_light_level": "light.bed", "color_under_bed_light_level": False},
            "switches": {"flat": "button.f"},
            "captions": {
                "label_back": "Hoofdeinde",
                "label_under_bed_light_level": "Onderbedlicht",
                "label_flat": "Vlak",
            },
            "layout": {"primary_control": "back", "enforce_captions": True, "inverted": ["back"]},
        },
    )
    await hass.config_entries.options.async_configure(result["flow_id"], {"save": True})
    assert entry.options["inverted"] == ["back"]
    assert entry.options["color_under_bed_light_level"] is False
