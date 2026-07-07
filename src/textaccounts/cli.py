from __future__ import annotations

import subprocess as _sp
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from textaccounts import __version__
from textaccounts.config import load_registry, save_registry, SigningConfig, SIGNING_MODES
from textaccounts import core
from textaccounts.shell_templates import (
    _FISH_FUNCTION,
    _FISH_SWITCH_COMPLETIONS,
    _FISH_TA_FUNCTION,
    _FISH_CLICK_WRAPPER,
    _BASH_FUNCTION,
    _BASH_SWITCH_COMPLETIONS,
    _ZSH_FUNCTION,
    _ZSH_SWITCH_COMPLETIONS,
)

console = Console()

try:
    _git_hash = _sp.check_output(
        ["git", "rev-parse", "--short", "HEAD"],
        stderr=_sp.DEVNULL, text=True,
        cwd=Path(__file__).parent,
    ).strip()
    _version_str = f"textaccounts, version {__version__} ({_git_hash})"
except Exception:
    _version_str = f"textaccounts, version {__version__}"


def _complete_profile_names(ctx, param, incomplete):
    """Click shell_complete callback: dynamic profile names from the registry.
    Used by every command that takes a profile name argument."""
    try:
        registry = load_registry()
        names = list(registry.profiles.keys())
        # aliases too — users may complete by alias
        for p in registry.profiles.values():
            names.extend(p.aliases)
        # "default" is always a valid target (means: unset overrides)
        names.append("default")
    except Exception:
        return []
    return [n for n in names if n.startswith(incomplete)]


@click.group()
@click.version_option(_version_str, "--version", "-V", prog_name="textaccounts")
def main() -> None:
    """Manage Claude config profiles."""


@main.command()
@click.argument("name")
@click.argument("path", type=click.Path())
def adopt(name: str, path: str) -> None:
    """Adopt an existing Claude config directory as a named profile."""
    registry = load_registry()
    profile = core.adopt(name, Path(path), registry)
    save_registry(registry)
    console.print(
        f"[green]Adopted[/green] profile [bold]{profile.name}[/bold] → {profile.path}"
    )


@main.command("adopt-token")
@click.argument("name")
@click.option("--path", "profile_path", default=None, type=click.Path(),
              help="Config dir to use (created if absent). Defaults to ~/.claude-<name>.")
def adopt_token(name: str, profile_path: str | None) -> None:
    """Register a profile that authenticates via CLAUDE_CODE_OAUTH_TOKEN.

    The token is stored in the macOS Keychain (never in profiles.yaml).
    Run this command again to rotate the token.
    """
    import platform as _platform
    if _platform.system() != "Darwin":
        raise click.UsageError("adopt-token is macOS-only in v0.1.0 (Keychain is required).")

    dest = Path(profile_path).expanduser().resolve() if profile_path else Path.home() / f".claude-{name}"
    if dest.exists() and not dest.is_dir():
        raise click.UsageError(f"Path exists but is not a directory: {dest}")

    token = click.prompt("CLAUDE_CODE_OAUTH_TOKEN", hide_input=True)
    if not token.strip():
        raise click.UsageError("Token must not be empty.")

    registry = load_registry()
    profile = core.adopt_token(name, dest, token.strip(), registry)
    save_registry(registry)
    console.print(f"[green]Registered[/green] token profile [bold]{profile.name}[/bold] → {dest}")
    console.print(f"[dim]Token stored in Keychain as: {core._token_keychain_service_name(name)}[/dim]")


@main.command("create")
@click.argument("name")
@click.option("--shallow", "shallow", is_flag=True,
              help="Shallow clone: copy only .claude.json + settings.json from --from parent.")
@click.option("--worker", "worker", is_flag=True, hidden=True,
              help="Deprecated alias for --shallow.")
@click.option("--from", "parent", default=None,
              help="Parent profile name (required with --shallow).")
@click.option("--clone-from", "clone_from", default=None,
              help="Deep clone: copy auth + settings + agents/hooks/plugins, stripped of state.")
@click.option("--ephemeral", "ephemeral", is_flag=True,
              help="Mark the new profile ephemeral so `textaccounts gc/destroy` can sweep it.")
@click.option("--owner", "owner", default="",
              help="Owner ID (e.g. orchestrator run-id) for `gc --owner` filtering. Implies --ephemeral.")
