"""The list of controls that ends up in HomeKit.

Manual mode (default for existing beds): the catalog of 22 controls, each
linked to an entity in the options.

Automatic mode: every control the bed's feature detection offers
(detection.py), filtered by the user's selection or the default exposure,
plus every manually linked catalog control (for example a Hue lamp next to
the bed). A manual link wins over a detected control with the same id or
entity.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.core import HomeAssistant

from .const import (
    ACTION_KEYS,
    CONF_ADDED,
    CONF_AUTO,
    CONF_AUTO_SELECTED,
    CONF_BED_DEVICE,
    CONF_HIDDEN,
    CONF_OVERRIDES,
    CONF_SLIDERS,
    CONF_TIMED,
    CONF_TIMED_ON,
    CONTROLS_BY_KEY,
    KIND_SWITCH,
    LABEL_PREFIX,
    MOTOR_KEYS,
    RENAMED_KEYS,
    SLIDER_KEYS,
    TIMED_MAX_SECONDS,
)
from .detection import (
    DETECTION_GROUPS,
    HK_CLIMATE,
    HK_COVER,
    HK_FAN,
    HK_LIGHT,
    HK_MOMENTARY,
    HK_SELECT,
    HK_SWITCH,
    DetectedControl,
    detect_controls,
)
from .layout import homekit_name


@dataclass(slots=True)
class Control:
    """One control as it will appear in HomeKit."""

    id: str
    caption: str
    entity_id: str
    hk_type: str  # cover / light / fan / momentary / switch / select
    motor: bool = False
    interrupts_motion: bool = False
    group: str = "positions"
    detected: bool = False
    # Service call instead of an entity (timed moves): domain, service, data.
    action: dict[str, Any] | None = None

    @property
    def is_slider(self) -> bool:
        return self.hk_type in (HK_COVER, HK_LIGHT, HK_FAN)


def _catalog_control(key: str, entity_id: str, caption: str) -> Control:
    spec = CONTROLS_BY_KEY[key]
    hk_type = {
        "cover": HK_COVER,
        "light": HK_LIGHT,
        "fan": HK_FAN,
    }.get(spec.kind, HK_MOMENTARY if spec.kind == KIND_SWITCH else HK_COVER)
    return Control(
        id=key,
        caption=caption,
        entity_id=entity_id,
        hk_type=hk_type,
        motor=key in MOTOR_KEYS,
        interrupts_motion=spec.interrupts_motion,
        group=_CATALOG_GROUP.get(key, "settings"),
    )


# Catalog controls placed in the detection groups.
_CATALOG_GROUP = {
    "back": "positions",
    "legs": "positions",
    "tilt": "positions",
    "lumbar": "positions",
    "stop": "presets",
    "flat": "presets",
    **{f"memory_{i}": "presets" for i in range(1, 6)},
    "head_massage": "massage",
    "foot_massage": "massage",
    "wave_massage": "massage",
    "massage_toggle": "massage",
    "massage_head_toggle": "massage",
    "massage_foot_toggle": "massage",
    "light_level": "lighting",
    "under_bed_light_level": "lighting",
    "light_toggle": "lighting",
    "under_bed_light_toggle": "lighting",
    "light_level_left": "lighting",
    "light_level_right": "lighting",
    "under_bed_light_level_left": "lighting",
    "under_bed_light_level_right": "lighting",
    "fan_level": "climate",
}


def selected_ids(detected: list[DetectedControl], options: dict[str, Any]) -> set[str]:
    """Ids of detected controls in HomeKit: defaults, minus removed, plus added."""
    model = options if CONF_HIDDEN in options or CONF_ADDED in options else None
    if model is None and options.get(CONF_AUTO_SELECTED) is not None:
        return set(options[CONF_AUTO_SELECTED])  # legacy explicit selection
    hidden = set(options.get(CONF_HIDDEN) or [])
    added = set(options.get(CONF_ADDED) or [])
    return ({c.control_id for c in detected if c.exposed} - hidden) | added


def migrate_renamed(options: dict[str, Any]) -> dict[str, Any]:
    """Rename control ids of earlier versions (e.g. light_level_2 -> _right)."""
    if not any(old in str(options) for old in RENAMED_KEYS):
        return options

    def ren(value: Any) -> Any:
        if isinstance(value, str):
            return RENAMED_KEYS.get(value, value)
        if isinstance(value, list):
            return [ren(v) for v in value]
        if isinstance(value, dict):
            return {ren_key(k): ren(v) for k, v in value.items()}
        return value

    def ren_key(key: str) -> str:
        for old, new in RENAMED_KEYS.items():
            for prefix in ("", LABEL_PREFIX, "color_"):
                if key == prefix + old:
                    return prefix + new
        return key

    return {ren_key(k): ren(v) for k, v in options.items()}


def normalize_options(detected: list[DetectedControl], options: dict[str, Any]) -> dict[str, Any]:
    """Bring options of any earlier version into the exception-based model.

    The model, used whenever the bed is linked and detection finds entities:
      hidden_controls   detected ids shown by default that the user removed
      added_controls    detected ids hidden by default that the user added
      entity_overrides  {id: entity}: another entity for a detected control,
                        or an extra catalog control (e.g. a Hue lamp)
    Only exceptions are stored, so controls that a later ha-adjustable-bed
    version detects simply follow the defaults.
    Earlier versions stored catalog links (key: entity) and an optional
    explicit selection; they are converted so HomeKit keeps what it had.
    """
    options = migrate_renamed(options)
    if CONF_HIDDEN in options or CONF_ADDED in options or CONF_OVERRIDES in options:
        result = dict(options)
        for key in (*SLIDER_KEYS, *ACTION_KEYS, CONF_AUTO, CONF_AUTO_SELECTED):
            result.pop(key, None)
        return result
    by_id = {d.control_id: d for d in detected}
    bed_entities = {d.entity_id: d.control_id for d in detected}
    defaults = {d.control_id for d in detected if d.exposed}
    overrides: dict[str, str] = {}
    linked: set[str] = set()
    for key in (*SLIDER_KEYS, *ACTION_KEYS):
        entity = options.get(key)
        if not entity:
            continue
        if entity in bed_entities:
            linked.add(bed_entities[entity])  # a bed entity: part of detection
        elif key in by_id and by_id[key].entity_id != entity:
            overrides[key] = entity
            linked.add(key)
        else:
            overrides[key] = entity  # extra, e.g. a Hue lamp or a script
    if not linked and not overrides and not options.get(CONF_AUTO):
        chosen = defaults  # nothing configured yet: the detection defaults
    elif options.get(CONF_AUTO):
        # 4.0/4.1 automatic mode: the detection list decided for bed entities.
        chosen = selected_ids(detected, options) | (linked & set(overrides))
    else:
        chosen = linked  # manual mode: exactly what HomeKit had
    result = {
        k: v
        for k, v in options.items()
        if k not in (*SLIDER_KEYS, *ACTION_KEYS, CONF_AUTO, CONF_AUTO_SELECTED)
    }
    result[CONF_HIDDEN] = sorted(defaults - chosen)
    result[CONF_ADDED] = sorted((chosen & set(by_id)) - defaults)
    result[CONF_OVERRIDES] = overrides
    return result


def reports_position(hass: HomeAssistant, detected: list[DetectedControl]) -> bool:
    """True when a bed section reports its position (number, or cover with a %)."""
    for d in detected:
        if not d.motor:
            continue
        if d.domain == "number":
            return True
        state = hass.states.get(d.entity_id)
        if state is not None and state.attributes.get("current_position") is not None:
            return True
    return False


def timed_sections(detected: list[DetectedControl]) -> list[DetectedControl]:
    """One entry per motor and side that a timed move can drive.

    A section can have both a position number and a cover; the shown one
    (exposed) names the section.
    """
    best: dict[tuple[str, str | None], DetectedControl] = {}
    for d in detected:
        if d.timed_motor is None:
            continue
        key = (d.timed_motor, d.side)
        if key not in best or (d.exposed and not best[key].exposed):
            best[key] = d
    return list(best.values())


def timed_enabled(model: dict[str, Any], position_bed: bool) -> bool:
    """Timed buttons on? Always for beds without positions; else the switch."""
    if not position_bed:
        return True
    return bool(model.get(CONF_TIMED_ON, bool(model.get(CONF_TIMED))))


def data_device_id(data: dict[str, Any]) -> str:
    """The bed device of an entry's data."""
    return str(data.get(CONF_BED_DEVICE) or "")


