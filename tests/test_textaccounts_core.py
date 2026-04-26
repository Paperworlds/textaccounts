import pytest
import click

from textaccounts.config import ProfileRegistry, Profile, load_registry
from textaccounts.core import (
    adopt,
    clone_profile,
    create_from_current,
    create_shallow,
    create_worker,
    destroy,
    gc,
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


# --- create_shallow / create_worker (deprecated alias) ---

def test_create_shallow_copies_only_claude_json_and_settings(tmp_path):
    registry, _ = make_registry(tmp_path)

    parent_dir = tmp_path / "claude-work"
    parent_dir.mkdir()
    make_claude_json(parent_dir)
    (parent_dir / "settings.json").write_text('{"key": "val"}')
    (parent_dir / "extra.txt").write_text("should not copy")

    registry.profiles["work"] = Profile(
        name="work", path=parent_dir, email="pao***@example.com"
    )

    profile = create_shallow("work-bot", "work", registry)

    dest = registry.profiles_dir / "work-bot"
    assert (dest / ".claude.json").exists()
    assert (dest / "settings.json").exists()
    assert not (dest / "extra.txt").exists()
    assert profile.shallow is True
    assert profile.ephemeral is False
    assert profile.owner == ""
    assert profile.parent == "work"


def test_create_worker_alias_still_works(tmp_path):
    """create_worker() is the deprecated alias for create_shallow()."""
    registry, _ = make_registry(tmp_path)
    src = tmp_path / "claude-work"
    src.mkdir()
    make_claude_json(src)
    registry.profiles["work"] = Profile(name="work", path=src, email="")

    profile = create_worker("work-bot", "work", registry)
    assert profile.shallow is True


def test_create_shallow_with_ephemeral_and_owner(tmp_path):
    registry, _ = make_registry(tmp_path)
    src = tmp_path / "claude-work"
    src.mkdir()
    make_claude_json(src)
    registry.profiles["work"] = Profile(name="work", path=src, email="")

    profile = create_shallow(
        "ephemeral-bot", "work", registry, ephemeral=True, owner="run-42"
    )
    assert profile.shallow is True
    assert profile.ephemeral is True
    assert profile.owner == "run-42"


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
    assert profile.shallow is False


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


# --- gc / destroy ---

def _mk_ephemeral(registry, name, *, owner="", days_old=0):
    """Build a real ephemeral profile dir + register it with `adopted` shifted into the past."""
    from datetime import datetime, timezone, timedelta
    p = registry.profiles_dir / name
    p.mkdir(parents=True)
    make_claude_json(p)
    adopted_dt = datetime.now(timezone.utc) - timedelta(days=days_old)
    adopted = adopted_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    registry.profiles[name] = Profile(
        name=name, path=p, email="", adopted=adopted,
        shallow=True, ephemeral=True, owner=owner,
    )
    return registry.profiles[name]


def test_gc_sweeps_old_ephemerals_only(tmp_path):
    registry, _ = make_registry(tmp_path)

    fresh = _mk_ephemeral(registry, "fresh", days_old=1)
    old = _mk_ephemeral(registry, "old", days_old=10)
    permanent = registry.profiles_dir / "permanent"
    permanent.mkdir()
    make_claude_json(permanent)
    registry.profiles["permanent"] = Profile(
        name="permanent", path=permanent, email="",
        shallow=False, ephemeral=False,
    )

    removed = gc(registry, max_age_days=7)

    removed_names = {p.name for p in removed}
    assert removed_names == {"old"}
    assert "old" not in registry.profiles
    assert "fresh" in registry.profiles
    assert "permanent" in registry.profiles
    assert not old.path.exists()
    assert fresh.path.exists()
    assert permanent.exists()


def test_gc_owner_filter(tmp_path):
    registry, _ = make_registry(tmp_path)
    _mk_ephemeral(registry, "alpha", owner="run-1", days_old=10)
    _mk_ephemeral(registry, "beta", owner="run-2", days_old=10)

    removed = gc(registry, max_age_days=7, owner="run-1")
    removed_names = {p.name for p in removed}
    assert removed_names == {"alpha"}
    assert "beta" in registry.profiles


def test_gc_dry_run_does_not_remove(tmp_path):
    registry, _ = make_registry(tmp_path)
    p = _mk_ephemeral(registry, "old", days_old=10)

    removed = gc(registry, max_age_days=7, dry_run=True)

    assert {x.name for x in removed} == {"old"}
    assert "old" in registry.profiles
    assert p.path.exists()


def test_destroy_removes_ephemeral(tmp_path):
    registry, _ = make_registry(tmp_path)
    p = _mk_ephemeral(registry, "bot", owner="run-1")

    destroy("bot", registry)
    assert "bot" not in registry.profiles
    assert not p.path.exists()


def test_destroy_refuses_non_ephemeral(tmp_path):
    registry, _ = make_registry(tmp_path)
    src = tmp_path / "claude-work"
    src.mkdir()
    make_claude_json(src)
    registry.profiles["work"] = Profile(
        name="work", path=src, email="", shallow=False, ephemeral=False,
    )

    with pytest.raises(click.UsageError, match="not ephemeral"):
        destroy("work", registry)
    # Untouched
    assert "work" in registry.profiles
    assert src.exists()


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
