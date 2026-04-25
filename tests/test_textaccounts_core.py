import pytest
import click

from textaccounts.config import ProfileRegistry, Profile, load_registry
from textaccounts.core import (
    adopt,
    clone_profile,
    create_from_current,
    create_worker,
    rename,
    show,
    list_profiles,
)
from conftest import make_claude_json, make_registry


# --- adopt ---

def test_adopt_registers_profile_and_extracts_email(tmp_path, monkeypatch):
    registry, config_path = make_registry(tmp_path)

    source = tmp_path / "claude-work"
    source.mkdir()
    make_claude_json(source, "paolo@example.com")

    profile = adopt("work", source, registry)

    assert profile.name == "work"
    assert profile.path == source.resolve()
    assert "pao***@example.com" == profile.email
    assert "work" in registry.profiles


def test_adopt_rejects_dir_without_claude_json(tmp_path):
    registry, _ = make_registry(tmp_path)

    source = tmp_path / "empty-dir"
    source.mkdir()

    with pytest.raises(click.UsageError, match="missing .claude.json"):
        adopt("work", source, registry)


def test_adopt_rejects_duplicate_name(tmp_path):
    registry, _ = make_registry(tmp_path)

    source = tmp_path / "claude-work"
    source.mkdir()
    make_claude_json(source)

    adopt("work", source, registry)

    with pytest.raises(click.UsageError, match="already exists"):
        adopt("work", source, registry)


# --- create_from_current ---

def test_create_from_current_copies_full_directory(tmp_path, monkeypatch):
    registry, _ = make_registry(tmp_path)

    source = tmp_path / "current-claude"
    source.mkdir()
    make_claude_json(source)
    (source / "settings.json").write_text('{"theme": "dark"}')
    (source / "extra.txt").write_text("extra data")

    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(source))

    profile = create_from_current("snap", registry)

    dest = registry.profiles_dir / "snap"
    assert dest.is_dir()
    assert (dest / ".claude.json").exists()
    assert (dest / "settings.json").exists()
    assert (dest / "extra.txt").exists()
    assert profile.name == "snap"


# --- create_worker ---

def test_create_worker_copies_only_claude_json_and_settings(tmp_path):
    registry, _ = make_registry(tmp_path)

    parent_dir = tmp_path / "claude-work"
    parent_dir.mkdir()
    make_claude_json(parent_dir)
    (parent_dir / "settings.json").write_text('{"key": "val"}')
    (parent_dir / "extra.txt").write_text("should not copy")

    registry.profiles["work"] = Profile(
        name="work", path=parent_dir, email="pao***@example.com"
    )

    profile = create_worker("work-bot", "work", registry)

    dest = registry.profiles_dir / "work-bot"
    assert (dest / ".claude.json").exists()
    assert (dest / "settings.json").exists()
    assert not (dest / "extra.txt").exists()
    assert profile.worker is True
    assert profile.parent == "work"


# --- show ---

def test_show_returns_fish_env_line(tmp_path):
    registry, _ = make_registry(tmp_path)

    p = tmp_path / "claude-work"
    p.mkdir()
    make_claude_json(p)
    registry.profiles["work"] = Profile(name="work", path=p, email="")

    line = show("work", registry)
    assert line == f"set -gx CLAUDE_CONFIG_DIR {p}"


def test_show_to_default_returns_unset_line(tmp_path):
    registry, _ = make_registry(tmp_path)

    line = show("default", registry)
    assert line == "set -e CLAUDE_CONFIG_DIR"


def test_show_updates_active_in_registry(tmp_path):
    registry, _ = make_registry(tmp_path)

    p = tmp_path / "claude-work"
    p.mkdir()
    make_claude_json(p)
    registry.profiles["work"] = Profile(name="work", path=p, email="")

    show("work", registry)
    assert registry.active == "work"


# --- clone_profile ---

