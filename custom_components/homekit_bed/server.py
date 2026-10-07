"""Runs the HAP accessory server for one config entry.

Mirrors how the built-in HomeKit Bridge (homeassistant/components/homekit)
drives HAP-python: the driver shares HA's event loop and zeroconf instance,
pairing state is persisted under .storage, and the setup code is shown as a
persistent notification with a QR code.
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import secrets
import socket
from functools import partial
from typing import Any

from homeassistant.components import network, persistent_notification, zeroconf
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import instance_id
from homeassistant.helpers.storage import STORAGE_DIR
from pyhap.accessory_driver import AccessoryDriver
from pyhap.loader import get_loader
from pyhap.util import callback as pyhap_callback

from .accessory import BedAccessory, BedBridge
from .const import (
    COLOR_PREFIX,
    CONF_BED_DEVICE,
    CONF_ENFORCE_CAPTIONS,
    CONF_INVERTED,
    CONF_PORT,
    CONF_PRIMARY,
    DEFAULT_COLOR,
    DEFAULT_ENFORCE_CAPTIONS,
    DEFAULT_PORT,
    DEFAULT_PRIMARY,
    DOMAIN,
    QR_VIEW_URL,
    SLIDER_KEYS,
    VERSION,
)
from .controls import (
    HK_CLIMATE,
    HK_MOMENTARY,
    HK_SELECT,
    HK_SWITCH,
    effective_controls,
)
from .devices import hardware_info
from .iids import StableIIDManager, load_iids, save_iids
from .labels import (
    FALLBACK_TEXTS,
    async_climate_mode_names,
    async_default_labels,
    async_texts,
    render,
)
from .sources import ServiceActionSource

_LOGGER = logging.getLogger(__name__)

SHUTDOWN_TIMEOUT = 30  # seconds, same as homeassistant.components.homekit
_HAS_IPV6 = socket.has_ipv6
_DEFAULT_BIND = ["0.0.0.0", "::"] if _HAS_IPV6 else ["0.0.0.0"]


def persist_file_path(hass: HomeAssistant, entry_id: str) -> str:
    """Return where the pairing state of an entry lives.

    v2 uses a new file (= a new HomeKit identity): v1 published the bed as a
    standalone accessory and the Home app caches names at pairing time, so the
    bridged v2 layout must be paired fresh to pick up the captions.
    """
    return hass.config.path(STORAGE_DIR, f"{DOMAIN}.{entry_id}.v2.state")


def iid_file_path(hass: HomeAssistant, entry_id: str) -> str:
    """Where the stable IID map of an entry lives."""
    return hass.config.path(STORAGE_DIR, f"{DOMAIN}.{entry_id}.iids")


def legacy_persist_file_path(hass: HomeAssistant, entry_id: str) -> str:
    """Pairing state file of v1 entries."""
    return hass.config.path(STORAGE_DIR, f"{DOMAIN}.{entry_id}.state")


class BedDriver(AccessoryDriver):
    """AccessoryDriver that keeps the HA pairing notification in sync."""

    def __init__(self, server: BedHomeKitServer, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._server = server

    @pyhap_callback
    def pair(self, client_username_bytes, client_public, client_permissions):  # type: ignore[no-untyped-def]
        success = super().pair(client_username_bytes, client_public, client_permissions)
        if success:
            self._server.async_dismiss_setup_message()
            if self._server.accessory:
                self._server.accessory.async_schedule_caption_push()
        return success

    @pyhap_callback
    def unpair(self, client_uuid):  # type: ignore[no-untyped-def]
        super().unpair(client_uuid)
        if not self.state.paired:
            self._server.async_show_setup_message()


class BedHomeKitServer:
    """Owns the driver and accessory of one bed."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.driver: BedDriver | None = None
        self.texts: dict[str, str] = dict(FALLBACK_TEXTS)
        self.accessory: BedAccessory | None = None
        self._started = False
        # (data, options) the server was started with; a title-only change of
        # the entry is handled as a live rename instead of a reload.
        self.config_snapshot: tuple[dict, dict] | None = None

    # ----------------------------------------------------------- lifecycle
    async def async_start(self) -> None:
        """Create the accessory and start advertising it."""
        if self.driver is not None:
            return
        hass, entry = self.hass, self.entry
        options = {**entry.data, **entry.options}
        # The bed follows the entry title, so renaming the entry in HA renames
        # the bed. The (invisible) bridge keeps the name it was paired with:
        # its mDNS service name is derived from it.
        name = entry.title or options.get(CONF_NAME) or "Bed"
        bridge_name = f"{options.get(CONF_NAME) or name} HomeKit"
        port = int(entry.data.get(CONF_PORT, DEFAULT_PORT))

        labels = await async_default_labels(hass)
        self.texts = await async_texts(hass)
        controls = effective_controls(hass, dict(entry.data), options, labels)
        sliders = [(c.id, c.caption, c.entity_id, c.motor) for c in controls if c.is_slider]
        actions = [
            (c.id, c.caption, c.entity_id)
            for c in controls
            if c.hk_type in (HK_MOMENTARY, HK_SWITCH)
        ]
        selects = [(c.id, c.caption, c.entity_id) for c in controls if c.hk_type == HK_SELECT]
        climates = [(c.id, c.caption, c.entity_id) for c in controls if c.hk_type == HK_CLIMATE]
        kinds = {c.id: c.hk_type for c in controls if c.is_slider}
        action_sources = {c.id: ServiceActionSource(hass, c.action) for c in controls if c.action}
        interrupts = {c.id for c in controls if c.interrupts_motion}
        if not sliders and not actions and not selects and not climates:
            _LOGGER.error("%s: no source entities configured", name)
            return

        manufacturer, model = "Home Assistant", "Adjustable bed"
        if device_id := entry.data.get(CONF_BED_DEVICE):
            # Read from the parent when the bed is a child device (HA 2026.9+).
            hw_manufacturer, hw_model = hardware_info(hass, device_id)
            manufacturer = hw_manufacturer or manufacturer
            model = hw_model or model

        async_zc = await zeroconf.async_get_async_instance(hass)
        uuid = await instance_id.async_get(hass)
        advertise = await network.async_get_announce_addresses(hass)
        loader = await hass.async_add_executor_job(get_loader)

        driver = BedDriver(
            self,
            loop=hass.loop,
            address=_DEFAULT_BIND,
            port=port,
            persist_file=persist_file_path(hass, entry.entry_id),
            advertised_address=advertise,
            async_zeroconf_instance=async_zc,
            zeroconf_server=f"{uuid}-hap.local.",
            loader=loader,
        )
        iid_path = iid_file_path(hass, entry.entry_id)
        iid_manager = StableIIDManager(await hass.async_add_executor_job(load_iids, iid_path))
        accessory = BedAccessory(
            hass,
            driver,
            entry,
            name,
            sliders,
            actions,
            manufacturer=manufacturer,
            model=model,
            serial=entry.entry_id,
            firmware=VERSION,
            enforce_captions=options.get(CONF_ENFORCE_CAPTIONS, DEFAULT_ENFORCE_CAPTIONS),
            primary_key=options.get(CONF_PRIMARY, DEFAULT_PRIMARY),
            texts=self.texts,
            iid_manager=iid_manager,
            inverted=set(options.get(CONF_INVERTED) or []),
            kinds=kinds,
            interrupts=interrupts,
            selects=selects,
            action_sources=action_sources,
            climates=climates,
            mode_names=await async_climate_mode_names(hass),
            color_off={
                key for key in SLIDER_KEYS if not options.get(f"{COLOR_PREFIX}{key}", DEFAULT_COLOR)
            },
        )
        bridge = BedBridge(driver, bridge_name)
        bridge.set_info_service(
            firmware_revision=VERSION,
            manufacturer="Home Assistant",
            model="HomeKit Bed Aggregator",
            serial_number=f"{entry.entry_id}-bridge",
        )
        bridge.add_accessory(accessory)
        # add_accessory loads or writes the persist file: blocking I/O.
        await hass.async_add_executor_job(driver.add_accessory, bridge)
        if iid_manager.changed:
            await hass.async_add_executor_job(save_iids, iid_path, iid_manager.map)
        self.driver, self.accessory = driver, accessory

        accessory.async_attach()
        try:
            await driver.async_start()
        except OSError as err:
            _LOGGER.error("Cannot start HomeKit accessory %s on port %s: %s", name, port, err)
            persistent_notification.async_create(
                hass,
                render(self.texts, "port_error", name=name, port=port, error=err),
                render(self.texts, "notification_title"),
                f"{DOMAIN}_{entry.entry_id}_error",
            )
            accessory.async_detach()
            self.driver = self.accessory = None
            return
        self._started = True
        _LOGGER.info("HomeKit bed accessory %s running on port %s", name, port)

        if not driver.state.paired:
            self.async_show_setup_message()
        else:
            accessory.async_schedule_caption_push()

    @callback
    def async_rename(self, title: str) -> None:
        """Rename the bed in HomeKit without restarting the HAP server.

        A restart drops every HomeKit connection and the mDNS record for a
        moment, which the Home app can show as "not responding".
        """
        if self.accessory:
            self.accessory.async_set_name(title)

    async def async_stop(self, *_: Any) -> None:
        """Stop advertising and release the port."""
        if self.accessory:
            self.accessory.async_detach()
        if self.driver and self._started:
            try:
                await self.driver.async_stop()
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Error while stopping HomeKit bed accessory")
        self._started = False
        self.driver = self.accessory = None
        # Like the HA HomeKit Bridge: wait until the port is really free, so an
        # immediate restart (reload) can bind it again.
        port = int(self.entry.data.get(CONF_PORT, DEFAULT_PORT))
        for _attempt in range(SHUTDOWN_TIMEOUT):
            if await async_port_is_free(self.hass, port):
                break
            await asyncio.sleep(1)

    # ------------------------------------------------------------- pairing
    @callback
    def async_show_setup_message(self) -> None:
        """Show the pairing code and QR code as a persistent notification."""
        if not self.driver or not self.accessory:
            return
        import pyqrcode  # noqa: PLC0415 - light import, only when needed

        pin = self.driver.state.pincode.decode()
        bridge = self.driver.accessory
        assert bridge is not None
        buffer = io.BytesIO()
        pyqrcode.create(bridge.xhm_uri()).svg(
            buffer, scale=5, module_color="#000", background="#FFF"
        )
        secret = secrets.token_hex(32)
        self.hass.data.setdefault(DOMAIN, {}).setdefault("qr", {})[self.entry.entry_id] = (
            secret,
            buffer.getvalue(),
        )
        _LOGGER.info("HomeKit bed %s pincode: %s", self.entry.title, pin)
        persistent_notification.async_create(
            self.hass,
            render(
                self.texts,
                "pairing_message",
                name=self.entry.title,
                pin=pin,
                qr_url=f"{QR_VIEW_URL}?{self.entry.entry_id}-{secret}",
            ),
            render(self.texts, "pairing_title"),
            f"{DOMAIN}_{self.entry.entry_id}",
        )

    @callback
    def pairing_info(self) -> dict[str, Any] | None:
        """Pairing status for the options flow; None when not running."""
        if not self.driver or not self._started or self.driver.accessory is None:
            return None
        return {
            "paired": self.driver.state.paired,
            "controllers": len(self.driver.state.paired_clients),
            "pin": self.driver.state.pincode.decode(),
            "uri": self.driver.accessory.xhm_uri(),
        }

    async def async_reset_pairing(self) -> None:
        """Forget every HomeKit pairing and start with a new identity.

        Needed when the bed was removed in the Home app while it could not
        be reached: the Home app forgets it, but the bed still believes it is
        paired, does not advertise itself as pairable, and cannot be added
        again. Stored IIDs are kept; the new identity is a new accessory to
        the Home app anyway.
        """
        await self.async_stop()
        await self.hass.async_add_executor_job(remove_pairing_state, self.hass, self.entry.entry_id)
        await self.async_start()

    @callback
    def async_dismiss_setup_message(self) -> None:
        persistent_notification.async_dismiss(self.hass, f"{DOMAIN}_{self.entry.entry_id}")
        self.hass.data.get(DOMAIN, {}).get("qr", {}).pop(self.entry.entry_id, None)


def remove_pairing_state(hass: HomeAssistant, entry_id: str) -> None:
    """Delete only the pairing state, keeping the IID map (executor)."""
    for path in (
        persist_file_path(hass, entry_id),
        legacy_persist_file_path(hass, entry_id),
    ):
        if os.path.exists(path):
            os.remove(path)


def remove_persist_file(hass: HomeAssistant, entry_id: str) -> None:
    """Delete the pairing state (run in executor)."""
    for path in (
        persist_file_path(hass, entry_id),
        legacy_persist_file_path(hass, entry_id),
        iid_file_path(hass, entry_id),
    ):
        if os.path.exists(path):
            os.remove(path)


async def async_port_is_free(hass: HomeAssistant, port: int) -> bool:
    """Return True if nothing listens on the TCP port yet."""

    def _check() -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("0.0.0.0", port))
            except OSError:
                return False
        return True

    return await hass.async_add_executor_job(partial(_check))
