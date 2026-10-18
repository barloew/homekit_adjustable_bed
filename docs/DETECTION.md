# Detection

Adjustable Bed only creates entities for what a bed can do. HomeKit Bed reads those entities from
the entity registry, recognises each by its `translation_key` (the `unique_id` key as fallback,
for `<address>_<key>` and combined beds' `pair_<hex>_<key>`) and maps it with the rules in
`custom_components/homekit_bed/detection.py`.

## Mapping

| Group | HomeKit type | On by default |
|---|---|---|
| Adjustable sections | Blinds slider: position number when available, else the cover | One slider per section and side |
| Quick actions | Push button; Foundation Preset as a set of switches (one on) | Flat, presets, Memory, Stop |
| Massage | Blinds slider for strength (0-10 in 10 % steps); push buttons | Strength sliders, on/off buttons |
| Lighting | Lamp (colour if supported); switch; push button | Under-bed light or light level |
| Climate | Fan; Sleep Number cooling/heating and footwarming as a fan with *Cool*/*Heat* switches | Fan level, climate |
| Firmness | Blinds slider (Sleep Number) | Yes |
| Settings | Switches and buttons | No |

Off by default:

- saving memories, resets, connect/disconnect, factory reset and other maintenance actions
  (HomeKit asks for no confirmation);
- motor up/down buttons when the section has a slider; the cover when a position number exists;
- covers moving several sections or both sides (Back + Legs, Both backs, ...) when the separate
  sections exist;
- on split beds, per-side presets and stop when a "both" variant exists;
- the light button when a lamp or light level exists;
- vendor and runtime entities without a rule.

Entities without a rule are placed in a group by the words in their key (for example
`vmatbasic_massage_back` under Massage, `vibradorm_app_mood_toggle` under Lighting; `save`,
`reset`, `refresh` and similar under Settings), else under Settings by their domain. They are
available under *Add controls*.

Read-only sensors are never controls.

## Sliders and positions

| Source | Behaviour |
|---|---|
| Position number | Moves to the exact position (motion queue, one section at a time) |
| Cover that reports its position | Moves in the right direction and stops at the target; repeats while the section progresses |
| Cover without position | Like the HomeKit Bridge: above 70 % raise, below 30 % lower, in between stop |

## Climate

Sleep Number climate has no temperature: on/off is *Active*, the level preset is the fan speed in
equal steps (low/medium/high = 33/67/100 %; with boost while cooling 25/50/75/100 %).

## Identity

Every control has a stable id (the fixed catalog id such as `back` or `memory_1` where one
exists, else the entity key). Ids name options, captions and the HomeKit services, and the
HomeKit instance IDs are stored per id, so adding or removing controls never changes the others.

## Coverage

[Supported beds](SUPPORTED_BEDS.md) lists every bed type of the Adjustable Bed release this
version is checked against, how many of its entities are recognised by a rule, by keyword or by
domain only, and the controls without a rule. `tests/test_adjustable_bed_sync.py` checks that
every entity of that release has a HomeKit type and a name. `tests/test_bed_families.py` models
the entity sets of Okin/Keeson, Linak, Reverie/Octo, Jiecang split, combined-motor and Sleep
Number split beds and checks the defaults and unique ids. `tools/sync_adjustable_bed.py` keeps
all of this up to date (see [Development](DEVELOPMENT.md)).