def create(
    name: str,
    shallow: bool,
    worker: bool,
    parent: str | None,
    clone_from: str | None,
    ephemeral: bool,
    owner: str,
) -> None:
    """Create a new profile from the current config, as a shallow clone, or as a deep clone."""
    registry = load_registry()

    # --owner implies --ephemeral
    if owner:
        ephemeral = True

    # Backward compat: --worker is now --shallow.
    if worker:
        if shallow:
            raise click.UsageError("--worker is a deprecated alias for --shallow; pass only one")
        click.echo("warning: --worker is deprecated, use --shallow instead", err=True)
        shallow = True

    if shallow and clone_from:
        raise click.UsageError("--shallow and --clone-from are mutually exclusive")
    if ephemeral and not (shallow or clone_from):
        raise click.UsageError("--ephemeral / --owner require --shallow or --clone-from")

    if shallow:
        if not parent:
            raise click.UsageError("--from <parent> is required with --shallow")
        profile = core.create_shallow(name, parent, registry, ephemeral=ephemeral, owner=owner)
        save_registry(registry)
        tag = " [dim]ephemeral[/dim]" if ephemeral else ""
        owner_tag = f" [dim]owner={owner}[/dim]" if owner else ""
        console.print(
            f"[green]Created[/green] shallow clone [bold]{profile.name}[/bold]"
            f" (parent: {profile.parent}){tag}{owner_tag}"
        )
    elif clone_from:
        profile = core.clone_profile(name, clone_from, registry)
        if ephemeral:
            profile.ephemeral = True
            profile.owner = owner
            save_registry(registry)
        else:
            save_registry(registry)
        tag = " [dim]ephemeral[/dim]" if ephemeral else ""
        owner_tag = f" [dim]owner={owner}[/dim]" if owner else ""
        console.print(
            f"[green]Cloned[/green] [bold]{clone_from}[/bold] → [bold]{profile.name}[/bold]"
            f" at {profile.path} [dim](stripped of sessions/history/caches)[/dim]{tag}{owner_tag}"
        )
    else:
        profile = core.create_from_current(name, registry)
        save_registry(registry)
        console.print(
            f"[green]Created[/green] profile [bold]{profile.name}[/bold] → {profile.path}"
        )


@main.command("list")
def list_cmd() -> None:
    """List all profiles."""
    registry = load_registry()
    profiles = core.list_profiles(registry)

    table = Table(show_header=True, header_style="bold")
    table.add_column("", width=1)
    table.add_column("Name")
    table.add_column("Path")
    table.add_column("Email")
    table.add_column("Size")
    table.add_column("Tags")

    for p in profiles:
        active_marker = "*" if p["active"] else ""
        size_kb = p["dir_size"] // 1024
        tag_parts: list[str] = []
        if p["shallow"]:
            tag_parts.append("\\[shallow]")
        if p.get("auth_method") == "token":
            tag_parts.append("\\[token-auth]")
        if p.get("ephemeral"):
            tag_parts.append("\\[ephemeral]")
        if p.get("owner"):
            tag_parts.append(f"\\[owner={p['owner']}]")
        table.add_row(
            active_marker,
            p["name"],
            str(p["path"]),
            p["email"] or "",
            f"{size_kb}K",
            " ".join(tag_parts),
        )

    console.print(table)


@main.command()
@click.argument("old_name", shell_complete=_complete_profile_names)
@click.argument("new_name")
def rename(old_name: str, new_name: str) -> None:
    """Rename a profile."""
    registry = load_registry()
    profile = core.rename(old_name, new_name, registry)
    save_registry(registry)
    console.print(f"[green]Renamed[/green] [bold]{old_name}[/bold] → [bold]{profile.name}[/bold]")


@main.command()
@click.argument("profile_name", shell_complete=_complete_profile_names)
@click.argument("alias")
@click.option("--remove", is_flag=True, help="Remove the alias instead of adding it.")
def alias(profile_name: str, alias: str, remove: bool) -> None:
    """Add or remove an alias for a profile."""
    registry = load_registry()
    if remove:
        profile = core.remove_alias(profile_name, alias, registry)
        save_registry(registry)
        console.print(f"[red]Removed[/red] alias [bold]{alias}[/bold] from [bold]{profile.name}[/bold]")
    else:
        profile = core.add_alias(profile_name, alias, registry)
        save_registry(registry)
        console.print(f"[green]Added[/green] alias [bold]{alias}[/bold] → [bold]{profile.name}[/bold]")


