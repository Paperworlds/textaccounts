# textaccounts

Manage multiple Claude Code accounts with full directory isolation. Each profile is a complete `~/.claude/` config directory — sessions, memory, settings, and auth stay separate.

## Why?

Claude Code stores everything in a single directory tree (`~/.claude/`). If you use multiple accounts (work + personal), you need separate directories. `textaccounts` registers and switches between them by setting `CLAUDE_CONFIG_DIR`.

## Install

```sh
pip install textaccounts
```

Then install shell integration:

```sh
textaccounts install
```

This writes a fish function and completions to `~/.config/fish/`. Open a new shell to activate.

## Quick start

```sh
# Register existing directories — nothing is moved or copied
textaccounts adopt work ~/.claude-work
textaccounts adopt personal ~/.claude-personal

# Switch profile (sets CLAUDE_CONFIG_DIR in your shell)
textaccounts switch work

# Check status
textaccounts status

# Interactive view
textaccounts view
```

## Commands

```sh
textaccounts list                        # show all profiles
textaccounts status                      # active profile + sync state
textaccounts adopt <name> <path>         # register an existing dir
textaccounts create <name>               # snapshot current config dir
textaccounts create <name> --worker \
  --from <parent>                        # auth-only copy for parallel work
textaccounts switch <name>               # switch profile (sets CLAUDE_CONFIG_DIR)
textaccounts show <name>                 # print shell command without executing
textaccounts rename <old> <new>          # rename a profile
textaccounts alias <profile> <alias>     # add a shorthand alias
textaccounts view                        # interactive profile view
textaccounts install [--shell fish]      # install shell integration
```

## Interactive view

`textaccounts view` provides a Textual TUI for managing profiles:

| Key | Action |
|-----|--------|
| `s` | Switch to selected profile |
| `a` | Adopt a new directory |
| `r` | Rename selected profile |
| `l` | Edit aliases |
| `q` | Quit |

Auto-discovers unregistered `~/.claude*/` directories and shows them as adoption suggestions.

## Config

Profiles are stored in `~/.textaccounts/profiles.yaml`:

```yaml
version: '1.0'
active: work

profiles:
  work:
    path: /Users/you/.claude-work
    email: yo***@company.com
    adopted: 2026-04-12T10:00:00Z
    worker: false
  personal:
    path: /Users/you/.claude-personal
    email: y***@gmail.com
    adopted: 2026-04-12T10:00:00Z
    worker: false
    aliases:
      - p

defaults:
  profiles_dir: ~/.textaccounts/profiles
```

New profiles created with `textaccounts create` go into `~/.textaccounts/profiles/`.

## How it works

`textaccounts switch` sets `CLAUDE_CONFIG_DIR` in your shell via a fish function that evals the output of `textaccounts show`. A Python subprocess can't modify the parent shell's environment directly — the fish function bridges that gap.

Claude Code reads `CLAUDE_CONFIG_DIR` natively. No patches, no wrappers around `claude` itself.

## Roadmap

- [ ] Publish to PyPI (under Paperworlds org — account TBD)
- [ ] Upgrade to Python 3.13
- [ ] `d` key in view to remove/unregister a profile
- [ ] Bash/zsh shell integration (currently fish only)

> [!NOTE]
> **Part of Paperworlds**
>
> textaccounts is part of [Paperworlds](https://github.com/Paperworlds) — an open org building tools and games around AI agents and text interfaces.

## License

MIT
