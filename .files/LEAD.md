# textaccounts — Feature Context

Feature of: textsessions

A standalone CLI tool (`textaccounts`) that manages multiple Claude Code accounts by treating full config directories as profiles. Replaces the third-party `cloak` npm package with a native Python solution that understands the real structure of `~/.claude/`. Lives inside the textsessions repo as a sibling package, with its own entry point.

## Feature scope

### What it adds
- New package `src/textaccounts/` with CLI entry point `textaccounts`
- Profile registry at `~/.config/textaccounts/profiles.yaml`
- Commands: `adopt`, `create`, `list`, `switch`, `status`
- Fish shell integration (`ta` function for switch eval)
- `src/textaccounts/README.md` with motivation, cloak comparison, design

### What it changes in textsessions
- `profiles.py` — swap cloak detection for textaccounts detection in `build_launch_env()`
- `config.py` — add `textaccounts: bool` to IntegrationsConfig
- `cli.py` — remove the `textsessions profile` group (status/list/setup/check) since textaccounts handles all of that now
- `pyproject.toml` — add `textaccounts` entry point and package

### Boundaries
- textaccounts is usable standalone (no textsessions dependency)
- textsessions detects textaccounts passively (reads its YAML config)
- cloak fallback kept in `build_launch_env()` for other users

## What exists

### Current manual setup (what textaccounts formalizes)
- `~/.claude/` — main config dir, symlinked into `~/.claude-work/`
- `~/.claude-work/` — full work profile (auth, settings, sessions, projects, agent-memory, 2M history)
- `~/.claude-personal/` — full personal profile (auth, sessions, projects, 194K history)
- `~/.claude-profiles/primary/` — earlier attempt at profiles

### textsessions profile code (to be replaced)
- `src/textsessions/profiles.py` — cloak detection: `cloak_available()`, `cloak_profile_dir()`, `list_cloak_profiles()`, `cloak_version()`, plus `build_launch_env()` and `resume_cmd()`
- `src/textsessions/cli.py` lines 116-265 — `textsessions profile` group with status/list/setup/check subcommands
- `src/textsessions/config.py` — `IntegrationsConfig(cloak=True, aiproxy=True)`
- `tests/test_profiles.py` — 18 tests for cloak integration
- `docs/cloak-setup.md` — cloak setup guide (to be replaced by textaccounts README)

### Why not cloak?
| | cloak | textaccounts |
|---|---|---|
| What's a profile? | 2 files (auth + settings) | Full config dir |
| Profile dir | hardcoded `~/.cloak/profiles/` | configurable, default `~/.claude-profiles/` |
| Sessions | lost per switch | preserved per profile |
| Memory/CLAUDE.md | shared fallthrough | isolated per profile |
| Install | npm | pip/pipx (same as textsessions) |
| Adopt existing dirs | no | yes (`adopt` command) |

## Key files

- `src/textsessions/profiles.py` — swap cloak functions for textaccounts detection
- `src/textsessions/config.py` — IntegrationsConfig changes
- `src/textsessions/cli.py` — remove profile group
- `pyproject.toml` — add textaccounts package + entry point
- `tests/test_profiles.py` — update for textaccounts

## Config schema

```yaml
# ~/.config/textaccounts/profiles.yaml
version: 1
active: work

profiles:
  work:
    path: /Users/paulie/.claude-work
    email: paolo.d***@paradigm.co
    adopted: 2026-04-12T10:00:00Z
    worker: false
  personal:
    path: /Users/paulie/.claude-personal
    email: paolo@personal.dev
    adopted: 2026-04-12T10:00:00Z
    worker: false
  work-worker:
    path: /Users/paulie/.claude-profiles/work-worker
    email: paolo.d***@paradigm.co
    worker: true
    parent: work

defaults:
  profiles_dir: ~/.claude-profiles
```

## CLI reference

```
textaccounts adopt <name> <path>                    # register existing dir as profile
textaccounts create <name>                          # snapshot current config dir
textaccounts create <name> --worker --from <parent> # worker (auth-only copy)
textaccounts list                                   # show all profiles
textaccounts switch <name>                          # print fish env line, update registry
textaccounts status                                 # active profile info
```

Fish wrapper (needed because subprocess can't set parent env):
```fish
function ta --description "textaccounts shorthand"
    if test (count $argv) -ge 1; and test "$argv[1]" = "switch"
        eval (textaccounts switch $argv[2..-1])
    else
        textaccounts $argv
    end
end
```

## Constraints

- Python 3.12+, click for CLI (match textsessions)
- YAML config (not TOML) — cleaner for dynamic profile keys, differentiates from textsessions config
- No runtime dependency on textsessions (standalone)
- Fish shell native — no bash eval hacks
- `adopt` is the primary migration path (dirs already exist, no copying needed)
- Keep `build_launch_env()` and `resume_cmd()` in textsessions — only change the profile lookup
- Tests must use tmp dirs, never touch real `~/.claude*` paths
