"""Device registry helpers that work with and without child devices.

Since Home Assistant 2026.9 an integration can model parts of one product as
child devices (ChildDeviceEntry). A child device has a ``parent_device_id``
but no manufacturer, model, firmware or serial number of its own - those
belong to the parent - and reading them on a child is deprecated (removed in
2027.9). ha-adjustable-bed registers the bed whose entities we use as such a
child device. On older Home Assistant versions the attribute simply does not
exist, so everything here falls back to plain devices.
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr


def parent_device_id(device: Any) -> str | None:
    """Return the parent id of a child device, None for a main device."""
    return getattr(device, "parent_device_id", None)


def hardware_info(hass: HomeAssistant, device_id: str | None) -> tuple[str | None, str | None]:
    """Return (manufacturer, model) of a device, read from the parent for a child."""
    if not device_id:
        return None, None
    registry = dr.async_get(hass)
    device = registry.async_get(device_id)
    if device is None:
        return None, None
    if parent_id := parent_device_id(device):
        device = registry.async_get(parent_id)
        if device is None:
            return None, None
    # getattr: on HA 2026.9+ a lookup may also return a child entry.
    return getattr(device, "manufacturer", None), getattr(device, "model", None)


def related_device_ids(hass: HomeAssistant, device_id: str) -> list[str]:
    """The device itself plus its child devices, if any.

    Lets a user pick either the parent or the child: entities are found on
    whichever one ha-adjustable-bed attached them to.
    """
    ids = [device_id]
    children = getattr(dr, "async_entries_for_parent_device", None)
    if children is not None:
        ids.extend(child.id for child in children(dr.async_get(hass), device_id))
    return ids


def child_device_ids(hass: HomeAssistant, device_id: str) -> list[str]:
    """Child devices (HA 2026.9+), e.g. the two sides of a combined bed."""
    children = getattr(dr, "async_entries_for_parent_device", None)
    if children is None:
        return []
    return [child.id for child in children(dr.async_get(hass), device_id)]
