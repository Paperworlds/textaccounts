from __future__ import annotations

import getpass
import hashlib
import os
import platform
import shutil
import subprocess
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import click

from textaccounts.config import Profile, ProfileRegistry, extract_email, save_registry


# ---------------------------------------------------------------------------
# macOS Keychain helpers
# ---------------------------------------------------------------------------

_KEYCHAIN_SERVICE_BASE = "Claude Code-credentials"
_TOKEN_KEYCHAIN_SERVICE_PREFIX = "textaccounts-oauth-token"


def _keychain_service_name(config_dir: Path) -> str:
    """Return the Keychain service name Claude Code uses for config_dir.

    Default profile (~/.claude) uses the bare service name.
    Named profiles use service-<sha256(path)[:8]>.
    """
    default_claude = Path.home() / ".claude"
    if config_dir.resolve() == default_claude.resolve():
        return _KEYCHAIN_SERVICE_BASE
    digest = hashlib.sha256(str(config_dir).encode()).hexdigest()[:8]
    return f"{_KEYCHAIN_SERVICE_BASE}-{digest}"


def _token_keychain_service_name(profile_name: str) -> str:
    return f"{_TOKEN_KEYCHAIN_SERVICE_PREFIX}-{profile_name}"


def _security(action: str, service: str, data: str | None = None) -> str | None:
    """Thin wrapper around the macOS `security` CLI.

    Returns stdout (stripped) on success, None on non-Darwin / exception / non-zero exit.
    For find-generic-password that is the secret; for add/delete it is an empty string.
    """
    if platform.system() != "Darwin":
        return None
    cmd = ["security", action, "-s", service, "-a", getpass.getuser()]
    if action == "find-generic-password":
        cmd.append("-w")
    elif action == "add-generic-password":
        cmd += ["-w", data or ""]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def _keychain_read(config_dir: Path) -> str | None:
    return _security("find-generic-password", _keychain_service_name(config_dir))


def _keychain_write(config_dir: Path, data: str) -> bool:
    return _security("add-generic-password", _keychain_service_name(config_dir), data) is not None


def _keychain_delete(config_dir: Path) -> None:
    _security("delete-generic-password", _keychain_service_name(config_dir))


def _token_keychain_read(profile_name: str) -> str | None:
    return _security("find-generic-password", _token_keychain_service_name(profile_name))


def _token_keychain_write(profile_name: str, token: str) -> bool:
    return _security("add-generic-password", _token_keychain_service_name(profile_name), token) is not None


def _token_keychain_delete(profile_name: str) -> None:
    _security("delete-generic-password", _token_keychain_service_name(profile_name))


def adopt_token(name: str, dest: Path, token: str, registry: ProfileRegistry) -> Profile:
    """Register a token-auth profile. Creates dest + seeds .claude.json if absent,
    writes the token to Keychain, and inserts the Profile into registry.
    Raises click.UsageError if the name is already taken or the Keychain write fails.
    """
    import json as _json
    if name in registry.profiles:
        raise click.UsageError(f"Profile '{name}' already exists.")
    dest.mkdir(parents=True, exist_ok=True)
    claude_json = dest / ".claude.json"
    if not claude_json.exists():
        # Seed the onboarding flag so the first interactive launch goes straight
        # to the session instead of the "Select login method" welcome screen —
        # Claude Code gates that screen on hasCompletedOnboarding even when a
        # valid CLAUDE_CODE_OAUTH_TOKEN is present.
        claude_json.write_text(_json.dumps({"hasCompletedOnboarding": True}))
    ok = _token_keychain_write(name, token)
    if not ok:
        raise click.ClickException("Failed to write token to Keychain.")
    profile = Profile(
        name=name,
        path=dest,
        email="",
        adopted=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        auth_method="token",
    )
    registry.profiles[name] = profile
    return profile


def validate_config_dir(path: Path) -> bool:
    return (path / ".claude.json").exists()


def resolve_profile(name: str, registry: ProfileRegistry) -> str:
    """Resolve a name or alias to a profile key. Returns the canonical name."""
    if name in registry.profiles:
        return name
    for key, profile in registry.profiles.items():
        if name in profile.aliases:
            return key
    raise click.UsageError(f"Profile '{name}' not found.")