@main.command()
@click.argument("name", shell_complete=_complete_profile_names)
@click.option("--shell", "shell_name", default="fish", hidden=True,
              help="Shell syntax to emit (fish, bash, zsh).")
def show(name: str, shell_name: str) -> None:
    """Print the shell command to activate a profile (used by shell integration)."""
    registry = load_registry()
    line = core.show(name, registry, shell=shell_name)
    if name != "default":
        save_registry(registry)
    click.echo(line)


@main.command()
def status() -> None:
    """Show active profile status."""
    registry = load_registry()
    info = core.get_status(registry)

    if not info["active"]:
        console.print("[yellow]No active profile[/yellow]")
        return

    console.print(f"[bold]Active profile:[/bold] {info['active']}")
    console.print(f"[bold]Path:[/bold] {info['path']}")
    if info["email"]:
        console.print(f"[bold]Email:[/bold] {info['email']}")
    console.print(f"[bold]Sessions:[/bold] {info['sessions']}")
    if info["env_dir"]:
        sync = "[green]in sync[/green]" if info["in_sync"] else "[red]out of sync[/red]"
        console.print(f"[bold]CLAUDE_CONFIG_DIR:[/bold] {info['env_dir']} ({sync})")
    else:
        console.print("[bold]CLAUDE_CONFIG_DIR:[/bold] [dim]not set[/dim]")


@main.command()
@click.argument("name", shell_complete=_complete_profile_names)
@click.argument("text", required=False, default="")
def describe(name: str, text: str) -> None:
    """Set (or clear) the description for a profile."""
    registry = load_registry()
    canonical = core.resolve_profile(name, registry)
    registry.profiles[canonical].description = text.strip()
    save_registry(registry)
    if text.strip():
        console.print(f"[green]Set[/green] description for [bold]{canonical}[/bold]: {text.strip()}")
    else:
        console.print(f"[yellow]Cleared[/yellow] description for [bold]{canonical}[/bold]")


@main.group("signing")
def signing_group() -> None:
    """Manage per-profile git commit signing."""


@signing_group.command("set")
@click.argument("name", shell_complete=_complete_profile_names)
@click.option("--mode", type=click.Choice(SIGNING_MODES), required=True)
@click.option("--key", default="", help="GPG key id/fingerprint (required for gpg-sw/gpg-hw)")
@click.option("--name", "user_name", default="", help="git user.name")
@click.option("--email", default="", help="git user.email")
def signing_set(name: str, mode: str, key: str, user_name: str, email: str) -> None:
    """Set signing config for a profile and write its gitconfig."""
    registry = load_registry()
    canonical = core.resolve_profile(name, registry)
    profile = registry.profiles[canonical]
    if mode in ("gpg-sw", "gpg-hw") and not key:
        raise click.UsageError(f"--key is required for mode={mode}")
    profile.signing = SigningConfig(mode=mode, key=key, name=user_name, email=email)
    gc_path = core.write_profile_gitconfig(profile)
    save_registry(registry)
    console.print(f"[green]Set[/green] signing for [bold]{canonical}[/bold]: mode={mode} key={key or '-'}")
    if gc_path:
        console.print(f"  gitconfig → {gc_path}")


@signing_group.command("show")
@click.argument("name", shell_complete=_complete_profile_names)
def signing_show(name: str) -> None:
    """Show signing config for a profile."""
    registry = load_registry()
    canonical = core.resolve_profile(name, registry)
    s = registry.profiles[canonical].signing
    if s is None:
        console.print(f"[yellow]{canonical}[/yellow]: no signing config (falls through to ~/.gitconfig)")
        return
    console.print(f"[bold]{canonical}[/bold] signing:")
    console.print(f"  mode:  {s.mode}")
    console.print(f"  key:   {s.key or '-'}")
    console.print(f"  name:  {s.name or '-'}")
    console.print(f"  email: {s.email or '-'}")


@signing_group.command("unset")
@click.argument("name", shell_complete=_complete_profile_names)
def signing_unset(name: str) -> None:
    """Remove signing config for a profile."""
    registry = load_registry()
    canonical = core.resolve_profile(name, registry)
    profile = registry.profiles[canonical]
    if profile.signing is None:
        console.print(f"[yellow]{canonical}[/yellow]: no signing config to remove")
        return
    profile.signing = None
    gc_path = profile.path / "gitconfig"
    if gc_path.exists():
        gc_path.unlink()
    save_registry(registry)
    console.print(f"[green]Removed[/green] signing for [bold]{canonical}[/bold]")
    console.print(
        f"[dim]If this shell has GIT_CONFIG_GLOBAL set, run: ta switch {canonical}[/dim]"
    )


