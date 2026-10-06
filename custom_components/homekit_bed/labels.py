"""Default captions, read from the translation files.

All user-visible text lives in translations/<language>.json. The default
caption of every control is stored under selector.control.options.<key>, so
adding a language only means adding a JSON file - no code change.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers.translation import async_get_translations

from .const import CAPTION_TRANSLATION_KEY, CONTROLS, DOMAIN


async def async_default_labels(hass: HomeAssistant) -> dict[str, str]:
    """Return {control key: default caption} in the HA language.

    Home Assistant fills missing strings of a language with English; the
    English fallback in const.py is only used if no file could be read.
    """
    labels = {spec.key: spec.fallback for spec in CONTROLS}
    language = hass.config.language or "en"
    try:
        strings = await async_get_translations(hass, language, "selector", [DOMAIN])
    except Exception:  # noqa: BLE001 - captions must never break setup
        return labels
    prefix = f"component.{DOMAIN}.selector.{CAPTION_TRANSLATION_KEY}.options."
    for key in labels:
        if value := strings.get(prefix + key):
            labels[key] = value
    return labels


# Notification texts: translations/<lang>.json -> exceptions.<key>.message.
# English fallbacks, only used when no translation file could be read.
FALLBACK_TEXTS: dict[str, str] = {
    "notification_title": "HomeKit Bed",
    "pairing_title": "Pair HomeKit Bed",
    "pairing_message": (
        "Add **{name}** in the Home app: scan the QR code or enter this code:"
        "\n### {pin}\n![QR]({qr_url})"
    ),
    "port_error": (
        "The HomeKit accessory **{name}** could not start on port {port}: "
        "{error}. Choose another port (remove and re-add the integration)."
    ),
    "action_failed": "**{label}** ({bed}) failed: {error}",
    "memory_not_saved": (
        "This Jensen bed keeps memory positions in Home Assistant. Put the bed "
        "in the wanted position and press *Save to Memory {slot}* "
        "(button.*_program_memory_{slot}) of Adjustable Bed once."
    ),
    "memory_one_slot": (
        "This Jensen box (type 4) has only one memory slot. Remove the other "
        "memory switches in the HomeKit Bed options."
    ),
}


async def async_texts(hass: HomeAssistant) -> dict[str, str]:
    """Return the notification templates in the HA language."""
    texts = dict(FALLBACK_TEXTS)
    language = hass.config.language or "en"
    try:
        strings = await async_get_translations(hass, language, "exceptions", [DOMAIN])
    except Exception:  # noqa: BLE001
        return texts
    for key in texts:
        if value := strings.get(f"component.{DOMAIN}.exceptions.{key}.message"):
            texts[key] = value
    return texts


def render(texts: dict[str, str], key: str, **placeholders: object) -> str:
    """Fill a template; fall back to English if a translation is broken."""
    try:
        return texts[key].format(**placeholders)
    except KeyError, IndexError, ValueError:
        return FALLBACK_TEXTS[key].format(**placeholders)


async def async_group_names(hass: HomeAssistant) -> dict[str, str]:
    """Names of the detection groups (selector.detection_group.options)."""
    names = {
        "positions": "Adjustable sections",
        "presets": "Presets",
        "massage": "Massage",
        "lighting": "Lighting",
        "climate": "Climate",
        "firmness": "Firmness",
        "settings": "Settings",
    }
    try:
        strings = await async_get_translations(
            hass, hass.config.language or "en", "selector", [DOMAIN]
        )
    except Exception:  # noqa: BLE001
        return names
    prefix = f"component.{DOMAIN}.selector.detection_group.options."
    for key in names:
        if value := strings.get(prefix + key):
            names[key] = value
    return names


async def async_climate_mode_names(hass: HomeAssistant) -> dict[str, str]:
    """Names for the cool/heat switches (selector.climate_mode.options)."""
    names = {"cool": "Cool", "heat": "Heat"}
    try:
        strings = await async_get_translations(
            hass, hass.config.language or "en", "selector", [DOMAIN]
        )
    except Exception:  # noqa: BLE001
        return names
    prefix = f"component.{DOMAIN}.selector.climate_mode.options."
    for key in names:
        if value := strings.get(prefix + key):
            names[key] = value
    return names


async def async_control_names(hass: HomeAssistant) -> dict[str, str]:
    """Names of all controls as shown in the options form (by control id)."""
    try:
        strings = await async_get_translations(
            hass, hass.config.language or "en", "options", [DOMAIN]
        )
    except Exception:  # noqa: BLE001
        return {}
    prefix = f"component.{DOMAIN}.options.step.controls.sections."
    names: dict[str, str] = {}
    for key, value in strings.items():
        if key.startswith(prefix) and ".data." in key:
            control_id = key.rsplit(".", 1)[1]
            if not control_id.startswith(("label_", "color_")):
                names.setdefault(control_id, value)
    return names
