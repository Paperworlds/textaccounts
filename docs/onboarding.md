# textaccounts — Onboarding

## Prerequisites

Install textaccounts in editable mode (from the textsessions repo):

```sh
uv pip install -e src/textaccounts
```

Then install shell integration:

```sh
textaccounts install
```

This writes a fish function and completions to `~/.config/fish/`. Open a new
shell (or `source ~/.config/fish/functions/textaccounts.fish`) to activate.

## Interactive onboarding (recommended)

```sh
textaccounts view
```

The view auto-discovers any `~/.claude*/` directories with a valid `.claude.json`.
Unregistered directories appear as dimmed `+` rows.

1. Arrow to a suggestion row and press **a** — the adopt modal pre-fills name and path
2. Confirm with Enter or click Adopt
3. Repeat for each directory
4. Press **s** on a profile to switch to it
5. Press **l** to add aliases (e.g. `w` for `work`)
6. Press **r** to rename a profile
7. Press **q** to quit

## CLI onboarding

If you prefer the command line:

```sh
textaccounts adopt work ~/.claude-work
textaccounts adopt personal ~/.claude-personal
textaccounts list          # verify
textaccounts switch work   # sets CLAUDE_CONFIG_DIR in your shell
```

## Switching profiles

```sh
textaccounts switch work       # sets CLAUDE_CONFIG_DIR
textaccounts switch default    # unsets CLAUDE_CONFIG_DIR (back to ~/.claude)
textaccounts status            # shows active profile + sync state
textaccounts list              # table of all profiles
```

## Aliases

Add short aliases so you can switch faster:

```sh
textaccounts alias work w
textaccounts switch w          # same as: textaccounts switch work
```

## What happens under the hood

- **No data is moved or copied.** `adopt` registers a pointer to your existing directory.
- Profiles are stored in `~/.textaccounts/profiles.yaml`.
- New profiles created with `textaccounts create` go into `~/.textaccounts/profiles/`.
- Switching sets `CLAUDE_CONFIG_DIR` — Claude Code reads this natively.
- The shell integration wraps `textaccounts switch` so it evals the env line in your current shell (a Python subprocess can't modify the parent shell's environment directly).
