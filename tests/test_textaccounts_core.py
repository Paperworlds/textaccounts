import hashlib
from pathlib import Path
from unittest.mock import patch

import pytest
import click

from textaccounts.config import ProfileRegistry, Profile, SigningConfig, load_registry, save_registry
from textaccounts.core import (
    adopt,
    clone_profile,
    create_from_current,
    create_shallow,
    destroy,
    export_profiles,
    gc,
    import_profiles,
    rename,
    show,
    list_profiles,
    _keychain_service_name,
    _token_keychain_service_name,
    _token_keychain_read,
    _token_keychain_write,
    _token_keychain_delete,
    _dir_size_bytes,
    write_profile_gitconfig,
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


# --- adopt_token ---

def test_adopt_token_creates_profile_and_writes_keychain(tmp_path):
    from textaccounts.core import adopt_token
    registry, _ = make_registry(tmp_path)
    dest = tmp_path / "claude-tok"

    with patch("textaccounts.core._token_keychain_write", return_value=True) as mock_write:
        profile = adopt_token("tok", dest, "secret", registry)

    assert profile.name == "tok"
    assert profile.auth_method == "token"
    assert profile.path == dest
    assert dest.is_dir()
    assert (dest / ".claude.json").exists()
    assert "tok" in registry.profiles
    mock_write.assert_called_once_with("tok", "secret")


def test_adopt_token_rejects_duplicate_name(tmp_path):
    from textaccounts.core import adopt_token
    registry, _ = make_registry(tmp_path)
    dest = tmp_path / "claude-tok"
    dest.mkdir()

    registry.profiles["tok"] = Profile(name="tok", path=dest, email="")

    with pytest.raises(click.UsageError, match="already exists"):
        adopt_token("tok", dest, "secret", registry)


def test_adopt_token_raises_on_keychain_failure(tmp_path):
    from textaccounts.core import adopt_token
    registry, _ = make_registry(tmp_path)
    dest = tmp_path / "claude-tok"

    with patch("textaccounts.core._token_keychain_write", return_value=False):
        with pytest.raises(click.ClickException):
            adopt_token("tok", dest, "secret", registry)


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


# --- create_shallow ---

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
    assert f"set -gx CLAUDE_CONFIG_DIR {p}" in line
    assert "set -e GIT_CONFIG_GLOBAL" in line


def test_show_to_default_returns_unset_line(tmp_path):
    registry, _ = make_registry(tmp_path)

    line = show("default", registry)
    assert "set -e CLAUDE_CONFIG_DIR" in line
    assert "set -e CLAUDE_CODE_OAUTH_TOKEN" in line


def test_show_does_not_mutate_registry(tmp_path):
    """Active state is per-shell (env-derived); show() must not write
    a global `active` marker to the registry."""
    registry, _ = make_registry(tmp_path)

    p = tmp_path / "claude-work"
    p.mkdir()
    make_claude_json(p)
    registry.profiles["work"] = Profile(name="work", path=p, email="")

    show("work", registry)
    assert not hasattr(registry, "active") or getattr(registry, "active", None) is None


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


def test_rename_preserves_auth_method_and_signing(tmp_path):
    registry, _ = make_registry(tmp_path)
    d = tmp_path / "claude-tok"
    d.mkdir()
    make_claude_json(d)
    signing = SigningConfig(mode="gpg-sw", key="ABCD1234", name="Dev", email="dev@example.com")
    registry.profiles["tok"] = Profile(
        name="tok", path=d, email="", auth_method="token", signing=signing
    )

    renamed = rename("tok", "tok2", registry)

    assert renamed.name == "tok2"
    assert renamed.auth_method == "token"
    assert renamed.signing is not None
    assert renamed.signing.mode == "gpg-sw"
    assert renamed.signing.key == "ABCD1234"


# --- list_profiles ---

def test_list_profiles_returns_all_profiles(tmp_path):
    registry, _ = make_registry(tmp_path)

    for name in ("alice", "bob"):
        d = tmp_path / f"claude-{name}"
        d.mkdir()
        make_claude_json(d)
        registry.profiles[name] = Profile(name=name, path=d, email="")

    # Active = whichever profile matches CLAUDE_CONFIG_DIR in this shell
    import os
    os.environ["CLAUDE_CONFIG_DIR"] = str(tmp_path / "claude-alice")
    try:
        profiles = list_profiles(registry)
    finally:
        os.environ.pop("CLAUDE_CONFIG_DIR", None)

    names = {p["name"] for p in profiles}
    assert names == {"alice", "bob"}

    alice = next(p for p in profiles if p["name"] == "alice")
    assert alice["active"] is True

    bob = next(p for p in profiles if p["name"] == "bob")
    assert bob["active"] is False


# --- Keychain helpers ---

def test_keychain_service_name_default_profile(tmp_path, monkeypatch):
    """Default profile path gets the bare service name (no suffix)."""
    monkeypatch.setenv("HOME", str(tmp_path))
    default_dir = tmp_path / ".claude"
    assert _keychain_service_name(default_dir) == "Claude Code-credentials"


def test_keychain_service_name_named_profile(tmp_path):
    """Named profiles get the sha256-prefixed service name."""
    named_dir = tmp_path / ".claude-work"
    expected_hash = hashlib.sha256(str(named_dir).encode()).hexdigest()[:8]
    expected = f"Claude Code-credentials-{expected_hash}"
    assert _keychain_service_name(named_dir) == expected


# --- create_shallow Keychain mirroring ---

def test_create_shallow_mirrors_keychain_when_parent_has_entry(tmp_path):
    """create_shallow mirrors the parent's Keychain entry to the clone."""
    registry, _ = make_registry(tmp_path)
    parent_dir = tmp_path / "claude-work"
    parent_dir.mkdir()
    make_claude_json(parent_dir)
    registry.profiles["work"] = Profile(name="work", path=parent_dir, email="")

    with patch("textaccounts.core._keychain_read", return_value='{"token":"abc"}') as mock_read, \
         patch("textaccounts.core._keychain_write", return_value=True) as mock_write:
        profile = create_shallow("work-bot", "work", registry)

    mock_read.assert_called_once_with(parent_dir)
    assert mock_write.call_count == 1
    call_args = mock_write.call_args
    assert call_args[0][1] == '{"token":"abc"}'
    # The clone's path should differ from the parent's
    assert call_args[0][0] != parent_dir
    assert profile.shallow is True


def test_create_shallow_warns_when_keychain_read_returns_none(tmp_path, capsys):
    """When parent has no Keychain entry on macOS, a warning is emitted."""
    registry, _ = make_registry(tmp_path)
    parent_dir = tmp_path / "claude-work"
    parent_dir.mkdir()
    make_claude_json(parent_dir)
    registry.profiles["work"] = Profile(name="work", path=parent_dir, email="")

    with patch("textaccounts.core._keychain_read", return_value=None), \
         patch("textaccounts.core.platform.system", return_value="Darwin"):
        profile = create_shallow("work-bot", "work", registry)

    assert profile.shallow is True
    captured = capsys.readouterr()
    assert "warning" in captured.err
    assert "work-bot" in captured.err


def test_create_shallow_no_warning_on_non_darwin(tmp_path, capsys):
    """On non-macOS, no Keychain warning is emitted (expected behaviour)."""
    registry, _ = make_registry(tmp_path)
    parent_dir = tmp_path / "claude-work"
    parent_dir.mkdir()
    make_claude_json(parent_dir)
    registry.profiles["work"] = Profile(name="work", path=parent_dir, email="")

    with patch("textaccounts.core._keychain_read", return_value=None), \
         patch("textaccounts.core.platform.system", return_value="Linux"):
        profile = create_shallow("work-bot", "work", registry)

    captured = capsys.readouterr()
    assert captured.err == ""


def test_destroy_deletes_keychain_entry_for_shallow_profile(tmp_path):
    """destroy() calls _keychain_delete for shallow profiles."""
    registry, _ = make_registry(tmp_path)
    p = _mk_ephemeral(registry, "bot", owner="run-1")

    with patch("textaccounts.core._keychain_delete") as mock_del:
        destroy("bot", registry)

    mock_del.assert_called_once_with(p.path)


def test_gc_deletes_keychain_entry_for_shallow_profiles(tmp_path):
    """gc() triggers Keychain cleanup for swept shallow profiles."""
    registry, _ = make_registry(tmp_path)
    old = _mk_ephemeral(registry, "old", days_old=10)

    with patch("textaccounts.core._keychain_delete") as mock_del:
        gc(registry, max_age_days=7)

    mock_del.assert_called_once_with(old.path)


# --- _token_keychain_* helpers ---

def test_token_keychain_service_name():
    assert _token_keychain_service_name("myprofile") == "textaccounts-oauth-token-myprofile"


# --- show with token profile ---

def test_show_token_profile_emits_both_env_vars(tmp_path):
    registry, _ = make_registry(tmp_path)
    p_dir = tmp_path / "claude-svc"
    p_dir.mkdir()
    make_claude_json(p_dir)
    registry.profiles["svc"] = Profile(name="svc", path=p_dir, email="", auth_method="token")

    with patch("textaccounts.core._token_keychain_read", return_value="mytoken123"):
        line = show("svc", registry)

    assert f"CLAUDE_CONFIG_DIR" in line
    assert str(p_dir) in line
    assert "CLAUDE_CODE_OAUTH_TOKEN" in line
    assert "mytoken123" in line


def test_show_token_profile_raises_when_no_keychain_entry(tmp_path):
    registry, _ = make_registry(tmp_path)
    p_dir = tmp_path / "claude-svc"
    p_dir.mkdir()
    make_claude_json(p_dir)
    registry.profiles["svc"] = Profile(name="svc", path=p_dir, email="", auth_method="token")

    with patch("textaccounts.core._token_keychain_read", return_value=None):
        with pytest.raises(click.UsageError, match="adopt-token"):
            show("svc", registry)


# --- _remove_profile for token profile ---

def _mk_token_profile(registry: ProfileRegistry, name: str, tmp_path: Path) -> Profile:
    p_dir = tmp_path / f"claude-{name}"
    p_dir.mkdir()
    make_claude_json(p_dir)
    from datetime import datetime, timezone
    profile = Profile(
        name=name,
        path=p_dir,
        email="",
        adopted=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        auth_method="token",
        ephemeral=True,
        owner="test-run",
    )
    registry.profiles[name] = profile
    return profile


def test_remove_token_profile_calls_token_keychain_delete(tmp_path):
    """_remove_profile deletes token Keychain entry for token profiles."""
    registry, _ = make_registry(tmp_path)
    profile = _mk_token_profile(registry, "svc", tmp_path)

    with patch("textaccounts.core._token_keychain_delete") as mock_del, \
         patch("textaccounts.core._keychain_delete") as mock_cc_del:
        destroy("svc", registry)

    mock_del.assert_called_once_with("svc")
    mock_cc_del.assert_not_called()


def test_remove_shallow_token_profile_calls_both_deletes(tmp_path):
    """A shallow+token profile cleans up both Keychain entries."""
    registry, _ = make_registry(tmp_path)
    p_dir = tmp_path / "claude-hybrid"
    p_dir.mkdir()
    make_claude_json(p_dir)
    from datetime import datetime, timezone
    profile = Profile(
        name="hybrid",
        path=p_dir,
        email="",
        adopted=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        auth_method="token",
        shallow=True,
        ephemeral=True,
        owner="test",
    )
    registry.profiles["hybrid"] = profile

    with patch("textaccounts.core._token_keychain_delete") as mock_tok, \
         patch("textaccounts.core._keychain_delete") as mock_cc:
        destroy("hybrid", registry)

    mock_tok.assert_called_once_with("hybrid")


# --- export / import ---

def _make_export_registry(tmp_path: Path) -> tuple[ProfileRegistry, Path]:
    registry, config_path = make_registry(tmp_path)
    p1 = tmp_path / "claude-work"
    make_claude_json(p1, "work@example.com")
    (p1 / "settings.json").write_text('{"theme": "dark"}')
    p2 = tmp_path / "claude-personal"
    make_claude_json(p2, "personal@example.com")
    adopt("work", p1, registry)
    adopt("personal", p2, registry)
    from textaccounts.config import save_registry
    save_registry(registry, config_path)
    return registry, config_path


def test_export_creates_zip_and_hash_file(tmp_path):
    registry, config_path = _make_export_registry(tmp_path)
    out = tmp_path / "backup.zip"

    result = export_profiles(registry, out, "s3cr3t", config_path=config_path)

    assert result == out
    assert out.exists()
    hash_file = out.with_name(out.name + ".sha256")
    assert hash_file.exists()
    digest_line = hash_file.read_text().strip()
    expected = hashlib.sha256(out.read_bytes()).hexdigest()
    assert digest_line == f"{expected}  {out.name}"


def test_export_zip_contains_expected_entries(tmp_path):
    import pyzipper
    registry, config_path = _make_export_registry(tmp_path)
    out = tmp_path / "backup.zip"

    export_profiles(registry, out, "pw", config_path=config_path)

    with pyzipper.AESZipFile(out, "r") as zf:
        zf.setpassword(b"pw")
        names = zf.namelist()

    assert "profiles.yaml" in names
    assert "profiles/work/.claude.json" in names
    assert "profiles/work/settings.json" in names
    assert "profiles/personal/.claude.json" in names


def test_export_wrong_password_raises(tmp_path):
    import pyzipper
    registry, config_path = _make_export_registry(tmp_path)
    out = tmp_path / "backup.zip"

    export_profiles(registry, out, "correct", config_path=config_path)

    with pytest.raises(Exception):
        with pyzipper.AESZipFile(out, "r") as zf:
            zf.setpassword(b"wrong")
            zf.read("profiles.yaml")


def test_import_round_trip(tmp_path):
    registry, config_path = _make_export_registry(tmp_path)
    out = tmp_path / "backup.zip"

    export_profiles(registry, out, "pw", config_path=config_path)

    dest = tmp_path / "dest"
    dest.mkdir()
    empty_registry, _ = make_registry(dest)
    imported, skipped = import_profiles(out, "pw", empty_registry)

    assert set(imported) == {"work", "personal"}
    assert skipped == []
    assert "work" in empty_registry.profiles
    assert "personal" in empty_registry.profiles
    work_path = empty_registry.profiles["work"].path
    assert (work_path / ".claude.json").exists()
    assert (work_path / "settings.json").exists()


def test_import_round_trip_preserves_all_fields(tmp_path):
    """B2 regression: import must not silently drop ephemeral/owner/signing/auth_method."""
    registry, config_path = _make_export_registry(tmp_path)
    signing = SigningConfig(mode="gpg-sw", key="DEAD", name="Dev", email="dev@example.com")
    registry.profiles["work"].ephemeral = True
    registry.profiles["work"].owner = "ci-run-42"
    registry.profiles["work"].auth_method = "token"
    registry.profiles["work"].signing = signing
    from textaccounts.config import save_registry as _save
    _save(registry, config_path)

    out = tmp_path / "backup.zip"
    export_profiles(registry, out, "pw", config_path=config_path)

    dest = tmp_path / "dest"
    dest.mkdir()
    empty_registry, _ = make_registry(dest)
    import_profiles(out, "pw", empty_registry)

    work = empty_registry.profiles["work"]
    assert work.ephemeral is True
    assert work.owner == "ci-run-42"
    assert work.auth_method == "token"
    assert work.signing is not None
    assert work.signing.mode == "gpg-sw"
    assert work.signing.key == "DEAD"


def test_import_skips_existing_without_overwrite(tmp_path):
    registry, config_path = _make_export_registry(tmp_path)
    out = tmp_path / "backup.zip"

    export_profiles(registry, out, "pw", config_path=config_path)

    dest = tmp_path / "dest"
    dest.mkdir()
    dest_registry, _ = make_registry(dest)
    import_profiles(out, "pw", dest_registry)

    imported2, skipped2 = import_profiles(out, "pw", dest_registry, overwrite=False)
    assert imported2 == []
    assert set(skipped2) == {"work", "personal"}


def test_import_overwrite_replaces_profile(tmp_path):
    registry, config_path = _make_export_registry(tmp_path)
    out = tmp_path / "backup.zip"

    export_profiles(registry, out, "pw", config_path=config_path)

    dest = tmp_path / "dest"
    dest.mkdir()
    dest_registry, _ = make_registry(dest)
    import_profiles(out, "pw", dest_registry)

    imported2, skipped2 = import_profiles(out, "pw", dest_registry, overwrite=True)
    assert set(imported2) == {"work", "personal"}
    assert skipped2 == []


def test_import_bad_zip_raises(tmp_path):
    bad_zip = tmp_path / "bad.zip"
    bad_zip.write_bytes(b"not a zip")
    registry, _ = make_registry(tmp_path)

    with pytest.raises(Exception):
        import_profiles(bad_zip, "pw", registry)


# --- _dir_size_bytes guard ---

def test_dir_size_bytes_refuses_home(monkeypatch, tmp_path):
    """Never du the entire home directory — a misconfigured profile pointing
    there would otherwise walk all of $HOME and time out."""
    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    (fake_home / "big.txt").write_text("x" * 1024)
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    assert _dir_size_bytes(fake_home) == 0


def test_dir_size_bytes_refuses_root():
    assert _dir_size_bytes(Path("/")) == 0


def test_dir_size_bytes_returns_size_for_normal_dir(tmp_path):
    (tmp_path / "a.txt").write_text("hello")
    size = _dir_size_bytes(tmp_path)
    assert size > 0


# --- per-profile commit signing ---

def _signing_profile(tmp_path, mode="gpg-sw", key="ABCD1234", name="Alice", email="a@x.com"):
    p_dir = tmp_path / "p"
    p_dir.mkdir()
    return Profile(
        name="p",
        path=p_dir,
        signing=SigningConfig(mode=mode, key=key, name=name, email=email),
    )


def test_write_profile_gitconfig_gpg_sw(tmp_path):
    profile = _signing_profile(tmp_path)
    path = write_profile_gitconfig(profile)
    assert path == profile.path / "gitconfig"
    content = path.read_text()
    # ~/.gitconfig must be included first so core.excludesfile, aliases etc. survive
    assert "[include]" in content
    assert "path = ~/.gitconfig" in content
    assert content.index("[include]") < content.index("[user]")
    assert 'name = "Alice"' in content
    assert 'email = "a@x.com"' in content
    assert "signingkey = ABCD1234" in content
    assert "[commit]" in content and "gpgsign = true" in content
    assert "[tag]" in content


def test_write_profile_gitconfig_unsigned_writes_false(tmp_path):
    profile = _signing_profile(tmp_path, mode="unsigned", key="")
    path = write_profile_gitconfig(profile)
    content = path.read_text()
    assert "gpgsign = false" in content
    assert "signingkey" not in content


def test_write_profile_gitconfig_no_signing_returns_none(tmp_path):
    p_dir = tmp_path / "p"
    p_dir.mkdir()
    profile = Profile(name="p", path=p_dir, signing=None)
    assert write_profile_gitconfig(profile) is None


def test_show_emits_git_config_global_for_signed_profile(tmp_path):
    profile = _signing_profile(tmp_path)
    reg = ProfileRegistry(profiles={"p": profile})
    out = show("p", reg, shell="fish")
    assert f"set -gx CLAUDE_CONFIG_DIR {profile.path}" in out
    assert f"set -gx GIT_CONFIG_GLOBAL {profile.path}/gitconfig" in out


def test_show_unsets_git_config_global_for_unsigned_profile(tmp_path):
    p_dir = tmp_path / "p"
    p_dir.mkdir()
    profile = Profile(name="p", path=p_dir, signing=None)
    reg = ProfileRegistry(profiles={"p": profile})
    out = show("p", reg, shell="fish")
    assert "set -e GIT_CONFIG_GLOBAL" in out


def test_show_default_unsets_git_config_global():
    out = show("default", ProfileRegistry(), shell="fish")
    assert "set -e GIT_CONFIG_GLOBAL" in out
    assert "set -e CLAUDE_CONFIG_DIR" in out


def test_compute_env_parity_with_show(tmp_path):
    """S4 parity: compute_env keys must match the vars show() sets or unsets."""
    from textaccounts.core import compute_env
    registry, _ = make_registry(tmp_path)
    d = tmp_path / "claude-parity"
    d.mkdir()
    make_claude_json(d)
    signing = SigningConfig(mode="unsigned")
    registry.profiles["parity"] = Profile(name="parity", path=d, email="", signing=signing)

    env = compute_env(registry.profiles["parity"])
    out = show("parity", registry, shell="fish")

    for key, val in env.items():
        if val is not None:
            assert key in out, f"compute_env set {key} but show() didn't emit it"
        else:
            assert key in out, f"compute_env unset {key} but show() didn't emit it"


def test_signing_config_round_trip_yaml(tmp_path):
    cfg = tmp_path / "profiles.yaml"
    p_dir = tmp_path / "p"
    p_dir.mkdir()
    reg = ProfileRegistry(profiles={"p": Profile(
        name="p", path=p_dir,
        signing=SigningConfig(mode="gpg-sw", key="K1", name="Alice", email="a@x.com"),
    )})
    save_registry(reg, cfg)
    loaded = load_registry(cfg)
    s = loaded.profiles["p"].signing
    assert s is not None
    assert s.mode == "gpg-sw"
    assert s.key == "K1"
    assert s.email == "a@x.com"


def test_load_registry_rejects_invalid_signing_mode(tmp_path):
    cfg = tmp_path / "profiles.yaml"
    cfg.write_text(
        "version: '1.0'\nprofiles:\n  p:\n    path: /tmp/p\n"
        "    signing:\n      mode: bogus\n"
    )
    with pytest.raises(ValueError, match="signing.mode"):
        load_registry(cfg)
