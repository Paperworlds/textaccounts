from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

CONFIG_PATH = Path.home() / ".textaccounts" / "profiles.yaml"
DEFAULT_PROFILES_DIR = Path.home() / ".textaccounts" / "profiles"


@dataclass
class Profile:
    name: str
    path: Path
    email: str = ""
    adopted: str = ""
    worker: bool = False
    parent: Optional[str] = None
    aliases: list[str] = field(default_factory=list)


@dataclass
class ProfileRegistry:
    active: Optional[str] = None
    profiles: dict[str, Profile] = field(default_factory=dict)
    profiles_dir: Path = field(default_factory=lambda: DEFAULT_PROFILES_DIR)


def load_registry(config_path: Path = CONFIG_PATH) -> ProfileRegistry:
    if not config_path.exists():
        return ProfileRegistry()

    with config_path.open() as f:
        data = yaml.safe_load(f) or {}

    profiles_dir = DEFAULT_PROFILES_DIR
    defaults = data.get("defaults", {})
    if "profiles_dir" in defaults:
        profiles_dir = Path(defaults["profiles_dir"]).expanduser()

    profiles: dict[str, Profile] = {}
    for name, entry in (data.get("profiles") or {}).items():
        if not isinstance(entry, dict):
            raise ValueError(
                f"profiles.yaml: profile '{name}' must be a mapping, got {type(entry).__name__}"
            )
        if "path" not in entry:
            raise ValueError(
                f"profiles.yaml: profile '{name}' is missing required key 'path'"
            )
        profiles[name] = Profile(
            name=name,
            path=Path(entry["path"]),
            email=entry.get("email", ""),
            adopted=entry.get("adopted", ""),
            worker=entry.get("worker", False),
            parent=entry.get("parent"),
            aliases=entry.get("aliases", []),
        )

    return ProfileRegistry(
        active=data.get("active"),
        profiles=profiles,
        profiles_dir=profiles_dir,
    )


def save_registry(registry: ProfileRegistry, config_path: Path = CONFIG_PATH) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)

    profiles_data: dict = {}
    for name, profile in registry.profiles.items():
        entry: dict = {"path": str(profile.path)}
        if profile.email:
            entry["email"] = profile.email
        if profile.adopted:
            entry["adopted"] = profile.adopted
        entry["worker"] = profile.worker
        if profile.parent is not None:
            entry["parent"] = profile.parent
        if profile.aliases:
            entry["aliases"] = profile.aliases
        profiles_data[name] = entry

    data: dict = {"version": "1.0"}
    if registry.active is not None:
        data["active"] = registry.active
    data["profiles"] = profiles_data
    data["defaults"] = {"profiles_dir": str(registry.profiles_dir)}

    with config_path.open("w") as f:
        yaml.safe_dump(data, f, default_flow_style=False, allow_unicode=True)


def extract_email(config_dir: Path) -> str:
    claude_json = config_dir / ".claude.json"
    if not claude_json.exists():
        return ""

    try:
        with claude_json.open() as f:
            data = json.load(f)
        email: str = data.get("oauthAccount", {}).get("emailAddress", "")
    except (json.JSONDecodeError, OSError):
        return ""

    if not email or "@" not in email:
        return email

    local, domain = email.split("@", 1)
    if len(local) <= 3:
        masked_local = local
    else:
        masked_local = local[:3] + "***"

    return f"{masked_local}@{domain}"
