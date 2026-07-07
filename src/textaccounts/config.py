from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

CONFIG_PATH = Path.home() / ".local" / "paperworlds" / "textaccounts" / "profiles.yaml"
DEFAULT_PROFILES_DIR = Path.home() / ".local" / "paperworlds" / "textaccounts" / "profiles"


SIGNING_MODES = ("unsigned", "gpg-sw", "gpg-hw")


@dataclass
class SigningConfig:
    mode: str = "unsigned"     # one of SIGNING_MODES
    key: str = ""              # GPG key id / fingerprint
    name: str = ""             # git user.name
    email: str = ""            # git user.email

    @classmethod
    def from_dict(cls, profile_name: str, s: dict) -> "SigningConfig":
        mode = s.get("mode", "unsigned")
        if mode not in SIGNING_MODES:
            raise ValueError(
                f"profiles.yaml: profile '{profile_name}' signing.mode={mode!r} not in {SIGNING_MODES}"
            )
        return cls(mode=mode, key=s.get("key", ""), name=s.get("name", ""), email=s.get("email", ""))

    def to_dict(self) -> dict:
        entry: dict = {"mode": self.mode}
        if self.key:
            entry["key"] = self.key
        if self.name:
            entry["name"] = self.name
        if self.email:
            entry["email"] = self.email
        return entry


@dataclass
class Profile:
    name: str
    path: Path
    email: str = ""
    adopted: str = ""
    shallow: bool = False
    parent: Optional[str] = None
    aliases: list[str] = field(default_factory=list)
    description: str = ""
    ephemeral: bool = False
    owner: str = ""
    auth_method: str = "oauth"
    signing: Optional[SigningConfig] = None

    @classmethod
    def from_dict(cls, name: str, entry: dict) -> "Profile":
        if not isinstance(entry, dict):
            raise ValueError(
                f"profiles.yaml: profile '{name}' must be a mapping, got {type(entry).__name__}"
            )
        if "path" not in entry:
            raise ValueError(
                f"profiles.yaml: profile '{name}' is missing required key 'path'"
            )
        shallow = entry.get("shallow", False)
        signing = (
            SigningConfig.from_dict(name, entry["signing"])
            if isinstance(entry.get("signing"), dict)
            else None
        )
        return cls(
            name=name,
            path=Path(entry["path"]),
            email=entry.get("email", ""),
            adopted=entry.get("adopted", ""),
            shallow=shallow,
            parent=entry.get("parent"),
            aliases=entry.get("aliases", []),
            description=entry.get("description", ""),
            ephemeral=entry.get("ephemeral", False),
            owner=entry.get("owner", ""),
            auth_method=entry.get("auth_method", "oauth"),
            signing=signing,
        )

    def to_dict(self) -> dict:
        entry: dict = {"path": str(self.path)}
        if self.email:
            entry["email"] = self.email
        if self.adopted:
            entry["adopted"] = self.adopted
        entry["shallow"] = self.shallow
        if self.parent is not None:
            entry["parent"] = self.parent
        if self.aliases:
            entry["aliases"] = self.aliases
        if self.description:
            entry["description"] = self.description
        if self.ephemeral:
            entry["ephemeral"] = True
        if self.owner:
            entry["owner"] = self.owner
        if self.auth_method != "oauth":
            entry["auth_method"] = self.auth_method
        if self.signing is not None:
            entry["signing"] = self.signing.to_dict()
        return entry


@dataclass
class ProfileRegistry:
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
        profiles[name] = Profile.from_dict(name, entry)

    # `active` key in the YAML (legacy) is ignored — active state is now
    # derived per-shell from $CLAUDE_CONFIG_DIR. Tolerated on load for
    # backward compat; never written on save.
    return ProfileRegistry(
        profiles=profiles,
        profiles_dir=profiles_dir,
    )


def save_registry(registry: ProfileRegistry, config_path: Path = CONFIG_PATH) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)

    profiles_data: dict = {name: profile.to_dict() for name, profile in registry.profiles.items()}

    data: dict = {"version": "1.0"}
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