@main.command()
def desc() -> None:
    """Print the active profile's description (for statusline integration).

    Active = whichever registered profile matches $CLAUDE_CONFIG_DIR in this
    shell. No active profile (or no description) → prints nothing.
    """
    try:
        registry = load_registry()
    except Exception:
        return
    profile = core.active_profile_from_env(registry)
    if profile and profile.description:
        click.echo(profile.description)


@main.command("export")
@click.argument("output", required=False, default=None, type=click.Path())
@click.option("--password", "password", default=None, help="Zip password (prompted if omitted).")
def export_cmd(output: str | None, password: str | None) -> None:
    """Export profiles registry + settings to a password-protected zip.

    Creates OUTPUT (default: textaccounts-YYYYMMDD.zip) and a .sha256 hash file
    alongside it. The zip contains profiles.yaml and each profile's .claude.json
    and settings.json. Auth tokens are NOT included (they live in the Keychain).
    """
    from datetime import date as _date
    registry = load_registry()

    if output is None:
        today = _date.today().strftime("%Y%m%d")
        output = f"textaccounts-{today}.zip"

    out_path = Path(output).expanduser().resolve()

    if password is None:
        password = click.prompt("Zip password", hide_input=True, confirmation_prompt=True)
    if not password:
        raise click.UsageError("Password must not be empty.")

    zip_path = core.export_profiles(registry, out_path, password)
    hash_path = zip_path.with_name(zip_path.name + ".sha256")
    console.print(f"[green]Exported[/green] → {zip_path}")
    console.print(f"[green]Hash[/green]    → {hash_path}")


@main.command("import")
@click.argument("zipfile", type=click.Path(exists=True))
@click.option("--password", "password", default=None, help="Zip password (prompted if omitted).")
@click.option("--overwrite", is_flag=True, help="Overwrite existing profiles with the same name.")
def import_cmd(zipfile: str, password: str | None, overwrite: bool) -> None:
    """Import profiles from a textaccounts export zip.

    Merges profiles from ZIPFILE into the current registry. Existing profiles
    are skipped unless --overwrite is passed. Auth tokens are not restored
    (re-authenticate with `textaccounts switch` after import).
    """
    registry = load_registry()

    if password is None:
        password = click.prompt("Zip password", hide_input=True)
    if not password:
        raise click.UsageError("Password must not be empty.")

    imported, skipped = core.import_profiles(Path(zipfile), password, registry, overwrite=overwrite)
    save_registry(registry)

    if imported:
        console.print(f"[green]Imported[/green] {len(imported)} profile(s): {', '.join(imported)}")
    if skipped:
        console.print(
            f"[yellow]Skipped[/yellow] {len(skipped)} existing profile(s): {', '.join(skipped)}"
            f" [dim](use --overwrite to replace)[/dim]"
        )
    if not imported and not skipped:
        console.print("[dim]Nothing to import.[/dim]")


@main.command()
def view() -> None:
    """Launch the interactive profile view."""
    from textaccounts.view import TextAccountsApp
    TextAccountsApp().run()


_MIN_CLAUDE_VERSION = (2, 1, 56)


def _claude_version() -> tuple[int, int, int] | None:
    """Return the running claude binary's (major, minor, patch), or None."""
    import shutil
    if not shutil.which("claude"):
        return None
    try:
        out = _sp.check_output(
            ["claude", "--version"], stderr=_sp.DEVNULL, text=True, timeout=5
        ).strip()
    except (_sp.SubprocessError, OSError):
        return None
    import re
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", out)
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


