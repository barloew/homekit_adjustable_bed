"""Adapters that translate Home Assistant entities to HomeKit values.

A slider source turns any number / input_number / cover into a 0-100 %
value and back. An action source "presses" a button, script, scene or
switch. Keeping this separate from the HAP code means the accessory never
needs to know which domain it is driving (a lesson taken from
sammcj/homekit_device, which forwards through generic services so a switch,
input_boolean or fan source all work).
"""

from __future__ import annotations

import asyncio
from math import isfinite
from typing import Any

from homeassistant.components.cover import (
    ATTR_CURRENT_POSITION,
    ATTR_POSITION,
    CoverEntityFeature,
)
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_SUPPORTED_FEATURES,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant, State

from .const import STATEFUL_DOMAINS

UNREADABLE_STATES = (STATE_UNAVAILABLE, STATE_UNKNOWN)


def _as_float(value: object) -> float | None:
    """Return value as a finite float, or None."""
    try:
        number = float(value)  # type: ignore[arg-type]
    except TypeError, ValueError:
        return None
    return number if isfinite(number) else None


def _clamp_pct(value: float) -> int:
    return max(0, min(100, round(value)))


class SliderSource:
    """A number, input_number or cover exposed as a 0-100 % slider."""

    def __init__(
        self, hass: HomeAssistant, entity_id: str, *, unknown_is_off: bool = False
    ) -> None:
        """Initialise the source.

        unknown_is_off: the bed never reports massage levels, so
        ha-adjustable-bed shows them as "unknown" until one is set (for
        example after a restart). For such sources "unknown" means off.
        """
        self.hass = hass
        self.entity_id = entity_id
        self.domain = entity_id.split(".", 1)[0]
        self.unknown_is_off = unknown_is_off

    @property
    def off_percent(self) -> int:
        """The HomeKit value that means 'off / flat'."""
        return 0

    # ------------------------------------------------------------------ read
    def _range(self, state: State | None) -> tuple[float, float, float]:
        """Return (min, max, step) of a numeric source."""
        attrs = state.attributes if state else {}
        low = _as_float(attrs.get("min"))
        high = _as_float(attrs.get("max"))
        step = _as_float(attrs.get("step"))
        low = 0.0 if low is None else low
        high = 100.0 if high is None or high <= low else high
        step = 1.0 if not step or step <= 0 else step
        return low, high, step

    @property
    def native_steps(self) -> int | None:
        """Number of discrete steps of a numeric source (10 for massage 0-10)."""
        if self.domain in ("cover", "light"):
            return None
        if self.domain == "fan":
            state = self.hass.states.get(self.entity_id)
            step = _as_float(state.attributes.get("percentage_step")) if state else None
            steps = round(100 / step) if step else 0
            return steps if 0 < steps <= 100 else None
        low, high, step = self._range(self.hass.states.get(self.entity_id))
        steps = round((high - low) / step)
        return steps if 0 < steps <= 100 else None

    def read_percent(self, state: State | None) -> int | None:
        """Return the source position as a percentage, or None if unknown."""
        if state is not None and state.state == STATE_UNKNOWN and self.unknown_is_off:
            return 0
        if state is None or state.state in UNREADABLE_STATES:
            return None
        if self.domain == "light":
            if state.state != "on":
                return 0
            brightness = _as_float(state.attributes.get("brightness"))
            return 100 if brightness is None else max(1, _clamp_pct(brightness / 255 * 100))
        if self.domain == "fan":
            if state.state != "on":
                return 0
            pct = _as_float(state.attributes.get("percentage"))
            return 100 if pct is None else _clamp_pct(pct)
        if self.domain == "cover":
            pos = _as_float(state.attributes.get(ATTR_CURRENT_POSITION))
            if pos is None:
                # Open/close-only cover: best effort from its state.
                if state.state == "closed":
                    return 0
                if state.state == "open":
                    return 100
                return None
            return _clamp_pct(pos)
        value = _as_float(state.state)
        if value is None:
            return None
        low, high, _ = self._range(state)
        return _clamp_pct((value - low) / (high - low) * 100)

    # ----------------------------------------------------------------- write
    async def _async_set_cover(self, state: State | None, percent: int, *, blocking: bool) -> None:
        await _async_cover_set(self, state, percent, blocking)

    async def async_set_percent(self, percent: int, *, blocking: bool) -> None:
        """Move the source to a percentage."""
        state = self.hass.states.get(self.entity_id)
        if self.domain in ("light", "fan"):
            if percent <= 0:
                service, data = "turn_off", {}
            elif self.domain == "light":
                service, data = "turn_on", {"brightness_pct": percent}
            else:
                service, data = "set_percentage", {"percentage": percent}
            await self.hass.services.async_call(
                self.domain,
                service,
                {ATTR_ENTITY_ID: self.entity_id, **data},
                blocking=blocking,
            )
            return
        if self.domain == "cover":
            await self._async_set_cover(state, percent, blocking=blocking)
            return

        low, high, step = self._range(state)
        raw = low + (percent / 100) * (high - low)
        # Snap to the source's own step so number validation never rejects it.
        value = low + round((raw - low) / step) * step
        value = max(low, min(high, value))
        if float(value).is_integer():
            value = int(value)
        await self.hass.services.async_call(
            self.domain,  # number / input_number both expose set_value
            "set_value",
            {ATTR_ENTITY_ID: self.entity_id, "value": value},
            blocking=blocking,
        )


