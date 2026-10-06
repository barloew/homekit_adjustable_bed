# Architecture

## Why an own HomeKit accessory

The HomeKit Bridge of Home Assistant creates one accessory per entity and does not support
`number` entities, which Adjustable Bed uses for real positions and massage levels. One accessory
with many controls therefore needs its own HAP accessory. HomeKit Bed runs HAP-python (the
library the HomeKit Bridge uses) inside Home Assistant's event loop and zeroconf instance, one
server per bed, with pairing state under `.storage`.

## Modules

| Module | Role |
|---|---|
| `__init__.py` | Setup, live rename, migrations, actions, QR view |
| `server.py` | HAP driver lifecycle, pairing, notifications, port handling |
| `accessory.py` | Bridge and bed accessory; channels per control type; motion queue |
| `sources.py` | Reading and writing HA entities as percentages, presses and toggles; cover seek |
| `detection.py` | Bed entities to HomeKit controls (rules, defaults, redundancy) |
| `controls.py` | Options model and the effective list of controls |
| `config_flow.py` | Setup and options forms (shared form for detected beds) |
| `iids.py` | Stable HomeKit instance IDs |
| `layout.py` | Expected tile layout and HomeKit-safe names |
| `labels.py` | Default captions and texts from the translation files |
| `devices.py` | Device registry helpers, including child devices |

## Options model

For a detected bed only exceptions are stored:

| Key | Meaning |
|---|---|
| `hidden_controls` | Detected ids shown by default that the user removed |
| `added_controls` | Detected ids hidden by default that the user added |
| `entity_overrides` | Another entity for a control, or an extra catalog control (a lamp) |
| `label_<id>`, `color_<id>`, `inverted`, `primary_control`, `enforce_captions` | Naming and display |

Options of earlier versions are converted on read (`controls.normalize_options`), so HomeKit keeps
what it had.

## Motion

Sliders of bed sections go through one queue: Adjustable Bed's go-to for some controllers moves
both sections and a new command interrupts the running one, so moves run one after another.
HomeKit drags are debounced (0.6 s). Flat, Memory and Stop clear the queue.
