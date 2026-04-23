---
slug: textaccounts-api
owner: textaccounts
status: draft
version: 0.1.0
consumers:
- textsessions
---
# textaccounts public Python API

## Summary

`textaccounts.api` is the stable import surface for tools that want to
discover, activate, or query Claude Code profiles managed by textaccounts.
Consumers import from this module only — never from `textaccounts.core` or
`textaccounts.config` directly.

## Motivation

Multiple repos (textsessions, future clients) need to switch profiles, resolve
profile metadata, and query descriptions without duplicating YAML-parsing logic
or coupling to textaccounts internals. A versioned, opt-in import contract lets
textaccounts evolve its internals without breaking consumers.

## Interface

All symbols live in `textaccounts.api`. Import with a try/except so the tool
degrades gracefully when textaccounts is not installed.

```python
try:
    from textaccounts.api import (
        available,
        list_profiles,
        active_profile,
        profile_dir,
        env_for_profile,
        profile_description,
    )
except ImportError:
    pass  # provide no-op fallbacks
```

### Functions

```python
def available() -> bool:
    """True if textaccounts is configured (profiles.yaml exists with ≥1 profile)."""

def list_profiles() -> list[str]:
    """Return sorted canonical profile names."""

def active_profile() -> str | None:
    """Return the name of the currently active profile, or None."""

def profile_dir(name: str) -> Path | None:
    """Return the config directory Path for a profile, or None if not found."""

def env_for_profile(name: str) -> dict[str, str]:
    """Return env vars to set to activate a profile.

    Returns {"CLAUDE_CONFIG_DIR": "<path>"} for a real profile.
    Returns {} for "default" (meaning: unset any override).
    Raises ValueError if the profile is not found.
    """

def profile_description(name: str) -> str:
    """Return the free-text description for a profile, or "" if not set.

    Returns "" for "default" or unknown profiles — never raises.
    """
```

## Conformance

A conforming consumer MUST:

1. Import only from `textaccounts.api`, never from `textaccounts.core` or
   `textaccounts.config`.
2. Wrap the import in try/except ImportError and provide no-op fallbacks so
   the tool works without textaccounts installed.
3. Mark each call-site with `# SPEC: textaccounts-api`.
4. Declare conformance in `docs/SPECS.yaml` (see example below).

### Consumer manifest (`docs/SPECS.yaml`)

```yaml
follows:
  - slug: textaccounts-api
    pinned_version: "0.1.0"
    implemented_in:
      - src/<tool>/profiles.py
```

## Open questions

- Should `env_for_profile` also unset `CLAUDE_CONFIG_DIR` when name=="default"
  (i.e. return `{"CLAUDE_CONFIG_DIR": ""}`) to let callers apply it uniformly?
  Currently it returns `{}` and callers must handle the default case separately.