class InvertedSliderSource(SliderSource):
    """A slider source shown upside down in HomeKit (100 - value).

    Like inverting a projector screen: a flat bed (0 %) shows as 100 % /
    "Open" in the Home app, and HomeKit 100 % moves the bed flat. Everything
    upstream (debounce, motion queue, settle logic) keeps working in HomeKit
    terms; only reading and writing flip.
    """

    @property
    def off_percent(self) -> int:
        return 100

    def read_percent(self, state: State | None) -> int | None:
        value = super().read_percent(state)
        return None if value is None else 100 - value

    async def async_set_percent(self, percent: int, *, blocking: bool) -> None:
        await super().async_set_percent(100 - percent, blocking=blocking)


# --------------------------------------------------------------------------
# Covers without a "set position" (most beds): open/close are finite moves.
# --------------------------------------------------------------------------
SEEK_TOLERANCE = 3  # percentage points
SEEK_POLL_SECONDS = 0.25
SEEK_TIMEOUT_SECONDS = 110.0
ZONE_OPEN = 70  # like the HA HomeKit Bridge: >70 raise, <30 lower, else stop
ZONE_CLOSE = 30


def _cover_percent(state: State | None) -> int | None:
    """Real (not inverted) cover position, or None without angle sensing."""
    if state is None or state.state in UNREADABLE_STATES:
        return None
    pos = _as_float(state.attributes.get(ATTR_CURRENT_POSITION))
    return None if pos is None else _clamp_pct(pos)


async def _async_cover_set(
    source: SliderSource, state: State | None, percent: int, blocking: bool
) -> None:
    hass = source.hass
    data = {ATTR_ENTITY_ID: source.entity_id}
    features = int(state.attributes.get(ATTR_SUPPORTED_FEATURES, 0)) if state else 0
    if features & CoverEntityFeature.SET_POSITION:
        await hass.services.async_call(
            "cover", "set_cover_position", {**data, ATTR_POSITION: percent}, blocking=blocking
        )
        return
    if _cover_percent(state) is not None:
        await _async_seek(source, percent)
        return
    # No position at all: the three zones of the HA HomeKit Bridge.
    if percent >= ZONE_OPEN:
        service = "open_cover"
    elif percent <= ZONE_CLOSE:
        service = "close_cover"
    else:
        service = "stop_cover"
    await hass.services.async_call("cover", service, data, blocking=blocking)


