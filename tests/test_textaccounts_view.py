"""Tests for the textaccounts interactive view."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from textaccounts.view import TextAccountsApp, _fmt_size, _render_detail, _short_path
from conftest import make_claude_json


def _write_registry(config_path: Path, active: str | None, profiles: dict) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    data: dict = {"version": "1.0", "profiles": profiles}
    if active:
        data["active"] = active
    with config_path.open("w") as f:
        yaml.safe_dump(data, f)


# ---------------------------------------------------------------------------
# Unit tests (no Textual runtime)
# ---------------------------------------------------------------------------

def test_fmt_size_megabytes():
    assert _fmt_size(2 * 1024 * 1024) == "2M"


def test_fmt_size_kilobytes():
    assert _fmt_size(500 * 1024) == "500K"


def test_render_detail_none():
    assert "No profiles" in _render_detail(None, None)


def test_render_detail_active_profile():
    p = {
        "name": "work",
        "active": True,
        "exists": True,
        "path": Path("/tmp/work"),
        "email": "pao***@example.com",
        "sessions": 12,
        "dir_size": 1024 * 512,
        "worker": False,
    }
    text = _render_detail(p, None)
    assert "work" in text
    assert "active" in text
    assert "12" in text
    assert "pao***@example.com" in text


def test_render_detail_broken_path():
    p = {
        "name": "stale",
        "active": False,
        "exists": False,
        "path": Path("/tmp/gone"),
        "email": "",
        "sessions": 0,
        "dir_size": 0,
        "worker": False,
    }
    assert "not found" in _render_detail(p, None)


def test_render_detail_suggestion(tmp_path: Path):
    text = _render_detail(None, tmp_path)
    assert "Not yet adopted" in text
    assert "adopt" in text.lower()


def test_render_detail_worker_flag():
    p = {
        "name": "work-bot",
        "active": False,
        "exists": True,
        "path": Path("/tmp/work-bot"),
        "email": "",
        "sessions": 0,
        "dir_size": 0,
        "worker": True,
    }
    assert "worker" in _render_detail(p, None)


def test_short_path_home_relative(tmp_path: Path):
    from pathlib import Path
    home = Path.home()
    assert _short_path(home / "foo" / "bar") == "~/foo/bar"


def test_short_path_outside_home():
    assert _short_path(Path("/etc/passwd")) == "/etc/passwd"


# ---------------------------------------------------------------------------
# Textual app tests
# ---------------------------------------------------------------------------

_NO_SUGGESTIONS = patch("textaccounts.core.discover_unregistered", return_value=[])


def test_view_mounts_with_profiles(tmp_path: Path):
    work = tmp_path / "claude-work"
    make_claude_json(work, "work@example.com")
    personal = tmp_path / "claude-personal"
    make_claude_json(personal, "me@example.com")
    config = tmp_path / "profiles.yaml"
    _write_registry(config, "work", {
        "work": {"path": str(work)},
        "personal": {"path": str(personal)},
    })

    async def _run():
        app = TextAccountsApp(config_path=config)
        async with app.run_test() as pilot:
            table = app.query_one("DataTable")
            assert table.row_count == 2

    with _NO_SUGGESTIONS:
        asyncio.run(_run())


def test_view_shows_active_marker(tmp_path: Path):
    work = tmp_path / "claude-work"
    make_claude_json(work)
    config = tmp_path / "profiles.yaml"
    _write_registry(config, "work", {"work": {"path": str(work)}})

    async def _run():
        app = TextAccountsApp(config_path=config)
        async with app.run_test() as pilot:
            table = app.query_one("DataTable")
            cell = table.get_cell_at((0, 0))
            assert "[green]*[/green]" in str(cell) or cell == "*"

    with _NO_SUGGESTIONS:
        asyncio.run(_run())


def test_switch_updates_active_marker(tmp_path: Path):
    work = tmp_path / "claude-work"
    make_claude_json(work)
    personal = tmp_path / "claude-personal"
    make_claude_json(personal)
    config = tmp_path / "profiles.yaml"
    _write_registry(config, "work", {
        "work": {"path": str(work)},
        "personal": {"path": str(personal)},
    })

    async def _run():
        app = TextAccountsApp(config_path=config)
        async with app.run_test() as pilot:
            table = app.query_one("DataTable")
            await pilot.press("down")
            await pilot.press("s")
            await pilot.pause()
            # personal (row 1) should now be active; work (row 0) should not
            assert table.get_cell_at((1, 0)) != ""
            assert table.get_cell_at((0, 0)) == ""

    with _NO_SUGGESTIONS:
        asyncio.run(_run())


def test_adopt_modal_opens_on_a(tmp_path: Path):
    config = tmp_path / "profiles.yaml"
    _write_registry(config, None, {})

    async def _run():
        from textaccounts.view import AdoptModal
        app = TextAccountsApp(config_path=config)
        async with app.run_test() as pilot:
            await pilot.press("a")
            await pilot.pause()
            assert app.screen_stack[-1].__class__ is AdoptModal

    with _NO_SUGGESTIONS:
        asyncio.run(_run())


def test_adopt_registers_profile(tmp_path: Path):
    work = tmp_path / "claude-work"
    make_claude_json(work)
    config = tmp_path / "profiles.yaml"
    _write_registry(config, None, {})

    async def _run():
        from textual.widgets import Input
        from textaccounts.view import AdoptModal
        app = TextAccountsApp(config_path=config)
        async with app.run_test() as pilot:
            await pilot.press("a")
            await pilot.pause()
            modal = app.screen_stack[-1]
            modal.query_one("#name-input", Input).value = "work"
            modal.query_one("#path-input", Input).value = str(work)
            await pilot.click("#adopt-btn")
            await pilot.pause()
            table = app.query_one("DataTable")
            assert table.row_count == 1

    with _NO_SUGGESTIONS:
        asyncio.run(_run())