def adopt(name: str, path: Path, registry: ProfileRegistry) -> Profile:
    path = path.expanduser().resolve()
    if name in registry.profiles:
        raise click.UsageError(f"Profile '{name}' already exists.")
    if not path.is_dir():
        raise click.UsageError(f"Directory not found: {path}")
    if not validate_config_dir(path):
        raise click.UsageError(f"Not a valid Claude config dir (missing .claude.json): {path}")

    email = extract_email(path)
    profile = Profile(
        name=name,
        path=path,
        email=email,
        adopted=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        shallow=False,
        parent=None,
    )
    registry.profiles[name] = profile
    return profile


def create_from_current(name: str, registry: ProfileRegistry) -> Profile:
    if name in registry.profiles:
        raise click.UsageError(f"Profile '{name}' already exists.")

    source = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude")).expanduser()
    if not validate_config_dir(source):
        raise click.UsageError(f"Current config dir is not a valid Claude config dir: {source}")

    dest = registry.profiles_dir / name
    if dest.exists():
        raise click.UsageError(f"Destination already exists: {dest}")

    shutil.copytree(source, dest)
    return adopt(name, dest, registry)


# Fields to preserve from .claude.json when cloning. Everything else
# (projects, mcpServers, UI counters, caches) is stripped to leave a clean slate.
_CLONE_KEEP_CLAUDE_JSON: frozenset[str] = frozenset({
    "oauthAccount",
    "userID",
    "anonymousId",
    "migrationVersion",
    "theme",
})

# Top-level entries to copy from a source profile dir during clone (if present).
# Symlinks are preserved as symlinks; directories are deep-copied.
_CLONE_COPY_ENTRIES: tuple[str, ...] = (
    "settings.json",
    "agents",
    "hooks",
    "plugins",
    "commands",
    "memory",
    "agent-memory",
)


def clone_profile(name: str, source_name: str, registry: ProfileRegistry) -> Profile:
    """Clone a profile's setup (auth + settings + agents/hooks/plugins + symlinks),
    stripping all state (sessions, projects, history, caches).
    """
    import json

    if name in registry.profiles:
        raise click.UsageError(f"Profile '{name}' already exists.")
    if source_name not in registry.profiles:
        raise click.UsageError(f"Source profile '{source_name}' not found.")

    source = registry.profiles[source_name].path
    if not validate_config_dir(source):
        raise click.UsageError(f"Source profile is missing .claude.json: {source}")

    dest = registry.profiles_dir / name
    if dest.exists():
        raise click.UsageError(f"Destination already exists: {dest}")

    dest.mkdir(parents=True)

    with (source / ".claude.json").open() as f:
        src_data = json.load(f)
    cleaned = {k: v for k, v in src_data.items() if k in _CLONE_KEEP_CLAUDE_JSON}
    with (dest / ".claude.json").open("w") as f:
        json.dump(cleaned, f, indent=2)

    for entry in _CLONE_COPY_ENTRIES:
        src_entry = source / entry
        if not src_entry.exists() and not src_entry.is_symlink():
            continue
        dst_entry = dest / entry
        if src_entry.is_symlink():
            dst_entry.symlink_to(os.readlink(src_entry))
        elif src_entry.is_dir():
            shutil.copytree(src_entry, dst_entry, symlinks=True)
        else:
            shutil.copy2(src_entry, dst_entry)

    email = extract_email(dest)
    profile = Profile(
        name=name,
        path=dest,
        email=email,
        adopted=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        shallow=False,
        parent=source_name,
    )
    registry.profiles[name] = profile
    return profile


