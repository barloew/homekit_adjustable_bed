"""Renaming the entry renames the bed live; real start/stop/start works."""

import asyncio
import socket
from unittest.mock import AsyncMock, patch

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.homekit_bed import _async_update_listener, _snapshot
from custom_components.homekit_bed.server import BedHomeKitServer


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _entry(hass, port):
    hass.states.async_set("number.a", "10", {"min": 0, "max": 100, "step": 1})
    entry = MockConfigEntry(
        domain="homekit_bed",
        title="Ons bed",
        version=2,
        data={"name": "Ons bed", "port": port},
        options={"back": "number.a", "label_back": "Rug"},
    )
    entry.add_to_hass(hass)
    return entry


async def test_start_stop_start_and_live_rename(
    hass: HomeAssistant, mock_async_zeroconf, socket_enabled, tmp_path
) -> None:
    hass.config.config_dir = str(tmp_path)
    (tmp_path / ".storage").mkdir()
    port = _free_port()
    entry = _entry(hass, port)
    with (
        patch(
            "homeassistant.components.network.async_get_announce_addresses",
            return_value=["127.0.0.1"],
        ),
        patch("homeassistant.helpers.instance_id.async_get", return_value="abc"),
    ):
        server = BedHomeKitServer(hass, entry)
        server.config_snapshot = _snapshot(entry)
        entry.runtime_data = server
        await server.async_start()
        assert server.driver is not None
        bed = server.accessory
        bridge = server.driver.accessory
        assert bridge.display_name == "Ons bed HomeKit"
        assert bed.char_bed_name.value == "Ons bed"
        # HomeKit client can connect
        _, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.close()

        # Rename the entry: no reload, the evented name changes.
        published = []
        server.driver.publish = lambda data, *a, **k: published.append(data)
        reload = AsyncMock()
        with patch.object(hass.config_entries, "async_reload", reload):
            hass.config_entries.async_update_entry(entry, title="Barloew's bed")
            await _async_update_listener(hass, entry)
        reload.assert_not_called()
        assert server.driver is not None and server.accessory is bed
        assert bed.char_bed_name.value == "Barloew's bed"
        assert bed.display_name == "Barloew's bed"
        assert any(d.get("value") == "Barloew's bed" for d in published)
        # The bridge keeps its paired name (mDNS service name).
        assert bridge.display_name == "Ons bed HomeKit"

        # An options change still reloads.
        with patch.object(hass.config_entries, "async_reload", reload):
            hass.config_entries.async_update_entry(
                entry, options={**entry.options, "label_back": "Hoofdeinde"}
            )
            await _async_update_listener(hass, entry)
        reload.assert_called_once()

        # Stop, then a fresh server binds the same port right away.
        await server.async_stop()
        server2 = BedHomeKitServer(hass, entry)
        await server2.async_start()
        assert server2.driver is not None
        assert server2.accessory.char_bed_name.value == "Barloew's bed"
        await server2.async_stop()


async def test_reset_pairing_gives_new_identity(
    hass: HomeAssistant, mock_async_zeroconf, socket_enabled, tmp_path
) -> None:
    """A stale pairing is forgotten; new identity, new code, IIDs kept."""
    import os
    import uuid

    from custom_components.homekit_bed.server import iid_file_path

    hass.config.config_dir = str(tmp_path)
    (tmp_path / ".storage").mkdir()
    port = _free_port()
    entry = _entry(hass, port)
    with (
        patch(
            "homeassistant.components.network.async_get_announce_addresses",
            return_value=["127.0.0.1"],
        ),
        patch("homeassistant.helpers.instance_id.async_get", return_value="abc"),
    ):
        server = BedHomeKitServer(hass, entry)
        await server.async_start()
        state = server.driver.state
        state.add_paired_client(str(uuid.uuid4()).encode(), b"0" * 32, b"\x01")
        await hass.async_add_executor_job(server.driver.persist)
        old_mac, old_pin = state.mac, state.pincode
        assert server.pairing_info()["paired"]

        await server.async_reset_pairing()
        info = server.pairing_info()
        assert info is not None and not info["paired"]
        assert server.driver.state.mac != old_mac
        assert server.driver.state.pincode != old_pin
        assert info["uri"].startswith("X-HM://")
        assert os.path.exists(iid_file_path(hass, entry.entry_id))  # IIDs kept
        await server.async_stop()
