"""Config flow for HomeKit Bed Aggregator."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers import (
    device_registry as dr,
)
from homeassistant.helpers import (
    entity_registry as er,
)
from homeassistant.helpers import (
    selector,
)

from .const import (
    ADJUSTABLE_BED_DOMAIN,
    ALL_KEYS,
    ALWAYS_OFFERED_KEYS,
    COLOR_PREFIX,
    COMBINED_LIGHT_KEYS,
    CONF_ADDED,
    CONF_BED_DEVICE,
    CONF_ENFORCE_CAPTIONS,
    CONF_HIDDEN,
    CONF_INVERTED,
    CONF_MASSAGE_BUTTONS,
    CONF_MASSAGE_SLIDERS,
    CONF_OVERRIDES,
    CONF_PORT,
    CONF_PRIMARY,
    CONF_SLIDERS,
    CONF_TIMED,
    CONF_TIMED_ON,
    CONTROLS,
    CONTROLS_BY_KEY,
    DEFAULT_COLOR,
    DEFAULT_ENFORCE_CAPTIONS,
    DEFAULT_NAME,
    DEFAULT_PORT,
    DEFAULT_PRIMARY,
    DOMAIN,
    GROUPS,
    KIND_LIGHT,
    LABEL_PREFIX,
    SOURCE_DOMAINS,
    TIMED_MAX_SECONDS,
)
from .controls import (
    Control,
    effective_controls,
    is_massage_button,
    is_massage_slider,
    normalize_options,
    reports_position,
    selected_ids,
    switched_off_ids,
    timed_enabled,
    timed_sections,
)
from .detection import DETECTION_GROUPS, DetectedControl, _bed_entries, detect_controls
from .devices import child_device_ids, related_device_ids
from .labels import async_control_names, async_default_labels, async_group_names
from .layout import preview_markdown
from .server import async_port_is_free

SECTION_CAPTIONS = "captions"
SECTION_LAYOUT = "layout"
SECTION_ADD = "add"
SECTION_DISPLAY = "display"
SECTION_TIMED = "timed"
TIMED_PREFIX = "timed_"
CONF_ADD_CONTROLS = "add_controls"

# Entity domains per HomeKit type in the linked-bed form.
_HK_DOMAINS = {
    "cover": ["number", "input_number", "cover"],
    "light": ["number", "input_number", "light"],
    "fan": ["number", "input_number", "fan"],
    "momentary": ["button", "input_button", "script", "scene", "switch", "input_boolean"],
    "switch": ["switch", "input_boolean", "light", "fan", "button", "script"],
    "select": ["select", "input_select"],
    "climate_fan": ["climate"],
}
CONF_AUTODETECT = "autodetect"
CONF_SHOW_ALL = "show_all"


def autodetect_entities(hass: HomeAssistant, device_id: str) -> dict[str, str]:
    """Find the controls of an ha-adjustable-bed device by unique_id suffix."""
    registry = er.async_get(hass)
    entries = _bed_entries(hass, registry, device_id)
    found: dict[str, str] = {}
    for spec in CONTROLS:
        for domain, suffix in spec.detect:
            pattern = re.compile(rf"_{re.escape(suffix)}(_left|_right)?$")
            match = next(
                (
                    e.entity_id
                    for e in entries
                    if e.domain == domain
                    and (e.translation_key == suffix or pattern.search(e.unique_id))
                ),
                None,
            )
            if match:
                found[spec.key] = match
                break
    return found


def offered_keys(hass: HomeAssistant, device_id: str | None, current: dict[str, Any]) -> list[str]:
    """Controls to show in the forms.

    ha-adjustable-bed already works out what the connected bed can do and
    only creates entities for those capabilities (required_capability,
    memory_slot_count, motor list, ...). Its entity registry entries are the
    stable, public result of that detection, so we use them rather than
    reaching into its coordinator. Lights are always offered, because any HA
    light can be used; controls already configured stay visible so they can
    be removed. Without a bed device everything is shown.
    """
    if not device_id:
        return list(ALL_KEYS)
    registry = er.async_get(hass)
    if not any(
        e.platform == ADJUSTABLE_BED_DOMAIN
        for dev_id in related_device_ids(hass, device_id)
        for e in er.async_entries_for_device(registry, dev_id)
    ):
        return list(ALL_KEYS)
    wanted = (
        set(autodetect_entities(hass, device_id))
        | set(ALWAYS_OFFERED_KEYS)
        | {key for key in ALL_KEYS if current.get(key)}
    )
    return [key for key in ALL_KEYS if key in wanted]


def _entity_field(key: str, default: str | None) -> vol.Optional:
    return (
        vol.Optional(key, description={"suggested_value": default})
        if default
        else vol.Optional(key)
    )


def _entity_sections(defaults: dict[str, Any], keys: list[str] | None = None) -> dict[Any, Any]:
    """One section per group with the offered controls; all optional.

    Every light also gets its "Colour in HomeKit" switch right below it.
    """
    sections: dict[Any, Any] = {}
    for group in GROUPS:
        fields: dict[Any, Any] = {}
        for spec in CONTROLS:
            if spec.group != group or (keys is not None and spec.key not in keys):
                continue
            fields[_entity_field(spec.key, defaults.get(spec.key))] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain=SOURCE_DOMAINS[spec.kind])
            )
            if spec.kind == KIND_LIGHT:
                color_key = f"{COLOR_PREFIX}{spec.key}"
                fields[vol.Optional(color_key, default=defaults.get(color_key, DEFAULT_COLOR))] = (
                    selector.BooleanSelector()
                )

        if not fields:
            continue
        sections[vol.Required(group)] = section(vol.Schema(fields), {"collapsed": False})
    return sections


def _labels_section(labels: dict[str, str], current: dict[str, Any]) -> dict[Any, Any]:
    fields = {
        vol.Optional(
            f"{LABEL_PREFIX}{key}",
            default=current.get(f"{LABEL_PREFIX}{key}") or labels[key],
        ): selector.TextSelector()
        for key in ALL_KEYS
        if current.get(key)  # only captions of controls in use
    }
    return {vol.Required(SECTION_CAPTIONS): section(vol.Schema(fields), {"collapsed": True})}


def _flatten(user_input: dict[str, Any]) -> dict[str, Any]:
    """Merge section dicts into one flat options dict; drop empty values."""
    flat: dict[str, Any] = {}
    for key, value in user_input.items():
        if isinstance(value, dict):
            flat.update(value)
        else:
            flat[key] = value
    return {k: v for k, v in flat.items() if v not in (None, "")}


def _clean(user_input: dict[str, Any]) -> dict[str, Any]:
    return _flatten(user_input)


class BedControlsFormMixin:
    """The linked-bed form, shared by first setup and the options."""

    hass: HomeAssistant
    _pending: dict[str, Any] | None
    _shown: list[str]
    _form_step_id: str

    def _form_data(self) -> dict[str, Any]:
        raise NotImplementedError

    def _form_title(self) -> str:
        raise NotImplementedError

    def _form_base_options(self) -> dict[str, Any]:
        raise NotImplementedError

    async def _async_form_done(self, model: dict[str, Any]) -> ConfigFlowResult:
        raise NotImplementedError

    if TYPE_CHECKING:  # provided by the flow handler this mixin is used with

        def async_show_form(self, **kwargs: Any) -> ConfigFlowResult: ...

    # ------------------------------------------------------------------
    # Linked bed: one list of HomeKit controls, plus "add" for the rest
    # ------------------------------------------------------------------
    async def _async_controls_for_bed(
        self, user_input: dict[str, Any] | None, detected: list[DetectedControl]
    ) -> ConfigFlowResult:
        """Every control in HomeKit is a field in its group; the rest can be added.

        Clearing a field removes the control from HomeKit and moves it to the
        "add" list; picking it in the "add" list puts it back as a field.
        Only exceptions to the detection defaults are stored.
        """
        labels = await async_default_labels(self.hass)
        by_id = {d.control_id: d for d in detected}
        errors: dict[str, str] = {}
        model = self._pending or normalize_options(detected, self._form_base_options())

        if user_input is not None:
            model = dict(model)
            hidden = set(model.get(CONF_HIDDEN) or [])
            added = set(model.get(CONF_ADDED) or [])
            overrides = dict(model.get(CONF_OVERRIDES) or {})
            values: dict[str, Any] = {}
            for group in DETECTION_GROUPS:
                values.update(user_input.get(group) or {})
            moved = False
            for cid in self._shown:
                value = values.get(cid)
                if (control := by_id.get(cid)) is not None:
                    if not value:  # cleared: out of HomeKit, into "add"
                        overrides.pop(cid, None)
                        if control.exposed:
                            hidden.add(cid)
                        added.discard(cid)
                        moved = True
                    elif value == control.entity_id:
                        overrides.pop(cid, None)
                    else:
                        overrides[cid] = value
                elif value:
                    overrides[cid] = value  # extra link, e.g. a Hue lamp
                else:
                    overrides.pop(cid, None)
            for cid in (user_input.get(SECTION_ADD) or {}).get(CONF_ADD_CONTROLS) or []:
                if (control := by_id.get(cid)) is None:
                    continue
                hidden.discard(cid)
                if not control.exposed:
                    added.add(cid)
                moved = True
            for key, value in values.items():
                if key.startswith(COLOR_PREFIX):
                    model[key] = bool(value)
            for key, value in (user_input.get(SECTION_CAPTIONS) or {}).items():
                if value and key.startswith(LABEL_PREFIX):
                    model[key] = value
            captions_in = user_input.get(SECTION_CAPTIONS) or {}
            if CONF_ENFORCE_CAPTIONS in captions_in:
                model[CONF_ENFORCE_CAPTIONS] = captions_in[CONF_ENFORCE_CAPTIONS]
            if CONF_INVERTED in (user_input.get(SECTION_DISPLAY) or {}):
                model[CONF_INVERTED] = user_input[SECTION_DISPLAY][CONF_INVERTED]
            if CONF_PRIMARY in (user_input.get(SECTION_LAYOUT) or {}):
                model[CONF_PRIMARY] = user_input[SECTION_LAYOUT][CONF_PRIMARY]
            if SECTION_TIMED in user_input:  # hidden section: keep the durations
                model[CONF_TIMED] = {
                    key.removeprefix(TIMED_PREFIX): float(seconds)
                    for key, seconds in (user_input[SECTION_TIMED] or {}).items()
                    if seconds and float(seconds) > 0
                }
            switch_defaults = {
                CONF_SLIDERS: True,
                CONF_TIMED_ON: bool(model.get(CONF_TIMED)),
                CONF_MASSAGE_SLIDERS: True,
                CONF_MASSAGE_BUTTONS: True,
            }
            for group, keys in (
                ("positions", (CONF_TIMED_ON, CONF_SLIDERS)),
                ("massage", (CONF_MASSAGE_BUTTONS, CONF_MASSAGE_SLIDERS)),
            ):
                group_in = user_input.get(group) or {}
                for key in keys:
                    if key in group_in and bool(group_in[key]) != bool(
                        model.get(key, switch_defaults[key])
                    ):
                        model[key] = bool(group_in[key])
                        moved = True  # show or hide the related fields right away
            model[CONF_HIDDEN] = sorted(hidden)
            model[CONF_ADDED] = sorted(added)
            model[CONF_OVERRIDES] = overrides
            self._pending = model
            if moved:
                # Show the result right away: added controls appear in their
                # group, removed ones in the "add" list.
                return await self._async_controls_for_bed(None, detected)
            controls = effective_controls(self.hass, self._form_data(), model, labels, detected)
            if not controls:
                errors["base"] = "no_controls"
            else:
                for control in controls:
                    if control.id in CONTROLS_BY_KEY:
                        model.setdefault(f"{LABEL_PREFIX}{control.id}", labels[control.id])
                model.setdefault(CONF_ENFORCE_CAPTIONS, DEFAULT_ENFORCE_CAPTIONS)
                self._pending = model
                return await self._async_form_done(model)

        controls = effective_controls(self.hass, self._form_data(), model, labels, detected)
        in_homekit = {c.id for c in controls}
        position_bed = reports_position(self.hass, detected)
        sections: dict[Any, Any] = {}
        shown: list[str] = []
        for group in DETECTION_GROUPS:
            fields: dict[Any, Any] = {}
            if group == "positions" and position_bed:
                fields[vol.Optional(CONF_TIMED_ON, default=timed_enabled(model, True))] = (
                    selector.BooleanSelector()
                )
                fields[vol.Optional(CONF_SLIDERS, default=bool(model.get(CONF_SLIDERS, True)))] = (
                    selector.BooleanSelector()
                )
            if group == "massage":
                # Only switches for kinds this bed has.
                if any(is_massage_button(d) for d in detected):
                    fields[
                        vol.Optional(
                            CONF_MASSAGE_BUTTONS,
                            default=bool(model.get(CONF_MASSAGE_BUTTONS, True)),
                        )
                    ] = selector.BooleanSelector()
                if any(is_massage_slider(d) for d in detected):
                    fields[
                        vol.Optional(
                            CONF_MASSAGE_SLIDERS,
                            default=bool(model.get(CONF_MASSAGE_SLIDERS, True)),
                        )
                    ] = selector.BooleanSelector()
            members = [c for c in controls if c.group == group and not c.action]
            if group == "lighting":
                # Free slots for any HA light (e.g. Hue next to / under the bed);
                # a combined bed gets them per side.
                slots = list(ALWAYS_OFFERED_KEYS)
                if child_device_ids(self.hass, self._form_data().get(CONF_BED_DEVICE) or ""):
                    slots = list(COMBINED_LIGHT_KEYS)  # left and right
                for key in slots:
                    if key not in in_homekit:
                        members.append(
                            Control(
                                id=key, caption="", entity_id="", hk_type="light", group="lighting"
                            )
                        )
            for control in members:
                shown.append(control.id)
                fields[_entity_field(control.id, control.entity_id or None)] = (
                    selector.EntitySelector(
                        selector.EntitySelectorConfig(
                            domain=_HK_DOMAINS.get(control.hk_type, SOURCE_DOMAINS["switch"])
                        )
                    )
                )
                if control.hk_type == "light" and control.id in CONTROLS_BY_KEY:
                    color_key = f"{COLOR_PREFIX}{control.id}"
                    fields[vol.Optional(color_key, default=model.get(color_key, DEFAULT_COLOR))] = (
                        selector.BooleanSelector()
                    )
            if fields:
                sections[vol.Required(group)] = section(vol.Schema(fields), {"collapsed": True})
        self._shown = shown

        # Timed moves: seconds per section, right after the sections.
        timed_now: dict[str, float] = model.get(CONF_TIMED) or {}
        timed_fields: dict[Any, Any] = {}
        if timed_enabled(model, position_bed):
            for source in timed_sections(detected):
                timed_fields[
                    vol.Optional(
                        f"{TIMED_PREFIX}{source.control_id}",
                        default=float(timed_now.get(source.control_id, 0)),
                    )
                ] = selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0,
                        max=TIMED_MAX_SECONDS,
                        step=0.5,
                        unit_of_measurement="s",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                )
        if timed_fields:
            ordered: dict[Any, Any] = {}
            for marker, value in sections.items():
                ordered[marker] = value
                if str(marker) == "positions":
                    ordered[vol.Required(SECTION_TIMED)] = section(
                        vol.Schema(timed_fields), {"collapsed": True}
                    )
            if not any(str(k) == SECTION_TIMED for k in ordered):
                ordered = {
                    vol.Required(SECTION_TIMED): section(
                        vol.Schema(timed_fields), {"collapsed": True}
                    ),
                    **ordered,
                }
            sections = ordered

        groups = await async_group_names(self.hass)
        chosen = selected_ids(detected, model)
        # Kinds switched off are not offered for adding either.
        off = switched_off_ids(detected, model, position_bed)
        available = [d for d in detected if d.control_id not in chosen and d.control_id not in off]
        if available:
            names = await async_control_names(self.hass)
            sections[vol.Required(SECTION_ADD)] = section(
                vol.Schema(
                    {
                        vol.Optional(CONF_ADD_CONTROLS, default=[]): selector.SelectSelector(
                            selector.SelectSelectorConfig(
                                options=[
                                    selector.SelectOptionDict(
                                        value=d.control_id,
                                        label=f"{groups.get(d.group, d.group)} · "
                                        f"{names.get(d.control_id) or d.name or d.key}",
                                    )
                                    for d in available
                                ],
                                multiple=True,
                            )
                        )
                    }
                ),
                {"collapsed": True},
            )

        # Naming: a caption per control, and whether the Home app may rename.
        captions: dict[Any, Any] = {
            vol.Optional(f"{LABEL_PREFIX}{c.id}", default=c.caption): selector.TextSelector()
            for c in controls
            if not c.action  # timed-move buttons follow their section's name
        }
        captions[
            vol.Optional(
                CONF_ENFORCE_CAPTIONS,
                default=model.get(CONF_ENFORCE_CAPTIONS, DEFAULT_ENFORCE_CAPTIONS),
            )
        ] = selector.BooleanSelector()
        sections[vol.Required(SECTION_CAPTIONS)] = section(
            vol.Schema(captions), {"collapsed": True}
        )

        # Display in HomeKit: inverted blinds sliders.
        invertible = [
            selector.SelectOptionDict(value=c.id, label=c.caption)
            for c in controls
            if c.hk_type == "cover"
        ]
        if invertible and position_bed:  # beds without positions: no display options
            valid = {o["value"] for o in invertible}
            sections[vol.Required(SECTION_DISPLAY)] = section(
                vol.Schema(
                    {
                        vol.Optional(
                            CONF_INVERTED,
                            default=[k for k in model.get(CONF_INVERTED, []) if k in valid],
                        ): selector.SelectSelector(
                            selector.SelectSelectorConfig(options=invertible, multiple=True)
                        )
                    }
                ),
                {"collapsed": True},
            )

        # Layout: first control top left; the current grid is in its help text.
        primary_options = [
            selector.SelectOptionDict(value=c.id, label=c.caption) for c in controls
        ] or [selector.SelectOptionDict(value=DEFAULT_PRIMARY, label=DEFAULT_PRIMARY)]
        primary_default = model.get(CONF_PRIMARY, DEFAULT_PRIMARY)
        if primary_default not in [o["value"] for o in primary_options]:
            primary_default = primary_options[0]["value"]
        sections[vol.Required(SECTION_LAYOUT)] = section(
            vol.Schema(
                {
                    vol.Optional(CONF_PRIMARY, default=primary_default): selector.SelectSelector(
                        selector.SelectSelectorConfig(options=primary_options)
                    )
                }
            ),
            {"collapsed": True},
        )
        return self.async_show_form(
            step_id=self._form_step_id,
            data_schema=vol.Schema(sections),
            errors=errors,
            description_placeholders={
                "name": self._form_title(),
                "preview": preview_markdown([(c.id, c.caption) for c in controls], primary_default),
            },
        )


class HomeKitBedConfigFlow(BedControlsFormMixin, ConfigFlow, domain=DOMAIN):
    """Two steps: pick the bed, then confirm the six source entities."""

    VERSION = 2

    _form_step_id = "bed_controls"

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._pending: dict[str, Any] | None = None
        self._shown: list[str] = []

    def _form_data(self) -> dict[str, Any]:
        return dict(self._data)

    def _form_title(self) -> str:
        return self._data.get(CONF_NAME, DEFAULT_NAME)

    def _form_base_options(self) -> dict[str, Any]:
        return {}

    async def _async_form_done(self, model: dict[str, Any]) -> ConfigFlowResult:
        return self.async_create_entry(title=self._data[CONF_NAME], data=self._data, options=model)

    async def async_step_bed_controls(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """First setup of a detected bed: the same form as in the options."""
        detected = detect_controls(self.hass, self._data.get(CONF_BED_DEVICE))
        return await self._async_controls_for_bed(user_input, detected)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return HomeKitBedOptionsFlow()

    def _next_free_port(self) -> int:
        used = {
            int(e.data.get(CONF_PORT, 0))
            for e in self.hass.config_entries.async_entries()
            if e.domain in (DOMAIN, "homekit")
        }
        port = DEFAULT_PORT
        while port in used:
            port += 1
        return port

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            port = int(user_input[CONF_PORT])
            if not await async_port_is_free(self.hass, port):
                errors[CONF_PORT] = "port_in_use"
            else:
                if device_id := user_input.get(CONF_BED_DEVICE):
                    await self.async_set_unique_id(device_id)
                    self._abort_if_unique_id_configured()
                self._data = {
                    CONF_NAME: user_input[CONF_NAME],
                    CONF_PORT: port,
                    CONF_BED_DEVICE: device_id,
                }
                if detect_controls(self.hass, device_id):
                    return await self.async_step_bed_controls()
                return await self.async_step_entities()

        # Suggest the first adjustable_bed device and its name.
        suggested_device: str | None = None
        suggested_name = DEFAULT_NAME
        dev_reg = dr.async_get(self.hass)
        for entry in self.hass.config_entries.async_entries(ADJUSTABLE_BED_DOMAIN):
            devices = dr.async_entries_for_config_entry(dev_reg, entry.entry_id)
            ent_reg = er.async_get(self.hass)
            # Prefer the device that actually holds the bed entities; with
            # HA 2026.9 child devices that can be the child, not the parent.
            with_entities = [d for d in devices if er.async_entries_for_device(ent_reg, d.id)]
            if pick := (with_entities or devices)[:1]:
                suggested_device = pick[0].id
                suggested_name = pick[0].name_by_user or pick[0].name or DEFAULT_NAME
                break

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default=suggested_name): selector.TextSelector(),
                vol.Optional(
                    CONF_BED_DEVICE,
                    description={"suggested_value": suggested_device},
                ): selector.DeviceSelector(
                    selector.DeviceSelectorConfig(integration=ADJUSTABLE_BED_DOMAIN)
                ),
                vol.Required(CONF_PORT, default=self._next_free_port()): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1024, max=65535, mode=selector.NumberSelectorMode.BOX
                    )
                ),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_entities(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None and not any(_flatten(user_input).get(k) for k in ALL_KEYS):
            errors["base"] = "no_controls"
            user_input = None
        if user_input is None and errors:
            return self._show_entities(errors)
        if user_input is not None:
            options = _clean(user_input)
            labels = await async_default_labels(self.hass)
            for key in ALL_KEYS:
                if options.get(key):
                    options[f"{LABEL_PREFIX}{key}"] = labels[key]
            detected = detect_controls(self.hass, self._data.get(CONF_BED_DEVICE))
            if detected:
                # Start from the detection defaults: controls of this form
                # that were left empty are removed, everything else the bed
                # offers by default (Zero G, Anti-Snore, ...) is kept.
                offered = set(offered_keys(self.hass, self._data.get(CONF_BED_DEVICE), {}))
                emptied = {key for key in offered if not options.get(key)}
                model = normalize_options(detected, {})
                by_id = {d.control_id: d for d in detected}
                bed_entities = {d.entity_id: d.control_id for d in detected}
                added: set[str] = set()
                for key in ALL_KEYS:
                    entity = options.pop(key, None)
                    if not entity:
                        continue
                    if entity in bed_entities:
                        cid = bed_entities[entity]
                        if cid in by_id and not by_id[cid].exposed:
                            added.add(cid)
                    else:
                        model[CONF_OVERRIDES][key] = entity
                model[CONF_HIDDEN] = sorted({d.control_id for d in detected if d.exposed} & emptied)
                model[CONF_ADDED] = sorted(added)
                options = {**options, **model}
            return self.async_create_entry(
                title=self._data[CONF_NAME], data=self._data, options=options
            )

        return self._show_entities({})

    def _show_entities(self, errors: dict[str, str]) -> ConfigFlowResult:
        defaults: dict[str, str] = {}
        device_id = self._data.get(CONF_BED_DEVICE)
        if device_id:
            defaults = autodetect_entities(self.hass, device_id)
        keys = offered_keys(self.hass, device_id, {})
        return self.async_show_form(
            step_id="entities",
            data_schema=vol.Schema(_entity_sections(defaults, keys)),
            errors=errors,
            description_placeholders={
                "found": str(len(defaults)),
                "total": str(len(ALL_KEYS)),
            },
        )


class HomeKitBedOptionsFlow(BedControlsFormMixin, OptionsFlow):
    """Change source entities, captions and the layout of the Home tile."""

    def __init__(self) -> None:
        self._pending: dict[str, Any] | None = None
        self._show_all = False
        self._shown: list[str] = []

    def _effective(self, options: dict[str, Any], labels: dict[str, str]) -> list[Control]:
        return effective_controls(self.hass, dict(self.config_entry.data), options, labels)

    def _controls(self, options: dict[str, Any], labels: dict[str, str]) -> list[tuple[str, str]]:
        """(id, caption) of everything that will be in HomeKit."""
        return [(c.id, c.caption) for c in self._effective(options, labels)]

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Choose between the controls and HomeKit pairing."""
        return self.async_show_menu(step_id="init", menu_options=["controls", "pairing"])

    _form_step_id = "controls"

    def _form_data(self) -> dict[str, Any]:
        return dict(self.config_entry.data)

    def _form_title(self) -> str:
        return self.config_entry.title

    def _form_base_options(self) -> dict[str, Any]:
        return dict(self.config_entry.options)

    async def _async_form_done(self, model: dict[str, Any]) -> ConfigFlowResult:
        return await self.async_step_preview()

    def _server(self) -> Any:
        return getattr(self.config_entry, "runtime_data", None)

    async def async_step_pairing(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the setup code as a QR code, e.g. after removing the bed in Home."""
        server = self._server()
        info = server.pairing_info() if server else None
        if info is None:
            return self.async_abort(reason="not_running")
        if info["paired"]:
            return await self.async_step_paired()
        if user_input is not None:
            # Nothing to save: closing the dialog leaves the options unchanged.
            return self.async_create_entry(data=dict(self.config_entry.options))
        return self.async_show_form(
            step_id="pairing",
            data_schema=vol.Schema(
                {
                    vol.Optional("qr"): selector.QrCodeSelector(
                        selector.QrCodeSelectorConfig(
                            data=info["uri"],
                            scale=6,
                            error_correction_level=selector.QrErrorCorrectionLevel.MEDIUM,
                        )
                    )
                }
            ),
            description_placeholders={"name": self.config_entry.title, "pin": info["pin"]},
        )

    async def async_step_paired(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Already paired: explain, and offer to reset the pairing."""
        server = self._server()
        if user_input is not None:
            if user_input.get("reset"):
                await server.async_reset_pairing()
                return await self.async_step_pairing()
            return self.async_create_entry(data=dict(self.config_entry.options))
        info = server.pairing_info() if server else None
        if info is None:
            return self.async_abort(reason="not_running")
        return self.async_show_form(
            step_id="paired",
            data_schema=vol.Schema(
                {vol.Optional("reset", default=False): selector.BooleanSelector()}
            ),
            description_placeholders={
                "name": self.config_entry.title,
                "controllers": str(info["controllers"]),
            },
        )

    async def async_step_controls(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        detected = detect_controls(self.hass, self.config_entry.data.get(CONF_BED_DEVICE))
        if detected:
            return await self._async_controls_for_bed(user_input, detected)
        errors: dict[str, str] = {}
        if user_input is not None:
            layout = user_input.get(SECTION_LAYOUT, {})
            flat = _clean(user_input)
            labels = await async_default_labels(self.hass)
            in_use = {c.id for c in self._effective(flat, labels)}
            if not in_use:
                errors["base"] = "no_controls"
                self._pending = flat
            else:
                # Captions of controls that were just added: use defaults;
                # drop captions of catalog controls no longer in HomeKit.
                for key in ALL_KEYS:
                    if key in in_use:
                        flat.setdefault(f"{LABEL_PREFIX}{key}", labels[key])
                    else:
                        flat.pop(f"{LABEL_PREFIX}{key}", None)
                flat.setdefault(CONF_ENFORCE_CAPTIONS, layout.get(CONF_ENFORCE_CAPTIONS, True))
                self._pending = flat
                return await self.async_step_preview()

        current = self._pending or dict(self.config_entry.options)
        labels = await async_default_labels(self.hass)
        controls = self._controls(current, labels)
        primary_options = [
            selector.SelectOptionDict(value=key, label=label) for key, label in controls
        ] or [selector.SelectOptionDict(value=DEFAULT_PRIMARY, label=DEFAULT_PRIMARY)]
        primary_default = current.get(CONF_PRIMARY, DEFAULT_PRIMARY)
        if primary_default not in [o["value"] for o in primary_options]:
            primary_default = primary_options[0]["value"]
        layout_fields = {
            vol.Optional(CONF_PRIMARY, default=primary_default): selector.SelectSelector(
                selector.SelectSelectorConfig(options=primary_options)
            ),
            vol.Optional(
                CONF_ENFORCE_CAPTIONS,
                default=current.get(CONF_ENFORCE_CAPTIONS, DEFAULT_ENFORCE_CAPTIONS),
            ): selector.BooleanSelector(),
        }
        # Only blinds-type sliders can be inverted (sections and massage).
        invertible = [
            selector.SelectOptionDict(value=c.id, label=c.caption)
            for c in self._effective(current, labels)
            if c.hk_type == "cover"
        ]
        if invertible:
            valid = {o["value"] for o in invertible}
            layout_fields[
                vol.Optional(
                    CONF_INVERTED,
                    default=[k for k in current.get(CONF_INVERTED, []) if k in valid],
                )
            ] = selector.SelectSelector(
                selector.SelectSelectorConfig(options=invertible, multiple=True)
            )
        # No detected bed: every catalog control can be linked by hand.
        keys = list(ALL_KEYS)
        schema = vol.Schema(
            {
                **_entity_sections(current, keys),
                **_labels_section(
                    labels,
                    {
                        **current,
                        **{
                            c.id: c.entity_id
                            for c in self._effective(current, labels)
                            if c.id in CONTROLS_BY_KEY
                        },
                    },
                ),
                vol.Required(SECTION_LAYOUT): section(
                    vol.Schema(layout_fields), {"collapsed": False}
                ),
            }
        )
        return self.async_show_form(
            step_id="controls",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "name": self.config_entry.title,
                "preview": preview_markdown(controls, primary_default),
            },
        )

    async def async_step_preview(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the expected Home tile; save it or go back and adjust."""
        assert self._pending is not None
        if user_input is not None:
            if user_input.get("save", True):
                return self.async_create_entry(data=self._pending)
            return await self.async_step_controls()
        return self.async_show_form(
            step_id="preview",
            data_schema=vol.Schema(
                {vol.Required("save", default=True): selector.BooleanSelector()}
            ),
            description_placeholders={
                "preview": preview_markdown(
                    self._controls(self._pending, await async_default_labels(self.hass)),
                    self._pending.get(CONF_PRIMARY, DEFAULT_PRIMARY),
                )
            },
        )


__all__ = ["HomeKitBedConfigFlow", "autodetect_entities"]
