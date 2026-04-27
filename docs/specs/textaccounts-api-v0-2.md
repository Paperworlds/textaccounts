---
slug: textaccounts-api-v0-2
owner: textaccounts
status: adopted
version: 0.2.0
consumers:
- textsessions
- textworkspace
supersedes: textaccounts-api
adopted_at: '2026-04-27'
---
# textaccounts public Python API (v0.2)

## Summary

`textaccounts.api` is the stable import surface for tools that integrate with
textaccounts. v0.2.0 is an additive bump: the v0.1.0 surface is preserved
verbatim, plus one new function (`get_profile_lineage`) that exposes
shallow-clone lineage metadata so consumers can render it without dropping
into `textaccounts.core` / `.config`.

## Motivation

`shallow-clone` (now adopted) introduced four new fields on each profile —
`shallow`, `parent`, `ephemeral`, `owner` — that consumers like textsessions
need to surface in UIs ("[shallow ← personal] [ephemeral, owner=…]"). The
v0.1.0 contract didn't expose them, forcing consumers either to (a) violate
the api-only rule by importing `textaccounts.core`, or (b) parse
`profiles.yaml` themselves. v0.2.0 closes that gap with a single read-only
function.

This is a strictly additive change — every v0.1.0 consumer keeps working
unchanged.

## Interface

All symbols live in `textaccounts.api`. Unchanged from v0.1.0:

```python
def available() -> bool: ...
def list_profiles() -> list[str]: ...
def active_profile() -> str | None: ...
def profile_dir(name: str) -> Path | None: ...
def env_for_profile(name: str) -> dict[str, str]: ...
def profile_description(name: str) -> str: ...
```

New in v0.2.0:

```python
def get_profile_lineage(name: str) -> dict | None:
    """Return lineage metadata for a profile, or None if name is unknown.

    Keys: shallow (bool), parent (str | None), ephemeral (bool), owner (str).
    Read-only; surfaces shallow-clone metadata without requiring an import
    from textaccounts.core or textaccounts.config.

    Returns None for unknown names and for the special name "default".
    Aliases are resolved.
    """
```

Example:

```python
from textaccounts.api import get_profile_lineage  # SPEC: textaccounts-api-v0-2

lineage = get_profile_lineage("pp-run-42-3")
# → {"shallow": True, "parent": "work", "ephemeral": True,
#    "owner": "textprompts:run-42"}
```

## Conformance

A conforming consumer MUST:

1. Import only from `textaccounts.api`, never from `textaccounts.core` or
   `textaccounts.config`.
2. Wrap the import in try/except ImportError and provide no-op fallbacks so
   the tool works without textaccounts installed.
3. Mark each call-site with `# SPEC: textaccounts-api-v0-2`.
4. Declare conformance in `docs/SPECS.yaml` (see example below).

### Consumer manifest (`docs/SPECS.yaml`)

```yaml
follows:
  - slug: textaccounts-api-v0-2
    pinned_version: "0.2.0"
    implemented_in:
      - src/<tool>/profiles.py
```

Consumers migrating from v0.1.0: replace the slug, no signature changes
required for any v0.1.0 call site.

## Migration from v0.1.0

The supersession is non-breaking. To migrate a consumer:

1. Bump the slug in `docs/SPECS.yaml` from `textaccounts-api` to
   `textaccounts-api-v0-2`. Optionally bump `pinned_version` to `"0.2.0"`.
2. Update `# SPEC: textaccounts-api` markers to `# SPEC: textaccounts-api-v0-2`
   (or leave the old markers — both refer to the same source-code surface,
   just different spec doc versions).
3. New code can use `get_profile_lineage`; old code stays as is.

## Out of scope

- Mutation methods (creating, deleting, renaming profiles) — those go through
  the `textaccounts` CLI for proper safety checks, audit logging, and the
  shallow-clone lifecycle contract. The api stays read-only.
- Bulk lineage queries — `get_profile_lineage(name)` is per-profile by
  design. Callers iterate `list_profiles()` if they need everything.

## Open questions

- Should `get_profile_lineage` collapse the dict shape (parent=None,
  shallow=False) into `None` for non-shallow profiles, or always return a
  full record? Current choice: always return a full record so consumers can
  render uniformly without branching on None vs dict.
