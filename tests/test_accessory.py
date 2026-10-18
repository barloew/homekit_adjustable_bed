"""Behaviour of the aggregated HomeKit accessory."""

import asyncio
from datetime import timedelta

import pytest
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.util import dt as dt_util
from pyhap.accessory_driver import AccessoryDriver
from pyhap.loader import get_loader
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.homekit_adjustable_bed.accessory import (
    POS_INCREASING,
    POS_STOPPED,
    BedAccessory,
    BedBridge,
)

BACK = "number.bed_back_position"
LEGS = "number.bed_legs_position"
HEAD_M = "number.bed_massage_head_intensity"
FOOT_M = "number.bed_massage_foot_intensity"
WAVE_M = "number.bed_massage_wave_intensity"
FLAT = "button.bed_flat"
MEMORY = "button.bed_memory_1"
MEMORIES = [MEMORY] + [f"button.bed_memory_{i}" for i in (2, 3, 4)]

POS_ATTRS = {"min": 0, "max": 100, "step": 1}
MASSAGE_ATTRS = {"min": 0, "max": 10, "step": 1}


@pytest.fixture
async def bed(hass: HomeAssistant, tmp_path):
    """Build the accessory on a driver that is never started."""
    hass.states.async_set(BACK, "20", POS_ATTRS)
    hass.states.async_set(LEGS, "0", POS_ATTRS)
    hass.states.async_set(HEAD_M, "0", MASSAGE_ATTRS)
    hass.states.async_set(FOOT_M, "3", MASSAGE_ATTRS)
    hass.states.async_set(WAVE_M, "0", MASSAGE_ATTRS)
    hass.states.async_set(FLAT, "unknown")
    for mem in MEMORIES:
        hass.states.async_set(mem, "unknown")

    calls: list[tuple[str, str, dict]] = []
    move_gate = asyncio.Event()
    move_gate.set()

    async def _number_set(call: ServiceCall) -> None:
        calls.append(("number", "set_value", dict(call.data)))
        if call.data["entity_id"] in (BACK, LEGS):
            await move_gate.wait()  # emulate a monitored (blocking) move

    async def _press(call: ServiceCall) -> None:
        calls.append(("button", "press", dict(call.data)))
        if call.data["entity_id"] == MEMORY:
            raise ValueError("Jensen memory slot 1 has not been saved yet")

    hass.services.async_register("number", "set_value", _number_set)
    hass.services.async_register("button", "press", _press)

    entry = MockConfigEntry(domain="homekit_adjustable_bed", title="Bed")
    entry.add_to_hass(hass)
    loader = await hass.async_add_executor_job(get_loader)
    driver = AccessoryDriver(
        loop=hass.loop,
        address="127.0.0.1",
        port=0,
        persist_file=str(tmp_path / "state"),
        loader=loader,
    )
    acc = BedAccessory(
        hass,
        driver,
        entry,
        "Bed",
        [
            ("back", "Rug", BACK, True),
            ("legs", "Benen", LEGS, True),
            ("head_massage", "Hoofdmassage", HEAD_M, False),
            ("foot_massage", "Voetmassage", FOOT_M, False),
            ("wave_massage", "Massagegolf", WAVE_M, False),
        ],
        [("flat", "Bed vlak", FLAT)]
        + [(f"memory_{i}", f"Memory {i}", MEMORIES[i - 1]) for i in range(1, 5)],
        manufacturer="Jensen",
        model="JMC400",
        serial="x",
        firmware="1.0.0",
    )
    bridge = BedBridge(driver, "Bed HomeKit")
    bridge.add_accessory(acc)
    await hass.async_add_executor_job(driver.add_accessory, bridge)
    acc.async_attach()
    yield acc, calls, move_gate
    acc.async_detach()


def _later(hass, seconds):
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=seconds))


NAME = "23"
CONFIGURED_NAME = "E3"