def effective_controls(
    hass: HomeAssistant,
    data: dict[str, Any],
    options: dict[str, Any],
    labels: dict[str, str],
    detected: list[DetectedControl] | None = None,
) -> list[Control]:
    """Controls in HomeKit, ordered by group.

    With a linked bed whose entities are detected: the detected controls
    (defaults and the user's exceptions) plus extra catalog controls.
    Without a bed: the catalog controls linked in the options.
    """

    def caption(control_id: str, fallback: str) -> str:
        text = options.get(f"{LABEL_PREFIX}{control_id}") or fallback
        return homekit_name(text, fallback or control_id)

    options = migrate_renamed(options)
    if detected is None:
        detected = detect_controls(hass, data.get(CONF_BED_DEVICE))
    if not detected:
        return [
            _catalog_control(key, options[key], caption(key, labels.get(key, key)))
            for key in (*SLIDER_KEYS, *ACTION_KEYS)
            if options.get(key)
        ]

    model = normalize_options(detected, options)
    chosen = selected_ids(detected, model)
    position_bed = reports_position(hass, detected)
    if position_bed and not model.get(CONF_SLIDERS, True):
        # Exact sliders switched off: bed sections only via timed buttons.
        chosen = {cid for cid in chosen if cid not in {d.control_id for d in detected if d.motor}}
    overrides: dict[str, str] = model.get(CONF_OVERRIDES) or {}
    result: list[Control] = []
    for d in detected:
        cid = d.control_id
        if cid not in chosen:
            continue
        default = labels.get(cid) if d.catalog_key else (d.name or d.key)
        result.append(
            Control(
                id=cid,
                caption=caption(cid, default or d.key),
                entity_id=overrides.get(cid, d.entity_id),
                hk_type=d.hk_type,
                motor=d.motor,
                interrupts_motion=d.interrupts_motion,
                group=d.group,
                detected=True,
            )
        )
    # Timed moves: two push buttons per section with a duration set.
    timed: dict[str, float] = model.get(CONF_TIMED) or {}
    if not timed_enabled(model, position_bed):
        timed = {}
    for source in timed_sections(detected):
        seconds = float(timed.get(source.control_id) or 0)
        if seconds <= 0:
            continue
        section_caption = caption(
            source.control_id,
            (labels.get(source.control_id) if source.catalog_key else None)
            or source.name
            or source.key,
        )
        for direction in ("up", "down"):
            cid = f"timed_{source.control_id}_{direction}"
            word = labels.get(f"_timed_{direction}", direction)
            call_data: dict[str, Any] = {
                "device_id": data_device_id(data),
                "motor": source.timed_motor,
                "direction": direction,
                "duration_ms": int(min(seconds, TIMED_MAX_SECONDS) * 1000),
            }
            if source.side in ("left", "right"):
                call_data["side"] = source.side
            result.append(
                Control(
                    id=cid,
                    caption=caption(cid, f"{section_caption} {word}"),
                    entity_id="",
                    hk_type=HK_MOMENTARY,
                    interrupts_motion=True,
                    group=source.group,
                    detected=True,
                    action={
                        "domain": "adjustable_bed",
                        "service": "timed_move",
                        "data": call_data,
                    },
                )
            )
    detected_ids = {d.control_id for d in detected}
    for key, entity in overrides.items():
        if key in detected_ids or key not in CONTROLS_BY_KEY or not entity:
            continue
        result.append(_catalog_control(key, entity, caption(key, labels.get(key, key))))
    order = {g: i for i, g in enumerate(DETECTION_GROUPS)}
    result.sort(key=lambda c: order.get(c.group, len(order)))
    return result


__all__ = [
    "Control",
    "HK_CLIMATE",
    "HK_COVER",
    "HK_FAN",
    "HK_LIGHT",
    "HK_MOMENTARY",
    "HK_SELECT",
    "HK_SWITCH",
    "effective_controls",
    "normalize_options",
    "selected_ids",
]
