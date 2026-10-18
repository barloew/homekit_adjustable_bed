# HomeKit Bed

Publishes an adjustable bed from [Adjustable Bed](https://github.com/kristofferR/ha-adjustable-bed)
as **one HomeKit accessory** in the Apple Home app: the bed sections, presets, massage, lights and
climate become captioned sliders and switches in a single tile, with their own pairing code.

- Works for every bed type Adjustable Bed supports: the integration reads what the bed offers
  and registers sensible controls by default (see [Detection](docs/DETECTION.md)).
- Real positions where the bed reports them, a motion queue so sections never fight, and
  inverted sliders if you prefer "flat = 100 %".
- Any Home Assistant light (for example a Hue strip under the bed) can join the same tile,
  including colour.
- Combined beds (one parent with a left and right bed) are supported.

User interface languages: English and Dutch.

## Requirements

- Home Assistant **2026.9.0** or newer (Python 3.14)
- <!-- adjustable-bed-version -->[Adjustable Bed](https://github.com/kristofferR/ha-adjustable-bed) v4 with your bed set up (checked against v4.2.3, see [Supported beds](docs/SUPPORTED_BEDS.md))<!-- /adjustable-bed-version -->
- A free TCP port for the accessory (default 21070), reachable from your Apple home hub

## Installation

1. Copy `custom_components/homekit_bed` to `config/custom_components/` (or add this repository
   to HACS as a custom integration repository) and restart Home Assistant.
2. Settings → Devices & services → Add integration → **HomeKit Bed**.
3. Choose the Adjustable Bed device and a port, check the controls and submit.
4. Open the notification **Pair HomeKit Bed** and scan the QR code in the Home app.
5. If you also use the HomeKit Bridge, exclude the bed's own entities there to avoid
   duplicate tiles.

## Documentation

| Guide | Contents |
|---|---|
| [Configuration](docs/CONFIGURATION.md) | The setup and options forms, naming, display, layout, pairing |
| [Detection](docs/DETECTION.md) | How bed entities map to HomeKit controls, defaults per group |
| [Supported beds](docs/SUPPORTED_BEDS.md) | All bed types of the checked Adjustable Bed release |
| [Home app behaviour](docs/HOME_APP.md) | Captions, order, colour button, open/closed, renames |
| [Architecture](docs/ARCHITECTURE.md) | Why an own HAP accessory, modules, data model |
| [Development](docs/DEVELOPMENT.md) | Environment, tests, translations, CI, releases |
| [Changelog](CHANGELOG.md) | Version history |

## Status

Developed and used with a Jensen JMC400 (single beds and a combined bed). Other bed types are
covered by modelled tests per bed family; reports from owners of other beds are welcome.
