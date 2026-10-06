"""The HomeKit accessory: one bed, four sliders, two switches.

Why a standalone HAP accessory instead of proxy entities for the HomeKit
Bridge? The analysis of sammcj/homekit_device showed the decisive rule: the HA
HomeKit Bridge creates exactly one accessory per *entity* and never merges
entities that share a device. Its only way to aggregate is a richer entity
type (a climate for a kettle, a cover with lift + tilt for a shutter). No HA
entity type carries four positions and two switches, so the only way to get
one HomeKit device is to build the HAP accessory ourselves with HAP-python -
the same library the HomeKit Bridge runs on - holding four WindowCovering and
two Switch services.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import (
    CALLBACK_TYPE,
    Event,
    EventStateChangedData,
    HassJob,
    HomeAssistant,
    callback,
)
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
)
from pyhap.accessory import Accessory, Bridge
from pyhap.const import CATEGORY_WINDOW_COVERING

from .const import (
    BED_AID,
    CAPTION_PUSH_DELAYS,
    CAPTION_REASSERT_SECONDS,
    CONTROLS_BY_KEY,
    DEBOUNCE_SECONDS,
    KIND_COVER,
    KIND_FAN,
    KIND_LIGHT,
    MOMENTARY_RESET_SECONDS,
    MOVE_TIMEOUT_SECONDS,
    POSITION_TOLERANCE,
    SETTLE_SECONDS,
)
from .labels import FALLBACK_TEXTS, render
from .layout import homekit_name
from .sources import ActionSource, InvertedSliderSource, SliderSource

if TYPE_CHECKING:
    from pyhap.accessory_driver import AccessoryDriver

_LOGGER = logging.getLogger(__name__)


def add_named_service(
    acc: BedAccessory,
    service_type: str,
    key: str,
    label: str,
    extra_chars: list[str] | None = None,
) -> Any:
    """Add a service that the Home app will caption with ``label``.

    Home copies service names at pairing time. Since iOS 17 it reads the
    writable ConfiguredName for ordinary services (before, only for TV
    inputs); Name is kept for older clients and other controllers. Home only
    *shows* the caption when an accessory holds several services of the same
    type, which is the case here (5 sliders, 2-5 switches).
    """
    loader = acc.driver.loader
    svc = loader.get_service(service_type)
    for char_name in ("Name", "ConfiguredName", *(extra_chars or [])):
        svc.add_characteristic(loader.get_char(char_name))
    svc.unique_id = key
    acc.add_service(svc)
    svc.configure_char("Name", value=label)
    char = svc.configure_char("ConfiguredName", value=label)
    # Bound after creation so the callback can reach the characteristic.
    char.setter_callback = lambda value: acc.async_on_home_rename(char, label, value)
    acc.caption_chars.append((char, label))
    return svc


POS_DECREASING = 0
POS_INCREASING = 1
POS_STOPPED = 2


class MotionQueue:
    """Serialise motor moves for the whole bed.

    A Jensen JMC400 moves by sending one go-to frame that carries *both* head
    and foot targets. Since ha-adjustable-bed #632 (commit 77049c8) the other
    section is filled in from its *measured* position, the number's set_value
    only returns once the bed's pushed reports show the move ended, and a new
    command interrupts the running one (sending STOP). Moving the back and
    then the legs in quick succession would therefore stop the back halfway.
    Queueing the moves (latest target per axis wins) avoids that.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialise the queue."""
        self.hass = hass
        self.entry = entry
        self._pending: dict[SliderChannel, int] = {}
        self._running: SliderChannel | None = None
        self._task: asyncio.Task | None = None

    def is_busy(self, channel: SliderChannel) -> bool:
        """Return True while a move for this channel is queued or running."""
        return channel is self._running or channel in self._pending

    @callback
    def request(self, channel: SliderChannel, target: int) -> None:
        """Queue a move; a newer target for the same axis replaces the old."""
        self._pending.pop(channel, None)
        self._pending[channel] = target
        if self._task is None or self._task.done():
            self._task = self.entry.async_create_background_task(
                self.hass, self._async_run(), f"homekit_bed motion {self.entry.title}"
            )

    @callback
    def clear(self) -> None:
        """Drop queued moves, e.g. when Flat or Memory is pressed."""
        dropped = list(self._pending)
        self._pending.clear()
        for channel in dropped:
            channel.async_move_finished()

    async def _async_run(self) -> None:
        while self._pending:
            channel = next(iter(self._pending))
            target = self._pending.pop(channel)
            self._running = channel
            try:
                async with asyncio.timeout(MOVE_TIMEOUT_SECONDS):
                    # blocking=True: ha-adjustable-bed returns once the bed
                    # has reported the end of the move.
                    await channel.source.async_set_percent(target, blocking=True)
            except TimeoutError:
                _LOGGER.warning("Move of %s to %s%% timed out", channel.label, target)
            except Exception:  # noqa: BLE001 - never kill the queue
                _LOGGER.exception("Move of %s to %s%% failed", channel.label, target)
            finally:
                self._running = None
                if channel not in self._pending:
                    channel.async_move_finished()


class SliderChannel:
    """One WindowCovering service backed by a slider source."""

    def __init__(
        self,
        bed: BedAccessory,
        key: str,
        label: str,
        entity_id: str,
        *,
        motor: bool,
        inverted: bool = False,
    ) -> None:
        """Create the service and its characteristics."""
        self.bed = bed
        self.hass = bed.hass
        self.key = key
        self.label = label
        self.motor = motor
        self.inverted = inverted
        source_cls = InvertedSliderSource if inverted else SliderSource
        # Massage levels are "unknown" until set: treat that as off.
        self.source = source_cls(bed.hass, entity_id, unknown_is_off=not motor)
        # Start at "off/flat" (100 when inverted) until the bed reports.
        self._current = self._target = self.source.off_percent
        self._debounce_unsub: CALLBACK_TYPE | None = None
        self._settle_unsub: CALLBACK_TYPE | None = None

        svc = add_named_service(bed, "WindowCovering", key, label)
        self.service = svc

        # Massage has 0-10 levels: make the Home slider snap to 10 % steps.
        min_step = _min_step(self.source)
        self.char_current = svc.configure_char(
            "CurrentPosition",
            properties={"minStep": min_step},
            value=self._current,
        )
        self.char_target = svc.configure_char(
            "TargetPosition",
            properties={"minStep": min_step},
            value=self._target,
            setter_callback=self._hk_set_target,
        )
        self.char_state = svc.configure_char("PositionState", value=POS_STOPPED)

    # --------------------------------------------------------------- helpers
    @property
    def entity_id(self) -> str:
        return self.source.entity_id

    def _busy(self) -> bool:
        return self._debounce_unsub is not None or (self.motor and self.bed.motion.is_busy(self))

    @callback
    def _set_state(self, value: int) -> None:
        if self.char_state.value != value:
            self.char_state.set_value(value)

    @callback
    def _set_target_char(self, value: int) -> None:
        self._target = value
        if self.char_target.value != value:
            self.char_target.set_value(value)

    @callback
    def _direction(self) -> int:
        if abs(self._target - self._current) <= POSITION_TOLERANCE:
            return POS_STOPPED
        return POS_INCREASING if self._target > self._current else POS_DECREASING

    # ------------------------------------------------------- HomeKit -> HA
    def _hk_set_target(self, value: Any) -> None:
        """Called by HAP-python (in the HA event loop) on a slider change."""
        value = max(0, min(100, int(value)))
        _LOGGER.debug("HomeKit set %s -> %s%%", self.label, value)
        self._target = value
        if self.motor:
            self._set_state(self._direction())
        if self._debounce_unsub:
            self._debounce_unsub()
        self._debounce_unsub = async_call_later(
            self.hass, DEBOUNCE_SECONDS, HassJob(self._async_debounced, cancel_on_shutdown=True)
        )

    @callback
    def _async_debounced(self, _now: Any) -> None:
        self._debounce_unsub = None
        target = self._target
        if self.motor:
            self.bed.motion.request(self, target)
            return
        # Massage: the bed does not report state; the number entity reflects
        # what was last sent, so show the requested level right away.
        self._current = target
        self.char_current.set_value(target)
        self._set_state(POS_STOPPED)
        self.bed.async_run_service(self.source.async_set_percent(target, blocking=True), self.label)

    # ------------------------------------------------------- HA -> HomeKit
    @callback
    def async_update_from_state(self, state: Any) -> None:
        """Mirror the source entity into HomeKit."""
        percent = self.source.read_percent(state)
        if percent is None:
            return
        self._current = percent
        if self.char_current.value != percent:
            self.char_current.set_value(percent)

        if not self._busy():
            # Nothing of ours is in flight: the change came from the remote,
            # the app, Flat/Memory or an automation. Follow it.
            self._set_target_char(percent)
            self._set_state(POS_STOPPED)
            return

        if self.motor:
            self._set_state(self._direction())

    @callback
    def async_move_finished(self) -> None:
        """Called by the motion queue when this channel's move is done."""
        if self._settle_unsub:
            self._settle_unsub()
        self._settle_unsub = async_call_later(
            self.hass, SETTLE_SECONDS, HassJob(self._async_settle, cancel_on_shutdown=True)
        )

    @callback
    def _async_settle(self, _now: Any) -> None:
        self._settle_unsub = None
        if self._busy():
            return
        if state := self.hass.states.get(self.entity_id):
            percent = self.source.read_percent(state)
            if percent is not None:
                self._current = percent
                self.char_current.set_value(percent)
        # Snap target to where the bed really stopped so Home shows it idle.
        self._set_target_char(self._current)
        self._set_state(POS_STOPPED)

    @callback
    def async_cancel(self) -> None:
        for unsub in (self._debounce_unsub, self._settle_unsub):
            if unsub:
                unsub()
        self._debounce_unsub = self._settle_unsub = None


