"""HomeKit Adjustable Bed.

Publishes an adjustable bed (e.g. a Jensen JMC400 via kristofferR/ha-adjustable-bed)
as ONE HomeKit accessory with four sliders and two switches.
"""

from __future__ import annotations

import logging

from aiohttp import web
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.http import HomeAssistantView
from homeassistant.helpers.start import async_at_started
from homeassistant.helpers.typing import ConfigType

from .const import (
    DOMAIN,
    LABEL_PREFIX,
    LEGACY_CONF_MEMORY,
    QR_VIEW_URL,
    SERVICE_PUSH_CAPTIONS,
    SERVICE_RESET_PAIRING,
)
from .labels import async_default_labels
from .server import (
    BedHomeKitServer,
    legacy_persist_file_path,
    remove_persist_file,
)
from .vol import vol

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type HomeKitBedConfigEntry = ConfigEntry[BedHomeKitServer]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the pairing QR view once."""
    hass.data.setdefault(DOMAIN, {}).setdefault("qr", {})
    hass.http.register_view(PairingQRView(hass))

    async def _reset_pairing(call: ServiceCall) -> None:
        """Forget all HomeKit pairings and show a fresh setup code."""
        wanted = call.data.get("config_entry_id")
        for entry in hass.config_entries.async_loaded_entries(DOMAIN):
            if wanted and entry.entry_id != wanted:
                continue
            await entry.runtime_data.async_reset_pairing()

    async def _push_captions(call: ServiceCall) -> None:
        """Re-send all captions to the Home app (no re-pairing needed)."""
        wanted = call.data.get("config_entry_id")
        for entry in hass.config_entries.async_loaded_entries(DOMAIN):
            if wanted and entry.entry_id != wanted:
                continue
            if accessory := entry.runtime_data.accessory:
                accessory.async_push_captions()

    hass.services.async_register(
        DOMAIN,
        SERVICE_PUSH_CAPTIONS,
        _push_captions,
        schema=vol.Schema({vol.Optional("config_entry_id"): cv.string}),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_RESET_PAIRING,
        _reset_pairing,
        schema=vol.Schema({vol.Optional("config_entry_id"): cv.string}),
    )
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """v1 -> v2: single memory switch becomes memory_1, bridged layout."""
    if entry.version > 2:
        return False
    if entry.version == 1:
        options = dict(entry.options)
        if memory := options.pop(LEGACY_CONF_MEMORY, None):
            options.setdefault("memory_1", memory)
        old_label = options.pop(f"{LABEL_PREFIX}{LEGACY_CONF_MEMORY}", None)
        old_defaults = {"Memory positie", "Memory position"}
        options[f"{LABEL_PREFIX}memory_1"] = (
            old_label
            if old_label and old_label not in old_defaults
            else (await async_default_labels(hass))["memory_1"]
        )
        # The v1 pairing (standalone accessory) cannot show captions; drop
        # it so a fresh bridged pairing is offered.
        path = legacy_persist_file_path(hass, entry.entry_id)
        await hass.async_add_executor_job(_remove_if_exists, path)
        hass.config_entries.async_update_entry(entry, options=options, version=2)
        _LOGGER.warning(
            "HomeKit Adjustable Bed %s migrated to v2: remove the old bed from the Home app "
            "and pair again with the new code",
            entry.title,
        )
    return True


def _remove_if_exists(path: str) -> None:
    import os  # noqa: PLC0415

    if os.path.exists(path):
        os.remove(path)


async def async_setup_entry(hass: HomeAssistant, entry: HomeKitBedConfigEntry) -> bool:
    """Set up one bed accessory."""
    server = BedHomeKitServer(hass, entry)
    server.config_snapshot = _snapshot(entry)
    entry.runtime_data = server

    # Start once HA is fully up, so the bed entities have their states and
    # the massage sliders can read their 0-10 range.
    async def _start(_hass: HomeAssistant) -> None:
        await server.async_start()

    entry.async_on_unload(async_at_started(hass, _start))
    entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, server.async_stop))
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


def _snapshot(entry: ConfigEntry) -> tuple[dict, dict]:
    return dict(entry.data), dict(entry.options)


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload on real changes; a rename only renames the bed in HomeKit."""
    server: BedHomeKitServer = entry.runtime_data
    if server.config_snapshot == _snapshot(entry):
        server.async_rename(entry.title)
        return
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: HomeKitBedConfigEntry) -> bool:
    """Stop the accessory."""
    await entry.runtime_data.async_stop()
    return True


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Forget the HomeKit pairing when the entry is deleted."""
    await hass.async_add_executor_job(remove_persist_file, hass, entry.entry_id)


class PairingQRView(HomeAssistantView):
    """Serve the pairing QR code referenced by the notification."""

    url = QR_VIEW_URL
    name = "api:homekit_adjustable_bed:pairingqr"
    requires_auth = False  # protected by a one-time random secret

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    async def get(self, request: web.Request) -> web.Response:
        entry_id, _, secret = request.query_string.partition("-")
        stored = self.hass.data.get(DOMAIN, {}).get("qr", {}).get(entry_id)
        if not stored or not secret or not secrets_equal(stored[0], secret):
            raise web.HTTPUnauthorized
        return web.Response(body=stored[1], content_type="image/svg+xml")


def secrets_equal(a: str, b: str) -> bool:
    import hmac  # noqa: PLC0415

    return hmac.compare_digest(a, b)
