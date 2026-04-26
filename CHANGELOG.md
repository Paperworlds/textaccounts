# Changelog

## v0.4.1

- feat: `textaccounts create --clone-from <src>` for clean profile clones
- feat: `textaccounts describe` command (and `desc` short form for statusline integration)
- feat: expose `profile_description` in public API
- feat: write active profile description to cache file for statusline consumers
- feat: per-profile description shown in bottom bar of the interactive view
- fix: `textaccounts desc` resolves profile via `CLAUDE_CONFIG_DIR`
- spec: add textaccounts-api spec (draft v0.1.0); textworkspace listed as a consumer
- chore: full PyPI metadata in `pyproject.toml` (authors, urls, classifiers, keywords)
- chore: lower `requires-python` to `>=3.13`
- ci: pin CI Python to 3.14 to match local dev environment
- fix: add missing `Path` import in `test_textaccounts_cli.py` (CI failure)

## v0.4.0

- Add `textaccounts doctor` — checks all registered profile paths; exits 1 if any are stale
- Add `textaccounts repos` — prints parseable `REPO name path [active]` lines for scripting
- Add `textaccounts repo move <name> <new_path>` — updates a profile's registered path without moving files on disk
- Add GitHub Actions CI workflow — runs `pytest` on every push and PR to `main`
- Fix version string format to match CONVENTIONS (`textaccounts, version X.Y.Z (hash)`)
- Update shell completions (fish/bash/zsh) to include new commands

## v0.3.4

- Add `--version` / `-V` flag with embedded git hash
- Validate YAML structure in `load_registry` with clear error messages on malformed config
- Tighten exception handling in `_dir_size_bytes` and API resolvers
- Add bash/zsh shell integration alongside existing fish support
- Fix `ta` alias: registered as fish function so `textaccounts switch` environment changes propagate correctly
- Read `__version__` from package metadata; remove hardcoded duplicate

## v0.2.1

- Initial public release — adopt, create, switch, rename, alias, view, install commands
- Fish shell integration via `textaccounts install`
- Interactive TUI (`textaccounts view`) for browsing and managing profiles
- Worker profile support: `--worker --from <parent>` copies auth-only subset
- Auto-discovers unregistered `~/.claude*/` directories as adoption suggestions