def _min_step(source: SliderSource) -> int:
    """10 for 0-10 level sources so the Home slider snaps to real levels."""
    steps = source.native_steps
    return 100 // steps if steps and 100 % steps == 0 and steps < 100 else 1


_HS_MODES = {"hs", "xy", "rgb", "rgbw", "rgbww"}


@dataclass(slots=True)
class LightCaps:
    """Colour abilities of a light entity."""

    hs: bool = False
    ct: bool = False
    min_mireds: int = 153
    max_mireds: int = 500


def light_color_capabilities(hass: HomeAssistant, entity_id: str) -> LightCaps:
    """Read colour support from the state, or the registry if unavailable.

    The registry keeps supported_color_modes and the colour-temperature range
    even while a Hue lamp is unreachable, so colour does not vanish from
    HomeKit after a restart during which the lamp was offline.
    """
    attrs: dict[str, Any] = {}
    if entry := er.async_get(hass).async_get(entity_id):
        attrs.update(entry.capabilities or {})
    if state := hass.states.get(entity_id):
        attrs.update(state.attributes)
    modes = set(attrs.get("supported_color_modes") or [])
    caps = LightCaps(hs=bool(modes & _HS_MODES), ct="color_temp" in modes)
    if (max_k := attrs.get("max_color_temp_kelvin")) and float(max_k) > 0:
        caps.min_mireds = max(50, int(1_000_000 // float(max_k)))
    if (min_k := attrs.get("min_color_temp_kelvin")) and float(min_k) > 0:
        caps.max_mireds = max(caps.min_mireds + 1, -(-1_000_000 // int(float(min_k))))
    return caps


class LevelChannel:
    """On/off plus a level slider: Lightbulb (light) or Fanv2 (fan).

    Used for light level, under-bed light and fan level. Off means level 0;
    switching on restores the last non-zero level.
    """

    SERVICE = "Lightbulb"
    ON_CHAR = "On"
    LEVEL_CHAR = "Brightness"

    def __init__(
        self,
        bed: BedAccessory,
        key: str,
        label: str,
        entity_id: str,
        *,
        allow_color: bool = True,
    ) -> None:
        """Create the service."""
        self.bed = bed
        self.hass = bed.hass
        self.key = key
        self.label = label
        self.source = SliderSource(bed.hass, entity_id)
        self._target = 0
        self._last_level = 100
        self._debounce_unsub: CALLBACK_TYPE | None = None

        svc = add_named_service(bed, self.SERVICE, key, label, [self.LEVEL_CHAR])
        self.service = svc
        self.char_on = svc.configure_char(self.ON_CHAR, setter_callback=self._hk_set_on)
        self.char_level = svc.configure_char(
            self.LEVEL_CHAR,
            properties={"minStep": _min_step(self.source)},
            setter_callback=self._hk_set_level,
        )
        # Colour: only for real HA lights that support it (e.g. a Hue strip).
        self.char_hue = self.char_sat = self.char_ct = None
        self._pending_color: dict[str, float] = {}
        self._caps = (
            light_color_capabilities(bed.hass, entity_id)
            if self.source.domain == "light" and allow_color
            else LightCaps()
        )

    @property
    def has_color(self) -> bool:
        return self._caps.hs or self._caps.ct

    def add_color_chars(self) -> None:
        """Append Hue/Saturation/ColorTemperature (called after all services).

        Appended last so earlier IIDs stay put on an upgrade (see iids.py).
        """
        if self._caps.hs:
            self.char_hue = self.bed.add_late_char(self.service, "Hue", setter=self._hk_set_hue)
            self.char_sat = self.bed.add_late_char(
                self.service, "Saturation", setter=self._hk_set_sat
            )
        if self._caps.ct:
            self.char_ct = self.bed.add_late_char(
                self.service,
                "ColorTemperature",
                properties={"minValue": self._caps.min_mireds, "maxValue": self._caps.max_mireds},
                setter=self._hk_set_ct,
            )

    def _hk_set_hue(self, value: Any) -> None:
        self._pending_color.pop("ct", None)
        self._pending_color["hue"] = float(value)
        self._schedule()

    def _hk_set_sat(self, value: Any) -> None:
        self._pending_color.pop("ct", None)
        self._pending_color["sat"] = float(value)
        self._schedule()

    def _hk_set_ct(self, value: Any) -> None:
        self._pending_color.pop("hue", None)
        self._pending_color.pop("sat", None)
        self._pending_color["ct"] = float(value)
        self._schedule()

    @property
    def entity_id(self) -> str:
        return self.source.entity_id

    def _on_value(self, on: bool) -> Any:
        return on

    def _hk_set_on(self, value: Any) -> None:
        if value:
            level = int(self.char_level.value or 0)
            self._target = level if level > 0 else self._last_level
        else:
            self._target = 0
        self._schedule()

    def _hk_set_level(self, value: Any) -> None:
        self._target = max(0, min(100, int(value)))
        if self._target > 0:
            self._last_level = self._target
        self._schedule()

    def _schedule(self) -> None:
        if self._debounce_unsub:
            self._debounce_unsub()
        self._debounce_unsub = async_call_later(
            self.hass,
            DEBOUNCE_SECONDS,
            HassJob(self._async_debounced, cancel_on_shutdown=True),
        )

    @callback
    def _async_debounced(self, _now: Any) -> None:
        self._debounce_unsub = None
        target = self._target
        color, self._pending_color = self._pending_color, {}
        if color and target <= 0:
            # Choosing a colour in the Home app means "on in this colour".
            target = self._last_level
        self._show(target)
        if not color:
            self.bed.async_run_service(
                self.source.async_set_percent(target, blocking=True), self.label
            )
            return
        data: dict[str, Any] = {"entity_id": self.entity_id, "brightness_pct": target}
        if "ct" in color:
            data["color_temp_kelvin"] = round(1_000_000 / max(1.0, color["ct"]))
        else:
            hue = color.get("hue", float(self.char_hue.value or 0) if self.char_hue else 0)
            sat = color.get("sat", float(self.char_sat.value or 0) if self.char_sat else 0)
            data["hs_color"] = [hue, sat]
        self.bed.async_run_service(
            self.hass.services.async_call("light", "turn_on", data, blocking=True),
            self.label,
        )

    @callback
    def _show_color(self, state: Any) -> None:
        if state is None or state.state != "on":
            return
        attrs = state.attributes
        hs = attrs.get("hs_color")
        if self.char_hue and self.char_sat and hs and len(hs) == 2:
            hue, sat = round(float(hs[0]), 1), round(float(hs[1]), 1)
            if self.char_hue.value != hue:
                self.char_hue.set_value(hue)
            if self.char_sat.value != sat:
                self.char_sat.set_value(sat)
        kelvin = attrs.get("color_temp_kelvin")
        if self.char_ct and kelvin:
            mireds = round(1_000_000 / float(kelvin))
            mireds = max(self._caps.min_mireds, min(self._caps.max_mireds, mireds))
            if self.char_ct.value != mireds:
                self.char_ct.set_value(mireds)

    @callback
    def _show(self, percent: int) -> None:
        on = self._on_value(percent > 0)
        if self.char_on.value != on:
            self.char_on.set_value(on)
        if percent > 0:
            self._last_level = percent
            if self.char_level.value != percent:
                self.char_level.set_value(percent)

    @callback
    def async_update_from_state(self, state: Any) -> None:
        percent = self.source.read_percent(state)
        if percent is None or self._debounce_unsub is not None:
            return
        self._target = percent
        self._show(percent)
        self._show_color(state)

    @callback
    def async_cancel(self) -> None:
        if self._debounce_unsub:
            self._debounce_unsub()
            self._debounce_unsub = None


class FanChannel(LevelChannel):
    """Fan level as a HomeKit fan (Active + RotationSpeed)."""

    SERVICE = "Fanv2"
    ON_CHAR = "Active"
    LEVEL_CHAR = "RotationSpeed"

    def _on_value(self, on: bool) -> Any:
        return 1 if on else 0


class ActionChannel:
    """A Switch service.

    For a button/script/scene it is a push button that falls back to off.
    For a switch/light/fan/input_boolean it mirrors and sets the real state.
    """

    def __init__(
        self,
        bed: BedAccessory,
        key: str,
        label: str,
        entity_id: str,
        *,
        interrupts_motion: bool = False,
    ) -> None:
        """Create the service."""
        self.bed = bed
        self.hass = bed.hass
        self.key = key
        self.label = label
        self.interrupts_motion = interrupts_motion
        self.source = ActionSource(bed.hass, entity_id)
        self._reset_unsub: CALLBACK_TYPE | None = None

        svc = add_named_service(bed, "Switch", key, label)
        self.service = svc
        self.char_on = svc.configure_char("On", setter_callback=self._hk_set_on)

    @property
    def entity_id(self) -> str:
        return self.source.entity_id

    def _hk_set_on(self, value: Any) -> None:
        if self.source.stateful:
            _LOGGER.debug("HomeKit set %s %s", self.label, "on" if value else "off")
            self.bed.async_run_service(
                self.source.async_set(bool(value)), self.label, notify_on_error=True
            )
            return
        if not value:
            return
        _LOGGER.debug("HomeKit pressed %s", self.label)
        if self.interrupts_motion:
            # Stop/Flat/Memory move (or halt) the bed on their own; queued
            # slider moves would drag it away again afterwards.
            self.bed.motion.clear()
        self.bed.async_run_service(
            self.source.async_trigger(), self.label, notify_on_error=True, key=self.key
        )
        if self._reset_unsub:
            self._reset_unsub()
        self._reset_unsub = async_call_later(
            self.hass,
            MOMENTARY_RESET_SECONDS,
            HassJob(self._async_reset, cancel_on_shutdown=True),
        )

    @callback
    def _async_reset(self, _now: Any) -> None:
        self._reset_unsub = None
        self.char_on.set_value(False)

    @callback
    def async_update_from_state(self, state: Any) -> None:
        if not self.source.stateful:
            return
        on = self.source.read_on(state)
        if on is not None and self.char_on.value != on:
            self.char_on.set_value(on)

    @callback
    def async_cancel(self) -> None:
        if self._reset_unsub:
            self._reset_unsub()
            self._reset_unsub = None


class SelectChannel:
    """A select entity as one Switch per option; only one is on at a time.

    Turning a switch on selects that option. Turning the active one off is
    not possible for a select, so it is switched back on.
    """

    def __init__(self, bed: BedAccessory, key: str, label: str, entity_id: str) -> None:
        """Create one service per option."""
        self.bed = bed
        self.hass = bed.hass
        self.key = key
        self.label = label
        self.entity_id = entity_id
        self._unsubs: list[CALLBACK_TYPE] = []
        attrs: dict[str, Any] = {}
        if entry := er.async_get(bed.hass).async_get(entity_id):
            attrs.update(entry.capabilities or {})
        if state := bed.hass.states.get(entity_id):
            attrs.update(state.attributes)
        self.chars: dict[str, Any] = {}
        self.services: list[Any] = []
        for option in attrs.get("options") or []:
            svc = add_named_service(
                bed,
                "Switch",
                f"{key}:{option}",
                homekit_name(f"{label} {option}", f"{label} {len(self.services) + 1}"),
            )
            svc.is_primary_service = False
            self.services.append(svc)
            self.chars[option] = svc.configure_char(
                "On", setter_callback=lambda value, opt=option: self._hk_set(opt, value)
            )
        self.service = self.services[0] if self.services else None

    def _hk_set(self, option: str, value: Any) -> None:
        if value:
            self.bed.async_run_service(
                self.hass.services.async_call(
                    "select",
                    "select_option",
                    {"entity_id": self.entity_id, "option": option},
                    blocking=True,
                ),
                self.label,
                notify_on_error=True,
            )
            for other, char in self.chars.items():
                if other != option and char.value:
                    char.set_value(False)
            return
        # Deselecting is not possible: restore the real state shortly.
        self._unsubs.append(
            async_call_later(
                self.hass,
                MOMENTARY_RESET_SECONDS,
                HassJob(
                    lambda _now: self.async_update_from_state(self.hass.states.get(self.entity_id)),
                    cancel_on_shutdown=True,
                ),
            )
        )

    @callback
    def async_update_from_state(self, state: Any) -> None:
        if state is None:
            return
        for option, char in self.chars.items():
            on = state.state == option
            if char.value != on:
                char.set_value(on)

    @callback
    def async_cancel(self) -> None:
        while self._unsubs:
            self._unsubs.pop()()


class ClimateFanChannel:
    """A bed climate entity (Sleep Number cooling/heating, footwarming) as a fan.

    The bed's climate has no temperature, only on/off, a mode (cool/heat)
    and a level preset, so a HomeKit thermostat would show a fake dial.
    Instead:
      * Fan: Active = on/off, RotationSpeed = level. With n presets the
        speed is split in n equal steps (low/medium/high = 33/67/100 %; with
        boost while cooling 25/50/75/100 %).
      * Two mutually exclusive switches "<caption> Cool" / "<caption> Heat"
        when the bed supports both modes (footwarming is heat only).
    """

    def __init__(
        self,
        bed: BedAccessory,
        key: str,
        label: str,
        entity_id: str,
        mode_names: dict[str, str],
    ) -> None:
        """Create the fan and, if needed, the mode switches."""
        self.bed = bed
        self.hass = bed.hass
        self.key = key
        self.label = label
        self.entity_id = entity_id
        self._debounce_unsub: CALLBACK_TYPE | None = None
        self._pending: tuple[str, Any] | None = None
        self._unsubs: list[CALLBACK_TYPE] = []

        svc = add_named_service(bed, "Fanv2", key, label, ["RotationSpeed"])
        self.service = svc
        self.char_active = svc.configure_char("Active", setter_callback=self._hk_active)
        self.char_speed = svc.configure_char("RotationSpeed", setter_callback=self._hk_speed)

        attrs: dict[str, Any] = {}
        if entry := er.async_get(bed.hass).async_get(entity_id):
            attrs.update(entry.capabilities or {})
        if state := bed.hass.states.get(entity_id):
            attrs.update(state.attributes)
        modes = [m for m in attrs.get("hvac_modes") or [] if m in ("cool", "heat")]
        self.mode_chars: dict[str, Any] = {}
        if len(modes) > 1:
            for mode in modes:
                msvc = add_named_service(
                    bed,
                    "Switch",
                    f"{key}:{mode}",
                    homekit_name(f"{label} {mode_names.get(mode, mode)}", f"{label} {mode}"),
                )
                msvc.is_primary_service = False
                self.mode_chars[mode] = msvc.configure_char(
                    "On", setter_callback=lambda value, m=mode: self._hk_mode(m, value)
                )

    # ------------------------------------------------------------ mapping
    def _presets(self) -> list[str]:
        state = self.hass.states.get(self.entity_id)
        presets = list((state.attributes.get("preset_modes") if state else None) or [])
        return presets or ["low", "medium", "high"]

    def _percent_for(self, preset: str | None) -> int:
        presets = self._presets()
        if preset not in presets:
            return 0
        return round((presets.index(preset) + 1) * 100 / len(presets))

    def _preset_for(self, percent: int) -> str:
        presets = self._presets()
        index = max(1, -(-percent * len(presets) // 100)) - 1  # ceil, at least 1
        return presets[min(index, len(presets) - 1)]

    # ---------------------------------------------------- HomeKit -> HA
    def _hk_active(self, value: Any) -> None:
        self._pending = ("active", bool(value))
        self._schedule()

    def _hk_speed(self, value: Any) -> None:
        self._pending = ("speed", int(value))
        self._schedule()

    def _hk_mode(self, mode: str, value: Any) -> None:
        if value:
            for other, char in self.mode_chars.items():
                if other != mode and char.value:
                    char.set_value(False)
            self._call("set_hvac_mode", {"hvac_mode": mode})
        else:
            self._call("turn_off", {})

    def _schedule(self) -> None:
        if self._debounce_unsub:
            self._debounce_unsub()
        self._debounce_unsub = async_call_later(
            self.hass, DEBOUNCE_SECONDS, HassJob(self._async_send, cancel_on_shutdown=True)
        )

    @callback
    def _async_send(self, _now: Any) -> None:
        self._debounce_unsub = None
        pending, self._pending = self._pending, None
        if pending is None:
            return
        what, value = pending
        if what == "active":
            # turn_on resumes the last mode and level of the bed.
            self._call("turn_on" if value else "turn_off", {})
        elif value <= 0:
            self._call("turn_off", {})
        else:
            # Setting a level also turns the climate on (bed's own default mode).
            self._call("set_preset_mode", {"preset_mode": self._preset_for(value)})

    def _call(self, service: str, data: dict[str, Any]) -> None:
        self.bed.async_run_service(
            self.hass.services.async_call(
                "climate", service, {"entity_id": self.entity_id, **data}, blocking=True
            ),
            self.label,
            notify_on_error=True,
        )

    # ---------------------------------------------------- HA -> HomeKit
    @callback
    def async_update_from_state(self, state: Any) -> None:
        if state is None or state.state in ("unavailable", "unknown"):
            return
        if self._debounce_unsub is not None:
            return
        on = state.state != "off"
        if self.char_active.value != int(on):
            self.char_active.set_value(1 if on else 0)
        if on:
            percent = self._percent_for(state.attributes.get("preset_mode"))
            if percent and self.char_speed.value != percent:
                self.char_speed.set_value(percent)
        for mode, char in self.mode_chars.items():
            active = state.state == mode
            if char.value != active:
                char.set_value(active)

    @callback
    def async_cancel(self) -> None:
        if self._debounce_unsub:
            self._debounce_unsub()
            self._debounce_unsub = None


class BedBridge(Bridge):
    """Invisible HAP bridge in front of the bed.

    The first accessory on a HAP server always inherits the pairing (server)
    name in the Home app, and service captions of that first accessory are
    unreliable. Hosting the bed as accessory #2 behind a bridge - as the HA
    HomeKit Bridge and HomeSpan do - lets the bed and each of its controls
    keep their own names.
    """

    def setup_message(self) -> None:
        """Suppress pyhap's stdout QR code; HA shows a notification instead."""


class BedAccessory(Accessory):
    """A single HomeKit accessory aggregating the whole bed."""

    category = CATEGORY_WINDOW_COVERING

    def __init__(
        self,
        hass: HomeAssistant,
        driver: AccessoryDriver,
        entry: ConfigEntry,
        name: str,
        sliders: list[tuple[str, str, str, bool]],
        actions: list[tuple[str, str, str]],
        *,
        manufacturer: str,
        model: str,
        serial: str,
        firmware: str,
        enforce_captions: bool = True,
        primary_key: str | None = None,
        texts: dict[str, str] | None = None,
        iid_manager: Any = None,
        color_off: set[str] | None = None,
        inverted: set[str] | None = None,
        kinds: dict[str, str] | None = None,
        interrupts: set[str] | None = None,
        selects: list[tuple[str, str, str]] | None = None,
        climates: list[tuple[str, str, str]] | None = None,
        mode_names: dict[str, str] | None = None,
    ) -> None:
        """Build all services.

        sliders: (key, label, entity_id, is_motor)
        actions: (key, label, entity_id)
        """
        self.hass = hass
        self.entry = entry
        self.enforce_captions = enforce_captions
        self.texts = texts or dict(FALLBACK_TEXTS)
        self.caption_chars: list[tuple[Any, str]] = []
        self._caption_unsubs: list[CALLBACK_TYPE] = []
        super().__init__(driver, name, aid=BED_AID, iid_manager=iid_manager)
        self.set_info_service(
            firmware_revision=firmware,
            manufacturer=manufacturer,
            model=model,
            serial_number=serial,
        )
        self.motion = MotionQueue(hass, entry)
        self.sliders: list[SliderChannel | LevelChannel] = []
        for key, label, entity_id, motor in sliders:
            spec = CONTROLS_BY_KEY.get(key)
            kind = (kinds or {}).get(key) or (spec.kind if spec else KIND_COVER)
            if kind == KIND_LIGHT:
                self.sliders.append(
                    LevelChannel(
                        self,
                        key,
                        label,
                        entity_id,
                        allow_color=key not in (color_off or ()),
                    )
                )
            elif kind == KIND_FAN:
                self.sliders.append(FanChannel(self, key, label, entity_id))
            else:
                self.sliders.append(
                    SliderChannel(
                        self,
                        key,
                        label,
                        entity_id,
                        motor=motor,
                        inverted=key in (inverted or ()),
                    )
                )
        self.actions: list[ActionChannel] = []
        for key, label, entity_id in actions:
            spec = CONTROLS_BY_KEY.get(key)
            self.actions.append(
                ActionChannel(
                    self,
                    key,
                    label,
                    entity_id,
                    interrupts_motion=(spec.interrupts_motion if spec else False)
                    or key in (interrupts or ()),
                )
            )
        # The Home app shows the primary service first and sorts the rest by
        # name (see layout.py). Exactly one service is marked primary.
        self.selects: list[SelectChannel] = [
            SelectChannel(self, key, label, entity_id) for key, label, entity_id in (selects or [])
        ]
        self.climates: list[ClimateFanChannel] = [
            ClimateFanChannel(self, key, label, entity_id, mode_names or {})
            for key, label, entity_id in (climates or [])
        ]
        channels = [*self.sliders, *self.actions, *self.climates]
        primary = next((c for c in channels if c.key == primary_key), None)
        if primary is None and channels:
            primary = channels[0]
        for channel in channels:
            channel.service.is_primary_service = channel is primary

        # Deliberately not linked to the primary service: linked services are
        # meant for sub-parts (TV inputs, faucet valves). Plain sibling
        # services are what multi-control devices like the VOCOlinc VAP-1 use.

        self._unsubs: list[Callable[[], None]] = []

        # Evented name of the whole bed, so a rename in HA reaches the Home
        # app without re-pairing (Name itself is read-only and cached).
        # Added last on purpose: pyhap numbers IIDs in creation order, and a
        # characteristic inserted earlier would shift the IIDs of every
        # control, making the Home app treat them as new (names, scenes and
        # automations lost). Appended here it simply gets the next free IID.
        self.char_bed_name = self.add_late_char(
            self.get_service("AccessoryInformation"),
            "ConfiguredName",
            value=name,
            setter=self._hk_bed_renamed,
        )
        # Colour characteristics come after the bed name (added in 3.2).
        for channel in self.sliders:
            if isinstance(channel, LevelChannel) and channel.has_color:
                channel.add_color_chars()

    def setup_message(self) -> None:
        """Suppress pyhap's stdout QR code; HA shows a notification instead."""

    # ------------------------------------------------------------- HA glue
    @callback
    def async_run_service(
        self,
        coro: Any,
        label: str,
        *,
        notify_on_error: bool = False,
        key: str | None = None,
    ) -> None:
        """Run a service call in the background and log failures.

        Since ha-adjustable-bed #632 (commit 77049c8) Flat, Memory and go-to
        are held until the bed reports the end of the move, so these calls
        can take up to ~90 s; never await them in a HAP setter.
        """

        async def _runner() -> None:
            try:
                await coro
            except Exception as err:  # noqa: BLE001
                _LOGGER.exception("Command for %s failed", label)
                if notify_on_error:
                    self._async_notify_error(label, err, key)

        self.entry.async_create_background_task(self.hass, _runner(), f"homekit_bed {label}")

    @callback
    def _async_notify_error(self, label: str, err: Exception, key: str | None) -> None:
        """Explain a failed switch press; HomeKit itself cannot show errors."""
        message = render(self.texts, "action_failed", label=label, bed=self.display_name, error=err)
        slot = key.rsplit("_", 1)[-1] if key and key.startswith("memory_") else "1"
        if "has not been saved" in str(err):
            # JMC400 boxes other than type 4 keep memories as positions stored
            # by Home Assistant; an empty slot cannot be recalled (#632).
            message += "\n\n" + render(self.texts, "memory_not_saved", slot=slot)
        elif "one memory slot" in str(err):
            message += "\n\n" + render(self.texts, "memory_one_slot")
        persistent_notification.async_create(
            self.hass,
            message,
            render(self.texts, "notification_title"),
            f"homekit_bed_{self.entry.entry_id}_action_error",
        )

    def add_late_char(
        self,
        service: Any,
        name: str,
        *,
        value: Any = None,
        properties: dict[str, Any] | None = None,
        setter: Any = None,
    ) -> Any:
        """Append a characteristic to an already added service.

        pyhap expects characteristics before add_service; doing it by hand
        (broker + IID) keeps every existing IID unchanged.
        """
        char = self.driver.loader.get_char(name)
        if properties:
            char.override_properties(properties=properties)
        service.add_characteristic(char)
        char.broker = self
        self.iid_manager.assign(char)
        if value is not None:
            char.set_value(value, should_notify=False)
        if setter is not None:
            char.setter_callback = setter
        return char

    # ------------------------------------------------------------ bed name
    def _hk_bed_renamed(self, value: Any) -> None:
        """The Home app renamed the bed tile; accept it (never enforced)."""
        _LOGGER.info("Home app renamed bed %r to %r", self.display_name, value)

    @callback
    def async_set_name(self, name: str) -> None:
        """Push a new bed name to the Home app."""
        if not name or name == self.display_name and self.char_bed_name.value == name:
            return
        _LOGGER.info("Renaming bed %r to %r in HomeKit", self.display_name, name)
        self.display_name = name
        info = self.get_service("AccessoryInformation")
        assert info is not None
        info.get_characteristic("Name").set_value(name, should_notify=False)
        self.char_bed_name.set_value(name)  # evented -> Home app picks it up

    # ------------------------------------------------------------ captions
    @callback
    def async_on_home_rename(self, char: Any, label: str, value: Any) -> None:
        """The Home app wrote ConfiguredName (a rename or its own default).

        Observed: after pairing a multi-service accessory, the Home app can
        show generic names ("Jaloezieën 1", "Schakelaar 1") instead of the
        names the accessory offers, and write those into ConfiguredName.
        ConfiguredName is an evented characteristic, so pushing our caption
        back makes the Home app adopt it.
        """
        _LOGGER.info(
            "Home app wrote name %r for control %r (enforce captions: %s)",
            value,
            label,
            self.enforce_captions,
        )
        if not self.enforce_captions or value == label:
            return

        @callback
        def _reassert(_now: Any) -> None:
            # No sender address: the event also reaches the client that wrote.
            char.set_value(label)

        self._caption_unsubs.append(
            async_call_later(
                self.hass,
                CAPTION_REASSERT_SECONDS,
                HassJob(_reassert, cancel_on_shutdown=True),
            )
        )

    @callback
    def async_push_captions(self, *_: Any) -> None:
        """Send every caption to subscribed Home app clients again."""
        _LOGGER.debug("Pushing %d captions to HomeKit", len(self.caption_chars))
        for char, label in self.caption_chars:
            if char.value != label:
                char.set_value(label)  # notifies because the value changes
            else:
                char.notify()

    @callback
    def async_schedule_caption_push(self) -> None:
        """Push captions a few times while the Home app settles."""
        for delay in CAPTION_PUSH_DELAYS:
            self._caption_unsubs.append(
                async_call_later(
                    self.hass,
                    delay,
                    HassJob(self.async_push_captions, cancel_on_shutdown=True),
                )
            )

    @callback
    def async_attach(self) -> None:
        """Start following the source entities."""
        by_entity: dict[str, list[Any]] = {}
        for channel in [*self.sliders, *self.actions, *self.selects, *self.climates]:
            by_entity.setdefault(channel.entity_id, []).append(channel)
            channel.async_update_from_state(self.hass.states.get(channel.entity_id))

        @callback
        def _state_changed(event: Event[EventStateChangedData]) -> None:
            new_state = event.data["new_state"]
            for channel in by_entity.get(event.data["entity_id"], ()):
                channel.async_update_from_state(new_state)

        if by_entity:
            self._unsubs.append(
                async_track_state_change_event(self.hass, list(by_entity), _state_changed)
            )

    @callback
    def async_detach(self) -> None:
        """Stop following the source entities and cancel timers."""
        while self._unsubs:
            self._unsubs.pop()()
        while self._caption_unsubs:
            self._caption_unsubs.pop()()
        for channel in [*self.sliders, *self.actions, *self.selects, *self.climates]:
            channel.async_cancel()
        self.motion.clear()
