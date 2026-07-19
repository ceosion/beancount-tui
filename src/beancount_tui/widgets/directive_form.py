"""Modal form for editing a non-transaction directive as raw source text.

Uses the same validation path as the transaction form: the text must parse
as exactly one directive before it is handed back to the app.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Static, TextArea

from beancount_tui.editor import TransactionParseError, parse_directive_text


class DirectiveForm(ModalScreen[str | None]):
    """Returns the directive's source text, or ``None`` if cancelled."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    DEFAULT_CSS = """
    DirectiveForm {
        align: center middle;
    }
    DirectiveForm > Vertical {
        width: 80;
        height: auto;
        max-height: 90%;
        border: round $primary;
        padding: 1 2;
        background: $surface;
    }
    DirectiveForm #text {
        height: 6;
        margin-top: 1;
    }
    DirectiveForm #error {
        color: $error;
        height: auto;
    }
    DirectiveForm #buttons {
        height: auto;
        align-horizontal: right;
        margin-top: 1;
    }
    DirectiveForm Button {
        margin-left: 2;
    }
    """

    def __init__(self, text: str, *, title: str = "Edit directive") -> None:
        super().__init__()
        self._text = text
        self._title = title

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(f"[b]{self._title}[/b]")
            yield TextArea(self._text, id="text")
            yield Static("", id="error")
            with Horizontal(id="buttons"):
                yield Button("Cancel", id="cancel")
                yield Button("Save", id="save", variant="primary")

    def _save(self) -> None:
        text = self.query_one("#text", TextArea).text
        try:
            parse_directive_text(text)
        except TransactionParseError as exc:
            self.query_one("#error", Static).update(str(exc))
            return
        self.dismiss(text)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save":
            self._save()
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)