# SPEC: shallow-clone
def create_shallow(
    name: str,
    parent_name: str,
    registry: ProfileRegistry,
    ephemeral: bool = False,
    owner: str = "",
) -> Profile:
    """Create a shallow clone — copies only .claude.json + settings.json from
    the parent. No agents/, hooks/, plugins/, sessions/, etc. Optionally flagged
    `ephemeral` so `textaccounts gc` and `destroy` can sweep it later.
    """
    if name in registry.profiles:
        raise click.UsageError(f"Profile '{name}' already exists.")
    if parent_name not in registry.profiles:
        raise click.UsageError(f"Parent profile '{parent_name}' not found.")

    parent = registry.profiles[parent_name]
    dest = registry.profiles_dir / name
    if dest.exists():
        raise click.UsageError(f"Destination already exists: {dest}")

    dest.mkdir(parents=True)
    for fname in (".claude.json", "settings.json"):
        src_file = parent.path / fname
        if src_file.exists():
            shutil.copy2(src_file, dest / fname)

    if not validate_config_dir(dest):
        shutil.rmtree(dest)
        raise click.UsageError(f"Parent profile is missing .claude.json: {parent.path}")

    email = extract_email(dest)
    profile = Profile(
        name=name,
        path=dest,
        email=email,
        adopted=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        shallow=True,
        parent=parent_name,
        ephemeral=ephemeral,
        owner=owner,
    )
    registry.profiles[name] = profile

    # Mirror parent's Keychain entry so the clone is pre-authenticated.
    # Best-effort: never fail create_shallow if Keychain ops don't work.
    token_data = _keychain_read(parent.path)
    if token_data:
        ok = _keychain_write(dest, token_data)
        if not ok:
            click.echo(
                f"  warning: Keychain mirror failed — clone '{name}' will need /login",
                err=True,
            )
    else:
        if platform.system() == "Darwin":
            click.echo(
                f"  warning: no Keychain entry found for parent '{parent_name}' — "
                f"clone '{name}' will need /login",
                err=True,
            )

    return profile


def rename(old_name: str, new_name: str, registry: ProfileRegistry) -> Profile:
    if old_name not in registry.profiles:
        raise click.UsageError(f"Profile '{old_name}' not found.")
    if new_name in registry.profiles:
        raise click.UsageError(f"Profile '{new_name}' already exists.")

    profile = registry.profiles.pop(old_name)
    profile = replace(profile, name=new_name)
    registry.profiles[new_name] = profile
    return profile


def add_alias(profile_name: str, alias: str, registry: ProfileRegistry) -> Profile:
    """Add an alias to a profile."""
    canonical = resolve_profile(profile_name, registry)
    # Check alias doesn't collide with existing profile names or aliases
    if alias in registry.profiles:
        raise click.UsageError(f"'{alias}' is already a profile name.")
    for key, p in registry.profiles.items():
        if alias in p.aliases:
            raise click.UsageError(f"'{alias}' is already an alias for '{key}'.")
    profile = registry.profiles[canonical]
    profile.aliases.append(alias)
    return profile


def remove_alias(profile_name: str, alias: str, registry: ProfileRegistry) -> Profile:
    """Remove an alias from a profile."""
    canonical = resolve_profile(profile_name, registry)
    profile = registry.profiles[canonical]
    if alias not in profile.aliases:
        raise click.UsageError(f"'{alias}' is not an alias for '{canonical}'.")
    profile.aliases.remove(alias)
    return profile


def active_profile_from_env(registry: ProfileRegistry) -> "Profile | None":
    """Return the profile whose path matches $CLAUDE_CONFIG_DIR, or None.

    Active state is per-shell — derived from the env var, never from a global
    file or registry field. A shell with no CLAUDE_CONFIG_DIR has no active
    profile (falls back to ~/.claude).
    """
    env_dir = os.environ.get("CLAUDE_CONFIG_DIR")
    if not env_dir:
        return None
    try:
        target = Path(env_dir).resolve()
    except OSError:
        return None
    for profile in registry.profiles.values():
        try:
            if profile.path.resolve() == target:
                return profile
        except OSError:
            continue
    return None


def _profile_gitconfig_path(profile: "Profile") -> Path:
    return profile.path / "gitconfig"


