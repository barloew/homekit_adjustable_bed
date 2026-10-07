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


async def _open_form(hass, keys):
    device_id = _bed(hass, keys)
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
    return entry, result


def _collapsed(result) -> bool:
    return all(
        v.options["collapsed"]
        for v in result["data_schema"].schema.values()
        if hasattr(v, "options")
    )


async def test_position_bed_switches(hass: HomeAssistant, mock_async_zeroconf) -> None:
    """Jensen (position numbers): two switches on top; timed off by default."""
    entry, result = await _open_form(hass, JENSEN)
    secs = _sections(result)
    assert secs["positions"][:2] == ["timed_buttons", "position_sliders"]
    assert "back" in secs["positions"] and "timed" not in secs
    assert "display" in secs and _collapsed(result)

    # Timed buttons on -> the durations appear right after the sections
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], _submit_unchanged(result, positions__timed_buttons=True)
    )
    secs = _sections(result)
    assert list(secs)[:2] == ["positions", "timed"]
    assert secs["timed"] == ["timed_back", "timed_legs"]

    # Sliders off -> the slider fields disappear
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        _submit_unchanged(result, positions__position_sliders=False, timed__timed_back=2.5),
    )
    secs = _sections(result)
    assert secs["positions"] == ["timed_buttons", "position_sliders"]
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], _submit_unchanged(result)
    )
    assert result["step_id"] == "preview"
    await hass.config_entries.options.async_configure(result["flow_id"], {"save": True})
    o = entry.options
    assert o["timed_buttons"] is True and o["position_sliders"] is False
    assert o["timed_moves"] == {"back": 2.5}
    ids = {c.id for c in effective_controls(hass, dict(entry.data), dict(o), LABELS)}
    assert "back" not in ids and "legs" not in ids  # no exact sliders
    assert {"timed_back_up", "timed_back_down"} <= ids


async def test_bed_without_positions(hass: HomeAssistant, mock_async_zeroconf) -> None:
    """Covers without position: no switches, timed always, no display section."""
    _entry, result = await _open_form(
        hass, [("cover", "back"), ("cover", "legs"), ("button", "preset_flat")]
    )
    secs = _sections(result)
    assert "timed_buttons" not in secs["positions"]
    assert secs["timed"] == ["timed_back", "timed_legs"]
    assert "display" not in secs and _collapsed(result)


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


def _display_options(result) -> list[str]:
    for marker, value in result["data_schema"].schema.items():
        if str(marker) == "display":
            sel = next(iter(value.schema.schema.values()))
            return [o["value"] for o in sel.config["options"]]
    return []


async def test_massage_switches_and_display(hass: HomeAssistant, mock_async_zeroconf) -> None:
    entry, result = await _open_form(hass, JENSEN)
    secs = _sections(result)
    assert secs["massage"][:2] == ["massage_buttons", "massage_sliders"]
    assert "head_massage" in secs["massage"] and "massage_toggle" in secs["massage"]
    assert set(_display_options(result)) >= {"back", "legs", "head_massage"}

    # Massage sliders off: gone from the form, from "add" and from Display
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], _submit_unchanged(result, massage__massage_sliders=False)
    )
    secs = _sections(result)
    assert "head_massage" not in secs["massage"] and "massage_toggle" in secs["massage"]
    assert set(_display_options(result)) == {"back", "legs"}
    add = next((v for k, v in result["data_schema"].schema.items() if str(k) == "add"), None)
    if add is not None:
        offered = [o["value"] for o in next(iter(add.schema.schema.values())).config["options"]]
        assert "head_massage" not in offered

    # Bed section sliders off too: no sliders at all -> no Display block
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], _submit_unchanged(result, positions__position_sliders=False)
    )
    assert "display" not in _sections(result)

    # Massage buttons off: only the switches remain in Massage
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], _submit_unchanged(result, massage__massage_buttons=False)
    )
    assert _sections(result)["massage"] == ["massage_buttons", "massage_sliders"]
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], _submit_unchanged(result)
    )
    await hass.config_entries.options.async_configure(result["flow_id"], {"save": True})
    ids = {c.id for c in effective_controls(hass, dict(entry.data), dict(entry.options), LABELS)}
    assert not ids & {"head_massage", "foot_massage", "wave_massage", "massage_toggle"}
    assert "flat" in ids


async def test_only_massage_buttons(hass: HomeAssistant, mock_async_zeroconf) -> None:
    _entry, result = await _open_form(
        hass, [("cover", "back"), ("button", "massage_all_toggle"), ("button", "preset_flat")]
    )
    assert _sections(result)["massage"][0] == "massage_buttons"
    assert "massage_sliders" not in _sections(result)["massage"]
