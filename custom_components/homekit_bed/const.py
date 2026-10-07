"""Constants for the HomeKit Bed Aggregator integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

DOMAIN: Final = "homekit_bed"
# Keep equal to manifest.json and pyproject.toml (tests/test_version.py).
VERSION: Final = "4.9.0"

# Config entry data
CONF_BED_DEVICE: Final = "bed_device"
CONF_PORT: Final = "port"

# --------------------------------------------------------------------------
# Control catalog. Every control is optional; the key is also the option key
# holding its source entity, and LABEL_PREFIX + key holds its caption.
# Keys of v2.x (back, legs, *_massage, flat, memory_1-4) are unchanged.
# --------------------------------------------------------------------------
KIND_COVER: Final = "cover"  # WindowCovering slider
KIND_LIGHT: Final = "light"  # Lightbulb: on/off + brightness slider
KIND_FAN: Final = "fan"  # Fanv2: on/off + speed slider
KIND_SWITCH: Final = "switch"  # Switch: push button or real on/off

GROUP_POSITIONS: Final = "positions"
GROUP_COMFORT: Final = "comfort"
GROUP_SWITCHES: Final = "switches"
GROUPS: Final = (GROUP_POSITIONS, GROUP_COMFORT, GROUP_SWITCHES)

# ha-adjustable-bed unique_id = f"{ble_address}_{entity_key}" (paired beds add
# _left/_right). Candidates are tried in order; the first existing one wins.
NUMBER, COVER, BUTTON, LIGHT, SWITCH = "number", "cover", "button", "light", "switch"


@dataclass(frozen=True, slots=True)
class ControlSpec:
    """One possible HomeKit control of the bed."""

    key: str
    kind: str
    group: str
    # English fallback caption; real defaults come from the translation
    # files (selector.control.options.<key>), so every language is JSON-only.
    fallback: str
    detect: tuple[tuple[str, str], ...] = ()
    # Moves a motor: serialised in the motion queue, shows opening/closing.
    motor: bool = False
    # Pressing it moves the bed itself: drop queued slider moves first.
    interrupts_motion: bool = False


CONTROLS: Final[tuple[ControlSpec, ...]] = (
    # Sliders - positions (motors)
    ControlSpec(
        "back",
        KIND_COVER,
        GROUP_POSITIONS,
        "Head section",
        ((NUMBER, "back_position"), (NUMBER, "head_position"), (COVER, "back"), (COVER, "head")),
        motor=True,
    ),
    ControlSpec(
        "legs",
        KIND_COVER,
        GROUP_POSITIONS,
        "Foot section",
        ((NUMBER, "legs_position"), (NUMBER, "feet_position"), (COVER, "legs"), (COVER, "feet")),
        motor=True,
    ),
    ControlSpec(
        "tilt",
        KIND_COVER,
        GROUP_POSITIONS,
        "Tilt",
        (
            (NUMBER, "tilt_position"),
            (NUMBER, "pillow_position"),
            (COVER, "tilt"),
            (COVER, "pillow"),
        ),
        motor=True,
    ),
    ControlSpec(
        "lumbar",
        KIND_COVER,
        GROUP_POSITIONS,
        "Lumbar",
        ((NUMBER, "lumbar_position"), (COVER, "lumbar")),
        motor=True,
    ),
    # Sliders - comfort (levels)
    ControlSpec(
        "head_massage",
        KIND_COVER,
        GROUP_COMFORT,
        "Head massage",
        ((NUMBER, "massage_head_intensity"),),
    ),
    ControlSpec(
        "foot_massage",
        KIND_COVER,
        GROUP_COMFORT,
        "Foot massage",
        ((NUMBER, "massage_foot_intensity"),),
    ),
    ControlSpec(
        "wave_massage",
        KIND_COVER,
        GROUP_COMFORT,
        "Massage wave",
        ((NUMBER, "massage_wave_intensity"),),
    ),
    ControlSpec(
        "light_level", KIND_LIGHT, GROUP_COMFORT, "Bed lighting", ((NUMBER, "light_level"),)
    ),
    ControlSpec(
        "under_bed_light_level",
        KIND_LIGHT,
        GROUP_COMFORT,
        "Under-bed lighting",
        ((LIGHT, "under_bed_lights"),),
    ),
    # Free light slots per side, offered for combined beds.
    ControlSpec("light_level_left", KIND_LIGHT, GROUP_COMFORT, "Bed lighting left"),
    ControlSpec("light_level_right", KIND_LIGHT, GROUP_COMFORT, "Bed lighting right"),
    ControlSpec("under_bed_light_level_left", KIND_LIGHT, GROUP_COMFORT, "Under-bed lighting left"),
    ControlSpec(
        "under_bed_light_level_right", KIND_LIGHT, GROUP_COMFORT, "Under-bed lighting right"
    ),
    ControlSpec("fan_level", KIND_FAN, GROUP_COMFORT, "Fan", ((NUMBER, "fan_level"),)),
    # Switches
    ControlSpec(
        "stop", KIND_SWITCH, GROUP_SWITCHES, "Stop", ((BUTTON, "stop"),), interrupts_motion=True
    ),
    ControlSpec(
        "flat",
        KIND_SWITCH,
        GROUP_SWITCHES,
        "Flat",
        ((BUTTON, "preset_flat"),),
        interrupts_motion=True,
    ),
    # Jensen box type 4 has one device slot; other JMC400 boxes get slots that
    # ha-adjustable-bed stores itself (#632). Only existing ones are found.
    *(
        ControlSpec(
            f"memory_{i}",
            KIND_SWITCH,
            GROUP_SWITCHES,
            f"Memory {i}",
            ((BUTTON, f"preset_memory_{i}"),),
            interrupts_motion=True,
        )
        for i in range(1, 6)
    ),
    ControlSpec(
        "massage_toggle",
        KIND_SWITCH,
        GROUP_SWITCHES,
        "Massage button",
        ((BUTTON, "massage_all_toggle"),),
    ),
    ControlSpec(
        "massage_head_toggle",
        KIND_SWITCH,
        GROUP_SWITCHES,
        "Head massage button",
        ((BUTTON, "massage_head_toggle"),),
    ),
    ControlSpec(
        "massage_foot_toggle",
        KIND_SWITCH,
        GROUP_SWITCHES,
        "Foot massage button",
        ((BUTTON, "massage_foot_toggle"),),
    ),
    ControlSpec(
        "light_toggle", KIND_SWITCH, GROUP_SWITCHES, "Light button", ((BUTTON, "toggle_light"),)
    ),
    ControlSpec(
        "under_bed_light_toggle",
        KIND_SWITCH,
        GROUP_SWITCHES,
        "Under-bed lighting button",
        ((SWITCH, "under_bed_lights"), (LIGHT, "under_bed_lights")),
    ),
)
CONTROLS_BY_KEY: Final = {c.key: c for c in CONTROLS}
ALL_KEYS: Final = tuple(c.key for c in CONTROLS)
SLIDER_KEYS: Final = tuple(c.key for c in CONTROLS if c.kind != KIND_SWITCH)
ACTION_KEYS: Final = tuple(c.key for c in CONTROLS if c.kind == KIND_SWITCH)
MOTOR_KEYS: Final = tuple(c.key for c in CONTROLS if c.motor)
MEMORY_KEYS: Final = tuple(k for k in ALL_KEYS if k.startswith("memory_"))
# v1 had a single "memory" switch; migrated to memory_1.
LEGACY_CONF_MEMORY: Final = "memory"

# Kept for readability elsewhere.
CONF_BACK: Final = "back"
CONF_LEGS: Final = "legs"

# Per-control caption options, e.g. "label_back"
LABEL_PREFIX: Final = "label_"
# Translation key holding the default caption of every control.
CAPTION_TRANSLATION_KEY: Final = "control"

ADJUSTABLE_BED_DOMAIN: Final = "adjustable_bed"

# Shown in the forms even when the bed has no such entity: any HA light (for
# example a Hue lamp next to the bed or a strip under it) can be used here.
ALWAYS_OFFERED_KEYS: Final = ("light_level", "under_bed_light_level")
# Light slots for a combined bed (parent with a child per side), instead of
# the two single ones.
COMBINED_LIGHT_KEYS: Final = (
    "light_level_left",
    "light_level_right",
    "under_bed_light_level_left",
    "under_bed_light_level_right",
)
# 4.5/4.6 names -> current names.
RENAMED_KEYS: Final = {
    "light_level_2": "light_level_right",
    "under_bed_light_level_2": "under_bed_light_level_right",
}

# Per-light switch "Colour in HomeKit", e.g. "color_under_bed_light_level".
# The Home app shows a colour button instead of the caption under a colour
# light in the grouped bed tile; turning colour off brings the caption back.
COLOR_PREFIX: Final = "color_"
DEFAULT_COLOR: Final = True

# Automatic registration from feature detection (bool) and the chosen
# detected controls (list of control ids; absent = detection defaults).
CONF_AUTO: Final = "auto_register"  # legacy (<= 4.1), converted
CONF_AUTO_SELECTED: Final = "auto_controls"  # legacy (<= 4.1), converted
# Exception-based model (4.2+), see controls.normalize_options.
CONF_HIDDEN: Final = "hidden_controls"
CONF_ADDED: Final = "added_controls"
CONF_OVERRIDES: Final = "entity_overrides"

# Beds that report positions: show exact sliders and/or timed buttons.
CONF_SLIDERS: Final = "position_sliders"
CONF_TIMED_ON: Final = "timed_buttons"

# Timed moves (adjustable_bed.timed_move) per section: {control id: seconds}.
CONF_TIMED: Final = "timed_moves"
TIMED_MAX_SECONDS: Final = 30.0  # ha-adjustable-bed accepts 100-30000 ms
# Motors the timed_move action accepts.
TIMED_MOTORS: Final = (
    "back",
    "right_back",
    "legs",
    "head",
    "feet",
    "tilt",
    "lumbar",
    "bed_height",
    "stair",
    "tv_lift",
)

# Blinds sliders shown upside down in HomeKit (list of control keys).
CONF_INVERTED: Final = "inverted"

# Entity domains the user may pick per kind.
SOURCE_DOMAINS: Final = {
    KIND_COVER: ["number", "input_number", "cover"],
    KIND_LIGHT: ["number", "input_number", "light"],
    KIND_FAN: ["number", "input_number", "fan"],
    KIND_SWITCH: [
        "button",
        "input_button",
        "script",
        "scene",
        "switch",
        "input_boolean",
        "light",
        "fan",
    ],
}
# Sources with a real on/off state: the HomeKit switch mirrors and sets it
# instead of acting as a push button.
STATEFUL_DOMAINS: Final = ("switch", "input_boolean", "light", "fan")

DEFAULT_NAME: Final = "Bed"
DEFAULT_PORT: Final = 21070

# Timings (seconds)
# HomeKit can send a burst of TargetPosition writes while a slider is dragged;
# only the last one is forwarded after this quiet period.
DEBOUNCE_SECONDS: Final = 0.6
# A HomeKit switch used as a push button falls back to "off" after this delay.
MOMENTARY_RESET_SECONDS: Final = 1.0
# The Jensen controller aborts a move after 90 s; give it a little headroom.
MOVE_TIMEOUT_SECONDS: Final = 120.0
# After a move, wait for the last position report before syncing the target.
SETTLE_SECONDS: Final = 2.0
# Report "stopped" once current is this close to target (percentage points).
POSITION_TOLERANCE: Final = 3

QR_VIEW_URL: Final = "/api/homekit_bed/pairingqr"

# AID of the bed accessory behind the (invisible) HAP bridge.
BED_AID: Final = 2
SERVICE_RESET_PAIRING: Final = "reset_pairing"
SERVICE_PUSH_CAPTIONS: Final = "push_captions"

# When on, a name the Home app writes into ConfiguredName (e.g. its own
# default "Jaloezieën 1") is answered by pushing our caption back.
CONF_ENFORCE_CAPTIONS: Final = "enforce_captions"
DEFAULT_ENFORCE_CAPTIONS: Final = True
# Delays (s) after pairing / start before captions are pushed to the Home app;
# the Home app is still busy setting up the accessory right after pairing.
CAPTION_PUSH_DELAYS: Final = (10.0, 60.0)
CAPTION_REASSERT_SECONDS: Final = 2.0


# The control the Home app shows first (top left); all others follow sorted
# by caption. See layout.py.
CONF_PRIMARY: Final = "primary_control"
DEFAULT_PRIMARY: Final = "back"
