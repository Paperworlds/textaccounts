"""Public API for consumers (e.g. textsessions).

This module is the stable contract. External tools should import from here,
not from core or config directly.

Usage:
    try:
        from textaccounts.api import available, list_profiles, env_for_profile
    except ImportError:
        # textaccounts not installed — handle gracefully
        pass
"""

from __future__ import annotations

from pathlib import Path

import click

from textaccounts.config import load_registry
from textaccounts.core import resolve_profile


def available() -> bool:
    """True if textaccounts is configured (profiles.yaml exists with profiles)."""
    registry = load_registry()
    return len(registry.profiles) > 0


def list_profiles() -> list[str]:
    """Return canonical profile names."""
    registry = load_registry()
    return sorted(registry.profiles.keys())


def active_profile() -> str | None:
    """Return the name of the currently active profile, or None."""
    registry = load_registry()
    return registry.active


def profile_dir(name: str) -> Path | None:
    """Return the config directory path for a profile, or None if not found."""
    registry = load_registry()
    try:
        canonical = resolve_profile(name, registry)
    except click.UsageError:
        return None
    return registry.profiles[canonical].path


def profile_description(name: str) -> str:
    """Return the description for a profile, or empty string if not found."""
    if name == "default":
        return ""
    registry = load_registry()
    try:
        canonical = resolve_profile(name, registry)
    except click.UsageError:
        return ""
    return registry.profiles[canonical].description


def get_profile_lineage(name: str) -> dict | None:
    """Return lineage metadata for a profile, or None if the name is unknown.

    Keys: shallow (bool), parent (str | None), ephemeral (bool), owner (str).
    Read-only; consumers can use this to surface lineage in UIs without
    importing from ``textaccounts.core`` or ``textaccounts.config``.

    Added in textaccounts-api v0.2.0.
    """
    if name == "default":
        return None
    registry = load_registry()
    try:
        canonical = resolve_profile(name, registry)
    except click.UsageError:
        return None
    p = registry.profiles[canonical]
    return {
        "shallow": p.shallow,
        "parent": p.parent,
        "ephemeral": p.ephemeral,
        "owner": p.owner,
    }


def env_for_profile(name: str) -> dict[str, str]:
    """Return env vars that should be set to activate a profile.

    Returns a dict (e.g. {"CLAUDE_CONFIG_DIR": "/path/to/dir"}).
    Returns empty dict if the profile is "default" (meaning: unset any override).
    Raises ValueError if profile not found.
    """
    if name == "default":
        return {}

    registry = load_registry()
    try:
        canonical = resolve_profile(name, registry)
    except click.UsageError:
        raise ValueError(f"Profile '{name}' not found.") from None

    profile = registry.profiles[canonical]
    return {"CLAUDE_CONFIG_DIR": str(profile.path)}
