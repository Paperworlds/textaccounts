# Changelog

## v0.8.0

- BREAKING: storage root moves from `~/.textaccounts/` to `~/.local/paperworlds/textaccounts/`. `CONFIG_PATH`, `DEFAULT_PROFILES_DIR`, `GC_LOG_PATH`, and the shell-wrapper write target (`textaccounts install`) all follow.
- Single-user move — no migration command. `profiles.yaml`, `shell.bash`, `shell.zsh` moved by hand from the prior root.
- Test paths updated to match (`test_install_bash_uses_spec_paths`, `test_install_zsh_uses_spec_paths`).
- Fix: `test_write_profile_gitconfig_gpg_sw` was asserting the pre-quoting form (`name = Alice`); the writer started quoting name/email defensively (handles names with spaces) but the test wasn't updated. Quoted form is valid git-config syntax.

## v0.7.3

- refactor(shell): completion helpers now use `textaccounts repos | awk '{print $2}'` — replaces three per-shell YAML-parsing snippets; immune to registry format changes
- refactor(cli): remove function-local `active_profile_from_env` imports in `desc` and `repos_cmd`; use `core.active_profile_from_env` via the already-imported module
- refactor(api): hoist local `active_profile_from_env` import to module top
- breaking(core): drop `create_worker()` deprecated alias (use `create_shallow()`) — v1.0 cleanup
- breaking(config): drop `worker:` backward-compat key in `Profile.from_dict`; `profiles.yaml` must use `shallow:` — v1.0 cleanup

## v0.7.2

- refactor(cli): shell template strings moved out of cli.py into `textaccounts/shell_templates.py` — cli.py drops from 855 to 684 LoC; templates are now diffable in isolation
- refactor(core): `adopt_token` business logic extracted from CLI handler into `core.adopt_token(name, dest, token, registry)` — CLI handler is now ~15 lines of orchestration; testable without CliRunner
- refactor(core): `compute_env(profile) -> dict[str, str | None]` unifies env-var computation shared between `show()` and `env_for_profile()` — drift between the two code paths was the root cause of B3
- refactor(api): `env_for_profile` now delegates to `core.compute_env`; `api.py` no longer imports private `_token_keychain_read` from core
- fix(cli): `signing unset` now prints a hint to re-run `ta switch <profile>` when `GIT_CONFIG_GLOBAL` may still point at the deleted gitconfig

## v0.7.1

- fix(core): `rename()` was silently dropping `auth_method` and `signing` — replaced 12-line manual field repack with `dataclasses.replace(profile, name=new_name)`
- fix(core): `import_profiles()` was silently dropping `ephemeral`, `owner`, `signing`, and `auth_method` on import — now delegates to `Profile.from_dict`, same path as `load_registry`
- refactor(config): `Profile` and `SigningConfig` now carry `from_dict` / `to_dict` classmethods — `load_registry` and `save_registry` are thin wrappers; adding a new field requires touching one place
- refactor(core): deduplicated two near-identical 60-line Keychain blocks into a single `_security(action, service, data)` helper; the six public helpers are now one-liners (−80 LoC)

## v0.7.0

- feat(cli): shell completions per paperworlds CONVENTIONS spec — Click-generated for all subcommands (was hand-written and missing `adopt-token`, `desc`, `describe`, `destroy`, `gc`, `repo`, `signing`)
- feat(cli): dynamic profile-name completion via Click's `shell_complete` callback on `show/rename/alias/describe/destroy/signing set/show/unset`
- fix(install): bash completions now write to `~/.local/share/bash-completion/completions/textaccounts` per spec (was `~/.textaccounts/shell.bash`)
- fix(install): zsh completions now write to `~/.zfunc/_textaccounts` per spec (was `~/.textaccounts/shell.zsh`)
- fix(install): ship a corrected fish completion wrapper — Click 8.3.2's generated wrapper expects comma-separated output but the runtime emits newline-separated triplets (upstream Click bug)

## v0.6.0

- feat(core): per-profile git commit signing — profiles declare `signing: {mode, key, name, email}` in `profiles.yaml`; on switch, textaccounts writes `<profile_path>/gitconfig` and injects `GIT_CONFIG_GLOBAL` alongside `CLAUDE_CONFIG_DIR`. Per-shell isolation (no `~/.gitconfig` mutation). Modes: `unsigned`, `gpg-sw`, `gpg-hw` (hw deferred — schema is forward-compatible).
- feat(cli): `textaccounts signing set/show/unset` to manage signing config per profile
- feat(api): `env_for_profile` now includes `GIT_CONFIG_GLOBAL` when the profile has a signing block
- The generated profile gitconfig `[include]`s `~/.gitconfig` first, so `core.excludesfile`, aliases, pull.rebase, etc. survive the GIT_CONFIG_GLOBAL replacement
- refactor: active profile is now per-shell, derived from `$CLAUDE_CONFIG_DIR` via `core.active_profile_from_env()`. Dropped the global `~/.textaccounts/active-description` cache file and the `active:` key in `profiles.yaml` (legacy values ignored on load). `ta status` / `ta list` / `ta desc` / public `api.active_profile()` all reflect the current shell, not the last-switched profile machine-wide.

## v0.5.3

- fix(core): `_dir_size_bytes` refuses to scan `$HOME` or `/` — a misconfigured profile pointing there caused `textaccounts list` to walk the entire home and time out (~3s → 0.3s)

## v0.5.2

- feat(cli): `textaccounts export` — password-protected AES-256 zip of registry + per-profile settings, with `.sha256` hash file
- feat(cli): `textaccounts import` — merge profiles from an export zip, with `--overwrite` flag for conflict resolution
- dep: add `pyzipper>=0.3.6` for AES zip support

## v0.5.1

- fix(core): replace `os.getlogin()` with `getpass.getuser()` — avoids `OSError` in SSH sessions, CI/CD, and containers; `os.getlogin()` is deprecated in Python 3.11+

## v0.5.0

- feat(core): token-auth profiles via `CLAUDE_CODE_OAUTH_TOKEN` — non-interactive profiles for automated sessions
- feat(core): Keychain-aware shallow clones — `create --shallow-from <src>` copies profile config without sensitive secrets
- feat(api): `get_profile_lineage` + supersedes api v0.1.0 → v0.2.0
- feat: shallow clone ephemeral lifecycle (gc, destroy)
- docs: `TESTING.yaml` smoke-test runbook

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
