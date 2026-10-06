# Home app behaviour

Observed with iOS 17/18 and the Home app; Apple does not document most of it.

## One tile

The bed is accessory #2 behind an invisible HAP bridge. The first accessory on a HAP server takes
the server's name and loses its service names, so the bed is never the first one.
*Show as separate tiles* in the Home app splits the tile if you want that.

## Captions

Every control has `Name` and the writable, evented `ConfiguredName`. The Home app copies names
when pairing and may assign its own defaults ("Blinds 1"); with *Enforce names* the integration
pushes its names back. Captions are only shown when an accessory has several services of the
same type. Names are pushed again 10 s and 60 s after start and pairing.

## Order

The Home app shows the primary service first and all others alphabetically by name, mixed across
types, in rows of two. HAP has no order characteristic for these services (only TV inputs have
one); creation order is ignored. Choose the first control and the names to get the layout you
want; the form shows the expected grid.

## Colour lights

Under a colour light the grouped tile shows a colour button where other controls show their
caption. Turn off *Colour in HomeKit* for that light to keep the caption.

## Blinds sliders

A blinds slider shows a percentage and Open/Closed. The grouped tile draws an open blind as an
empty slider, while the list and the summary count an open blind as "on". *Inverted sliders*
therefore make a flat bed look off in the grouped tile and "Open" in the list; no blinds setting
looks off in both.

## Pairing

Removing the bed in the Home app while it is reachable unpairs it and a new pairing notification
appears. Removed while unreachable, the bed still believes it is paired: use *Reset pairing*.

## Renaming

Renaming the integration entry pushes the accessory's `ConfiguredName` without a restart.
A restart drops all HomeKit connections briefly, which the Home app can show as "not responding".