async def test_structure(bed) -> None:
    acc, _, _ = bed
    hap_all = acc.driver.accessory.to_HAP()
    assert [a["aid"] for a in hap_all] == [1, 2]  # bridge + bed
    hap = next(a for a in hap_all if a["aid"] == 2)
    types = [s["type"] for s in hap["services"]]
    assert types.count("8C") == 5  # WindowCovering: rug, benen, 3x massage
    assert types.count("49") == 5  # Switch: vlak + memory 1-4
    primaries = [s for s in hap["services"] if s.get("primary")]
    assert len(primaries) == 1
    assert not any(s.get("linked") for s in hap["services"])


async def test_captions(bed) -> None:
    """Every control carries its caption in Name and ConfiguredName."""
    acc, _, _ = bed
    hap = next(a for a in acc.driver.accessory.to_HAP() if a["aid"] == 2)
    captions = []
    for svc in hap["services"]:
        if svc["type"] not in ("8C", "49"):
            continue
        chars = {c["type"]: c for c in svc["characteristics"]}
        assert chars[NAME]["value"] == chars[CONFIGURED_NAME]["value"]
        assert "pw" in chars[CONFIGURED_NAME]["perms"]
        captions.append(chars[CONFIGURED_NAME]["value"])
    assert captions == [
        "Rug",
        "Benen",
        "Hoofdmassage",
        "Voetmassage",
        "Massagegolf",
        "Bed vlak",
        "Memory 1",
        "Memory 2",
        "Memory 3",
        "Memory 4",
    ]


async def test_home_default_name_is_pushed_back(hass, bed) -> None:
    """Home writes 'Jaloezieën 1'; our caption is re-asserted and notified."""
    acc, _, _ = bed
    char = acc.sliders[0].service.get_characteristic("ConfiguredName")
    published = []
    acc.driver.publish = lambda data, *a, **k: published.append(data)
    char.client_update_value("Jaloezieën 1", ("10.0.0.2", 5000))
    assert char.value == "Jaloezieën 1"
    _later(hass, 3)
    await hass.async_block_till_done()
    assert char.value == "Rug"
    assert any(d.get("value") == "Rug" for d in published)


async def test_rename_kept_when_not_enforced(hass, bed) -> None:
    acc, _, _ = bed
    acc.enforce_captions = False
    char = acc.sliders[0].service.get_characteristic("ConfiguredName")
    char.client_update_value("Rugleuning")
    _later(hass, 3)
    await hass.async_block_till_done()
    assert char.value == "Rugleuning"


async def test_push_captions_notifies_all(hass, bed) -> None:
    acc, _, _ = bed
    published = []
    acc.driver.publish = lambda data, *a, **k: published.append(data)
    acc.async_push_captions()
    assert len(published) == 10


async def test_wave_slider(hass, bed) -> None:
    acc, calls, _ = bed
    acc.sliders[4].char_target.client_update_value(30)
    _later(hass, 1)
    await hass.async_block_till_done()
    assert ("number", "set_value", {"entity_id": WAVE_M, "value": 3}) in calls


async def test_memory_3_pressed(hass, bed) -> None:
    acc, calls, _ = bed
    acc.actions[3].char_on.client_update_value(True)
    await hass.async_block_till_done()
    assert ("button", "press", {"entity_id": MEMORIES[2]}) in calls
    # Massage sliders snap to 10 % (0-10 levels), motors to 1 %.
    assert acc.sliders[2].char_target.properties["minStep"] == 10
    assert acc.sliders[0].char_target.properties["minStep"] == 1


async def test_initial_state(bed) -> None:
    acc, _, _ = bed
    back, legs, head, foot, _wave = acc.sliders
    assert back.char_current.value == 20 and back.char_target.value == 20
    assert legs.char_current.value == 0
    assert head.char_current.value == 0
    assert foot.char_current.value == 30


async def test_massage_maps_to_level(hass, bed) -> None:
    acc, calls, _ = bed
    acc.sliders[2].char_target.client_update_value(60)
    _later(hass, 1)
    await hass.async_block_till_done()
    assert ("number", "set_value", {"entity_id": HEAD_M, "value": 6}) in calls
    assert acc.sliders[2].char_current.value == 60


