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

Top to bottom:

| Block | Contents |
|---|---|
| Adjustable sections | One slider per section (back, legs, tilt, lumbar, ...) |
| Quick actions | Flat, Zero G, Memory positions, Stop, Foundation Preset, ... |
| Massage | Strength sliders and on/off buttons |
| Lighting | Bed lights, plus free slots for any Home Assistant light |
| Climate, Firmness, Settings | Only when the bed has them |
| Add controls | Everything the bed offers that is not in HomeKit |
| Naming | The name of every control in the Home app, and *Enforce names* |
| Display in HomeKit | *Inverted sliders* |
| Layout | *First control (top left)* and the expected tile layout |

Every field holds the matched entity. The entity picker shows the device under each entity.

- **Remove** a control: clear its field and submit. The form returns with the control moved to
  *Add controls*.
- **Add** a control: tick it in *Add controls* and submit. It appears in its group.
- **Another entity**: pick it in the field (for example a script).
- **Save**: submit without moving anything; a preview of the expected layout follows.

Only exceptions to the detection defaults are stored, so controls that a later Adjustable Bed
version detects follow the defaults automatically.

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
