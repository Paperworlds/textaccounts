# Report: 002 — Implement textaccounts core logic
Date: 2026-04-11T00:00:00Z
Status: DONE

## Changes
- feat: add textaccounts core logic — adopt, create, switch, list_profiles (textsessions)

## Test results
- textaccounts config: 6 tests passed
- textaccounts core: 9 tests passed

## Notes for next prompt
- `save_registry` is called with a default `config_path` from the module-level `CONFIG_PATH`. Tests monkey-patch this via a closure in `make_registry()` — works but slightly fragile. Consider accepting `config_path` kwarg in core functions if this becomes a pain.
- `switch("default", ...)` does not update `registry.active` — it just returns the unset line. If the next prompt adds a CLI command, ensure the CLI does not persist active=None inadvertently.
- `create_from_current` and `create_worker` call `adopt` internally, so duplicate-name checks happen there.
- `pyproject.toml` now has `[tool.pytest.ini_options] pythonpath = ["src"]` — this was missing and caused all textaccounts tests to fail on import.
