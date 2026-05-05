from __future__ import annotations

import hashlib
import os
import platform
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import click

from textaccounts.config import Profile, ProfileRegistry, extract_email, save_registry


# ---------------------------------------------------------------------------
# macOS Keychain helpers
# ---------------------------------------------------------------------------

_KEYCHAIN_SERVICE_BASE = "Claude Code-credentials"


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


def _keychain_read(config_dir: Path) -> str | None:
    """Read the Keychain token JSON for config_dir. Returns None on any failure."""
    if platform.system() != "Darwin":
        return None
    service = _keychain_service_name(config_dir)
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", service, "-a", os.getlogin(), "-w"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def _keychain_write(config_dir: Path, data: str) -> bool:
    """Write token JSON to Keychain for config_dir. Returns True on success."""
    if platform.system() != "Darwin":
        return False
    service = _keychain_service_name(config_dir)
    try:
        result = subprocess.run(
            ["security", "add-generic-password", "-s", service, "-a", os.getlogin(), "-w", data],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


def _keychain_delete(config_dir: Path) -> None:
    """Delete the Keychain entry for config_dir. Best-effort, never raises."""
    if platform.system() != "Darwin":
        return
    service = _keychain_service_name(config_dir)
    try:
        subprocess.run(
            ["security", "delete-generic-password", "-s", service, "-a", os.getlogin()],
            capture_output=True,
            timeout=5,
        )
    except Exception:
        pass


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


# Deprecated alias — kept for backward compat. New code should use create_shallow.
def create_worker(name: str, parent_name: str, registry: ProfileRegistry) -> Profile:
    return create_shallow(name, parent_name, registry)


def rename(old_name: str, new_name: str, registry: ProfileRegistry) -> Profile:
    if old_name not in registry.profiles:
        raise click.UsageError(f"Profile '{old_name}' not found.")
    if new_name in registry.profiles:
        raise click.UsageError(f"Profile '{new_name}' already exists.")

    profile = registry.profiles.pop(old_name)
    profile = Profile(
        name=new_name,
        path=profile.path,
        email=profile.email,
        adopted=profile.adopted,
        shallow=profile.shallow,
        parent=profile.parent,
        aliases=profile.aliases,
        description=profile.description,
        ephemeral=profile.ephemeral,
        owner=profile.owner,
    )
    registry.profiles[new_name] = profile
    if registry.active == old_name:
        registry.active = new_name
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


_ACTIVE_DESC_FILE = Path.home() / ".textaccounts" / "active-description"


def _write_active_description(description: str) -> None:
    try:
        _ACTIVE_DESC_FILE.parent.mkdir(parents=True, exist_ok=True)
        _ACTIVE_DESC_FILE.write_text(description)
    except OSError:
        pass


def show(name: str, registry: ProfileRegistry, shell: str = "fish") -> str:
    if name == "default":
        _write_active_description("")
        if shell == "fish":
            return "set -e CLAUDE_CONFIG_DIR"
        return "unset CLAUDE_CONFIG_DIR"

    canonical = resolve_profile(name, registry)
    registry.active = canonical
    profile = registry.profiles[canonical]
    _write_active_description(profile.description)
    if shell == "fish":
        return f"set -gx CLAUDE_CONFIG_DIR {profile.path}"
    return f"export CLAUDE_CONFIG_DIR={profile.path}"


def get_status(registry: ProfileRegistry) -> dict:
    env_dir = os.environ.get("CLAUDE_CONFIG_DIR")
    active = registry.active
    profile = registry.profiles.get(active) if active else None

    in_sync = True
    if env_dir and profile:
        in_sync = Path(env_dir).resolve() == profile.path.resolve()
    elif env_dir and not profile:
        in_sync = False

    sessions = count_sessions(profile.path) if profile else 0

    return {
        "active": active,
        "path": str(profile.path) if profile else None,
        "email": profile.email if profile else None,
        "env_dir": env_dir,
        "in_sync": in_sync,
        "sessions": sessions,
    }


def count_sessions(path: Path) -> int:
    projects_dir = path / "projects"
    if not projects_dir.is_dir():
        return 0
    return sum(1 for p in projects_dir.iterdir() if p.is_dir())


def _dir_size_bytes(path: Path) -> int:
    """Return disk usage of path in bytes using du (fast, handles large dirs)."""
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
                "active": name == registry.active,
                "exists": exists,
                "aliases": profile.aliases,
                "description": profile.description,
                "ephemeral": profile.ephemeral,
                "owner": profile.owner,
                "adopted": profile.adopted,
            }
        )
    return result


# ---------------------------------------------------------------------------
# Ephemeral lifecycle: gc + destroy
# ---------------------------------------------------------------------------

GC_LOG_PATH = Path.home() / ".local" / "state" / "textaccounts" / "gc.log"
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
    if registry.active == canonical:
        registry.active = None
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
            if registry.active == profile.name:
                registry.active = None

    return to_remove


def discover_unregistered(registry: ProfileRegistry) -> list[Path]:
    """Scan ~/.claude-*/ for valid Claude config dirs not yet registered."""
    registered = {p.path.resolve() for p in registry.profiles.values()}
    found = []
    for d in sorted(Path.home().glob(".claude*")):
        if d.is_dir() and d.resolve() not in registered and validate_config_dir(d):
            found.append(d)
    return found
