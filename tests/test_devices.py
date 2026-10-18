"""Child devices (HA 2026.9+): never read manufacturer/model on a child."""

from types import SimpleNamespace
from unittest.mock import patch

from homeassistant.core import HomeAssistant

from custom_components.homekit_adjustable_bed import devices


class _Child:
    """Mimics ChildDeviceEntry: reading hardware fields is deprecated."""

    id = "child"
    parent_device_id = "parent"

    @property
    def manufacturer(self):  # pragma: no cover - must not be called
        raise AssertionError("manufacturer read on a child device")

    @property
    def model(self):  # pragma: no cover - must not be called
        raise AssertionError("model read on a child device")


class _Registry:
    def __init__(self):
        self.items = {
            "child": _Child(),
            "parent": SimpleNamespace(id="parent", manufacturer="Jensen", model="JMC400"),
            "plain": SimpleNamespace(id="plain", manufacturer="Okin", model="X"),
        }

    def async_get(self, device_id):
        return self.items.get(device_id)


async def test_hardware_info_reads_parent_of_child(hass: HomeAssistant) -> None:
    with patch.object(devices.dr, "async_get", return_value=_Registry()):
        assert devices.hardware_info(hass, "child") == ("Jensen", "JMC400")
        assert devices.hardware_info(hass, "plain") == ("Okin", "X")
        assert devices.hardware_info(hass, "missing") == (None, None)
        assert devices.hardware_info(hass, None) == (None, None)


async def test_related_device_ids(hass: HomeAssistant) -> None:
    # Older HA without child devices: just the device itself.
    with patch.object(devices.dr, "async_entries_for_parent_device", None, create=True):
        assert devices.related_device_ids(hass, "parent") == ["parent"]
    # HA 2026.9+: parent plus its children.
    with patch.object(
        devices.dr,
        "async_entries_for_parent_device",
        lambda reg, dev_id: [SimpleNamespace(id="child")] if dev_id == "parent" else [],
        create=True,
    ):
        assert devices.related_device_ids(hass, "parent") == ["parent", "child"]
        assert devices.related_device_ids(hass, "child") == ["child"]
