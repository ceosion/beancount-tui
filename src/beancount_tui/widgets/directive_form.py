"""Modal form for creating or editing a non-transaction directive as raw
source text.

Uses the same validation path as the transaction form: the text must parse
as exactly one directive before it is handed back to the app.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Select, Static, TextArea

from beancount_tui.editor import TransactionParseError, parse_directive_text


@dataclass
class DirectiveFormResult:
    """What the form hands back on save."""

    text: str
    filename: str | None = None  # target file for a new entry; None = caller's default


class DirectiveForm(ModalScreen[DirectiveFormResult | None]):
    """Returns a :class:`DirectiveFormResult`, or ``None`` if cancelled."""

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
    DirectiveForm .field-label {
        margin-top: 1;
        color: $text-muted;
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

    def __init__(
        self,
        text: str,
        *,
        title: str = "Edit directive",
        files: list[Path] | None = None,
    ) -> None:
        super().__init__()
        self._text = text
        self._title = title
        # Offer a target-file picker only when there is a real choice.
        self._files = files if files and len(files) > 1 else None

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(f"[b]{self._title}[/b]")
            yield TextArea(self._text, id="text")
            if self._files:
                yield Label("File", classes="field-label")
                yield Select(
                    [(self._file_label(f), str(f)) for f in self._files],
                    value=str(self._files[0]),
                    allow_blank=False,
                    id="target-file",
                )
            yield Static("", id="error")
            with Horizontal(id="buttons"):
                yield Button("Cancel", id="cancel")
                yield Button("Save", id="save", variant="primary")

    def _file_label(self, file: Path) -> str:
        assert self._files
        top_dir = self._files[0].parent
        try:
            return str(file.relative_to(top_dir))
        except ValueError:
            return str(file)

    def _save(self) -> None:
        text = self.query_one("#text", TextArea).text
        try:
            parse_directive_text(text)
        except TransactionParseError as exc:
            self.query_one("#error", Static).update(str(exc))
            return
        filename = None
        if self._files:
            filename = str(self.query_one("#target-file", Select).value)
        self.dismiss(DirectiveFormResult(text=text, filename=filename))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save":
            self._save()
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)
