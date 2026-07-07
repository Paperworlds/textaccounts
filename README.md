# textaccounts

Manage multiple Claude Code accounts with full directory isolation. Each profile is a complete `~/.claude/` config directory — sessions, memory, settings, and auth stay separate.

## Why?

Claude Code stores everything in a single directory tree (`~/.claude/`). If you use multiple accounts (work + personal), you need separate directories. `textaccounts` registers and switches between them by setting `CLAUDE_CONFIG_DIR`.

> [!IMPORTANT]
> **Requires Claude Code ≥ v2.1.56** for full OAuth isolation. Earlier
> versions stored every profile's tokens under the same macOS keychain entry
> (`Claude Code-credentials`), causing them to overwrite each other (see
> [issue #20553](https://github.com/anthropics/claude-code/issues/20553)).
> v2.1.56+ namespaces credentials per-profile using
> `Claude Code-credentials-<sha256(CLAUDE_CONFIG_DIR)[:8]>`. Run
> `textaccounts doctor` to verify your local version.

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
textaccounts create <name> --shallow \
  --from <parent>                        # shallow clone — copy only .claude.json + settings.json
textaccounts create <name> \
  --clone-from <src>                     # deep clone — auth + settings + agents/hooks/plugins,
                                         # strip state (sessions/projects/history/caches)
textaccounts create <name> --shallow \
  --from <parent> --ephemeral \
  [--owner <run-id>]                     # mark for sweep by `gc` / `destroy`
textaccounts gc [--max-age 7d] \
  [--owner <run-id>] [--dry-run]         # sweep ephemeral profiles older than max-age
textaccounts destroy <name>              # remove a single ephemeral profile
textaccounts adopt-token <name> \
  [--path <dir>]                         # register a token-auth profile (CLAUDE_CODE_OAUTH_TOKEN)
textaccounts switch <name>               # switch profile (sets CLAUDE_CONFIG_DIR)
textaccounts show <name>                 # print shell command without executing
textaccounts rename <old> <new>          # rename a profile
textaccounts alias <profile> <alias>     # add a shorthand alias
textaccounts describe <name> [text]      # set/clear a per-profile description (omit text to clear)
textaccounts desc                        # print current profile's description (for statuslines)
textaccounts view                        # interactive profile view
textaccounts doctor                      # check stale paths + Claude Code version
textaccounts install [--shell fish]      # install shell integration
textaccounts export [output.zip]         # export registry + settings to encrypted zip
textaccounts import <backup.zip>         # import profiles from an export zip
```

## Export and import

`textaccounts export` creates a password-protected AES-256 zip containing your
`profiles.yaml` registry and each profile's `.claude.json` and `settings.json`.
A `.sha256` hash file is written alongside for integrity verification.
**Auth tokens are not included** — they live exclusively in the macOS Keychain
and are never written to disk by textaccounts.

```sh
# Export (password prompted)
textaccounts export
# → textaccounts-20260514.zip
# → textaccounts-20260514.zip.sha256

# Export to a specific path
textaccounts export ~/backups/ta-backup.zip

# Import on another machine (password prompted, skips existing profiles)
textaccounts import ta-backup.zip

# Import and overwrite any conflicting profiles
textaccounts import ta-backup.zip --overwrite
```

After importing, run `textaccounts switch <name>` for each profile and
re-authenticate via `/login` — Keychain tokens are machine-local.

## Shallow clones and ephemeral lifecycle

`--shallow --from <parent>` creates a minimal copy: just `.claude.json` and
`settings.json`, no `agents/`, `hooks/`, `plugins/`, `sessions/`, etc. Useful
when an orchestrator (e.g. a parallel-agents batch leader) needs many isolated
worker profiles cheaply. `--clone-from <src>` is the deeper variant that also
copies `agents/`, `hooks/`, `plugins/`, and symlinks.

**Disposable runs.** Add `--ephemeral` (or `--owner <run-id>`, which implies
ephemeral) to flag the profile for cleanup:

```sh
# Orchestrator: spawn a worker for a specific run-id
textaccounts create bot-1 --shallow --from work --owner run-42

# When the run is done, sweep everything it created
textaccounts gc --owner run-42

# Or destroy a single one immediately
textaccounts destroy bot-1
```

`gc` defaults to `--max-age 7d` and ignores anything not flagged
`ephemeral: true` — so it can't accidentally remove your real profiles. Every
removal is appended to `~/.local/state/textaccounts/gc.log` for auditing.

> [!NOTE]
> **Auth share via Keychain mirroring (v0.1.1+).** Claude Code v2.1.56+ stores
> OAuth tokens exclusively in the macOS Keychain, keyed by
> `sha256(CLAUDE_CONFIG_DIR)[:8]`. A shallow clone gets a new config dir and
> therefore a new key. `textaccounts create --shallow` automatically mirrors
> the parent's Keychain entry to the clone at creation time; `gc` and `destroy`
> clean it up. If the parent has no Keychain entry, a warning is emitted and
> the clone will need `/login`.

> [!NOTE]
> `--worker` is a deprecated alias for `--shallow`. It still works but emits
> a one-line warning. The on-disk YAML key was renamed `worker` → `shallow`
> with read-time backward compat.

## Token-auth profiles

Some Claude accounts use a long-lived `CLAUDE_CODE_OAUTH_TOKEN` (service-account style) instead of the interactive OAuth flow. `textaccounts` supports these as first-class profiles — the token is stored in the macOS Keychain and injected automatically at switch time.

```sh
# Register a token-auth profile (you will be prompted for the token, no shell history)
textaccounts adopt-token my-service-account

# Optionally specify a config dir (created if absent)
textaccounts adopt-token my-service-account --path ~/.claude-svc

# Switch — injects both CLAUDE_CONFIG_DIR and CLAUDE_CODE_OAUTH_TOKEN into your shell
textaccounts switch my-service-account

# The profile shows [token-auth] in the list
textaccounts list
```

The config dir (`~/.claude-<name>` by default) still holds settings, sessions, and MCP config — only the auth part changes. Tooling that calls `env_for_profile("my-service-account")` gets both `CLAUDE_CONFIG_DIR` and `CLAUDE_CODE_OAUTH_TOKEN` automatically.

To rotate the token, run `adopt-token` again with a new value (coming in a future release; for now, delete and re-adopt the profile).

> [!IMPORTANT]
> **Non-interactive use only.** `CLAUDE_CODE_OAUTH_TOKEN` is honoured by Claude Code only for non-interactive invocations (`claude --print` / `claude -p`). Interactive terminal sessions (`claude` with no flags, `ts new`) ignore this env var and check the macOS Keychain instead — if no Keychain entry exists they show the login screen. Token-auth profiles are designed for agent/scripted workloads (textlives, textprompts, `claude -p` pipelines), not for shell switching via `ta switch`.

> [!NOTE]
> Token-auth profiles are macOS-only in v0.1.0 (Keychain is required). Linux support is planned.

## Per-profile descriptions

Each profile can carry a free-text description (a one-liner like `"day job"` or
`"hobby + paperworlds"`). It shows up:

- In the interactive view bottom bar when a profile is highlighted (`n` to edit)
- In your Claude Code statusline via `textaccounts desc`, which resolves the
  description for the *current* `CLAUDE_CONFIG_DIR` — so subprocesses launched
  by tools like `textsessions` show the right description automatically

Wire it into your statusline script:

```bash
ta_desc=$(textaccounts desc 2>/dev/null)
[ -n "$ta_desc" ] && parts+=("$ta_desc")
```

## Interactive view

`textaccounts view` provides a Textual TUI for managing profiles:

| Key | Action |
|-----|--------|
| `s` | Switch to selected profile |
| `a` | Adopt a new directory |
| `r` | Rename selected profile |
| `l` | Edit aliases |
| `n` | Edit description (shown in bottom bar) |
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
    description: day job
  personal:
    path: /Users/you/.claude-personal
    email: y***@gmail.com
    adopted: 2026-04-12T10:00:00Z
    worker: false
    description: hobby projects
    aliases:
      - p

defaults:
  profiles_dir: ~/.textaccounts/profiles
```

New profiles created with `textaccounts create` go into `~/.textaccounts/profiles/`.

## How it works

`textaccounts switch` sets `CLAUDE_CONFIG_DIR` in your shell via a fish function that evals the output of `textaccounts show`. A Python subprocess can't modify the parent shell's environment directly — the fish function bridges that gap.

Claude Code reads `CLAUDE_CONFIG_DIR` natively. No patches, no wrappers around `claude` itself.

## Public API

`textaccounts.api` is the stable import surface for tools that integrate with
textaccounts (see `textsessions` for an example consumer). Functions:
`available`, `list_profiles`, `active_profile`, `profile_dir`, `env_for_profile`,
`profile_description`. Full contract: [docs/specs/textaccounts-api.md](docs/specs/textaccounts-api.md).

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
