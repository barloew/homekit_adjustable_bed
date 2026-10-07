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
SECTION_TEXT = {
    "en": {
        "positions": ("Adjustable sections", "One slider per section."),
        "presets": (
            "Quick actions",
            "Switches to recall positions, such as Memory positions, Flat and Stop.",
        ),
        "massage": ("Massage", "Sliders and/or switches for the available massage functions."),
        "lighting": (
            "Lighting",
            "Switches and, where the light supports it, dimming sliders and colour controls. Shows the controllable bed and under-bed lighting, and lets you register Home Assistant lights in the same HomeKit control.",
        ),
        "climate": ("Climate", "Fan, and Sleep Number cooling/heating and footwarming as a fan."),
        "firmness": ("Firmness", "Sleep Number firmness."),
        "settings": ("Settings", "Settings and maintenance actions of the bed."),
        "add": (
            "Add controls",
            "Your bed shows the remaining controls here. Tick a control and press Submit to register it in HomeKit above.",
        ),
        "add_controls": "Add to HomeKit",
    },
    "nl": {
        "positions": ("Verstelbare bedsecties", "Eén schuifregelaar per sectie."),
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
    },
}
TIMED_TEXT = {
    "en": (
        "Timed moves",
        "Seconds per movement (0 = off). Every section with a duration gets two push buttons in "
        "HomeKit, up and down, that move it for that time (adjustable_bed.timed_move, at most "
        "30 s). Useful for beds without position feedback. Stop interrupts a running move.",
    ),
    "nl": (
        "Getimede bewegingen",
        "Seconden per beweging (0 = uit). Elke sectie met een duur krijgt in HomeKit twee "
        "drukknoppen, omhoog en omlaag, die haar die tijd laten bewegen "
        "(adjustable_bed.timed_move, maximaal 30 s). Handig voor bedden zonder standmelding. "
        "Stop onderbreekt een lopende beweging.",
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
            name = str(info.get("name") or key).replace("{action}", "Action")
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
            sec["name"], sec["description"] = text[group]
            sec.setdefault("data", {})
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
                if not key.startswith("color_"):
                    cap.setdefault(f"label_{key}", name)
        # Drop names of renamed or removed slots.
        for sec in sections.values():
            for k in [k for k in sec.get("data", {}) if k.endswith("light_level_2")]:
                sec["data"].pop(k)
                sec.get("data_description", {}).pop(k, None)
        # Timed moves: one seconds field per section, named after the section.
        timed_text = TIMED_TEXT[lang]
        sections["timed"] = {
            "name": timed_text[0],
            "description": timed_text[1],
            "data": {
                f"timed_{mid}": sections["positions"]["data"].get(mid, mid)
                for mid in sorted(motor_ids)
                if sections["positions"]["data"].get(mid)
            },
        }
        data["selector"]["timed_move"] = {"options": TIMED_WORDS[lang]}
        sections["add"] = {
            "name": text["add"][0],
            "description": text["add"][1],
            "data": {"add_controls": text["add_controls"]},
        }
        # First setup of a detected bed uses the same form as the options.
        data["config"]["step"]["bed_controls"] = json.loads(
            json.dumps(data["options"]["step"]["controls"])
        )
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    (BASE / "strings.json").write_text((BASE / "translations" / "en.json").read_text())
    print(f"{len(names)} detected controls named")


if __name__ == "__main__":
    main(sys.argv[1])
