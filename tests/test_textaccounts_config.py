import json
from pathlib import Path

import pytest

from textaccounts.config import (
    Profile,
    ProfileRegistry,
    extract_email,
    load_registry,
    save_registry,
)


def test_registry_round_trip(tmp_path):
    config_path = tmp_path / "profiles.yaml"
    profiles_dir = tmp_path / "profiles"

    registry = ProfileRegistry(
        active="work",
        profiles={
            "work": Profile(
                name="work",
                path=tmp_path / "claude-work",
                email="pau***@example.com",
                adopted="2026-04-12T10:00:00Z",
                shallow=False,
                description="Main work account",
            ),
            "work-worker": Profile(
                name="work-worker",
                path=tmp_path / "claude-profiles" / "work-worker",
                email="pau***@example.com",
                shallow=True,
                parent="work",
                ephemeral=True,
                owner="run-42",
            ),
        },
        profiles_dir=profiles_dir,
    )

    save_registry(registry, config_path=config_path)
    loaded = load_registry(config_path=config_path)

    assert loaded.active == "work"
    assert set(loaded.profiles) == {"work", "work-worker"}

    work = loaded.profiles["work"]
    assert work.path == tmp_path / "claude-work"
    assert work.email == "pau***@example.com"
    assert work.adopted == "2026-04-12T10:00:00Z"
    assert work.shallow is False
    assert work.parent is None
    assert work.description == "Main work account"
    assert work.ephemeral is False
    assert work.owner == ""

    worker = loaded.profiles["work-worker"]
    assert worker.shallow is True
    assert worker.parent == "work"
    assert worker.description == ""
    assert worker.ephemeral is True
    assert worker.owner == "run-42"

    assert loaded.profiles_dir == profiles_dir


def test_load_registry_accepts_legacy_worker_key(tmp_path):
    """Older profiles.yaml files used `worker:` instead of `shallow:`."""
    config_path = tmp_path / "profiles.yaml"
    config_path.write_text(
        "profiles:\n"
        "  bot:\n"
        "    path: /tmp/bot\n"
        "    worker: true\n"
        "    parent: main\n"
    )
    loaded = load_registry(config_path=config_path)
    assert loaded.profiles["bot"].shallow is True


def test_load_missing_file_returns_empty(tmp_path):
    config_path = tmp_path / "nonexistent.yaml"
    registry = load_registry(config_path=config_path)

    assert registry.active is None
    assert registry.profiles == {}


def test_load_registry_raises_on_missing_path_key(tmp_path):
    config_path = tmp_path / "profiles.yaml"
    config_path.write_text("profiles:\n  work:\n    email: foo@example.com\n")

    with pytest.raises(ValueError, match="missing required key 'path'"):
        load_registry(config_path=config_path)


def test_load_registry_raises_on_non_dict_entry(tmp_path):
    config_path = tmp_path / "profiles.yaml"
    config_path.write_text("profiles:\n  work: not-a-mapping\n")

    with pytest.raises(ValueError, match="must be a mapping"):
        load_registry(config_path=config_path)


def test_extract_email_masks_correctly(tmp_path):
    claude_json = tmp_path / ".claude.json"
    claude_json.write_text(
        json.dumps({"oauthAccount": {"emailAddress": "paolo.d@example.com"}})
    )

    result = extract_email(tmp_path)
    assert result == "pao***@example.com"


def test_extract_email_short_local_not_masked(tmp_path):
    claude_json = tmp_path / ".claude.json"
    claude_json.write_text(
        json.dumps({"oauthAccount": {"emailAddress": "ab@example.com"}})
    )

    result = extract_email(tmp_path)
    assert result == "ab@example.com"


def test_extract_email_missing_file_returns_empty(tmp_path):
    result = extract_email(tmp_path)
    assert result == ""


def test_extract_email_missing_field_returns_empty(tmp_path):
    claude_json = tmp_path / ".claude.json"
    claude_json.write_text(json.dumps({"someOtherKey": {}}))

    result = extract_email(tmp_path)
    assert result == ""
