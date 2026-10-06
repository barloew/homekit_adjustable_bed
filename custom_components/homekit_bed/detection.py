"""Feature detection: turn a bed's entities into HomeKit controls.

ha-adjustable-bed already detects what a bed can do and only creates
entities for those capabilities. This module maps every such entity to a
HomeKit control type, a logical group and a default "expose in HomeKit"
choice, following the mapping worked out for all supported beds:

  cover      blinds slider (motor sections with real %, massage, firmness)
  light      lamp with brightness (and colour when the light supports it)
  fan        fan with speed
  momentary  switch that runs an action and falls back to off
  switch     switch with real on/off state
  select     one switch per option, only one on at a time
  climate_fan  bed climate (no temperature) as a fan: on/off + level,
             plus cool/heat switches

Rules work on the entity key (unique_id = f"{ble_address}_{key}", with an
optional _left/_right/_both side suffix), so vendor-specific keys without a
rule still get a sensible type from their domain, hidden by default.

Defaults follow a few principles:
  * one slider per section: a position number (real %) wins over the
    section cover; motor up/down buttons stay hidden when a slider exists;
  * recall presets, stop and massage on/off are shown; saving, resetting,
    connecting and other maintenance actions are never shown by default,
    because HomeKit has no confirmation step;
  * a light or light-level slider makes the toggle-light button redundant.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import ADJUSTABLE_BED_DOMAIN, CONTROLS
from .devices import child_device_ids

# HomeKit control types
HK_COVER = "cover"
HK_LIGHT = "light"
HK_FAN = "fan"
HK_MOMENTARY = "momentary"
HK_SWITCH = "switch"
HK_SELECT = "select"
HK_CLIMATE = "climate_fan"  # bed climate as fan (+ cool/heat switches)

# Logical groups, in display order
G_POSITIONS = "positions"
G_PRESETS = "presets"
G_MASSAGE = "massage"
G_LIGHTING = "lighting"
G_CLIMATE = "climate"
G_FIRMNESS = "firmness"
G_SETTINGS = "settings"
DETECTION_GROUPS = (
    G_POSITIONS,
    G_PRESETS,
    G_MASSAGE,
    G_LIGHTING,
    G_CLIMATE,
    G_FIRMNESS,
    G_SETTINGS,
)

_SIDE_RE = re.compile(r"^(?P<base>.+?)_(?P<side>left|right|both)$")

# Section axes that can have a cover and/or a position number.
_AXES = (
    "back",
    "legs",
    "head",
    "feet",
    "lumbar",
    "pillow",
    "tilt",
    "neck",
    "hip",
    "waist",
    "bed_height",
    "stair",
    "tv_lift",
    "head_end_tilt",
    "foot_end_tilt",
    "auxiliary",
    "auxiliary_1",
    "auxiliary_2",
)
# Covers whose position lives in a differently named number.
_COVER_TO_NUMBER = {
    "keeson_back": "back",
    "keeson_head": "head",
    "keeson_legs": "legs",
}

# Never shown by default (maintenance, irreversible or confusing in HomeKit).
_NEVER = re.compile(
    r"^(factory_reset|reset_defaults|connect|disconnect|wake_controller|"
    r"control_mode_.+|program_memory_\d+|save_.+|child_lock_toggle|"
    r"product_action|remote_action|auxiliary_action)$"
)


@dataclass(frozen=True, slots=True)
class Rule:
    """How a family of entity keys maps to HomeKit."""

    pattern: str
    domain: str
    hk_type: str
    group: str
    exposed: bool = True
    motor: bool = False
    interrupts_motion: bool = False
    order: int = 50
    regex: re.Pattern = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "regex", re.compile(self.pattern))


RULES: tuple[Rule, ...] = (
    # --- bed sections -------------------------------------------------
    Rule(
        r"^(back|legs|head|feet|lumbar|auxiliary_\d)_position$",
        "number",
        HK_COVER,
        G_POSITIONS,
        motor=True,
        order=10,
    ),
    Rule(r"^.+_angle$", "number", HK_COVER, G_POSITIONS, motor=True, order=12),
    Rule(r"^.+$", "cover", HK_COVER, G_POSITIONS, motor=True, order=14),
    Rule(
        r"^(back_legs|back|legs|head|feet|lumbar)_(up|down)$",
        "button",
        HK_MOMENTARY,
        G_POSITIONS,
        exposed=False,
        interrupts_motion=True,
        order=30,
    ),
    Rule(r"^stop$", "button", HK_MOMENTARY, G_PRESETS, interrupts_motion=True, order=50),
    # --- presets --------------------------------------------------------
    Rule(r"^preset_flat$", "button", HK_MOMENTARY, G_PRESETS, interrupts_motion=True, order=10),
    Rule(
        r"^preset_memory_\d+$", "button", HK_MOMENTARY, G_PRESETS, interrupts_motion=True, order=20
    ),
    Rule(r"^preset_.+$", "button", HK_MOMENTARY, G_PRESETS, interrupts_motion=True, order=15),
    Rule(r"^program_memory_\d+$", "button", HK_MOMENTARY, G_PRESETS, exposed=False, order=25),
    Rule(
        r"^sync_positions$",
        "button",
        HK_MOMENTARY,
        G_PRESETS,
        exposed=False,
        interrupts_motion=True,
        order=40,
    ),
    Rule(r"^foundation_preset$", "select", HK_SELECT, G_PRESETS, order=30),
    # --- massage ----------------------------------------------------------
    Rule(r"^massage_(head|foot|wave|right)?_?intensity$", "number", HK_COVER, G_MASSAGE, order=10),
    Rule(r"^massage_(all|head|foot)_toggle$", "button", HK_MOMENTARY, G_MASSAGE, order=20),
    Rule(r"^massage_all_off$", "button", HK_MOMENTARY, G_MASSAGE, order=25),
    Rule(r"^massage_timer$", "select", HK_SELECT, G_MASSAGE, exposed=False, order=40),
    Rule(
        r"^(massage_.+|therapy_mode_\d+)$",
        "button",
        HK_MOMENTARY,
        G_MASSAGE,
        exposed=False,
        order=30,
    ),
    # --- lighting ---------------------------------------------------------
    Rule(r"^under_bed_lights$", "light", HK_LIGHT, G_LIGHTING, order=10),
    Rule(r"^light_level$", "number", HK_LIGHT, G_LIGHTING, order=12),
    Rule(r"^under_bed_lights$", "switch", HK_SWITCH, G_LIGHTING, order=14),
    Rule(r"^toggle_light$", "button", HK_MOMENTARY, G_LIGHTING, order=16),
    Rule(r"^automatic_light$", "switch", HK_SWITCH, G_LIGHTING, exposed=False, order=20),
    Rule(r"^light_timer$", "select", HK_SELECT, G_LIGHTING, exposed=False, order=30),
    Rule(
        r"^(light_cycle|toggle_sound|toggle_light_and_sound|solace_music_.+)$",
        "button",
        HK_MOMENTARY,
        G_LIGHTING,
        exposed=False,
        order=40,
    ),
    # --- climate ------------------------------------------------------------
    Rule(r"^fan_level$", "number", HK_FAN, G_CLIMATE, order=10),
    Rule(
        r"^(sleep_number_thermal_climate|footwarming_climate)$",
        "climate",
        HK_CLIMATE,
        G_CLIMATE,
        order=5,
    ),
    Rule(r"^(footwarming|thermal)_timer$", "select", HK_SELECT, G_CLIMATE, exposed=False, order=30),
    # --- firmness -----------------------------------------------------------
    Rule(r"^sleep_number_setting$", "number", HK_COVER, G_FIRMNESS, order=10),
    # --- settings -----------------------------------------------------------
    Rule(
        r"^(synchro_mode|linak_automatic_drive)$",
        "switch",
        HK_SWITCH,
        G_SETTINGS,
        exposed=False,
        order=10,
    ),
)

# Fallbacks per domain for keys without a rule (vendor-specific, runtime
# catalogs): available, but hidden by default.
_FALLBACK = {
    "number": (HK_COVER, G_SETTINGS),
    "button": (HK_MOMENTARY, G_SETTINGS),
    "switch": (HK_SWITCH, G_SETTINGS),
    "light": (HK_LIGHT, G_LIGHTING),
    "select": (HK_SELECT, G_SETTINGS),
    "climate": (HK_CLIMATE, G_CLIMATE),
}
# Read-only entities are not controls.
_IGNORED_DOMAINS = ("sensor", "binary_sensor")


@dataclass(slots=True)
class DetectedControl:
    """One bed entity as a possible HomeKit control."""

    entity_id: str
    key: str  # entity key including side suffix
    base: str  # key without side suffix
    side: str | None
    domain: str
    hk_type: str
    group: str
    exposed: bool
    motor: bool = False
    interrupts_motion: bool = False
    order: int = 50
    name: str | None = None  # entity name without the device name
    catalog_key: str | None = None  # legacy control id (stable IIDs/captions)
    lost_alias: bool = False  # another entity took the legacy id

    @property
    def control_id(self) -> str:
        """Id used for options, captions and the HomeKit service.

        A cover whose position number took the legacy id (e.g. "back") gets
        "cover_back", so ids stay unique.
        """
        if self.catalog_key:
            return self.catalog_key
        if self.lost_alias and self.key in _CATALOG_IDS:
            return f"{self.domain}_{self.key}"
        return self.key


def _split_side(key: str) -> tuple[str, str | None]:
    if match := _SIDE_RE.match(key):
        return match["base"], match["side"]
    return key, None


_UNIQUE_ID_RE = re.compile(r"^(?:pair_[0-9a-fA-F]+|[^_]+)_(?P<key>.+)$")


def entity_key(entry: er.RegistryEntry) -> str | None:
    """The ha-adjustable-bed entity key of a registry entry.

    Prefer the translation_key: ha-adjustable-bed gives every entity a stable
    one (its dashboard card relies on it too), side suffix included. The
    unique_id is only a fallback for entities without one.
    """
    return entry.translation_key or _entity_key(entry.unique_id)


def _entity_key(unique_id: str) -> str | None:
    """Entity key from a ha-adjustable-bed unique_id.

    Single beds use "<ble_address>_<key>" (the address has no underscore);
    a combined bed's own controls use "pair_<hex>_<key>".
    """
    match = _UNIQUE_ID_RE.match(unique_id)
    return match["key"] if match else None


def classify(domain: str, key: str) -> DetectedControl | None:
    """Classify one entity key (without registry data)."""
    if domain in _IGNORED_DOMAINS:
        return None
    base, side = _split_side(key)
    for rule in RULES:
        if rule.domain == domain and rule.regex.match(base):
            exposed = rule.exposed and not _NEVER.match(base)
            return DetectedControl(
                entity_id="",
                key=key,
                base=base,
                side=side,
                domain=domain,
                hk_type=rule.hk_type,
                group=rule.group,
                exposed=exposed,
                motor=rule.motor,
                interrupts_motion=rule.interrupts_motion,
                order=rule.order,
            )
    if domain not in _FALLBACK:
        return None
    hk_type, group = _FALLBACK[domain]
    return DetectedControl(
        entity_id="",
        key=key,
        base=base,
        side=side,
        domain=domain,
        hk_type=hk_type,
        group=group,
        exposed=False,
    )


# Legacy catalog ids, so controls keep their HomeKit identity and captions.
_CATALOG_ALIAS: dict[tuple[str, str], str] = {}
for _spec in CONTROLS:
    for _pair in _spec.detect:
        _CATALOG_ALIAS.setdefault(_pair, _spec.key)  # first claim wins


# Covers that move several sections or both sides at once. Shown only when
# the bed has no separate cover/slider for any of the parts.
_COMBINED_COVERS = {
    "both": ("back", "legs"),  # "Back and legs"
    "back_legs": ("back", "legs"),
    "head_feet": ("head", "feet"),
    "both_backs": ("back", "right_back"),  # both sides of a split bed
    "both_legs": ("legs", "right_legs"),
}


_CATALOG_IDS = {spec.key for spec in CONTROLS}


def _apply_redundancy(controls: list[DetectedControl]) -> None:
    """Hide controls that duplicate a better one (per side)."""
    present = {(c.domain, c.base, c.side) for c in controls}
    for c in controls:
        if c.domain == "cover" and c.base in _COMBINED_COVERS and c.exposed:
            parts = _COMBINED_COVERS[c.base]
            if any(
                ("cover", part, side) in present or ("number", f"{part}_position", side) in present
                for part in parts
                for side in (c.side, "left", "right", None)
            ):
                c.exposed = False
    # Split beds: a preset or stop for both sides makes the per-side ones
    # redundant by default (they stay available to add).
    for c in controls:
        if (
            c.exposed
            and c.group == G_PRESETS
            and c.side in ("left", "right")
            and (c.domain, c.base, "both") in present
        ):
            c.exposed = False
    for c in controls:
        if not c.exposed:
            continue
        if c.domain == "cover":
            axis = _COVER_TO_NUMBER.get(c.base, c.base)
            if ("number", f"{axis}_position", c.side) in present:
                c.exposed = False  # the position number gives a real %
        elif c.domain == "switch" and c.base == "under_bed_lights":
            if ("light", "under_bed_lights", c.side) in present:
                c.exposed = False
        elif c.domain == "button" and c.base == "toggle_light":
            if ("light", "under_bed_lights", c.side) in present or (
                "number",
                "light_level",
                c.side,
            ) in present:
                c.exposed = False
    # Motor up/down buttons only when the axis has no slider at all.
    for c in controls:
        match = re.match(r"^(back_legs|back|legs|head|feet|lumbar)_(up|down)$", c.base)
        if c.domain == "button" and match:
            axis = match[1]
            has_slider = ("number", f"{axis}_position", c.side) in present or (
                "cover",
                axis,
                c.side,
            ) in present
            c.exposed = not has_slider and axis != "back_legs"


def _sort_key(c: DetectedControl) -> tuple:
    return (
        DETECTION_GROUPS.index(c.group),
        c.order,
        {None: 0, "both": 1, "left": 2, "right": 3}[c.side],
        c.base,
    )


def _bed_entries(hass: HomeAssistant, registry: er.EntityRegistry, device_id: str) -> list:
    """Entities of the chosen device; its children only if it has none.

    A combined bed (e.g. "Ons Bed") is a parent device with a child per side
    (e.g. "Barloew's bed", "Snork Maiden's bed"). The parent's own controls move both
    sides; each side has its own HomeKit bed if wanted. Mixing in the sides'
    controls would give duplicate names such as two "Memory 1". A parent
    without own entities (all controls on its child) uses the child's.
    """

    def own(dev_id: str) -> list:
        return [
            e
            for e in er.async_entries_for_device(registry, dev_id)
            if e.platform == ADJUSTABLE_BED_DOMAIN and not e.disabled
        ]

    entries = own(device_id)
    if entries:
        return entries
    children = child_device_ids(hass, device_id)
    if len(children) == 1:
        return own(children[0])
    # Several sides and no own controls: do not guess which side to use.
    return []


def detect_controls(hass: HomeAssistant, device_id: str | None) -> list[DetectedControl]:
    """All controls the bed offers, ordered by group, with default exposure."""
    if not device_id:
        return []
    registry = er.async_get(hass)
    controls: list[DetectedControl] = []
    for entry in _bed_entries(hass, registry, device_id):
        key = entity_key(entry)
        if key is None:
            continue
        control = classify(entry.domain, key)
        if control is None:
            continue
        control.entity_id = entry.entity_id
        control.name = entry.name or entry.original_name
        if control.side is None:
            control.catalog_key = _CATALOG_ALIAS.get((entry.domain, key))
        controls.append(control)
    _apply_redundancy(controls)
    # Two entities may claim the same legacy id (e.g. cover "back" and number
    # "back_position"); only the exposed one keeps it.
    seen: set[str] = set()
    for c in sorted(controls, key=lambda c: not c.exposed):
        if c.catalog_key and c.catalog_key in seen:
            c.catalog_key = None
            c.lost_alias = True
        elif c.catalog_key:
            seen.add(c.catalog_key)
    return sorted(controls, key=_sort_key)
