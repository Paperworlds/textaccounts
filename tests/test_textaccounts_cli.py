from pathlib import Path

import pytest
from click.testing import CliRunner

from textaccounts.cli import main
from textaccounts.config import Profile, ProfileRegistry
from conftest import make_claude_json, make_registry


def patch_registry(monkeypatch, registry: ProfileRegistry, config_path: Path) -> None:
    """Make cli.load_registry return our test registry and wire save_registry."""
    import textaccounts.config as config_module

    original_save = config_module.save_registry

    def patched_save(reg, cp=config_path):
        original_save(reg, config_path=cp)

    monkeypatch.setattr("textaccounts.cli.save_registry", patched_save)
    monkeypatch.setattr("textaccounts.cli.load_registry", lambda: registry)


# ── adopt ─────────────────────────────────────────────────────────────────────


def test_adopt_prints_confirmation(tmp_path, monkeypatch):
    registry, config_path = make_registry(tmp_path)
    patch_registry(monkeypatch, registry, config_path)

    source = tmp_path / "claude-work"
    source.mkdir()
    make_claude_json(source, "paolo@example.com")

    runner = CliRunner()
    result = runner.invoke(main, ["adopt", "work", str(source)])

    assert result.exit_code == 0, result.output
    assert "Adopted" in result.output
    assert "work" in result.output


# ── list ──────────────────────────────────────────────────────────────────────


def test_list_shows_table(tmp_path, monkeypatch):
    registry, config_path = make_registry(tmp_path)

    for name in ("alice", "bob"):
        d = tmp_path / f"claude-{name}"
        d.mkdir()
        make_claude_json(d)
        registry.profiles[name] = Profile(name=name, path=d, email="")

    registry.active = "alice"
    patch_registry(monkeypatch, registry, config_path)

    runner = CliRunner()
    result = runner.invoke(main, ["list"])

    assert result.exit_code == 0, result.output
    assert "alice" in result.output
    assert "bob" in result.output
    assert "*" in result.output  # active marker


def test_list_shows_shallow_tag(tmp_path, monkeypatch):
    registry, config_path = make_registry(tmp_path)

    d = tmp_path / "claude-bot"
    d.mkdir()
    make_claude_json(d)
    registry.profiles["bot"] = Profile(
        name="bot", path=d, email="",
        shallow=True, ephemeral=True, owner="run-1",
    )
    patch_registry(monkeypatch, registry, config_path)

    runner = CliRunner()
    result = runner.invoke(main, ["list"])

    assert result.exit_code == 0
    assert "[shallow]" in result.output
    assert "[ephemeral]" in result.output
    assert "[owner=run-1]" in result.output


# ── show ──────────────────────────────────────────────────────────────────────


def test_show_outputs_fish_env_line(tmp_path, monkeypatch):
    registry, config_path = make_registry(tmp_path)

    d = tmp_path / "claude-work"
    d.mkdir()
    make_claude_json(d)
    registry.profiles["work"] = Profile(name="work", path=d, email="")
    patch_registry(monkeypatch, registry, config_path)

    runner = CliRunner()
    result = runner.invoke(main, ["show", "work"])

    assert result.exit_code == 0
    assert result.output.strip() == f"set -gx CLAUDE_CONFIG_DIR {d}"


def test_show_default_outputs_unset_line(tmp_path, monkeypatch):
    registry, config_path = make_registry(tmp_path)
    patch_registry(monkeypatch, registry, config_path)

    runner = CliRunner()
    result = runner.invoke(main, ["show", "default"])

    assert result.exit_code == 0
    assert result.output.strip() == "set -e CLAUDE_CONFIG_DIR"


def test_show_no_rich_markup(tmp_path, monkeypatch):
    """show must emit plain text only — no Rich markup or colour codes."""
    registry, config_path = make_registry(tmp_path)

    d = tmp_path / "claude-work"
    d.mkdir()
    make_claude_json(d)
    registry.profiles["work"] = Profile(name="work", path=d, email="")
    patch_registry(monkeypatch, registry, config_path)

    runner = CliRunner()
    result = runner.invoke(main, ["show", "work"])

    assert "[" not in result.output or "set" in result.output  # no Rich tags
    assert "\x1b" not in result.output  # no ANSI escapes


# ── status ────────────────────────────────────────────────────────────────────


def test_status_shows_active_profile(tmp_path, monkeypatch):
    registry, config_path = make_registry(tmp_path)

    d = tmp_path / "claude-work"
    d.mkdir()
    make_claude_json(d, "work@example.com")
    registry.profiles["work"] = Profile(
        name="work", path=d, email="wor***@example.com"
    )
    registry.active = "work"
    patch_registry(monkeypatch, registry, config_path)
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)

    runner = CliRunner()
    result = runner.invoke(main, ["status"])

    assert result.exit_code == 0
    assert "work" in result.output
    assert "wor***@example.com" in result.output


def test_status_no_active_profile(tmp_path, monkeypatch):
    registry, config_path = make_registry(tmp_path)
    patch_registry(monkeypatch, registry, config_path)
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)

    runner = CliRunner()
    result = runner.invoke(main, ["status"])

    assert result.exit_code == 0
    assert "No active profile" in result.output


