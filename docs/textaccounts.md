# textaccounts — Profile Management

**textaccounts** manages multiple Claude Code accounts with full directory isolation. Each profile is a complete, isolated config directory, preserving session history, memory, and credentials separately.

## Quick Start

### Installation

```sh
pip install textaccounts
```

### Install shell integration

```sh
textaccounts install
```

This writes a fish function and completions to `~/.config/fish/`. Open a new shell to activate.

### Register existing directories

If you already have Claude config directories (e.g. `~/.claude-work`, `~/.claude-personal`), register them without copying any data:

```sh
textaccounts adopt work ~/.claude-work
textaccounts adopt personal ~/.claude-personal
textaccounts list   # verify profiles
```

### Switch profiles

```sh
textaccounts switch work     # sets CLAUDE_CONFIG_DIR in your shell
```

## Full Documentation

For complete CLI reference, config schema, and design decisions, see the [textaccounts README](../src/textaccounts/README.md).

## Why textaccounts?

- **Full directory isolation** — Each profile is a complete `~/.claude/` directory, not just 2 files
- **Preserved sessions** — Session history, project memory, and agent state stay with their profile
- **Native adoption** — Register existing directories without moving or copying
- **Shell-native** — `textaccounts switch` sets environment variables correctly in the shell
