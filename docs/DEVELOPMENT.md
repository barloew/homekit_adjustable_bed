# Development

Same toolchain as [Adjustable Bed](https://github.com/kristofferR/ha-adjustable-bed): Python
3.14.2+, Home Assistant 2026.9.0+, `uv`, ruff, pyright, pytest.

## Environment and validation

```sh
uv sync --extra dev
uvx ruff@0.15.16 check custom_components tests tools
uvx ruff@0.15.16 format --check custom_components tests tools
uvx pyright@1.1.411 --pythonpath .venv/bin/python custom_components tests
uv run --no-sync pytest
```

CI (`.github/workflows/validate.yml`) runs the same plus HACS and hassfest validation.

## Tests

| File | Covers |
|---|---|
| `test_detection.py`, `test_bed_families.py` | Mapping and defaults, per bed family |
| `test_unified_form.py`, `test_config_flow.py`, `test_capabilities_color_iids.py` | Forms, options model, colour, IIDs |
| `test_accessory.py`, `test_cover_seek.py` | HomeKit channels, motion queue, cover seek |
| `test_combined_bed.py`, `test_devices.py` | Combined beds with real child devices |
| `test_rename_reload.py`, `test_pairing_flow.py` | HAP server with real sockets, pairing |
| `test_translations.py`, `test_version.py` | Translation completeness, one version everywhere |

## Translations

All user-visible text lives in `translations/<lang>.json`; `strings.json` is a copy of `en.json`.
Names of all detectable controls are generated from Adjustable Bed's English entity names:

```sh
python tools/gen_control_translations.py <ha-adjustable-bed>/custom_components/adjustable_bed/translations/en.json
```

Run it after Adjustable Bed adds entities, and after changing groups in `detection.py`.

## Releases

1. Set the version in `manifest.json`, `pyproject.toml` and `const.py` (`tests/test_version.py`
   checks they match).
2. Add the release to `CHANGELOG.md`.
3. `git commit -m "chore: Bump version to X.Y.Z"`, `git tag vX.Y.Z`, push with tags.
4. Create a GitHub release with **What's New** and **Bug Fixes**.
