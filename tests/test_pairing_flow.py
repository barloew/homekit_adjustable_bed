"""Options menu: show the QR code again, or reset a stale pairing."""

from unittest.mock import AsyncMock, patch

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.selector import QrCodeSelector
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.homekit_adjustable_bed.const import DOMAIN


class FakeServer:
    def __init__(self, paired: bool) -> None:
        self.paired = paired
        self.async_reset_pairing = AsyncMock(side_effect=self._reset)

    async def _reset(self) -> None:
        self.paired = False

    def pairing_info(self):
        return {
            "paired": self.paired,
            "controllers": 2 if self.paired else 0,
            "pin": "123-45-678",
            "uri": "X-HM://0023ABCDEFGHI",
        }


async def _open_pairing(hass, server):
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        title="Barloew's bed",
        data={"name": "Bed", "port": 21070},
        options={"back": "number.a", "label_back": "Rug"},
    )
    entry.add_to_hass(hass)
    with patch("custom_components.homekit_adjustable_bed.async_setup_entry", return_value=True):
        await hass.config_entries.async_setup(entry.entry_id)
    if server is not None:
        entry.runtime_data = server
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    assert result["menu_options"] == ["controls", "pairing"]
    return entry, await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "pairing"}
    )


async def test_qr_shown_when_not_paired(hass: HomeAssistant, mock_async_zeroconf) -> None:
    entry, result = await _open_pairing(hass, FakeServer(paired=False))
    assert result["step_id"] == "pairing"
    assert result["description_placeholders"]["pin"] == "123-45-678"
    qr = next(v for k, v in result["data_schema"].schema.items() if k == "qr")
    assert isinstance(qr, QrCodeSelector)
    assert qr.config["data"] == "X-HM://0023ABCDEFGHI"
    before = dict(entry.options)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert dict(entry.options) == before  # nothing changed, no reload


async def test_paired_offers_reset_then_qr(hass: HomeAssistant, mock_async_zeroconf) -> None:
    server = FakeServer(paired=True)
    entry, result = await _open_pairing(hass, server)
    assert result["step_id"] == "paired"
    assert result["description_placeholders"]["controllers"] == "2"
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"reset": True})
    server.async_reset_pairing.assert_awaited_once()
    assert result["step_id"] == "pairing"  # fresh QR right away


async def test_paired_without_reset_changes_nothing(
    hass: HomeAssistant, mock_async_zeroconf
) -> None:
    server = FakeServer(paired=True)
    _, result = await _open_pairing(hass, server)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"reset": False})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    server.async_reset_pairing.assert_not_awaited()


async def test_not_running_aborts(hass: HomeAssistant, mock_async_zeroconf) -> None:
    _, result = await _open_pairing(hass, None)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "not_running"
