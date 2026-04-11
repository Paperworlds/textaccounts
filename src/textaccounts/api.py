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
    except Exception:
        return None
    return registry.profiles[canonical].path


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
    except Exception:
        raise ValueError(f"Profile '{name}' not found.")

    profile = registry.profiles[canonical]
    return {"CLAUDE_CONFIG_DIR": str(profile.path)}