def test_clone_strips_state_keeps_auth_and_setup(tmp_path):
    import json

    registry, _ = make_registry(tmp_path)

    src = tmp_path / "claude-work"
    src.mkdir()
    # Rich .claude.json with both auth fields and lots of state to strip
    (src / ".claude.json").write_text(json.dumps({
        "oauthAccount": {"emailAddress": "paolo@example.com"},
        "userID": "abc",
        "anonymousId": "xyz",
        "theme": "dark",
        "projects": {"/some/path": {"history": ["secret"]}},
        "mcpServers": {"sentry": {"url": "..."}},
        "numStartups": 42,
        "tipsHistory": ["tip1", "tip2"],
    }))
    (src / "settings.json").write_text('{"key": "val"}')
    (src / "agents").mkdir()
    (src / "agents" / "explorer.json").write_text("{}")
    (src / "hooks").mkdir()
    (src / "hooks" / "hook.sh").write_text("#!/bin/bash")
    # State that must NOT be copied
    (src / "history.jsonl").write_text("session1\nsession2\n")
    (src / "projects").mkdir()
    (src / "projects" / "foo").mkdir()
    (src / "sessions").mkdir()
    (src / "cache").mkdir()
    # Symlink should be preserved as a symlink
    target = tmp_path / "shared-commands"
    target.mkdir()
    (src / "commands").symlink_to(target)

    registry.profiles["work"] = Profile(name="work", path=src, email="")

    profile = clone_profile("work-clean", "work", registry)
    dest = profile.path

    # Auth/setup kept
    cleaned = json.loads((dest / ".claude.json").read_text())
    assert cleaned["oauthAccount"] == {"emailAddress": "paolo@example.com"}
    assert cleaned["userID"] == "abc"
    assert cleaned["theme"] == "dark"
    # State stripped from .claude.json
    assert "projects" not in cleaned
    assert "mcpServers" not in cleaned
    assert "numStartups" not in cleaned
    assert "tipsHistory" not in cleaned

    assert (dest / "settings.json").read_text() == '{"key": "val"}'
    assert (dest / "agents" / "explorer.json").exists()
    assert (dest / "hooks" / "hook.sh").exists()
    assert (dest / "commands").is_symlink()

    # State dirs/files NOT copied
    assert not (dest / "history.jsonl").exists()
    assert not (dest / "projects").exists()
    assert not (dest / "sessions").exists()
    assert not (dest / "cache").exists()

    assert profile.parent == "work"
    assert profile.worker is False


def test_clone_rejects_duplicate_name(tmp_path):
    registry, _ = make_registry(tmp_path)
    src = tmp_path / "claude-work"
    src.mkdir()
    make_claude_json(src)
    registry.profiles["work"] = Profile(name="work", path=src, email="")
    registry.profiles["work-clean"] = Profile(
        name="work-clean", path=tmp_path / "x", email=""
    )

    with pytest.raises(click.UsageError, match="already exists"):
        clone_profile("work-clean", "work", registry)


def test_clone_rejects_unknown_source(tmp_path):
    registry, _ = make_registry(tmp_path)
    with pytest.raises(click.UsageError, match="not found"):
        clone_profile("new", "missing", registry)


# --- rename ---

def test_rename_preserves_aliases_and_description(tmp_path):
    registry, _ = make_registry(tmp_path)

    d = tmp_path / "claude-work"
    d.mkdir()
    make_claude_json(d)
    registry.profiles["work"] = Profile(
        name="work", path=d, email="", aliases=["w"], description="day job"
    )

    renamed = rename("work", "job", registry)

    assert renamed.name == "job"
    assert renamed.aliases == ["w"]
    assert renamed.description == "day job"
    assert "job" in registry.profiles
    assert "work" not in registry.profiles


# --- list_profiles ---

def test_list_profiles_returns_all_profiles(tmp_path):
    registry, _ = make_registry(tmp_path)

    for name in ("alice", "bob"):
        d = tmp_path / f"claude-{name}"
        d.mkdir()
        make_claude_json(d)
        registry.profiles[name] = Profile(name=name, path=d, email="")

    registry.active = "alice"
    profiles = list_profiles(registry)

    names = {p["name"] for p in profiles}
    assert names == {"alice", "bob"}

    alice = next(p for p in profiles if p["name"] == "alice")
    assert alice["active"] is True

    bob = next(p for p in profiles if p["name"] == "bob")
    assert bob["active"] is False
