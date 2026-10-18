"""Generate the names of all detectable controls for the options form.

Usage: python tools/gen_control_translations.py <ha-adjustable-bed>/custom_components/adjustable_bed/translations/en.json

Every entity key that ha-adjustable-bed can create gets a field name in its
detection group (options.step.controls.sections.<group>.data.<id>) and a
caption field (sections.captions.data.label_<id>), in en.json and nl.json.
Names come from ha-adjustable-bed (English only); Dutch keeps them, with the
side suffix translated. Catalog controls keep their hand-written names.
Run again after updating ha-adjustable-bed.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
from custom_components.homekit_bed.detection import (  # noqa: E402
    _CATALOG_ALIAS,
    classify,
)
from custom_components.homekit_bed.detection import (
    _CATALOG_IDS as CATALOG_IDS,
)

BASE = Path(__file__).parents[1] / "custom_components" / "homekit_bed"
GROUPS = ("positions", "presets", "massage", "lighting", "climate", "firmness", "settings")
# Section icons. icons.json carries the MDI icons (valid for hassfest, but the
# Home Assistant frontend does not show icons for config-flow sections yet),
# so the names also start with a matching emoji and three non-breaking spaces
# (normal spaces would collapse to one).
SECTION_ICONS = {
    "positions": ("mdi:bed", "🛏️"),
    "timed": ("mdi:bed-clock", "⏱️"),
    "presets": ("mdi:gesture-tap-button", "👆"),
    "massage": ("mdi:waves", "🌊"),
    "climate": ("mdi:hvac", "🌡️"),
    "firmness": ("mdi:diamond-stone", "💎"),
    "lighting": ("mdi:lightbulb", "💡"),
    "settings": ("mdi:cog-outline", "⚙️"),
    "add": ("mdi:link-plus", "🔗"),
    "captions": ("mdi:rename", "🏷️"),
    "display": ("mdi:gesture-swipe-up", "↕️"),
    "layout": ("mdi:view-grid-plus-outline", "🔲"),
}
GAP = "\u00a0\u00a0\u00a0"


def with_icon(section: str, name: str) -> str:
    """Section name with its emoji in front (any old prefix removed)."""
    name = re.sub(r"^[^\w(]+\s+", "", name)
    return f"{SECTION_ICONS[section][1]}{GAP}{name}"


SECTION_TEXT = {
    "en": {
        "positions": ("Adjustable sections", ""),
        "presets": (
            "Quick actions",
            "Switches to recall positions, such as Memory positions, Flat and Stop.",
        ),
        "massage": ("Massage", "Sliders and/or switches for the available massage functions."),
        "lighting": (
            "Lighting",
            "Switches and, where the light supports it, dimming sliders and colour controls. Shows the controllable bed and under-bed lights, and lets you register Home Assistant lights in the same HomeKit control.",
        ),
        "climate": ("Climate", "Fan, and Sleep Number cooling/heating and footwarming as a fan."),
        "firmness": ("Firmness", "Sleep Number firmness."),
        "settings": ("Settings", "Settings and maintenance actions of the bed."),
        "add": (
            "Add controls",
            "Your bed shows the remaining controls here. Tick a control and press Submit to register it in HomeKit above.",
        ),
        "add_controls": "Add to HomeKit",
        "captions": "Labels in HomeKit",
        "display": "Display in HomeKit",
        "layout": "Layout in HomeKit",
        "timed_buttons": (
            "Buttons for timed adjustments of bed sections",
            "Shows the durations per section (Submit to update the form).",
        ),
        "position_sliders": (
            "Sliders for exact position adjustments of bed sections",
            "Shows the slider per section (Submit to update the form).",
        ),
        "massage_buttons": (
            "Buttons for massage functions",
            "Shows the available massage buttons (Submit to update the form).",
        ),
        "massage_sliders": (
            "Sliders for massage strength",
            "Shows the available massage sliders (Submit to update the form).",
        ),
    },
    "nl": {
        "positions": ("Verstelbare bedsecties", ""),
        "presets": (
            "Snelle acties",
            "Schakelaars om standen op te roepen, zoals Geheugenposities, Vlak en Stop.",
        ),
        "massage": (
            "Massage",
            "Schuifregelaars en/of schakelaars voor beschikbare massagefuncties.",
        ),
        "lighting": (
            "Verlichting",
            "Schakelaars en, indien door de lamp ondersteund, dimschuifregelaars en kleurregelaars. Toont bedienbare bed- en onder-bedverlichting en biedt de mogelijkheid om ook Home Assistant-verlichting binnen dezelfde bediening in HomeKit te registreren.",
        ),
        "climate": (
            "Klimaat",
            "Ventilator, en Sleep Number koelen/verwarmen en voetverwarming als ventilator.",
        ),
        "firmness": ("Hardheid", "Sleep Number-hardheid."),
        "settings": ("Instellingen", "Instellingen en onderhoudsacties van het bed."),
        "add": (
            "Bediening toevoegen",
            "Jouw bed toont hier de resterende bedieningen. Vink een bediening aan en druk op Verzenden om deze hierboven in HomeKit te kunnen registreren.",
        ),
        "add_controls": "Toevoegen aan HomeKit",
        "captions": "Labels in HomeKit",
        "display": "Weergave in HomeKit",
        "layout": "Indeling in HomeKit",
        "timed_buttons": (
            "Knoppen voor getimede verstellingen van bedsecties",
            "Toont de tijdsduur per bedsectie (druk op Verzenden om het formulier bij te werken).",
        ),
        "position_sliders": (
            "Schuifregelaars voor exacte positieverstellingen van bedsecties",
            "Toont de schuifregelaar per bedsectie (druk op Verzenden om het formulier bij te werken).",
        ),
        "massage_buttons": (
            "Knoppen voor massagefuncties",
            "Toont de beschikbare massageknoppen (druk op Verzenden om het formulier bij te werken).",
        ),
        "massage_sliders": (
            "Schuifregelaars voor massagesterkte",
            "Toont de beschikbare massage-schuifregelaars (druk op Verzenden om het formulier bij te werken).",
        ),
    },
}
TIMED_TEXT = {
    "en": (
        "Timed adjustments",
        "Seconds per adjustment (0 = off, at most 30 s). The Home app shows two buttons per bed "
        "section, up and down. Pressing a button adjusts the bed section for this number of "
        "seconds in that direction. Stop interrupts a running adjustment.",
    ),
    "nl": (
        "Getimede verstellingen",
        "Seconden per verstelling (0 = uit, maximaal 30 s). De Woning-app toont twee knoppen "
        "per bedsectie, omhoog en omlaag. Bediening van de knop zal de bedsectie dit aantal "
        "seconden in de gekozen richting verstellen. Stop onderbreekt een lopende verstelling.",
    ),
}
TIMED_WORDS = {"en": {"up": "up", "down": "down"}, "nl": {"up": "omhoog", "down": "omlaag"}}
SIDE_NL = {
    "(left)": "(links)",
    "(right)": "(rechts)",
    "(both)": "(beide)",
    " Left": " links",
    " Right": " rechts",
    " Both": " beide",
}


def main(source: str) -> None:
    upstream = json.loads(Path(source).read_text())["entity"]
    names: dict[str, tuple[str, str]] = {}  # id -> (group, english name)
    motor_ids: set[str] = {"back", "legs", "tilt", "lumbar"}  # sections (timed moves)
    for domain, entries in upstream.items():
        for key, info in entries.items():
            control = classify(domain, key)
            if control is None:
                continue
            control_id = _CATALOG_ALIAS.get((domain, key)) if control.side is None else None
            if control.motor:
                if control_id:
                    motor_ids.add(f"{domain}_{key}" if key in CATALOG_IDS else key)
                else:
                    motor_ids.add(key)
            if control_id:
                # Catalog controls keep their own names; the entity may still
                # appear as "<domain>_<key>" when another one took the id.
                alt = f"{domain}_{key}" if key in CATALOG_IDS else key
                names.setdefault(alt, (control.group, str(info.get("name") or key)))
                continue
            name = str(info.get("name") or key)
            if "{" in name:  # runtime placeholder such as "{action}": name it after the key
                name = key.replace("_", " ").capitalize()
            names.setdefault(key, (control.group, name))
    for lang in ("en", "nl"):
        path = BASE / "translations" / f"{lang}.json"
        data = json.loads(path.read_text())
        sections = data["options"]["step"]["controls"]["sections"]
        catalog_names = {
            k: v
            for sec in ("positions", "comfort", "switches")
            for k, v in sections.get(sec, {}).get("data", {}).items()
        }
        catalog_group = {
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
        text = SECTION_TEXT[lang]
        for group in GROUPS:
            sec = sections.setdefault(group, {})
            name, description = text[group]
            sec["name"] = with_icon(group, name)
            if description:
                sec["description"] = description
            else:
                sec.pop("description", None)
            sec.setdefault("data", {})
        # Switches at the top of the sections block (beds with positions).
        for group, keys in (
            ("positions", ("timed_buttons", "position_sliders")),
            ("massage", ("massage_buttons", "massage_sliders")),
        ):
            for key in keys:
                sections[group]["data"][key] = text[key][0]
                sections[group].setdefault("data_description", {})[key] = text[key][1]
        for key in ("captions", "display", "layout"):
            sections[key]["name"] = with_icon(key, text[key])
        # A control whose group changed (detection rules) moves to its new section.
        for group in GROUPS:
            for key in names:
                sections[group]["data"].pop(key, None)
        # Catalog controls (hand-written names) into their detection group.
        for key, group in catalog_group.items():
            sections[group]["data"][key] = catalog_names[key]
        for key, (group, name) in sorted(names.items()):
            if lang == "nl":
                for en, nl in SIDE_NL.items():
                    name = name.replace(en, nl)
            sections[group]["data"][key] = name
        # colour switches stay in lighting (catalog lights)
        for key in (
            "light_level",
            "under_bed_light_level",
            "light_level_left",
            "light_level_right",
            "under_bed_light_level_left",
            "under_bed_light_level_right",
        ):
            sections["lighting"]["data"][f"color_{key}"] = sections["comfort"]["data"][
                f"color_{key}"
            ]
            sections["lighting"].setdefault("data_description", {})[f"color_{key}"] = sections[
                "comfort"
            ]["data_description"][f"color_{key}"]
        cap = sections["captions"]["data"]
        for group in GROUPS:
            for key, name in sections[group]["data"].items():
                if not key.startswith("color_") and key not in (
                    "timed_buttons",
                    "position_sliders",
                ):
                    cap.setdefault(f"label_{key}", name)
        # Drop names of renamed or removed slots.
        for sec in sections.values():
            for k in [k for k in sec.get("data", {}) if k.endswith("light_level_2")]:
                sec["data"].pop(k)
                sec.get("data_description", {}).pop(k, None)
        # Timed moves: one seconds field per section, named after the section.
        timed_text = TIMED_TEXT[lang]
        sections["timed"] = {
            "name": with_icon("timed", timed_text[0]),
            "description": timed_text[1],
            "data": {
                f"timed_{mid}": sections["positions"]["data"].get(mid, mid)
                for mid in sorted(motor_ids)
                if sections["positions"]["data"].get(mid)
            },
        }
        data["selector"]["timed_move"] = {"options": TIMED_WORDS[lang]}
        sections["add"] = {
            "name": with_icon("add", text["add"][0]),
            "description": text["add"][1],
            "data": {"add_controls": text["add_controls"]},
        }
        # First setup of a detected bed uses the same form as the options.
        data["config"]["step"]["bed_controls"] = json.loads(
            json.dumps(data["options"]["step"]["controls"])
        )
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    icon_map = {key: icon for key, (icon, _emoji) in SECTION_ICONS.items()}
    icons = {
        "config": {"step": {"bed_controls": {"sections": icon_map}}},
        "options": {"step": {"controls": {"sections": icon_map}}},
        "services": {"reset_pairing": "mdi:link-off", "push_captions": "mdi:rename"},
    }
    (BASE / "icons.json").write_text(json.dumps(icons, indent=2, ensure_ascii=False) + "\n")
    (BASE / "strings.json").write_text((BASE / "translations" / "en.json").read_text())
    print(f"{len(names)} detected controls named")


if __name__ == "__main__":
    main(sys.argv[1])
