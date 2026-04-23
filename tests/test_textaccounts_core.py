import pytest
import click

from textaccounts.config import ProfileRegistry, Profile, load_registry
from textaccounts.core import (
    adopt,
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
