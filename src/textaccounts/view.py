"""Interactive profile view for textaccounts."""

from __future__ import annotations

from pathlib import Path
from typing import TypeVar

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Footer, Header, Input, Label, Static

_T = TypeVar("_T")

from textaccounts import core
from textaccounts.config import CONFIG_PATH, extract_email, load_registry, save_registry

_HOME = Path.home()


def _fmt_size(size_bytes: int) -> str:
    kb = size_bytes // 1024
    return f"{kb // 1024}M" if kb > 1024 else f"{kb}K"


def _short_path(path: Path) -> str:
    try:
        return "~/" + str(path.relative_to(_HOME))
    except ValueError:
        return str(path)


def _render_detail(profile: dict | None, suggestion: Path | None) -> str:
    if suggestion is not None:
        email = extract_email(suggestion) if suggestion.is_dir() else ""
        lines = [
            "[dim]Not yet adopted[/dim]",
            "",
            f"[bold]{_short_path(suggestion)}[/bold]",
        ]
        if email:
            lines.append(f"Email: {email}")
        lines += [
            "",
            "Press [bold]a[/bold] to adopt this directory.",
            f"Suggested name: [bold]{suggestion.name.lstrip('.')}[/bold]",
        ]
        return "\n".join(lines)

    if profile is None:
        return (
            "[dim]No profiles registered.[/dim]\n\n"
            "Press [bold]a[/bold] to adopt an existing Claude config dir.\n\n"
            "textaccounts looks for dirs like:\n"
            "  ~/.claude/\n"
            "  ~/.claude-work/\n"
            "  ~/.claude-personal/"
        )

    lines = []
    if not profile["exists"]:
        lines.append("[bold red]✗ path not found[/bold red]")
    elif profile["active"]:
        lines.append("[bold green]● active[/bold green]")
    lines.append(f"[bold]{profile['name']}[/bold]")
    lines.append(f"Path:     {_short_path(profile['path'])}")
    if profile["email"]:
        lines.append(f"Email:    {profile['email']}")
    if profile["exists"]:
        lines.append(f"Sessions: {profile['sessions']}")
        lines.append(f"Size:     {_fmt_size(profile['dir_size'])}")
    if profile.get("aliases"):
        lines.append(f"Aliases:  {', '.join(profile['aliases'])}")
    if profile["worker"]:
        lines.append("[dim]worker (auth-only copy)[/dim]")
    return "\n".join(lines)


class _ModalBase(ModalScreen[_T]):
    """Shared behaviour for single-action modal dialogs."""

    BINDINGS = [Binding("escape", "dismiss(None)", "Cancel")]
    _PRIMARY_BTN: str = ""

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == self._PRIMARY_BTN:
            self._submit()
        else:
            self.dismiss(None)

    def on_input_submitted(self, _: Input.Submitted) -> None:
        self._submit()

    def _submit(self) -> None:
        raise NotImplementedError