# ── create ────────────────────────────────────────────────────────────────────


def test_create_shallow_from_parent(tmp_path, monkeypatch):
    registry, config_path = make_registry(tmp_path)

    parent_dir = tmp_path / "claude-main"
    parent_dir.mkdir()
    make_claude_json(parent_dir)
    (parent_dir / "settings.json").write_text('{"key": "val"}')
    registry.profiles["main"] = Profile(name="main", path=parent_dir, email="")
    patch_registry(monkeypatch, registry, config_path)

    runner = CliRunner()
    result = runner.invoke(main, ["create", "bot", "--shallow", "--from", "main"])

    assert result.exit_code == 0, result.output
    assert "shallow clone" in result.output
    assert "bot" in registry.profiles
    assert registry.profiles["bot"].shallow is True
    assert registry.profiles["bot"].ephemeral is False
    assert registry.profiles["bot"].parent == "main"


def test_create_worker_alias_emits_deprecation(tmp_path, monkeypatch):
    registry, config_path = make_registry(tmp_path)
    parent_dir = tmp_path / "claude-main"
    parent_dir.mkdir()
    make_claude_json(parent_dir)
    registry.profiles["main"] = Profile(name="main", path=parent_dir, email="")
    patch_registry(monkeypatch, registry, config_path)

    runner = CliRunner()
    result = runner.invoke(main, ["create", "bot", "--worker", "--from", "main"])

    assert result.exit_code == 0, result.output
    # Click 8 combines stderr into output by default.
    assert "deprecated" in result.output
    assert registry.profiles["bot"].shallow is True


def test_create_shallow_with_owner_implies_ephemeral(tmp_path, monkeypatch):
    registry, config_path = make_registry(tmp_path)
    parent_dir = tmp_path / "claude-main"
    parent_dir.mkdir()
    make_claude_json(parent_dir)
    registry.profiles["main"] = Profile(name="main", path=parent_dir, email="")
    patch_registry(monkeypatch, registry, config_path)

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["create", "bot", "--shallow", "--from", "main", "--owner", "run-7"],
    )

    assert result.exit_code == 0, result.output
    assert registry.profiles["bot"].ephemeral is True
    assert registry.profiles["bot"].owner == "run-7"


def test_destroy_removes_ephemeral(tmp_path, monkeypatch):
    registry, config_path = make_registry(tmp_path)
    p = tmp_path / "claude-bot"
    p.mkdir()
    make_claude_json(p)
    registry.profiles["bot"] = Profile(
        name="bot", path=p, email="",
        shallow=True, ephemeral=True, owner="run-1",
    )
    patch_registry(monkeypatch, registry, config_path)

    runner = CliRunner()
    result = runner.invoke(main, ["destroy", "bot"])

    assert result.exit_code == 0, result.output
    assert "Destroyed" in result.output
    assert "bot" not in registry.profiles
    assert not p.exists()


def test_destroy_refuses_non_ephemeral(tmp_path, monkeypatch):
    registry, config_path = make_registry(tmp_path)
    p = tmp_path / "claude-permanent"
    p.mkdir()
    make_claude_json(p)
    registry.profiles["permanent"] = Profile(name="permanent", path=p, email="")
    patch_registry(monkeypatch, registry, config_path)

    runner = CliRunner()
    result = runner.invoke(main, ["destroy", "permanent"])

    assert result.exit_code != 0
    assert "not ephemeral" in result.output
    assert "permanent" in registry.profiles
    assert p.exists()


def test_gc_dry_run_lists_without_removing(tmp_path, monkeypatch):
    from datetime import datetime, timezone, timedelta

    registry, config_path = make_registry(tmp_path)
    p = registry.profiles_dir / "old-bot"
    p.mkdir(parents=True)
    make_claude_json(p)
    old = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
    registry.profiles["old-bot"] = Profile(
        name="old-bot", path=p, email="",
        shallow=True, ephemeral=True, adopted=old,
    )
    patch_registry(monkeypatch, registry, config_path)

    runner = CliRunner()
    result = runner.invoke(main, ["gc", "--max-age", "7d", "--dry-run"])

    assert result.exit_code == 0, result.output
    assert "Would remove" in result.output
    assert "old-bot" in registry.profiles
    assert p.exists()


# ── install ──────────────────────────────────────────────────────────────────


def test_install_writes_fish_files(tmp_path, monkeypatch):
    fish_config = tmp_path / ".config" / "fish"
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    monkeypatch.setenv("SHELL", "/usr/local/bin/fish")

    runner = CliRunner()
    result = runner.invoke(main, ["install"])

    assert result.exit_code == 0, result.output
    assert (fish_config / "functions" / "textaccounts.fish").exists()
    assert (fish_config / "completions" / "textaccounts.fish").exists()
    fn_text = (fish_config / "functions" / "textaccounts.fish").read_text()
    assert "function textaccounts" in fn_text
    assert "command textaccounts show" in fn_text
