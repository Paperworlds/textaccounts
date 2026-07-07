import json
from pathlib import Path

from textaccounts.config import ProfileRegistry


def make_claude_json(path: Path, email: str = "test@example.com") -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / ".claude.json").write_text(
        json.dumps({"oauthAccount": {"emailAddress": email}})
    )


def make_registry(tmp_path: Path) -> tuple[ProfileRegistry, Path]:
    config_path = tmp_path / "profiles.yaml"
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    registry = ProfileRegistry(profiles_dir=profiles_dir)
    return registry, config_path
