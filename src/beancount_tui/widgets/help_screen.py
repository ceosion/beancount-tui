"""Modal help screen: lists all top-level app key bindings."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Label


class HelpScreen(ModalScreen[None]):
    """Read-only list of key bindings; Escape or the Close button dismisses it."""

    BINDINGS = [("escape", "close", "Close")]

    DEFAULT_CSS = """
    HelpScreen {
        align: center middle;
    }
    HelpScreen > Vertical {
        width: 60;
        height: auto;
        max-height: 90%;
        border: round $primary;
        padding: 1 2;
        background: $surface;
    }
    HelpScreen #bindings {
        height: auto;
        max-height: 24;
        margin-top: 1;
    }
    HelpScreen #close {
        margin-top: 1;
        width: auto;
    }
    """

    def __init__(self, bindings: list[tuple[str, str, str]]) -> None:
        super().__init__()
        self._app_bindings = bindings

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("[b]Key bindings[/b]")
            yield DataTable(id="bindings", cursor_type="none")
            yield Button("Close", id="close")

    def on_mount(self) -> None:
        table = self.query_one("#bindings", DataTable)
        table.add_columns("Key", "Action")
        for key, _action, description in self._app_bindings:
            table.add_row(key, description)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close":
            self.action_close()

    def action_close(self) -> None:
        self.dismiss(None)
