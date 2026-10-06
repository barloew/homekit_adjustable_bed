## Summary

<!-- What changes and why. -->

## Checks

- [ ] `uvx ruff@0.15.16 check custom_components tests tools` and `ruff format --check`
- [ ] `uvx pyright@1.1.411 --pythonpath .venv/bin/python custom_components tests`
- [ ] `uv run --no-sync pytest`
- [ ] Translations changed? `en.json` and `nl.json` updated, `strings.json` equals `en.json`
- [ ] Version bumped in `manifest.json`, `pyproject.toml` and `const.py` (releases only)

## AI disclosure

AI models used: <!-- None, or every model by its most specific name and version -->
Reasoning levels: <!-- per model, or "Unavailable (not exposed by tool)" -->
