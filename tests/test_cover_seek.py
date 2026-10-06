"""Covers without set_position: seek with stop, or the three zones."""

import asyncio
from unittest.mock import patch

from homeassistant.core import HomeAssistant, ServiceCall

from custom_components.homekit_bed import sources
from custom_components.homekit_bed.sources import InvertedSliderSource, SliderSource

COVER = "cover.bed_back"


class FakeCover:
    """Finite moves of 30 points (5 per tick), reports its position, stoppable."""

    def __init__(self, hass, position: int | None) -> None:
        self.hass = hass
        self.position = position
        self.calls: list[str] = []
        self._stop = asyncio.Event()
        self._publish()
        for service in ("open_cover", "close_cover", "stop_cover"):
            hass.services.async_register("cover", service, self._handle)

    def _publish(self) -> None:
        attrs = {"supported_features": 11}  # open | close | stop, no set_position
        if self.position is not None:
            attrs["current_position"] = self.position
        self.hass.states.async_set(COVER, "closed" if (self.position or 0) == 0 else "open", attrs)

    async def _handle(self, call: ServiceCall) -> None:
        self.calls.append(call.service)
        if call.service == "stop_cover":
            self._stop.set()
            return
        self._stop.clear()
        step = 5 if call.service == "open_cover" else -5
        for _ in range(6):
            if self._stop.is_set() or self.position is None:
                return
            await asyncio.sleep(0.01)
            self.position = max(0, min(100, self.position + step))
            self._publish()


async def test_seek_stops_at_target(hass: HomeAssistant) -> None:
    cover = FakeCover(hass, 0)
    with patch.object(sources, "SEEK_POLL_SECONDS", 0.005):
        await SliderSource(hass, COVER).async_set_percent(40, blocking=True)
    assert abs(cover.position - 40) <= 5
    # 40 is more than one finite move (30): two moves, the second stopped early
    assert cover.calls.count("open_cover") == 2 and "stop_cover" in cover.calls

    cover.calls.clear()
    with patch.object(sources, "SEEK_POLL_SECONDS", 0.005):
        await SliderSource(hass, COVER).async_set_percent(10, blocking=True)
    assert abs(cover.position - 10) <= 5 and cover.calls[0] == "close_cover"


async def test_seek_inverted(hass: HomeAssistant) -> None:
    cover = FakeCover(hass, 0)
    with patch.object(sources, "SEEK_POLL_SECONDS", 0.005):
        # HomeKit 75 % on an inverted slider = bed at 25 %
        await InvertedSliderSource(hass, COVER).async_set_percent(75, blocking=True)
    assert abs(cover.position - 25) <= 5


async def test_seek_stops_at_end_stop(hass: HomeAssistant) -> None:
    cover = FakeCover(hass, 95)
    with patch.object(sources, "SEEK_POLL_SECONDS", 0.005):
        await SliderSource(hass, COVER).async_set_percent(100, blocking=True)
    assert cover.position == 100


async def test_zones_without_position(hass: HomeAssistant) -> None:
    cover = FakeCover(hass, None)
    src = SliderSource(hass, COVER)
    await src.async_set_percent(85, blocking=True)
    await src.async_set_percent(50, blocking=True)
    await src.async_set_percent(10, blocking=True)
    assert cover.calls == ["open_cover", "stop_cover", "close_cover"]
