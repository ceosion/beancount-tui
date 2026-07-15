"""Modal form for creating or editing a transaction.

The form assembles Beancount source text and validates it with the real
Beancount parser before handing it back to the app, so anything the form
accepts is guaranteed to be syntactically valid.
"""

from __future__ import annotations

import datetime

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static, TextArea

from beancount_tui.editor import TransactionParseError, parse_transaction_text


class TransactionForm(ModalScreen[str | None]):
    """Returns the transaction's source text, or ``None`` if cancelled."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    DEFAULT_CSS = """
    TransactionForm {
        align: center middle;
    }
    TransactionForm > Vertical {
        width: 80;
        height: auto;
        max-height: 90%;
        border: round $primary;
        padding: 1 2;
        background: $surface;
    }
    TransactionForm .field-label {
        margin-top: 1;
        color: $text-muted;
    }
    TransactionForm #postings {
        height: 8;
    }
    TransactionForm #error {
        color: $error;
        height: auto;
    }
    TransactionForm #buttons {
        height: auto;
        align-horizontal: right;
        margin-top: 1;
    }
    TransactionForm Button {
        margin-left: 2;
    }
    """

    def __init__(
        self,
        *,
        date: str | None = None,
        payee: str = "",
        narration: str = "",
        postings_text: str = "",
        title: str = "New transaction",
    ) -> None:
        super().__init__()
        self._date = date or datetime.date.today().isoformat()
        self._payee = payee
        self._narration = narration
        self._postings_text = postings_text
        self._title = title

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(f"[b]{self._title}[/b]")
            yield Label("Date", classes="field-label")
            yield Input(value=self._date, id="date", placeholder="YYYY-MM-DD")
            yield Label("Payee", classes="field-label")
            yield Input(value=self._payee, id="payee", placeholder="(optional)")
            yield Label("Narration", classes="field-label")
            yield Input(value=self._narration, id="narration")
            yield Label("Postings (one per line: ACCOUNT  AMOUNT CURRENCY)", classes="field-label")
            yield TextArea(self._postings_text, id="postings")
            yield Static("", id="error")
            with Horizontal(id="buttons"):
                yield Button("Cancel", id="cancel")
                yield Button("Save", id="save", variant="primary")

    def _assemble_text(self) -> str:
        date = self.query_one("#date", Input).value.strip()
        payee = self.query_one("#payee", Input).value.strip()
        narration = self.query_one("#narration", Input).value.strip()
        postings = self.query_one("#postings", TextArea).text

        quoted_payee = f' "{payee}"' if payee else ""
        header = f'{date} *{quoted_payee} "{narration}"'
        body = "\n".join(
            "  " + line.strip() for line in postings.splitlines() if line.strip()
        )
        return f"{header}\n{body}\n"

    def _save(self) -> None:
        text = self._assemble_text()
        try:
            parse_transaction_text(text)
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