def write_profile_gitconfig(profile: "Profile") -> Path | None:
    """Write `<profile_path>/gitconfig` from profile.signing. Returns the path,
    or None if no signing config. Always overwrites — single source of truth."""
    s = profile.signing
    if s is None:
        return None
    profile.path.mkdir(parents=True, exist_ok=True)
    # GIT_CONFIG_GLOBAL fully replaces ~/.gitconfig — include it first so
    # core.excludesfile, aliases, pull.rebase, etc. survive. Then override
    # identity / signing below (later wins in git config).
    lines = [
        "# generated by textaccounts — edit profiles.yaml instead\n",
        "[include]\n",
        "\tpath = ~/.gitconfig\n",
        "[user]\n",
    ]
    if s.name:
        lines.append(f'\tname = "{s.name}"\n')
    if s.email:
        lines.append(f'\temail = "{s.email}"\n')
    if s.mode == "gpg-sw" or s.mode == "gpg-hw":
        if s.key:
            lines.append(f"\tsigningkey = {s.key}\n")
        lines.append("[commit]\n\tgpgsign = true\n")
        lines.append("[tag]\n\tgpgsign = true\n")
    else:  # unsigned — explicit false defeats any inherited true
        lines.append("[commit]\n\tgpgsign = false\n")
        lines.append("[tag]\n\tgpgsign = false\n")
    path = _profile_gitconfig_path(profile)
    path.write_text("".join(lines))
    return path


def compute_env(profile: "Profile") -> "dict[str, str | None]":
    """Return env vars needed to activate profile. None means unset in the calling shell.

    Raises ValueError if a token profile has no Keychain entry.
    """
    env: dict[str, str | None] = {"CLAUDE_CONFIG_DIR": str(profile.path)}
    if profile.auth_method == "token":
        token = _token_keychain_read(profile.name)
        if token is None:
            raise ValueError(
                f"Token profile '{profile.name}' has no Keychain entry. "
                f"Run: textaccounts adopt-token {profile.name}"
            )
        env["CLAUDE_CODE_OAUTH_TOKEN"] = token
    if profile.signing is not None:
        gc_path = write_profile_gitconfig(profile)
        if gc_path is not None:
            env["GIT_CONFIG_GLOBAL"] = str(gc_path)
    else:
        env["GIT_CONFIG_GLOBAL"] = None
    return env


def show(name: str, registry: ProfileRegistry, shell: str = "fish", redact: bool = False) -> str:
    def _unset(*vars: str) -> str:
        if shell == "fish":
            return "\n".join(f"set -e {v}" for v in vars)
        return "\n".join(f"unset {v}" for v in vars)

    def _set(pairs: list[tuple[str, str]]) -> str:
        if shell == "fish":
            return "\n".join(f"set -gx {k} {v}" for k, v in pairs)
        return "\n".join(f"export {k}={v}" for k, v in pairs)

    if name == "default":
        return _unset("CLAUDE_CONFIG_DIR", "CLAUDE_CODE_OAUTH_TOKEN", "GIT_CONFIG_GLOBAL")

    canonical = resolve_profile(name, registry)
    profile = registry.profiles[canonical]

    try:
        env = compute_env(profile)
    except ValueError as exc:
        raise click.UsageError(str(exc)) from None

    pairs = [(k, v) for k, v in env.items() if v is not None]
    unset_keys = [k for k, v in env.items() if v is None]

    # Redact the secret when the caller is a human at a TTY (not piping to
    # `source`). The masked value is shell-valid but deliberately useless, so a
    # copy-paste fails loudly and the human reaches for the documented pipe.
    notice = ""
    if redact:
        masked: list[tuple[str, str]] = []
        for k, v in pairs:
            if k == "CLAUDE_CODE_OAUTH_TOKEN":
                masked.append((k, "'<redacted>'"))
                notice = (
                    f"# token-auth profile {name!r}: secret hidden because output is a TTY.\n"
                    f"# to activate, pipe to your shell:  textaccounts show {name} | source\n"
                )
            else:
                masked.append((k, v))
        pairs = masked

    out = _set(pairs)
    if unset_keys:
        out += "\n" + _unset(*unset_keys)
    return notice + out if notice else out


def get_status(registry: ProfileRegistry) -> dict:
    """Report the active profile for *this shell* — derived from
    $CLAUDE_CONFIG_DIR, not from any global state."""
    env_dir = os.environ.get("CLAUDE_CONFIG_DIR")
    profile = active_profile_from_env(registry)

    sessions = count_sessions(profile.path) if profile else 0

    return {
        "active": profile.name if profile else None,
        "path": str(profile.path) if profile else None,
        "email": profile.email if profile else None,
        "env_dir": env_dir,
        # in_sync is meaningful when env points somewhere — true if the env
        # path matches a registered profile, false if it points elsewhere.
        "in_sync": True if (profile is not None or not env_dir) else False,
        "sessions": sessions,
    }


