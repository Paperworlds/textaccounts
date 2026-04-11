from __future__ import annotations

from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from textaccounts import __version__
from textaccounts.config import load_registry, save_registry
from textaccounts import core

console = Console()


@click.group()
@click.version_option(__version__, prog_name="textaccounts")
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
def create(name: str, worker: bool, parent: str | None) -> None:
    """Create a new profile from the current config or as a worker."""
    registry = load_registry()
    if worker:
        if not parent:
            raise click.UsageError("--from <parent> is required with --worker")
        profile = core.create_worker(name, parent, registry)
        save_registry(registry)
        console.print(
            f"[green]Created[/green] worker profile [bold]{profile.name}[/bold]"
            f" (parent: {profile.parent})"
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
def show(name: str) -> None:
    """Print the shell command to activate a profile (used by shell integration)."""
    registry = load_registry()
    line = core.show(name, registry)
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
        eval (command textaccounts show $argv[2..-1])
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

set -l __ta_cmds adopt alias create install list rename show status switch view

complete -c textaccounts -f -n "not __fish_seen_subcommand_from $__ta_cmds" -a "adopt" -d "Register existing dir as profile"
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

complete -c textaccounts -n "__fish_seen_subcommand_from install" -l shell -d "Shell type" -a "fish"
"""


@main.command()
@click.option("--shell", "shell_name", default=None, help="Shell to install for (default: auto-detect).")
def install(shell_name: str | None) -> None:
    """Install shell integration (function + completions)."""
    import os

    if shell_name is None:
        login_shell = os.environ.get("SHELL", "")
        if "fish" in login_shell:
            shell_name = "fish"
        else:
            raise click.UsageError(
                f"Could not auto-detect shell (SHELL={login_shell}). "
                "Pass --shell fish explicitly."
            )

    if shell_name != "fish":
        raise click.UsageError(f"Unsupported shell: {shell_name}. Only 'fish' is supported.")

    fish_fn_dir = Path.home() / ".config" / "fish" / "functions"
    fish_comp_dir = Path.home() / ".config" / "fish" / "completions"
    fish_fn_dir.mkdir(parents=True, exist_ok=True)
    fish_comp_dir.mkdir(parents=True, exist_ok=True)

    fn_path = fish_fn_dir / "textaccounts.fish"
    comp_path = fish_comp_dir / "textaccounts.fish"

    fn_path.write_text(_FISH_FUNCTION)
    comp_path.write_text(_FISH_COMPLETIONS)

    console.print(f"[green]Installed[/green] fish function → {fn_path}")
    console.print(f"[green]Installed[/green] completions  → {comp_path}")
    console.print(f"\nOpen a new shell or run: [bold]source {fn_path}[/bold]")
