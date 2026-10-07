# Configuration

## Adding a bed

1. **Name, bed and port.** The name becomes the accessory name in the Home app. The port must
   differ from every HomeKit Bridge port (21063, 21064, ...).
2. **Controls.** For a bed whose controls are detected, the form below is shown immediately and
   submitting it creates the accessory. For a device without detectable controls, a manual form
   with the fixed catalog of controls is shown instead.
3. **Pairing.** A persistent notification shows the QR code and setup code.

## Options

*Configure* opens a menu:

- **Publish bed controls as a HomeKit accessory**: the controls form.
- **Pair with HomeKit (show QR code)**: shows the QR code while the bed is not paired; when it is
  paired, shows the number of controllers and offers **Reset pairing** (needed after removing
  the bed in the Home app while it was unreachable). A reset gives the bed a new HomeKit identity
  and setup code.

## The controls form

All blocks start collapsed. `icons.json` defines an MDI icon per block (mdi:bed, mdi:bed-clock,
mdi:gesture-tap-button, mdi:waves, mdi:hvac, mdi:diamond-stone, mdi:lightbulb, mdi:cog-outline,
mdi:link-plus, mdi:rename, mdi:gesture-swipe-up, mdi:view-grid-plus-outline). The Home Assistant
frontend does not show icons for config-flow sections yet, so each name also starts with an emoji
and three non-breaking spaces.

| Block | Contents |
|---|---|
| 🛏️ Adjustable sections | Beds with positions: two switches on top (timed buttons, exact sliders), then one slider per section |
| ⏱️ Timed adjustments | Seconds per section (0 = off). Always for beds without positions; else when switched on |
| 👆 Quick actions | Flat, Zero G, Memory positions, Stop, Foundation Preset, ... |
| 🌊 Massage | Strength sliders and on/off buttons |
| 💡 Lighting | Bed lights, plus free slots for any Home Assistant light |
| 🌡️ Climate, 💎 Firmness, ⚙️ Settings | Only when the bed has them |
| 🔗 Add controls | Everything the bed offers that is not in HomeKit |
| 🏷️ Labels in HomeKit | The name of every control in the Home app, and *Enforce names* |
| ↕️ Display in HomeKit | *Inverted sliders* (beds with positions only) |
| 🔲 Layout in HomeKit | *First control (top left)* and the expected tile layout |

Switching *timed buttons* or *exact sliders* and pressing Submit updates the form right away.
With exact sliders off, the bed sections are only operated with the timed buttons.

Every field holds the matched entity. The entity picker shows the device under each entity.

- **Remove** a control: clear its field and submit. The form returns with the control moved to
  *Add controls*.
- **Add** a control: tick it in *Add controls* and submit. It appears in its group.
- **Another entity**: pick it in the field (for example a script).
- **Save**: submit without moving anything; a preview of the expected layout follows.

Only exceptions to the detection defaults are stored, so controls that a later Adjustable Bed
version detects follow the defaults automatically.

### Timed moves

For every section, enter a number of seconds (0.5 steps, at most 30). A section with a duration
gets two push buttons in HomeKit, *<section> up* and *<section> down*, which call
`adjustable_bed.timed_move` for that time on the right motor and side. They suit beds without
position feedback, where a slider can only raise, lower or stop. A timed move clears the motion
queue first; *Stop* interrupts it. The buttons take their names from the section.

### Lighting slots

A single bed has two free slots: *Bed lighting* and *Under-bed lighting*. A combined bed has four:
left and right of each. Every light has **Colour in HomeKit**: on gives a colour wheel and colour
temperature (when the light supports them); the Home app then shows a colour button instead of
the caption under that light in the grouped tile. Off keeps the caption.

### Naming

Names may contain letters, digits, spaces and apostrophes; other characters become a space.
With **Enforce names** on, names the Home app assigns itself (such as "Blinds 1") are replaced by
yours within two seconds. Turn it off to rename controls in the Home app.

### Inverted sliders

For blinds sliders, swaps the percentage and open/closed: a flat bed or massage off shows as
100 % / Open, and moving the slider down raises the section. Best for operating with the slider;
Siri and HomeKit scenes use the inverted percentage too.

### Layout

The Home app shows the first control top left and the others alphabetically by name, in rows of
two. See [Home app behaviour](HOME_APP.md#order).

## Combined beds

Choose the combined parent (for example *Our Bed*) to get its own controls, which move both
beds. Create a separate HomeKit bed per side if you want those as well. When a parent has no own
controls and exactly one side, that side's controls are used; with several sides and no own
controls nothing is guessed and the manual form is shown.

## Renaming the bed

Rename the integration entry in Home Assistant. The new name is pushed to the Home app without
restarting the accessory; the invisible bridge keeps the name it was paired with.

## Actions

| Action | Effect |
|---|---|
| `homekit_bed.push_captions` | Sends all names to the Home app again |
| `homekit_bed.reset_pairing` | Forgets all pairings and shows a new setup code |