@main.command()
def doctor() -> None:
    """Check for stale profile paths and verify Claude Code version supports per-profile keychain isolation.

    Exits 0 if clean, 1 if any profile path is stale.
    """
    registry = load_registry()
    stale = []
    for name, profile in registry.profiles.items():
        if profile.path.is_dir():
            console.print(f"[green]OK[/green]     {name}  {profile.path}")
        else:
            console.print(f"[red]STALE[/red]  {name}  {profile.path}")
            stale.append(name)

    version = _claude_version()
    min_str = ".".join(str(n) for n in _MIN_CLAUDE_VERSION)
    if version is None:
        console.print(
            f"[yellow]WARN[/yellow]   claude binary not found on PATH — cannot verify keychain isolation support (need ≥ v{min_str})"
        )
    elif version < _MIN_CLAUDE_VERSION:
        v_str = ".".join(str(n) for n in version)
        console.print(
            f"[red]WARN[/red]   claude v{v_str} < v{min_str} — OAuth tokens are SHARED across profiles (issue #20553). "
            f"Upgrade Claude Code to get per-CLAUDE_CONFIG_DIR keychain isolation."
        )
    else:
        v_str = ".".join(str(n) for n in version)
        console.print(
            f"[green]OK[/green]     claude v{v_str} ≥ v{min_str} — per-profile keychain isolation supported"
        )

    if stale:
        raise SystemExit(1)


@main.command()
@click.option("--max-age", "max_age", default=f"{core.DEFAULT_GC_MAX_AGE_DAYS}d",
              show_default=True,
              help="Sweep ephemeral profiles older than this. Format: <N>d for days, e.g. 7d.")
@click.option("--owner", "owner", default=None,
              help="Restrict sweep to profiles with this owner ID.")
@click.option("--dry-run", "dry_run", is_flag=True,
              help="List what would be removed without removing anything.")
def gc(max_age: str, owner: str | None, dry_run: bool) -> None:
    """Sweep ephemeral profiles. Refuses to touch anything not flagged ephemeral."""
    if not max_age.endswith("d") or not max_age[:-1].isdigit():
        raise click.UsageError(f"--max-age must be of the form <N>d (got: {max_age})")
    max_age_days = int(max_age[:-1])

    registry = load_registry()
    removed = core.gc(registry, max_age_days=max_age_days, owner=owner, dry_run=dry_run)

    if not removed:
        scope = f" (owner={owner})" if owner else ""
        console.print(f"[dim]No ephemeral profiles older than {max_age_days}d{scope}.[/dim]")
        return

    verb = "Would remove" if dry_run else "Removed"
    color = "yellow" if dry_run else "red"
    for profile in removed:
        owner_tag = f" owner={profile.owner}" if profile.owner else ""
        console.print(
            f"[{color}]{verb}[/{color}]  [bold]{profile.name}[/bold]  "
            f"[dim]{profile.path}{owner_tag}  adopted={profile.adopted or '?'}[/dim]"
        )

    if not dry_run:
        save_registry(registry)
    console.print(
        f"\n[dim]Audit log: {core.GC_LOG_PATH}[/dim]"
    )


@main.command()
@click.argument("name", shell_complete=_complete_profile_names)
def destroy(name: str) -> None:
    """Remove a single ephemeral profile (refuses non-ephemeral)."""
    registry = load_registry()
    profile = core.destroy(name, registry)
    save_registry(registry)
    console.print(
        f"[red]Destroyed[/red] [bold]{profile.name}[/bold]  [dim]{profile.path}[/dim]"
    )
    console.print(f"[dim]Audit log: {core.GC_LOG_PATH}[/dim]")


@main.command("repos")
def repos_cmd() -> None:
    """Print all registered profiles as parseable REPO lines."""
    registry = load_registry()
    active = core.active_profile_from_env(registry)
    active_name = active.name if active else None
    for name, profile in registry.profiles.items():
        active_flag = "active" if name == active_name else ""
        parts = ["REPO", name, str(profile.path)]
        if active_flag:
            parts.append(active_flag)
        click.echo("  ".join(parts))


@main.group("repo")
def repo_group() -> None:
    """Subcommands for managing profile paths."""


@repo_group.command("move")
@click.argument("name")
@click.argument("new_path", type=click.Path())
def repo_move(name: str, new_path: str) -> None:
    """Update a profile's registered path (does not move files on disk)."""
    registry = load_registry()
    canonical = core.resolve_profile(name, registry)
    dest = Path(new_path).expanduser().resolve()
    if not dest.is_dir():
        raise click.UsageError(f"Directory not found: {dest}")
    registry.profiles[canonical].path = dest
    save_registry(registry)
    console.print(f"[green]MOVED[/green]  {canonical}  →  {dest}")


@main.command()
@click.option("--shell", "shell_name", default=None,
              type=click.Choice(["fish", "bash", "zsh"]),
              help="Shell to install for (default: auto-detect).")