def count_sessions(path: Path) -> int:
    projects_dir = path / "projects"
    if not projects_dir.is_dir():
        return 0
    return sum(1 for p in projects_dir.iterdir() if p.is_dir())


def _dir_size_bytes(path: Path) -> int:
    """Return disk usage of path in bytes using du (fast, handles large dirs).

    Refuses to scan the user's home directory or root — a misconfigured
    profile pointing there would otherwise walk the entire home.
    """
    resolved = path.resolve()
    if resolved == Path.home().resolve() or resolved == Path("/"):
        return 0
    try:
        out = subprocess.run(
            ["du", "-sk", str(path)], capture_output=True, text=True, timeout=5
        )
        if out.returncode == 0:
            return int(out.stdout.split()[0]) * 1024
    except (ValueError, subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return 0


def list_profiles(registry: ProfileRegistry) -> list[dict]:
    active = active_profile_from_env(registry)
    active_name = active.name if active else None
    result = []
    for name, profile in registry.profiles.items():
        exists = profile.path.is_dir()
        size = _dir_size_bytes(profile.path) if exists else 0
        result.append(
            {
                "name": name,
                "path": profile.path,
                "email": profile.email,
                "shallow": profile.shallow,
                # Backward-compat key for older view/CLI code that still reads "worker".
                "worker": profile.shallow,
                "dir_size": size,
                "sessions": count_sessions(profile.path),
                "active": name == active_name,
                "exists": exists,
                "aliases": profile.aliases,
                "description": profile.description,
                "ephemeral": profile.ephemeral,
                "owner": profile.owner,
                "adopted": profile.adopted,
                "auth_method": profile.auth_method,
            }
        )
    return result


# ---------------------------------------------------------------------------
# Ephemeral lifecycle: gc + destroy
# ---------------------------------------------------------------------------

GC_LOG_PATH = Path.home() / ".local" / "paperworlds" / "textaccounts" / "gc.log"
DEFAULT_GC_MAX_AGE_DAYS = 7


def _parse_adopted(adopted: str) -> datetime | None:
    if not adopted:
        return None
    try:
        return datetime.strptime(adopted, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _audit_log(action: str, profile: Profile, reason: str) -> None:
    """Append one line to the gc audit log. Best-effort: never raises."""
    try:
        GC_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        line = (
            f"{ts}\t{action}\t{profile.name}\t"
            f"owner={profile.owner or '-'}\t"
            f"adopted={profile.adopted or '-'}\t"
            f"reason={reason}\n"
        )
        with GC_LOG_PATH.open("a") as f:
            f.write(line)
    except OSError:
        pass


def _remove_profile(profile: Profile, registry: ProfileRegistry) -> None:
    """Remove a profile dir + registry entry. Caller is responsible for safety
    checks (ephemeral flag, etc.) and audit logging."""
    if profile.shallow:
        _keychain_delete(profile.path)
    if profile.auth_method == "token":
        _token_keychain_delete(profile.name)
    if profile.path.is_dir():
        shutil.rmtree(profile.path)
    registry.profiles.pop(profile.name, None)


def destroy(name: str, registry: ProfileRegistry) -> Profile:
    """Remove a single ephemeral profile. Refuses non-ephemeral profiles."""
    canonical = resolve_profile(name, registry)
    profile = registry.profiles[canonical]
    if not profile.ephemeral:
        raise click.UsageError(
            f"Profile '{canonical}' is not ephemeral. "
            f"`destroy` only removes profiles marked `ephemeral: true`. "
            f"Use the registry edit path for permanent profiles."
        )
    _audit_log("destroy", profile, "explicit")
    _remove_profile(profile, registry)
    return profile


def gc(
    registry: ProfileRegistry,
    max_age_days: int = DEFAULT_GC_MAX_AGE_DAYS,
    owner: str | None = None,
    dry_run: bool = False,
) -> list[Profile]:
    """Sweep ephemeral profiles older than max_age_days (and matching owner if given).

    Returns the list of profiles that were (or would be, if dry_run) removed.
    Refuses to touch non-ephemeral profiles regardless of age.
    """
    now = datetime.now(timezone.utc)
    cutoff_seconds = max_age_days * 86400
    to_remove: list[Profile] = []

    for profile in list(registry.profiles.values()):
        if not profile.ephemeral:
            continue
        if owner is not None and profile.owner != owner:
            continue
        adopted_dt = _parse_adopted(profile.adopted)
        if adopted_dt is None:
            # No adopted timestamp — treat as old enough to sweep.
            age_seconds = cutoff_seconds + 1
        else:
            age_seconds = (now - adopted_dt).total_seconds()
        if age_seconds < cutoff_seconds:
            continue
        to_remove.append(profile)

    for profile in to_remove:
        if dry_run:
            _audit_log("gc-dry-run", profile, f"max_age={max_age_days}d")
        else:
            _audit_log("gc", profile, f"max_age={max_age_days}d")
            _remove_profile(profile, registry)

    return to_remove


def discover_unregistered(registry: ProfileRegistry) -> list[Path]:
    """Scan ~/.claude-*/ for valid Claude config dirs not yet registered."""
    registered = {p.path.resolve() for p in registry.profiles.values()}
    found = []
    for d in sorted(Path.home().glob(".claude*")):
        if d.is_dir() and d.resolve() not in registered and validate_config_dir(d):
            found.append(d)
    return found


_EXPORT_SETTINGS_FILES = (".claude.json", "settings.json")


def export_profiles(
    registry: ProfileRegistry,
    output_path: Path,
    password: str,
    config_path: Path | None = None,
) -> Path:
    """Export profiles.yaml + per-profile settings to a password-protected AES zip.

    Also writes a .sha256 integrity file alongside the zip.
    Returns the zip path.
    """
    import io
    import pyzipper
    from textaccounts.config import CONFIG_PATH as _DEFAULT_CONFIG_PATH

    registry_path = config_path if config_path is not None else _DEFAULT_CONFIG_PATH

    buf = io.BytesIO()
    with pyzipper.AESZipFile(
        buf, "w",
        compression=pyzipper.ZIP_DEFLATED,
        encryption=pyzipper.WZ_AES,
    ) as zf:
        zf.setpassword(password.encode())
        if registry_path.exists():
            zf.writestr("profiles.yaml", registry_path.read_bytes())
        for name, profile in registry.profiles.items():
            for filename in _EXPORT_SETTINGS_FILES:
                src = profile.path / filename
                if src.exists():
                    zf.writestr(f"profiles/{name}/{filename}", src.read_bytes())

    zip_bytes = buf.getvalue()
    output_path.write_bytes(zip_bytes)

    digest = hashlib.sha256(zip_bytes).hexdigest()
    hash_path = output_path.with_name(output_path.name + ".sha256")
    hash_path.write_text(f"{digest}  {output_path.name}\n")

    return output_path


def import_profiles(
    zip_path: Path,
    password: str,
    registry: ProfileRegistry,
    overwrite: bool = False,
) -> tuple[list[str], list[str]]:
    """Import profiles from a textaccounts export zip into registry.

    Returns (imported_names, skipped_names).
    Skipped profiles are those that already exist when overwrite=False.
    """
    import io
    import pyzipper
    import yaml

    with pyzipper.AESZipFile(zip_path, "r") as zf:
        zf.setpassword(password.encode())
        try:
            raw = zf.read("profiles.yaml")
        except KeyError:
            raise click.UsageError("Archive does not contain profiles.yaml — not a textaccounts export.")

        data = yaml.safe_load(io.BytesIO(raw)) or {}
        imported: list[str] = []
        skipped: list[str] = []

        for name, entry in (data.get("profiles") or {}).items():
            if name in registry.profiles and not overwrite:
                skipped.append(name)
                continue

            profile_path = Path(entry["path"]).expanduser()
            profile_path.mkdir(parents=True, exist_ok=True)

            for filename in _EXPORT_SETTINGS_FILES:
                arc_name = f"profiles/{name}/{filename}"
                try:
                    content = zf.read(arc_name)
                    (profile_path / filename).write_bytes(content)
                except KeyError:
                    pass

            from textaccounts.config import Profile as _Profile
            registry.profiles[name] = _Profile.from_dict(
                name, {**entry, "path": str(profile_path)}
            )
            imported.append(name)

    return imported, skipped
