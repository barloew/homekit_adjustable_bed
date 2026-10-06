"""Every visible text comes from translations/*.json and all languages match."""

import json
import re
import string
from pathlib import Path
from unittest.mock import patch

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import section
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.homekit_bed.const import ALL_KEYS, DOMAIN
from custom_components.homekit_bed.labels import FALLBACK_TEXTS

BASE = Path(__file__).parents[1] / "custom_components" / "homekit_bed"
EN = json.loads((BASE / "translations" / "en.json").read_text())
LANGS = {p.stem: json.loads(p.read_text()) for p in (BASE / "translations").glob("*.json")}


def _paths(node, prefix=""):
    if isinstance(node, dict):
        out = set()
        for key, value in node.items():
            out |= _paths(value, f"{prefix}{key}.")
        return out
    return {prefix[:-1]}


def _get(tree, path):
    for part in path.split("."):
        tree = tree[part]
    return tree


def _placeholders(text):
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def test_strings_json_is_english() -> None:
    assert json.loads((BASE / "strings.json").read_text()) == EN


@pytest.mark.parametrize("lang", sorted(LANGS))
def test_same_keys_and_placeholders_as_english(lang) -> None:
    other = LANGS[lang]
    assert _paths(other) == _paths(EN), lang
    for path in _paths(EN):
        assert _placeholders(_get(other, path)) == _placeholders(_get(EN, path)), path
        assert _get(other, path).strip(), path


def test_default_captions_and_texts_complete() -> None:
    assert set(EN["selector"]["control"]["options"]) == set(ALL_KEYS)
    assert set(EN["exceptions"]) == set(FALLBACK_TEXTS)
    for key, fallback in FALLBACK_TEXTS.items():
        assert _placeholders(EN["exceptions"][key]["message"]) == _placeholders(fallback)


def _assert_form_translated(tree: dict, step_id: str, schema) -> None:
    step = tree["step"][step_id]
    for marker, value in schema.schema.items():
        key = str(marker)
        if isinstance(value, section):
            sec = step["sections"][key]
            assert sec["name"]
            for inner in value.schema.schema:
                assert sec["data"][str(inner)], f"{step_id}.{key}.{inner}"
        else:
            assert step["data"][key], f"{step_id}.{key}"
    for sec in step.get("sections", {}).values():
        assert set(sec.get("data_description", {})) <= set(sec["data"])


async def test_every_config_field_has_a_label(hass: HomeAssistant, mock_async_zeroconf) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    for lang in LANGS.values():
        _assert_form_translated(lang["config"], "user", result["data_schema"])
    with patch("custom_components.homekit_bed.config_flow.async_port_is_free", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"name": "Bed", "port": 21070}
        )
    for lang in LANGS.values():
        _assert_form_translated(lang["config"], "entities", result["data_schema"])


async def test_every_options_field_has_a_label(hass: HomeAssistant, mock_async_zeroconf) -> None:
    options = {key: f"button.{key}" for key in ALL_KEYS}  # all controls in use
    entry = MockConfigEntry(
        domain=DOMAIN, version=2, data={"name": "Bed", "port": 21070}, options=options
    )
    entry.add_to_hass(hass)
    with patch("custom_components.homekit_bed.async_setup_entry", return_value=True):
        await hass.config_entries.async_setup(entry.entry_id)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "controls"}
    )
    for lang in LANGS.values():
        _assert_form_translated(lang["options"], "controls", result["data_schema"])


async def test_default_captions_follow_ha_language(hass: HomeAssistant) -> None:
    """Captions come from the JSON of the HA language, not from code."""
    from custom_components.homekit_bed.labels import async_default_labels

    nl = LANGS["nl"]["selector"]["control"]["options"]
    flat = {f"component.{DOMAIN}.selector.control.options.{k}": v for k, v in nl.items()}
    hass.config.language = "nl"
    with patch("custom_components.homekit_bed.labels.async_get_translations", return_value=flat):
        labels = await async_default_labels(hass)
    assert labels["back"] == "Rugdeel" and labels["flat"] == "Bed vlak"
    # Without translations the English fallback in code is used.
    with patch("custom_components.homekit_bed.labels.async_get_translations", return_value={}):
        labels = await async_default_labels(hass)
    assert labels["back"] == "Head section"


def test_no_dutch_left_in_code() -> None:
    """User-facing strings must live in translations, not in Python.

    Docstrings and comments may quote Dutch observations; string literals not.
    """
    import ast

    dutch = re.compile(r"Woning|koppelen|mislukt|bewaart|Bijschrift|Hoofdeinde|Voeg ")
    for py in BASE.glob("*.py"):
        tree = ast.parse(py.read_text())
        docstrings = {
            id(node.body[0].value)
            for node in ast.walk(tree)
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            and node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
        }
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in docstrings
            ):
                assert not dutch.search(node.value), f"{py.name}: {node.value!r}"