def install(shell_name: str | None) -> None:
    """Install shell integration (function + completions + ta alias)."""
    import os

    if shell_name is None:
        login_shell = os.environ.get("SHELL", "")
        if "fish" in login_shell:
            shell_name = "fish"
        elif "zsh" in login_shell:
            shell_name = "zsh"
        elif "bash" in login_shell:
            shell_name = "bash"
        else:
            raise click.UsageError(
                f"Could not auto-detect shell (SHELL={login_shell}). "
                "Pass --shell explicitly."
            )

    if shell_name == "fish":
        _install_fish()
    elif shell_name in ("bash", "zsh"):
        _install_posix(shell_name)


def _generate_click_completions(shell: str) -> str:
    """Generate completion script for `shell`. For bash/zsh, delegate to Click
    (its wrappers match its runtime output). For fish, use our corrected
    wrapper — see _FISH_CLICK_WRAPPER for the reason."""
    if shell == "fish":
        return _FISH_CLICK_WRAPPER
    import os as _os
    env = _os.environ.copy()
    env["_TEXTACCOUNTS_COMPLETE"] = f"{shell}_source"
    return _sp.check_output(["textaccounts"], env=env, text=True)


def _install_fish() -> None:
    fn_dir = Path.home() / ".config" / "fish" / "functions"
    comp_dir = Path.home() / ".config" / "fish" / "completions"
    fn_dir.mkdir(parents=True, exist_ok=True)
    comp_dir.mkdir(parents=True, exist_ok=True)

    fn_path = fn_dir / "textaccounts.fish"
    comp_path = comp_dir / "textaccounts.fish"
    ta_fn_path = fn_dir / "ta.fish"

    fn_path.write_text(_FISH_FUNCTION)
    ta_fn_path.write_text(_FISH_TA_FUNCTION)
    comp_path.write_text(_generate_click_completions("fish") + _FISH_SWITCH_COMPLETIONS)

    console.print(f"[green]Installed[/green] fish function → {fn_path}")
    console.print(f"[green]Installed[/green] ta alias     → {ta_fn_path}")
    console.print(f"[green]Installed[/green] completions  → {comp_path}")
    console.print(f"\nOpen a new shell or run: [bold]source {fn_path}[/bold]")
    console.print(
        "\n[dim]Claude Code statusline:[/dim] set in [bold]~/.claude/settings.json[/bold]:\n"
        '  [bold]"statusLine": {"type": "command", "command": "textaccounts desc"}[/bold]'
    )


def _install_posix(shell_name: str) -> None:
    """Install for bash or zsh per paperworlds CONVENTIONS.yaml:
      bash: ~/.local/share/bash-completion/completions/textaccounts
      zsh:  ~/.zfunc/_textaccounts
    The shell wrapper function (switch magic + ta alias) stays in
    ~/.local/paperworlds/textaccounts/shell.<shell> and must be sourced from ~/.bashrc or ~/.zshrc."""
    ta_dir = Path.home() / ".local" / "paperworlds" / "textaccounts"
    ta_dir.mkdir(parents=True, exist_ok=True)

    if shell_name == "zsh":
        fn_content = _ZSH_FUNCTION
        switch_extra = _ZSH_SWITCH_COMPLETIONS
        comp_dir = Path.home() / ".zfunc"
        comp_path = comp_dir / "_textaccounts"
        rc_file = "~/.zshrc"
        rc_hint = 'fpath=(~/.zfunc $fpath) && autoload -U compinit && compinit'
    else:
        fn_content = _BASH_FUNCTION
        switch_extra = _BASH_SWITCH_COMPLETIONS
        comp_dir = Path.home() / ".local" / "share" / "bash-completion" / "completions"
        comp_path = comp_dir / "textaccounts"
        rc_file = "~/.bashrc"
        rc_hint = ""  # bash-completion picks up files in this dir automatically

    comp_dir.mkdir(parents=True, exist_ok=True)
    fn_path = ta_dir / f"shell.{shell_name}"
    fn_path.write_text(fn_content)
    comp_path.write_text(_generate_click_completions(shell_name) + switch_extra)

    console.print(f"[green]Installed[/green] {shell_name} wrapper     → {fn_path}")
    console.print(f"[green]Installed[/green] {shell_name} completions → {comp_path}")
    console.print(f"\nAdd this to {rc_file}:")
    console.print(f'  [bold]source "{fn_path}"[/bold]')
    if rc_hint:
        console.print(f"  [bold]{rc_hint}[/bold]")
