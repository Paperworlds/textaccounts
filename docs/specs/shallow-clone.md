---
slug: shallow-clone
owner: textaccounts
status: adopted
version: 0.1.0
consumers:
- textprompts
- textworkspace
adopted_at: '2026-04-27'
---
# Shallow-clone profiles + ephemeral lifecycle (gc/destroy)

## Summary

`textaccounts` exposes **shallow clones** as a primitive for spawning
disposable, isolated Claude Code config dirs derived from a parent profile.
A shallow clone copies only `.claude.json` and `settings.json` from the
parent — no `agents/`, `hooks/`, `plugins/`, `sessions/`, `projects/`, etc.

Shallow clones can be marked **ephemeral** with an optional **owner** ID.
Two lifecycle commands sweep them:

- `textaccounts gc [--max-age 7d] [--owner ID] [--dry-run]` — bulk sweep
- `textaccounts destroy NAME` — single-profile immediate kill

Both refuse to touch anything not flagged `ephemeral: true`. Every removal
is appended to `~/.local/state/textaccounts/gc.log`.

## Motivation

Orchestrators that fan out parallel Claude Code agents (e.g. a `pp persona run`
batch leader, a CI runner spawning `claude -p` workers) need cheap, isolated
config dirs:

- Auth & basic settings of the parent profile (so agents are pre-authenticated)
- Independent session/project state (so workers don't collide on shared files)
- Discardable after the run (so the registry doesn't accumulate cruft)

Existing primitives didn't fit:

- `--clone-from` (deep clone) carries `agents/`, `hooks/`, `plugins/` and
  symlinks. Useful for *long-lived* derivative profiles, overkill for
  ephemeral workers.
- The legacy `--worker` flag did the right copying but had no lifecycle
  story — orchestrators had to manually `rm -rf` profiles and unregister
  them, racing with the human user.

This spec formalises shallow clones + ephemeral marker + GC as the supported
shape, replacing `--worker`.

## Interface

### CLI

```
textaccounts create NAME --shallow --from PARENT
                          [--ephemeral] [--owner ID]
                          [--clone-from SRC]   # mutually exclusive with --shallow

textaccounts gc [--max-age <N>d] [--owner ID] [--dry-run]
textaccounts destroy NAME
```

- `--owner` implies `--ephemeral`.
- `--shallow` and `--clone-from` are mutually exclusive.
- `--ephemeral` may be combined with `--clone-from` (deep clone, but
  marked for sweep).
- `--worker` is a hidden, deprecated alias for `--shallow`. It emits a
  one-line warning to stderr; the YAML key was renamed `worker` → `shallow`
  with read-time backward compat.

### Profile manifest (`~/.textaccounts/profiles.yaml`)

```yaml
profiles:
  bot-1:
    path: /Users/you/.textaccounts/profiles/bot-1
    parent: work
    shallow: true        # canonical (was: worker:)
    ephemeral: true      # only present when true
    owner: run-42        # only present when non-empty
    adopted: '2026-04-26T17:30:00Z'   # creation timestamp
```

`worker:` is accepted on read for older files; new writes use `shallow:`.

### Python API (consumer surface)

```python
# textaccounts.core
def create_shallow(
    name: str,
    parent_name: str,
    registry: ProfileRegistry,
    ephemeral: bool = False,
    owner: str = "",
) -> Profile: ...

def destroy(name: str, registry: ProfileRegistry) -> Profile:
    """Remove a single ephemeral profile. Raises click.UsageError if not ephemeral."""

def gc(
    registry: ProfileRegistry,
    max_age_days: int = 7,
    owner: str | None = None,
    dry_run: bool = False,
) -> list[Profile]:
    """Return profiles that were (or would be) removed."""
```

The deprecated `create_worker(name, parent_name, registry)` remains as a
thin alias to `create_shallow`.

### Audit log

Path: `~/.local/state/textaccounts/gc.log`
Format: tab-separated, append-only, one row per action:

```
<iso-timestamp>\t<action>\t<name>\towner=<id|->\tadopted=<iso|->\treason=<text>
```

Where `<action>` is one of: `gc`, `gc-dry-run`, `destroy`.

## Conformance

A conforming **orchestrator consumer** MUST:

1. Always pass `--owner <stable-run-id>` (or `owner=` to `create_shallow`)
   so failed runs can be cleaned up by run-id without TTL.
2. Call `textaccounts gc --owner <run-id>` (or `core.gc(owner=<run-id>)`)
   on successful run completion. Stale runs are caught by the human-driven
   weekly `textaccounts gc`.
3. Mark each call-site with `# SPEC: shallow-clone`.
4. Declare conformance in `docs/SPECS.yaml`.

A conforming consumer MUST NOT:

- Manually `rm -rf` a profile dir without going through `destroy`/`gc`
  (skips the audit log + registry update, leaving stale entries).
- Mark a profile `ephemeral: true` without an `owner` if the run might be
  longer than 7d, since the default human GC will sweep it.

## Caveats

- **Auth share is partial.** Claude Code v2.1.56+ keys keychain entries by
  `sha256(CLAUDE_CONFIG_DIR)[:8]`, so a shallow clone gets a *new*
  keychain entry. The clone inherits OAuth tokens embedded in the copied
  `.claude.json` and works until next refresh, after which it diverges.
  Long-lived clones may need a separate `/login`.
- **Registry race.** `gc` and `destroy` mutate `profiles.yaml` non-atomically
  with respect to a concurrent shell-side `textaccounts switch`. Out of scope
  for this spec; assume orchestrator runs and human shells don't fight.

## Out of scope

- tmpfs / in-memory profile dirs (filesystem-only).
- Auto-promote ephemeral → permanent (use `rename` or copy out before next
  `gc`).
- Auto-trigger of `gc` on process exit (lifecycle stays at the orchestration
  layer; textaccounts is just the storage).
- Per-profile keychain credential mirroring (Claude Code owns that;
  see `verify-claude-config-dir-keychain-isolation-across-textaccou`
  thread).

## Open questions

- **Owner field shape.** Currently free-form `str`. Could later become
  structured `kind:id` (e.g. `textprompts:run-42`) for richer filtering.
  No breaking change required — old free-form values stay valid.
- **Default TTL configurability.** Spec says 7d default; not yet wired to
  `~/.config/textaccounts/config.toml`. CLI `--max-age` overrides anyway.