class AdoptModal(_ModalBase["tuple[str, str] | None"]):
    _PRIMARY_BTN = "adopt-btn"
    _NAME_INPUT = "name-input"
    _PATH_INPUT = "path-input"

    def __init__(self, name_hint: str = "", path_hint: str = "") -> None:
        super().__init__()
        self._name_hint = name_hint
        self._path_hint = path_hint

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label("[bold]Adopt existing Claude config dir[/bold]", id="title")
            yield Label("Profile name:")
            yield Input(placeholder="e.g. work", value=self._name_hint, id=self._NAME_INPUT)
            yield Label("Path:")
            yield Input(placeholder="e.g. ~/.claude-work", value=self._path_hint, id=self._PATH_INPUT)
            with Horizontal(id="buttons"):
                yield Button("Adopt", variant="primary", id=self._PRIMARY_BTN)
                yield Button("Cancel", id="cancel-btn")

    def on_mount(self) -> None:
        if self._name_hint:
            self.query_one(f"#{self._PATH_INPUT}", Input).focus()
        else:
            self.query_one(f"#{self._NAME_INPUT}", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == self._NAME_INPUT:
            self.query_one(f"#{self._PATH_INPUT}", Input).focus()
        else:
            self._submit()

    def _submit(self) -> None:
        name = self.query_one(f"#{self._NAME_INPUT}", Input).value.strip()
        path = self.query_one(f"#{self._PATH_INPUT}", Input).value.strip()
        self.dismiss((name, path) if name and path else None)


class AliasModal(_ModalBase["str | None"]):
    """Modal to edit aliases (comma-separated)."""

    _PRIMARY_BTN = "save-btn"
    _ALIAS_INPUT = "alias-input"

    def __init__(self, profile_name: str, current_aliases: list[str]) -> None:
        super().__init__()
        self._profile_name = profile_name
        self._current = ", ".join(current_aliases)

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(f"[bold]Aliases for {self._profile_name}[/bold]", id="title")
            yield Label("Comma-separated aliases (leave empty to clear):")
            yield Input(value=self._current, id=self._ALIAS_INPUT)
            with Horizontal(id="buttons"):
                yield Button("Save", variant="primary", id=self._PRIMARY_BTN)
                yield Button("Cancel", id="cancel-btn")

    def on_mount(self) -> None:
        self.query_one(f"#{self._ALIAS_INPUT}", Input).focus()

    def _submit(self) -> None:
        self.dismiss(self.query_one(f"#{self._ALIAS_INPUT}", Input).value)


class RenameModal(_ModalBase["str | None"]):
    """Modal to rename a profile."""

    _PRIMARY_BTN = "rename-btn"
    _RENAME_INPUT = "rename-input"

    def __init__(self, current_name: str) -> None:
        super().__init__()
        self._current_name = current_name

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(f"[bold]Rename {self._current_name}[/bold]", id="title")
            yield Label("New name:")
            yield Input(value=self._current_name, id=self._RENAME_INPUT)
            with Horizontal(id="buttons"):
                yield Button("Rename", variant="primary", id=self._PRIMARY_BTN)
                yield Button("Cancel", id="cancel-btn")

    def on_mount(self) -> None:
        self.query_one(f"#{self._RENAME_INPUT}", Input).focus()

    def _submit(self) -> None:
        value = self.query_one(f"#{self._RENAME_INPUT}", Input).value.strip()
        self.dismiss(value if value else None)


class TextAccountsApp(App):
    CSS = """
    Screen { layout: horizontal; }
    #profiles {
        width: 3fr;
        border: solid $primary;
    }
    #detail {
        width: 2fr;
        padding: 1 2;
        border: solid $surface;
    }
    _ModalBase #dialog {
        width: 60;
        padding: 1 2;
        background: $surface;
        border: solid $primary;
        margin: 4 8;
    }
    _ModalBase #title { margin-bottom: 1; }
    _ModalBase #buttons { margin-top: 1; align-horizontal: right; }
    """

    TITLE = "textaccounts"

    BINDINGS = [
        Binding("s", "switch_profile", "Switch"),
        Binding("a", "adopt", "Adopt"),
        Binding("l", "edit_aliases", "Aliases"),
        Binding("r", "rename_profile", "Rename"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, config_path: Path = CONFIG_PATH) -> None:
        super().__init__()
        self._config_path = config_path
        self._profiles: list[dict] = []
        self._suggestions: list[Path] = []

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            yield DataTable(id="profiles", cursor_type="row")
            yield Static(id="detail")
        yield Footer()

    def on_mount(self) -> None:
        self._refresh()

    def _refresh(self) -> None:
        registry = load_registry(self._config_path)
        self._profiles = core.list_profiles(registry)
        self._suggestions = core.discover_unregistered(registry)

        table = self.query_one(DataTable)
        table.clear(columns=True)
        table.add_columns("", "Name", "Path", "Email", "Sessions", "Size")

        for p in self._profiles:
            if not p["exists"]:
                marker = "[red]✗[/red]"
                name_col = f"[red]{p['name']}[/red]"
            elif p["active"]:
                marker = "[green]*[/green]"
                name_col = f"[bold]{p['name']}[/bold]" + (" [worker]" if p["worker"] else "")
            else:
                marker = ""
                name_col = p["name"] + (" [worker]" if p["worker"] else "")
            table.add_row(
                marker,
                name_col,
                _short_path(p["path"]),
                p["email"] or "",
                str(p["sessions"]) if p["exists"] else "—",
                _fmt_size(p["dir_size"]) if p["exists"] else "—",
            )

        for sug in self._suggestions:
            name_hint = sug.name.lstrip(".")
            table.add_row(
                "[dim]+[/dim]",
                f"[dim]{name_hint}[/dim]",
                f"[dim]{_short_path(sug)}[/dim]",
                "[dim]not adopted[/dim]",
                "[dim]—[/dim]",
                "[dim]—[/dim]",
            )

        self._update_detail()

    def _selected_profile(self) -> dict | None:
        table = self.query_one(DataTable)
        idx = table.cursor_row
        if 0 <= idx < len(self._profiles):
            return self._profiles[idx]
        return None

    def _selected_suggestion(self) -> Path | None:
        table = self.query_one(DataTable)
        idx = table.cursor_row - len(self._profiles)
        if 0 <= idx < len(self._suggestions):
            return self._suggestions[idx]
        return None

    def _update_detail(self) -> None:
        profile = self._selected_profile()
        suggestion = self._selected_suggestion() if profile is None else None
        self.query_one("#detail", Static).update(_render_detail(profile, suggestion))

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        self._update_detail()

    def action_switch_profile(self) -> None:
        profile = self._selected_profile()
        if profile is None:
            return
        if not profile["exists"]:
            self.notify("Path not found — cannot switch to a broken profile.", severity="error")
            return
        name = profile["name"]
        try:
            registry = load_registry(self._config_path)
            core.show(name, registry)
            save_registry(registry, self._config_path)
            self._refresh()
            self.notify(f"Active: {name} — run: textaccounts switch {name}", timeout=6)
        except Exception as e:
            self.notify(str(e), severity="error")

    def action_adopt(self) -> None:
        suggestion = self._selected_suggestion()
        if suggestion is not None:
            name_hint = suggestion.name.lstrip(".")
            path_hint = _short_path(suggestion)
        else:
            name_hint = ""
            path_hint = ""

        def handle(result: tuple[str, str] | None) -> None:
            if result is None:
                return
            name, path_str = result
            try:
                registry = load_registry(self._config_path)
                core.adopt(name, Path(path_str).expanduser(), registry)
                save_registry(registry, self._config_path)
                self._refresh()
                self.notify(f"Adopted: {name}")
            except Exception as e:
                self.notify(str(e), severity="error")

        self.push_screen(AdoptModal(name_hint=name_hint, path_hint=path_hint), handle)

    def action_edit_aliases(self) -> None:
        profile = self._selected_profile()
        if profile is None:
            return

        def handle(result: str | None) -> None:
            if result is None:
                return
            new_aliases = [a.strip() for a in result.split(",") if a.strip()]
            try:
                registry = load_registry(self._config_path)
                p = registry.profiles.get(profile["name"])
                if p:
                    p.aliases = new_aliases
                    save_registry(registry, self._config_path)
                    self._refresh()
                    self.notify(f"Aliases updated for {profile['name']}")
            except Exception as e:
                self.notify(str(e), severity="error")

        self.push_screen(
            AliasModal(profile["name"], profile.get("aliases", [])), handle
        )

    def action_rename_profile(self) -> None:
        profile = self._selected_profile()
        if profile is None:
            return

        def handle(result: str | None) -> None:
            if result is None or result == profile["name"]:
                return
            try:
                registry = load_registry(self._config_path)
                core.rename(profile["name"], result, registry)
                save_registry(registry, self._config_path)
                self._refresh()
                self.notify(f"Renamed: {profile['name']} → {result}")
            except Exception as e:
                self.notify(str(e), severity="error")

        self.push_screen(RenameModal(profile["name"]), handle)