async def _async_seek(source: SliderSource, target: int) -> None:
    """Move a position-reporting cover to a target with open/close + stop.

    ha-adjustable-bed covers run a finite move per open/close and report the
    measured position while moving (angle sensing). Start a move in the right
    direction, stop it as soon as the target is reached, and repeat while the
    section makes progress (a finite move may end before the target).
    """
    hass = source.hass
    loop = asyncio.get_running_loop()
    deadline = loop.time() + SEEK_TIMEOUT_SECONDS
    data = {ATTR_ENTITY_ID: source.entity_id}

    def position() -> int | None:
        return _cover_percent(hass.states.get(source.entity_id))

    while loop.time() < deadline:
        start = position()
        if start is None or abs(start - target) <= SEEK_TOLERANCE:
            return
        opening = target > start
        move = hass.async_create_task(
            hass.services.async_call(
                "cover", "open_cover" if opening else "close_cover", data, blocking=True
            )
        )
        reached = False
        while not move.done():
            await asyncio.sleep(SEEK_POLL_SECONDS)
            now = position()
            if now is not None and (
                (opening and now >= target - SEEK_TOLERANCE)
                or (not opening and now <= target + SEEK_TOLERANCE)
            ):
                reached = True
                break
            if loop.time() >= deadline:
                break
        if not move.done():
            # Stop cancels the running move in ha-adjustable-bed.
            await hass.services.async_call("cover", "stop_cover", data, blocking=True)
        await asyncio.wait({move}, timeout=5)
        if move.done() and not move.cancelled():
            move.exception()  # retrieved; a cancelled move is expected
        if reached:
            return
        end = position()
        if end is None or abs(end - start) < 1:
            return  # no progress: end stop reached or no feedback


# domain -> (service domain, service)
_ACTION_SERVICES: dict[str, tuple[str, str]] = {
    "button": ("button", "press"),
    "input_button": ("input_button", "press"),
    "script": ("script", "turn_on"),
    "scene": ("scene", "turn_on"),
    "automation": ("automation", "trigger"),
}


class ActionSource:
    """A button/script/scene to press, or a switch/light/fan to toggle."""

    def __init__(self, hass: HomeAssistant, entity_id: str) -> None:
        """Initialise the source."""
        self.hass = hass
        self.entity_id = entity_id
        self.domain = entity_id.split(".", 1)[0]

    @property
    def stateful(self) -> bool:
        """True when the source has a real on/off state to mirror."""
        return self.domain in STATEFUL_DOMAINS

    def read_on(self, state: State | None) -> bool | None:
        """Return the on/off state of a stateful source."""
        if state is None or state.state in UNREADABLE_STATES:
            return None
        return state.state == "on"

    async def async_set(self, on: bool) -> None:
        """Turn a stateful source on or off."""
        await self.hass.services.async_call(
            "homeassistant",
            "turn_on" if on else "turn_off",
            {ATTR_ENTITY_ID: self.entity_id},
            blocking=True,
        )

    async def async_trigger(self) -> None:
        """Trigger the action."""
        # Fall back to the generic turn_on so switch/input_boolean/light work.
        service_domain, service = _ACTION_SERVICES.get(self.domain, ("homeassistant", "turn_on"))
        await self.hass.services.async_call(
            service_domain,
            service,
            {ATTR_ENTITY_ID: self.entity_id},
            blocking=True,
        )


class ServiceActionSource:
    """A push button that performs a service call (e.g. a timed move)."""

    stateful = False

    def __init__(self, hass: HomeAssistant, action: dict[str, Any]) -> None:
        """Initialise from {"domain", "service", "data"}."""
        self.hass = hass
        self.action = action
        self.entity_id = ""

    async def async_trigger(self) -> None:
        """Perform the call and wait for it (a timed move ends by itself)."""
        await self.hass.services.async_call(
            self.action["domain"],
            self.action["service"],
            dict(self.action["data"]),
            blocking=True,
        )
