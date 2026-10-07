"""Timed moves: seconds per section in the form, two push buttons in HomeKit."""

from unittest.mock import patch

from homeassistant.core import HomeAssistant, ServiceCall
from pyhap.accessory_driver import AccessoryDriver
from pyhap.loader import get_loader
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.homekit_bed.accessory import BedAccessory
from custom_components.homekit_bed.const import DOMAIN
from custom_components.homekit_bed.controls import effective_controls
from custom_components.homekit_bed.sources import ServiceActionSource

from .test_detection import JENSEN, _bed
from .test_unified_form import _sections, _submit_unchanged

LABELS = {"back": "Rugdeel", "legs": "Voetendeel", "_timed_up": "omhoog", "_timed_down": "omlaag"}


async def test_timed_controls(hass: HomeAssistant) -> None:
    device_id = _bed(hass, JENSEN)
    controls = effective_controls(
        hass, {"bed_device": device_id}, {"timed_moves": {"back": 3, "legs": 0}}, LABELS
    )
    timed = {c.id: c for c in controls if c.action}
    assert set(timed) == {"timed_back_up", "timed_back_down"}  # legs: 0 = off
    up = timed["timed_back_up"]
    assert up.caption == "Rugdeel omhoog" and up.interrupts_motion
    assert up.action == {
        "domain": "adjustable_bed",
        "service": "timed_move",
        "data": {"device_id": device_id, "motor": "back", "direction": "up", "duration_ms": 3000},
    }


async def test_head_feet_bed_and_sides(hass: HomeAssistant) -> None:
    device_id = _bed(
        hass, [("number", "head_position"), ("cover", "back_left"), ("cover", "back_right")]
    )
    controls = effective_controls(
        hass,
        {"bed_device": device_id},
        {"timed_moves": {"back": 1.5, "back_left": 2}},
        LABELS,
    )
    calls = {c.id: c.action["data"] for c in controls if c.action}
    # head_position takes the id "back" but the motor is "head"
    assert calls["timed_back_up"]["motor"] == "head"
    assert calls["timed_back_up"]["duration_ms"] == 1500
    assert calls["timed_back_left_down"]["side"] == "left"
    assert calls["timed_back_left_down"]["motor"] == "back"


async def test_form_section_after_sections(hass: HomeAssistant, mock_async_zeroconf) -> None:
    device_id = _bed(hass, JENSEN)
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        data={"name": "Bed", "port": 21070, "bed_device": device_id},
        options={},
    )
    entry.add_to_hass(hass)
    with patch("custom_components.homekit_bed.async_setup_entry", return_value=True):
        await hass.config_entries.async_setup(entry.entry_id)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "controls"}
    )
    secs = _sections(result)
    assert list(secs)[:2] == ["positions", "timed"]
    assert secs["timed"] == ["timed_back", "timed_legs"]
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], _submit_unchanged(result, timed__timed_back=2.5)
    )
    assert result["step_id"] == "preview"
    assert "Rugdeel omhoog" in result["description_placeholders"]["preview"] or (
        "Head section up" in result["description_placeholders"]["preview"]
    )
    await hass.config_entries.options.async_configure(result["flow_id"], {"save": True})
    assert entry.options["timed_moves"] == {"back": 2.5}


async def test_button_calls_timed_move(hass: HomeAssistant, tmp_path) -> None:
    calls: list[dict] = []

    async def _rec(call: ServiceCall) -> None:
        calls.append(dict(call.data))

    hass.services.async_register("adjustable_bed", "timed_move", _rec)
    entry = MockConfigEntry(domain=DOMAIN, title="Bed")
    entry.add_to_hass(hass)
    loader = await hass.async_add_executor_job(get_loader)
    driver = AccessoryDriver(
        loop=hass.loop,
        address="127.0.0.1",
        port=0,
        persist_file=str(tmp_path / "s"),
        loader=loader,
    )
    action = {
        "domain": "adjustable_bed",
        "service": "timed_move",
        "data": {"device_id": "d", "motor": "back", "direction": "up", "duration_ms": 2000},
    }
    acc = BedAccessory(
        hass,
        driver,
        entry,
        "Bed",
        [],
        [("timed_back_up", "Rugdeel omhoog", "")],
        manufacturer="J",
        model="M",
        serial="s",
        firmware="f",
        interrupts={"timed_back_up"},
        action_sources={"timed_back_up": ServiceActionSource(hass, action)},
    )
    acc.async_attach()  # no entity to follow: must not fail
    button = acc.actions[0]
    assert button.interrupts_motion
    button.char_on.client_update_value(True)
    await hass.async_block_till_done()
    assert calls == [action["data"]]
    acc.async_detach()