async def test_debounce_only_last_value(hass, bed) -> None:
    acc, calls, _ = bed
    for v in (10, 30, 50):
        acc.sliders[3].char_target.client_update_value(v)
    _later(hass, 1)
    await hass.async_block_till_done()
    sent = [c for c in calls if c[2]["entity_id"] == FOOT_M]
    assert sent == [("number", "set_value", {"entity_id": FOOT_M, "value": 5})]


async def test_motor_moves_are_serialised(hass, bed) -> None:
    acc, calls, gate = bed
    gate.clear()
    back, legs = acc.sliders[0], acc.sliders[1]
    back.char_target.client_update_value(60)
    assert back.char_state.value == POS_INCREASING
    _later(hass, 1)
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    legs.char_target.client_update_value(40)
    _later(hass, 2)
    await asyncio.sleep(0.05)
    moves = [c[2]["entity_id"] for c in calls]
    assert moves == [BACK]  # legs waits for the back move to finish

    # Bed reports progress; target stays, state follows.
    hass.states.async_set(BACK, "45", POS_ATTRS)
    await asyncio.sleep(0)
    assert back.char_current.value == 45 and back.char_target.value == 60

    gate.set()
    await asyncio.sleep(0.05)
    assert [c[2]["entity_id"] for c in calls] == [BACK, LEGS]
    hass.states.async_set(BACK, "59", POS_ATTRS)
    hass.states.async_set(LEGS, "40", POS_ATTRS)
    _later(hass, 5)
    await hass.async_block_till_done()
    assert back.char_target.value == 59 and back.char_state.value == POS_STOPPED


async def test_external_change_followed(hass, bed) -> None:
    acc, _, _ = bed
    hass.states.async_set(LEGS, "35", POS_ATTRS)
    await hass.async_block_till_done()
    legs = acc.sliders[1]
    assert legs.char_current.value == 35 and legs.char_target.value == 35


async def test_flat_is_momentary_and_clears_queue(hass, bed) -> None:
    acc, calls, gate = bed
    gate.clear()
    acc.sliders[0].char_target.client_update_value(80)
    acc.sliders[1].char_target.client_update_value(80)
    _later(hass, 1)
    await asyncio.sleep(0.05)
    flat = acc.actions[0]
    flat.char_on.client_update_value(True)
    await asyncio.sleep(0.05)
    assert ("button", "press", {"entity_id": FLAT}) in calls
    assert not acc.motion._pending  # queued legs move was dropped
    gate.set()
    _later(hass, 3)
    await hass.async_block_till_done()
    assert flat.char_on.value is False
    assert LEGS not in [c[2]["entity_id"] for c in calls]


async def test_memory_unsaved_slot_notifies(hass, bed) -> None:
    acc, _, _ = bed
    acc.actions[1].char_on.client_update_value(True)
    await hass.async_block_till_done()
    from homeassistant.components import persistent_notification as pn

    stored = pn._async_get_or_create_notifications(hass)
    msg = next(iter(stored.values()))["message"]
    assert "program_memory_1" in msg and "Save to Memory 1" in msg


def test_layout_matches_barloews_bed() -> None:
    """The observed tile: primary first, the rest alphabetical, rows of two."""
    from custom_components.homekit_adjustable_bed.layout import predicted_order

    controls = [
        ("back", "Hoofdeinde"),
        ("legs", "Voeteinde"),
        ("head_massage", "Hoofdmassage"),
        ("foot_massage", "Voetmassage"),
        ("flat", "Bed vlak"),
        ("memory_1", "Memory 1"),
    ]
    order = [label for _, label in predicted_order(controls, "back")]
    assert order == [
        "Hoofdeinde",
        "Bed vlak",
        "Hoofdmassage",
        "Memory 1",
        "Voeteinde",
        "Voetmassage",
    ]


async def test_primary_can_be_any_control(hass, tmp_path) -> None:
    """Exactly one service is primary, also when it is a switch."""
    from custom_components.homekit_adjustable_bed.accessory import BedAccessory

    hass.states.async_set("number.a", "0", POS_ATTRS)
    hass.states.async_set("button.f", "unknown")
    entry = MockConfigEntry(domain="homekit_adjustable_bed", title="Bed")
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
        [("back", "Rug", "number.a", True)],
        [("flat", "Bed vlak", "button.f")],
        manufacturer="J",
        model="M",
        serial="s",
        firmware="f",
        primary_key="flat",
    )
    assert acc.actions[0].service.is_primary_service is True
    assert acc.sliders[0].service.is_primary_service is False


