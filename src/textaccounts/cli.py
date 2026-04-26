from __future__ import annotations

import subprocess as _sp
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from textaccounts import __version__
from textaccounts.config import load_registry, save_registry
from textaccounts import core

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


@main.command("create")
@click.argument("name")
@click.option("--worker", is_flag=True, help="Create a minimal worker profile.")
@click.option("--from", "parent", default=None, help="Parent profile name (required with --worker).")
@click.option("--clone-from", "clone_from", default=None,
              help="Clone setup from another profile (auth + settings + agents/hooks/plugins, stripped of state).")
def create(name: str, worker: bool, parent: str | None, clone_from: str | None) -> None:
    """Create a new profile from the current config, as a worker, or by cloning another profile."""
    registry = load_registry()
    if worker and clone_from:
        raise click.UsageError("--worker and --clone-from are mutually exclusive")
    if worker:
        if not parent:
            raise click.UsageError("--from <parent> is required with --worker")
        profile = core.create_worker(name, parent, registry)
        save_registry(registry)
        console.print(
            f"[green]Created[/green] worker profile [bold]{profile.name}[/bold]"
            f" (parent: {profile.parent})"
        )
    elif clone_from:
        profile = core.clone_profile(name, clone_from, registry)
        save_registry(registry)
        console.print(
            f"[green]Cloned[/green] [bold]{clone_from}[/bold] → [bold]{profile.name}[/bold]"
            f" at {profile.path} [dim](stripped of sessions/history/caches)[/dim]"
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
        tags = "\\[worker]" if p["worker"] else ""
        table.add_row(
            active_marker,
            p["name"],
            str(p["path"]),
            p["email"] or "",
            f"{size_kb}K",
            tags,
        )

    console.print(table)


@main.command()
@click.argument("old_name")
@click.argument("new_name")
def rename(old_name: str, new_name: str) -> None:
    """Rename a profile."""
    registry = load_registry()
    profile = core.rename(old_name, new_name, registry)
    save_registry(registry)
    console.print(f"[green]Renamed[/green] [bold]{old_name}[/bold] → [bold]{profile.name}[/bold]")


@main.command()
@click.argument("profile_name")
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
@click.argument("name")
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
@click.argument("name")
@click.argument("text", required=False, default="")
def describe(name: str, text: str) -> None:
    """Set (or clear) the description for a profile."""
    from textaccounts.core import _write_active_description
    registry = load_registry()
    canonical = core.resolve_profile(name, registry)
    registry.profiles[canonical].description = text.strip()
    save_registry(registry)
    if registry.active == canonical:
        _write_active_description(text.strip())
    if text.strip():
        console.print(f"[green]Set[/green] description for [bold]{canonical}[/bold]: {text.strip()}")
    else:
        console.print(f"[yellow]Cleared[/yellow] description for [bold]{canonical}[/bold]")


@main.command()
def desc() -> None:
    """Print the active profile's description (for statusline integration).

    Resolves the profile in this order:
      1. $CLAUDE_CONFIG_DIR matches a registered profile (works for subprocesses
         launched by textsessions, where the env var is set directly).
      2. The registry's `active` field.
      3. Cache file written by `textaccounts switch`.
    """
    import os
    from pathlib import Path as _Path
    from textaccounts.core import _ACTIVE_DESC_FILE

    env_dir = os.environ.get("CLAUDE_CONFIG_DIR")
    if env_dir:
        try:
            registry = load_registry()
            target = _Path(env_dir).resolve()
            for profile in registry.profiles.values():
                if profile.path.resolve() == target:
                    if profile.description:
                        click.echo(profile.description)
                    return
        except Exception:
            pass

    try:
        registry = load_registry()
        if registry.active:
            profile = registry.profiles.get(registry.active)
            if profile and profile.description:
                click.echo(profile.description)
                return
    except Exception:
        pass

    if _ACTIVE_DESC_FILE.exists():
        text = _ACTIVE_DESC_FILE.read_text().strip()
        if text:
            click.echo(text)


@main.command()
def view() -> None:
    """Launch the interactive profile view."""
    from textaccounts.view import TextAccountsApp
    TextAccountsApp().run()


_FISH_FUNCTION = """\
# textaccounts — shell integration
# Wraps the Python CLI so that `textaccounts switch` sets CLAUDE_CONFIG_DIR
# and CLAUDE_PROFILE in the current shell. All other subcommands pass through.
# Installed by: textaccounts install

function textaccounts --description "Manage Claude Code profiles"
    if test (count $argv) -ge 1; and test "$argv[1]" = "switch"
        eval (command textaccounts show --shell fish $argv[2..-1])
    else
        command textaccounts $argv
    end
end
"""


_FISH_COMPLETIONS = """\
# textaccounts completions for fish shell
# Installed by: textaccounts install

function __textaccounts_profiles
    if test -f ~/.textaccounts/profiles.yaml
        grep -E '^\\s{2}[a-zA-Z0-9_-]+:' ~/.textaccounts/profiles.yaml | sed 's/^[[:space:]]*//; s/:.*$//' 2>/dev/null
    end
end

set -l __ta_cmds adopt alias create doctor install list rename repo repos show status switch view

complete -c textaccounts -f -n "not __fish_seen_subcommand_from $__ta_cmds" -a "adopt" -d "Register existing dir as profile"
complete -c textaccounts -f -n "not __fish_seen_subcommand_from $__ta_cmds" -a "doctor" -d "Check for stale profile paths"
complete -c textaccounts -f -n "not __fish_seen_subcommand_from $__ta_cmds" -a "repo" -d "Manage profile paths"
complete -c textaccounts -f -n "not __fish_seen_subcommand_from $__ta_cmds" -a "repos" -d "Print all profiles as REPO lines"
complete -c textaccounts -f -n "not __fish_seen_subcommand_from $__ta_cmds" -a "alias" -d "Add or remove a profile alias"
complete -c textaccounts -f -n "not __fish_seen_subcommand_from $__ta_cmds" -a "create" -d "Create a new profile"
complete -c textaccounts -f -n "not __fish_seen_subcommand_from $__ta_cmds" -a "install" -d "Install shell integration"
complete -c textaccounts -f -n "not __fish_seen_subcommand_from $__ta_cmds" -a "list" -d "Show all profiles"
complete -c textaccounts -f -n "not __fish_seen_subcommand_from $__ta_cmds" -a "rename" -d "Rename a profile"
complete -c textaccounts -f -n "not __fish_seen_subcommand_from $__ta_cmds" -a "show" -d "Print shell command for a profile"
complete -c textaccounts -f -n "not __fish_seen_subcommand_from $__ta_cmds" -a "status" -d "Show active profile info"
complete -c textaccounts -f -n "not __fish_seen_subcommand_from $__ta_cmds" -a "switch" -d "Switch to a profile"
complete -c textaccounts -f -n "not __fish_seen_subcommand_from $__ta_cmds" -a "view" -d "Launch interactive view"

complete -c textaccounts -f -n "__fish_seen_subcommand_from switch" -a "(__textaccounts_profiles)" -d "Profile"
complete -c textaccounts -f -n "__fish_seen_subcommand_from switch" -a "default" -d "Unset CLAUDE_CONFIG_DIR"
complete -c textaccounts -f -n "__fish_seen_subcommand_from show" -a "(__textaccounts_profiles)" -d "Profile"
complete -c textaccounts -f -n "__fish_seen_subcommand_from show" -a "default" -d "Unset CLAUDE_CONFIG_DIR"
complete -c textaccounts -f -n "__fish_seen_subcommand_from rename" -a "(__textaccounts_profiles)" -d "Profile"
complete -c textaccounts -f -n "__fish_seen_subcommand_from alias" -a "(__textaccounts_profiles)" -d "Profile"
complete -c textaccounts -n "__fish_seen_subcommand_from alias" -l remove -d "Remove the alias"

complete -c textaccounts -n "__fish_seen_subcommand_from create" -f
complete -c textaccounts -n "__fish_seen_subcommand_from create" -l worker -d "Create worker profile"
complete -c textaccounts -n "__fish_seen_subcommand_from create" -l from -d "Parent profile"

complete -c textaccounts -n "__fish_seen_subcommand_from install" -l shell -d "Shell type" -a "fish bash zsh"
"""

_FISH_TA_FUNCTION = """\
# ta — shorthand for textaccounts (with switch support)
# Installed by: textaccounts install

function ta --wraps=textaccounts --description 'textaccounts shortcut'
    textaccounts $argv
end
"""

_FISH_TA_COMPLETIONS = """\
# ta completions — mirrors textaccounts completions
# Installed by: textaccounts install

complete -c ta --wraps textaccounts
"""

# -- Bash / Zsh templates ---------------------------------------------------

_BASH_FUNCTION = """\
# textaccounts — shell integration
# Wraps the Python CLI so that `textaccounts switch` sets CLAUDE_CONFIG_DIR
# in the current shell. All other subcommands pass through.
# Installed by: textaccounts install
# Source this from ~/.bashrc

textaccounts() {
    if [ "$1" = "switch" ]; then
        eval "$(command textaccounts show --shell bash "${@:2}")"
    else
        command textaccounts "$@"
    fi
}

ta() { textaccounts "$@"; }
"""

_BASH_COMPLETIONS = """\
# textaccounts completions for bash
# Installed by: textaccounts install
# Source this from ~/.bashrc

_textaccounts_profiles() {
    if [ -f ~/.textaccounts/profiles.yaml ]; then
        grep -E '^  [a-zA-Z0-9_-]+:' ~/.textaccounts/profiles.yaml | sed 's/^[[:space:]]*//; s/:.*$//' 2>/dev/null
    fi
}

_textaccounts_complete() {
    local cur prev cmds
    COMPREPLY=()
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"
    cmds="adopt alias create doctor install list rename repo repos show status switch view"

    if [ "$COMP_CWORD" -eq 1 ]; then
        COMPREPLY=( $(compgen -W "$cmds" -- "$cur") )
    elif [ "$prev" = "switch" ] || [ "$prev" = "show" ]; then
        local profiles
        profiles="$(_textaccounts_profiles) default"
        COMPREPLY=( $(compgen -W "$profiles" -- "$cur") )
    fi
}

complete -F _textaccounts_complete textaccounts
complete -F _textaccounts_complete ta
"""

_ZSH_FUNCTION = """\
# textaccounts — shell integration
# Wraps the Python CLI so that `textaccounts switch` sets CLAUDE_CONFIG_DIR
# in the current shell. All other subcommands pass through.
# Installed by: textaccounts install
# Source this from ~/.zshrc

textaccounts() {
    if [[ "$1" == "switch" ]]; then
        eval "$(command textaccounts show --shell zsh "${@:2}")"
    else
        command textaccounts "$@"
    fi
}

ta() { textaccounts "$@"; }
"""

_ZSH_COMPLETIONS = """\
# textaccounts completions for zsh
# Installed by: textaccounts install
# Source this from ~/.zshrc

_textaccounts_profiles() {
    if [[ -f ~/.textaccounts/profiles.yaml ]]; then
        grep -E '^  [a-zA-Z0-9_-]+:' ~/.textaccounts/profiles.yaml | sed 's/^[[:space:]]*//; s/:.*$//' 2>/dev/null
    fi
}

_textaccounts() {
    local -a cmds profiles
    cmds=(adopt alias create doctor install list rename repo repos show status switch view)

    if (( CURRENT == 2 )); then
        _describe 'command' cmds
    elif [[ "${words[2]}" == "switch" || "${words[2]}" == "show" ]]; then
        profiles=($(_textaccounts_profiles) default)
        _describe 'profile' profiles
    fi
}

compdef _textaccounts textaccounts
compdef _textaccounts ta
"""


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


@main.command("repos")
def repos_cmd() -> None:
    """Print all registered profiles as parseable REPO lines."""
    registry = load_registry()
    for name, profile in registry.profiles.items():
        active_flag = "active" if name == registry.active else ""
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


def _install_fish() -> None:
    fish_fn_dir = Path.home() / ".config" / "fish" / "functions"
    fish_comp_dir = Path.home() / ".config" / "fish" / "completions"
    fish_fn_dir.mkdir(parents=True, exist_ok=True)
    fish_comp_dir.mkdir(parents=True, exist_ok=True)

    fn_path = fish_fn_dir / "textaccounts.fish"
    comp_path = fish_comp_dir / "textaccounts.fish"
    ta_fn_path = fish_fn_dir / "ta.fish"
    ta_comp_path = fish_comp_dir / "ta.fish"

    fn_path.write_text(_FISH_FUNCTION)
    comp_path.write_text(_FISH_COMPLETIONS)
    ta_fn_path.write_text(_FISH_TA_FUNCTION)
    ta_comp_path.write_text(_FISH_TA_COMPLETIONS)

    console.print(f"[green]Installed[/green] fish function → {fn_path}")
    console.print(f"[green]Installed[/green] completions  → {comp_path}")
    console.print(f"[green]Installed[/green] ta alias     → {ta_fn_path}")
    console.print(f"\nOpen a new shell or run: [bold]source {fn_path}[/bold]")
    console.print(
        "\n[dim]Claude Code statusline:[/dim] add [bold]$(textaccounts desc 2>/dev/null)[/bold] "
        "to your statusline script, or set:\n"
        '  [bold]"statusLine": {"type": "command", "command": "textaccounts desc"}[/bold]\n'
        "in [bold]~/.claude/settings.json[/bold]"
    )


def _install_posix(shell_name: str) -> None:
    ta_dir = Path.home() / ".textaccounts"
    ta_dir.mkdir(parents=True, exist_ok=True)

    if shell_name == "zsh":
        fn_content = _ZSH_FUNCTION
        comp_content = _ZSH_COMPLETIONS
        rc_file = "~/.zshrc"
    else:
        fn_content = _BASH_FUNCTION
        comp_content = _BASH_COMPLETIONS
        rc_file = "~/.bashrc"

    fn_path = ta_dir / f"shell.{shell_name}"
    fn_path.write_text(fn_content + "\n" + comp_content)

    console.print(f"[green]Installed[/green] {shell_name} integration → {fn_path}")
    console.print(f"\nAdd this to {rc_file}:")
    console.print(f'  [bold]source "{fn_path}"[/bold]')
