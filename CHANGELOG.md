# Changelog

## 4.11.2
- New brand icon: side view of a bed with a headboard, a box spring with a topper and the back
  section raised.

## 4.11.1
- Brand images (icon and dark icon, 1x and 2x) in `brand/`, shown by Home Assistant 2026.3+ and
  required by HACS.
- Requirements `PyQRCode` and `base36` as minimum versions: hassfest of Home Assistant 2026.10
  rejects pins of packages Home Assistant itself depends on.
- MIT license; README icon; HACS checklist in the development docs.

## 4.11.0
- `tools/sync_adjustable_bed.py`: fetches the latest Adjustable Bed release, reports new bed
  types, controls and `timed_move` motors, and updates names, timed motors, the test fixture and
  the documentation; a weekly workflow opens a pull request with the report.
- Vendor controls without a rule are grouped by the words in their key (massage, lighting,
  firmness, climate, quick actions, adjustable sections, settings) instead of all under
  Settings; still off by default.
- Docs: [Supported beds](docs/SUPPORTED_BEDS.md), generated from the checked release.
- Synced with Adjustable Bed v4.2.3.
  - New bed types: Adjustable bed (Lumbar) app, AdjustableM5X4 app (explicit profile),
    AdjustableM5X5 app (CB25 / F23 / kneading), Best Mattress app (Richmat), Blvd Home app
    (Richmat), Customatic Z-Series app, FSM Relax app (explicit chair/bed profile), FurniMove / OKIN
    Smart Remote (choose handset ID), HARMONY app (Richmat), Idealbed app (Richmat), Jordan's
    Serenity app, Jordan's Tranquil app, Limoss Remote app (bed / chair), Logicdata Sleep Smart air
    mattress pump, Motion Bed app, Revive Control app (Richmat), SIMMONS app, Tempur Sleeptracker-AI
    (ProSmart / ActiveBreeze processor), V-MAT Basic app, Vibradorm apps: VMAT, Caresse Diamant or
    Werkmeister.
  - New controls named and grouped: 255 (adjustable sections 70, settings 60, massage 54, lighting
    42, quick actions 22, firmness 4, climate 3).

## 4.10.0
- Massage: switches for massage buttons and massage sliders (only for kinds the bed has); each
  shows or hides its controls in the form and in HomeKit.
- Display in HomeKit only lists sliders that are on, and is hidden when no slider is on.
- Switched-off kinds are not offered under Add controls.
- Dutch: "Getimede verstellingen".

## 4.9.1
- `icons.json` with MDI icons for every form section and both actions. Home Assistant does not
  show icons for config-flow sections yet, so the section names keep a matching emoji followed by
  three non-breaking spaces.

## 4.9.0
- Form: all blocks collapsed, with an icon in each name; renamed to Adjustable sections, Timed
  adjustments, Quick actions, Massage, Lighting, Add controls, Labels in HomeKit, Display in
  HomeKit and Layout in HomeKit.
- Beds that report positions: switches for timed buttons and for exact sliders at the top of
  Adjustable sections; each shows or hides its fields. Beds without positions: timed
  adjustments always, no display block.
- Options menu: "Register controls in HomeKit".

## 4.8.0
- Timed moves: set seconds per bed section in the form; each section with a duration gets
  *up* and *down* push buttons in HomeKit that call `adjustable_bed.timed_move` (side-aware,
  at most 30 s). Stop interrupts a running move.

## 4.7.0
- Python 3.14 and Home Assistant 2026.9.0 minimum; tooling, CI and documentation aligned with
  Adjustable Bed (uv, ruff, pyright, pytest, HACS, hassfest).
- Controls are recognised by their `translation_key`; the `unique_id` is a fallback.
- Tests run against real child devices of Home Assistant 2026.9.
- One version in `manifest.json`, `pyproject.toml` and `const.py`.

## 4.6
- Detected beds use the same grouped form at setup as in the options.
- Combined beds: only the parent's own controls; light slots left and right.

## 4.5
- Combined beds recognised (`pair_` unique ids); new beds start from the detection defaults.

## 4.4
- Covers without position: seek with stop when the bed reports its position, else 70/30 zones.
- Combined covers and per-side presets of split beds off by default; bed family test matrix.

## 4.3
- New form order and texts; Stop under quick actions; larger subtitle.

## 4.2
- One grouped list of HomeKit controls with an *Add controls* block; only exceptions stored.

## 4.1
- Sleep Number cooling/heating and footwarming as a fan with Cool/Heat switches.

## 4.0
- Registration from feature detection for every bed type Adjustable Bed supports; selects as
  switch sets.

## 3.x
- Pairing menu with QR code and reset; inverted sliders; colour per light; stable instance IDs;
  live rename; child device support; detected-only forms; translations in JSON (English, Dutch);
  layout preview; captions pushed to the Home app.

## 2.x
- Captions via `ConfiguredName` behind an invisible bridge; Memory 1-4; massage wave slider.

## 1.0
- One HomeKit accessory with four sliders and two switches for a Jensen JMC400.