async def test_light_fan_and_stateful_switch(hass, tmp_path) -> None:
    """Lightbulb/Fanv2 level services and a switch that mirrors real state."""
    from custom_components.homekit_adjustable_bed.accessory import BedAccessory

    hass.states.async_set("number.light_level", "0", MASSAGE_ATTRS)
    hass.states.async_set("number.fan_level", "4", MASSAGE_ATTRS)
    hass.states.async_set("light.under_bed", "on", {"brightness": 128})
    hass.states.async_set("switch.ubl", "off")
    calls = []

    async def _rec(call: ServiceCall) -> None:
        calls.append((call.domain, call.service, dict(call.data)))

    hass.services.async_register("number", "set_value", _rec)
    hass.services.async_register("light", "turn_on", _rec)
    hass.services.async_register("light", "turn_off", _rec)
    hass.services.async_register("homeassistant", "turn_on", _rec)
    hass.services.async_register("homeassistant", "turn_off", _rec)

    entry = MockConfigEntry(domain="homekit_adjustable_bed", title="Bed")
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
        [
            ("light_level", "Licht", "number.light_level", False),
            ("under_bed_light_level", "Onderbedlicht", "light.under_bed", False),
            ("fan_level", "Ventilator", "number.fan_level", False),
        ],
        [
            ("under_bed_light_toggle", "Onderbedlichtknop", "switch.ubl"),
            ("stop", "Stop", "button.stop"),
        ],
        manufacturer="J",
        model="M",
        serial="s",
        firmware="f",
    )
    acc.async_attach()
    light, ubl, fan = acc.sliders
    hap = acc.to_HAP()
    types = [svc["type"] for svc in hap["services"]]
    assert types.count("43") == 2  # Lightbulb
    assert types.count("B7") == 1  # Fanv2
    # Initial state
    assert light.char_on.value is False
    assert ubl.char_on.value is True and ubl.char_level.value == 50
    assert fan.char_on.value == 1 and fan.char_level.value == 40
    assert light.char_level.properties["minStep"] == 10

    # Turning the light on without a level restores 100 % -> level 10
    light.char_on.client_update_value(True)
    # Dragging the fan to 70 % -> level 7; fan Active=0 -> level 0
    fan.char_level.client_update_value(70)
    ubl.char_level.client_update_value(30)
    _later(hass, 1)
    await hass.async_block_till_done()
    assert ("number", "set_value", {"entity_id": "number.light_level", "value": 10}) in calls
    assert ("number", "set_value", {"entity_id": "number.fan_level", "value": 7}) in calls
    assert ("light", "turn_on", {"entity_id": "light.under_bed", "brightness_pct": 30}) in calls
    calls.clear()
    fan.char_on.client_update_value(0)
    _later(hass, 2)
    await hass.async_block_till_done()
    assert ("number", "set_value", {"entity_id": "number.fan_level", "value": 0}) in calls

    # Stateful switch: sets and mirrors, never auto-resets
    toggle = acc.actions[0]
    toggle.char_on.client_update_value(True)
    await hass.async_block_till_done()
    assert ("homeassistant", "turn_on", {"entity_id": "switch.ubl"}) in calls
    hass.states.async_set("switch.ubl", "on")
    await hass.async_block_till_done()
    _later(hass, 3)
    await hass.async_block_till_done()
    assert toggle.char_on.value is True
    acc.async_detach()


async def test_stop_clears_queue_but_massage_toggle_not(hass, bed) -> None:
    from custom_components.homekit_adjustable_bed.const import CONTROLS_BY_KEY

    assert CONTROLS_BY_KEY["stop"].interrupts_motion
    assert not CONTROLS_BY_KEY["massage_toggle"].interrupts_motion
    assert not CONTROLS_BY_KEY["light_toggle"].interrupts_motion


