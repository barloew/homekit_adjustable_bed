# AGENTS.md

Guidance for agents working on this repository.

## Shared rules with Adjustable Bed

This integration runs in step with
[kristofferR/ha-adjustable-bed](https://github.com/kristofferR/ha-adjustable-bed) and follows
its `AGENTS.md` for everything not covered here, in particular:

- PR descriptions list `AI models used:` (or `None`) and `Reasoning levels:`; see
  `.github/pull_request_template.md`.
- Never post GitHub comments (issues, PRs, discussions, releases) without explicit approval for
  that exact comment. Never use em dashes in drafted GitHub replies.
- Inspect every screenshot supplied with a task before drawing conclusions.

## Project overview

HomeKit Adjustable Bed publishes one Adjustable Bed device as one HomeKit accessory (HAP-python
inside Home Assistant). Start with [docs/README.md](docs/README.md) and
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Rules

- Do not reach into Adjustable Bed internals (coordinator, controllers). Use only what it
  publishes: entities, their `translation_key`, devices and child devices.
- Behaviour of the Home app is undocumented; record observations in
  [docs/HOME_APP.md](docs/HOME_APP.md) and do not present guesses as facts.
- Stable identity: never change a control id or the creation order of existing HomeKit
  characteristics without a migration (`controls.migrate_renamed`, `iids.py`). Changed IIDs make
  the Home app forget names, scenes and automations.
- Options of earlier versions must keep working (`controls.normalize_options`): HomeKit keeps
  what it had after an update.
- All user-visible text lives in `translations/*.json` (English source, Dutch); never put
  Dutch or English UI strings in Python. `strings.json` equals `en.json`. Regenerate control
  names with `tools/sync_adjustable_bed.py --offline` (runs `gen_control_translations.py`).
- New Adjustable Bed release: `tools/sync_adjustable_bed.py`, then review its report
  (controls without a rule, renamed keys). Never import or run Adjustable Bed code in tools.
- New detection rules need a case in `tests/test_bed_families.py` or `tests/test_detection.py`.

## Validation

```sh
uv sync --extra dev
uvx ruff@0.15.16 check custom_components tests tools
uvx ruff@0.15.16 format --check custom_components tests tools
uvx pyright@1.1.411 --pythonpath .venv/bin/python custom_components tests
uv run --no-sync pytest
```

## Releases

Version in `manifest.json`, `pyproject.toml` and `const.py`; changelog entry; commit
`chore: Bump version to X.Y.Z`; tag `vX.Y.Z`; GitHub release with **What's New** and
**Bug Fixes** (no "Upgrading" section).
