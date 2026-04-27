"""Tests for the public API (textaccounts.api).

The API is the stable contract for consumers like textsessions.
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from textaccounts.config import CONFIG_PATH, ProfileRegistry, Profile, save_registry
from conftest import make_claude_json


def _write_registry(tmp_path: Path, profiles: dict[str, Profile], active: str | None = None) -> Path:
    config_path = tmp_path / "profiles.yaml"
    registry = ProfileRegistry(active=active, profiles=profiles, profiles_dir=tmp_path / "profiles")
    save_registry(registry, config_path)
    return config_path


@pytest.fixture
def two_profiles(tmp_path):
    work_dir = tmp_path / "claude-work"
    personal_dir = tmp_path / "claude-personal"
    make_claude_json(work_dir, "work@co.com")
    make_claude_json(personal_dir, "me@gmail.com")

    profiles = {
        "work": Profile(name="work", path=work_dir, email="wor***@co.com"),
        "personal": Profile(name="personal", path=personal_dir, email="me@gmail.com", aliases=["p"]),
    }
    config_path = _write_registry(tmp_path, profiles, active="work")
    return config_path, profiles


class TestAvailable:
    def test_true_when_profiles_exist(self, two_profiles):
        config_path, _ = two_profiles
        with patch("textaccounts.api.load_registry") as mock:
            mock.return_value = ProfileRegistry(
                profiles={"work": Profile(name="work", path=Path("/tmp/w"))}
            )
            from textaccounts.api import available
            assert available() is True

    def test_false_when_no_profiles(self):
        with patch("textaccounts.api.load_registry") as mock:
            mock.return_value = ProfileRegistry()
            from textaccounts.api import available
            assert available() is False


class TestListProfiles:
    def test_returns_sorted_names(self, two_profiles):
        config_path, profiles = two_profiles
        with patch("textaccounts.api.load_registry") as mock:
            mock.return_value = ProfileRegistry(profiles=profiles)
            from textaccounts.api import list_profiles
            assert list_profiles() == ["personal", "work"]

    def test_empty_when_no_profiles(self):
        with patch("textaccounts.api.load_registry") as mock:
            mock.return_value = ProfileRegistry()
            from textaccounts.api import list_profiles
            assert list_profiles() == []


class TestActiveProfile:
    def test_returns_active(self, two_profiles):
        config_path, profiles = two_profiles
        with patch("textaccounts.api.load_registry") as mock:
            mock.return_value = ProfileRegistry(active="work", profiles=profiles)
            from textaccounts.api import active_profile
            assert active_profile() == "work"

    def test_none_when_no_active(self):
        with patch("textaccounts.api.load_registry") as mock:
            mock.return_value = ProfileRegistry()
            from textaccounts.api import active_profile
            assert active_profile() is None


class TestProfileDir:
    def test_returns_path(self, two_profiles, tmp_path):
        config_path, profiles = two_profiles
        with patch("textaccounts.api.load_registry") as mock:
            mock.return_value = ProfileRegistry(profiles=profiles)
            from textaccounts.api import profile_dir
            assert profile_dir("work") == profiles["work"].path

    def test_resolves_alias(self, two_profiles, tmp_path):
        config_path, profiles = two_profiles
        with patch("textaccounts.api.load_registry") as mock:
            mock.return_value = ProfileRegistry(profiles=profiles)
            from textaccounts.api import profile_dir
            assert profile_dir("p") == profiles["personal"].path

    def test_none_for_unknown(self):
        with patch("textaccounts.api.load_registry") as mock:
            mock.return_value = ProfileRegistry()
            from textaccounts.api import profile_dir
            assert profile_dir("nope") is None


class TestEnvForProfile:
    def test_returns_config_dir(self, two_profiles, tmp_path):
        config_path, profiles = two_profiles
        with patch("textaccounts.api.load_registry") as mock:
            mock.return_value = ProfileRegistry(profiles=profiles)
            from textaccounts.api import env_for_profile
            result = env_for_profile("work")
            assert result == {"CLAUDE_CONFIG_DIR": str(profiles["work"].path)}

    def test_default_returns_empty(self):
        from textaccounts.api import env_for_profile
        assert env_for_profile("default") == {}

    def test_alias_resolves(self, two_profiles, tmp_path):
        config_path, profiles = two_profiles
        with patch("textaccounts.api.load_registry") as mock:
            mock.return_value = ProfileRegistry(profiles=profiles)
            from textaccounts.api import env_for_profile
            result = env_for_profile("p")
            assert result == {"CLAUDE_CONFIG_DIR": str(profiles["personal"].path)}

    def test_unknown_raises(self):
        with patch("textaccounts.api.load_registry") as mock:
            mock.return_value = ProfileRegistry()
            from textaccounts.api import env_for_profile
            with pytest.raises(ValueError, match="not found"):
                env_for_profile("nope")


class TestGetProfileLineage:
    def test_returns_full_lineage_for_shallow_ephemeral(self):
        profiles = {
            "bot": Profile(
                name="bot", path=Path("/tmp/bot"), email="",
                shallow=True, parent="work",
                ephemeral=True, owner="textprompts:run-42",
            ),
        }
        with patch("textaccounts.api.load_registry") as mock:
            mock.return_value = ProfileRegistry(profiles=profiles)
            from textaccounts.api import get_profile_lineage
            assert get_profile_lineage("bot") == {
                "shallow": True,
                "parent": "work",
                "ephemeral": True,
                "owner": "textprompts:run-42",
            }

    def test_returns_defaults_for_plain_profile(self):
        profiles = {"work": Profile(name="work", path=Path("/tmp/w"), email="")}
        with patch("textaccounts.api.load_registry") as mock:
            mock.return_value = ProfileRegistry(profiles=profiles)
            from textaccounts.api import get_profile_lineage
            assert get_profile_lineage("work") == {
                "shallow": False,
                "parent": None,
                "ephemeral": False,
                "owner": "",
            }

    def test_resolves_alias(self):
        profiles = {
            "personal": Profile(
                name="personal", path=Path("/tmp/p"), email="",
                aliases=["p"],
            ),
        }
        with patch("textaccounts.api.load_registry") as mock:
            mock.return_value = ProfileRegistry(profiles=profiles)
            from textaccounts.api import get_profile_lineage
            assert get_profile_lineage("p") is not None

    def test_none_for_unknown(self):
        with patch("textaccounts.api.load_registry") as mock:
            mock.return_value = ProfileRegistry()
            from textaccounts.api import get_profile_lineage
            assert get_profile_lineage("nope") is None

    def test_none_for_default(self):
        from textaccounts.api import get_profile_lineage
        assert get_profile_lineage("default") is None