def test_homekit_name_sanitizes() -> None:
    from custom_components.homekit_adjustable_bed.layout import homekit_name

    assert homekit_name("Massage aan/uit", "x") == "Massage aan uit"
    assert homekit_name("  -Licht!  ", "x") == "Licht"
    assert homekit_name("///", "Stop") == "Stop"
    assert homekit_name("Barloew's lamp", "x") == "Barloew's lamp"


async def test_bed_name_char_does_not_shift_iids(bed) -> None:
    """Adding the bed ConfiguredName must keep the IIDs of all controls."""
    acc, _, _ = bed
    name_iid = acc.iid_manager.get_iid(acc.char_bed_name)
    all_iids = [acc.iid_manager.get_iid(s) for s in acc.services] + [
        acc.iid_manager.get_iid(c)
        for s in acc.services
        for c in s.characteristics
        if c is not acc.char_bed_name
    ]
    assert name_iid == max(all_iids) + 1  # appended, nothing shifted
    info = next(s for s in acc.to_HAP()["services"] if s["type"] == "3E")
    assert any(c["type"] == "E3" and c["value"] == "Bed" for c in info["characteristics"])


async def test_inverted_slider(hass, tmp_path) -> None:
    """Inverted: flat bed shows 100 % (Open); HomeKit 70 % moves the bed to 30 %."""
    from custom_components.homekit_adjustable_bed.accessory import BedAccessory

    hass.states.async_set(BACK, "0", POS_ATTRS)
    hass.states.async_set(HEAD_M, "2", MASSAGE_ATTRS)
    calls = []

    async def _rec(call: ServiceCall) -> None:
        calls.append(dict(call.data))

    hass.services.async_register("number", "set_value", _rec)
    entry = MockConfigEntry(domain="homekit_adjustable_bed", title="Bed")
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
        [("back", "Hoofdeinde", BACK, True), ("head_massage", "Hoofdmassage", HEAD_M, False)],
        [],
        manufacturer="J",
        model="M",
        serial="s",
        firmware="f",
        inverted={"back", "head_massage"},
    )
    acc.async_attach()
    back, massage = acc.sliders
    assert back.char_current.value == 100 and back.char_target.value == 100
    assert massage.char_current.value == 80  # level 2 -> 20 % -> shown as 80 %

    back.char_target.client_update_value(70)  # HomeKit down = bed up
    assert back.char_state.value == 0  # decreasing in HomeKit terms
    massage.char_target.client_update_value(100)  # inverted 100 % = massage off
    _later(hass, 1)
    await hass.async_block_till_done()
    assert {"entity_id": BACK, "value": 30} in calls
    assert {"entity_id": HEAD_M, "value": 0} in calls

    hass.states.async_set(BACK, "30", POS_ATTRS)  # bed reports its new position
    _later(hass, 5)
    await hass.async_block_till_done()
    assert back.char_current.value == 70 and back.char_target.value == 70
    acc.async_detach()


async def test_unknown_massage_is_off(hass, tmp_path) -> None:
    """ha-adjustable-bed reports massage as 'unknown' until set: show it as off."""
    from custom_components.homekit_adjustable_bed.accessory import BedAccessory

    hass.states.async_set(BACK, "0", POS_ATTRS)
    hass.states.async_set(HEAD_M, "unknown", MASSAGE_ATTRS)
    hass.states.async_set(FOOT_M, "unknown", MASSAGE_ATTRS)
    entry = MockConfigEntry(domain="homekit_adjustable_bed", title="Bed")
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
        [
            ("back", "Hoofdeinde", BACK, True),
            ("head_massage", "Hoofdmassage", HEAD_M, False),
            ("foot_massage", "Voetmassage", FOOT_M, False),
        ],
        [],
        manufacturer="J",
        model="M",
        serial="s",
        firmware="f",
        inverted={"back", "head_massage"},
    )
    acc.async_attach()
    back, head, foot = acc.sliders
    assert back.char_current.value == 100  # flat, inverted -> Open/100
    assert head.char_current.value == 100 and head.char_target.value == 100  # off, inverted
    assert foot.char_current.value == 0  # off, not inverted
    # massage level 0-10 range still known while unknown -> 10 % steps
    assert head.char_target.properties["minStep"] == 10
    acc.async_detach()
