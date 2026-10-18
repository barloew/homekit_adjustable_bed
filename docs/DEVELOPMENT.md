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
| `test_adjustable_bed_sync.py` | The integration against the synced Adjustable Bed release |

## Translations

All user-visible text lives in `translations/<lang>.json`; `strings.json` is a copy of `en.json`.
Names of all detectable controls are generated from Adjustable Bed's English entity names by
`tools/gen_control_translations.py`; the sync below runs it.

## Keeping up with Adjustable Bed

`tools/sync_adjustable_bed.py` brings the integration up to date with the latest Adjustable Bed
release:

```sh
uv run --no-sync python tools/sync_adjustable_bed.py            # latest release + checks
uv run --no-sync python tools/sync_adjustable_bed.py --check    # is there a newer release?
uv run --no-sync python tools/sync_adjustable_bed.py --ref v4.2.3 --force
uv run --no-sync python tools/sync_adjustable_bed.py --offline  # after changing detection.py
uv run --no-sync python tools/sync_adjustable_bed.py --bump minor
```

What it does:

1. Finds the latest release tag (`git ls-remote`) and reads that release from a blobless clone
   in `.cache/`. Adjustable Bed's code is parsed (`ast`, `json`, `yaml.safe_load`), never
   imported or run.
2. Compares it with the previous sync (`tests/fixtures/adjustable_bed.json`; `--since` picks
   another release): bed types, controllable entities, `timed_move` motors and actions added,
   removed or renamed.
3. Classifies every entity with `detection.py`: by a rule, by a word in the key (vendor
   controls without a rule, off by default) or by domain only. Controls without a rule are
   listed for review: add a rule (with a test) when one deserves a better type or should be on
   by default; probably renamed keys need a migration in `controls.migrate_renamed`.
4. Regenerates the form and caption names (en, nl), `TIMED_MOTORS` in `const.py`, the fixture,
   [Supported beds](SUPPORTED_BEDS.md), the checked version in the README and a
   `CHANGELOG.md` entry.
5. Runs ruff, pyright and pytest (`--no-checks` skips them).

The report is printed and saved as `.cache/sync_report.md`. `tests/test_adjustable_bed_sync.py`
checks the integration against the fixture: every entity has a HomeKit type and a name in its
group, the timed motors match, and the generated documentation is current.

`.github/workflows/sync-adjustable-bed.yml` runs the sync every Monday (and on demand, with an
optional tag) and opens a pull request with the report when a new release is out.

## Releases

1. Set the version in `manifest.json`, `pyproject.toml` and `const.py` (`tests/test_version.py`
   checks they match).
2. Add the release to `CHANGELOG.md`.
3. `git commit -m "chore: Bump version to X.Y.Z"`, `git tag vX.Y.Z`, push with tags.
4. Create a GitHub release with **What's New** and **Bug Fixes**.

## HACS

Checked locally: hassfest (Home Assistant 2026.10) passes, and `tests/test_hacs_requirements.py`
covers what HACS reads from the repository: `hacs.json`, the brand images in
`custom_components/homekit_adjustable_bed/brand/` (`icon.png` 256 px and `icon@2x.png` 512 px, with `dark_`
variants for dark themes; sources in `docs/brand/`), unpinned requirements and the MIT license.

What HACS checks on GitHub itself, to set once the repository is public:

- a repository description and topics (for example `home-assistant`, `hacs`, `homekit`,
  `adjustable-bed`);
- issues enabled;
- at least one GitHub release (a release, not only a tag), created after the workflows pass;
- for the sync workflow: *Settings → Actions → Allow GitHub Actions to create pull requests*.

For the HACS default list, open a pull request to `hacs/default` once the HACS action and
hassfest pass without ignores.

