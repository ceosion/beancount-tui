"""Modal flow for loading a CSV export and mapping its columns to a
candidate transaction shape.

Two things happen in one screen, kept as simple as possible: point at a
file and preview its first few rows, then map columns to
date/amount/payee/narration and a target account. Submitting parses the
*whole* file via :func:`beancount_tui.importer.parse_csv` into an in-memory
list of :class:`~beancount_tui.importer.ImportCandidate`; nothing is
written to the ledger here — that happens in a later import stage, once
the user has had a chance to review the candidates.
"""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Input, Label, Select, Static

from beancount_tui.importer import CsvColumnMapping, ImportCandidate, parse_csv, preview_csv


class ImportForm(ModalScreen[list[ImportCandidate] | None]):
    """Returns the parsed candidate list, or ``None`` if cancelled."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    DEFAULT_CSS = """
    ImportForm {
        align: center middle;
    }
    ImportForm > Vertical {
        width: 90;
        height: auto;
        max-height: 90%;
        border: round $primary;
        padding: 1 2;
        background: $surface;
    }
    ImportForm .field-label {
        margin-top: 1;
        color: $text-muted;
    }
    ImportForm #path-row {
        height: auto;
    }
    ImportForm #path-row Input {
        width: 1fr;
    }
    ImportForm #preview {
        height: 8;
        margin-top: 1;
    }
    ImportForm #mapping-row {
        height: auto;
    }
    ImportForm #mapping-row Select {
        width: 1fr;
    }
    ImportForm #error {
        color: $error;
        height: auto;
    }
    ImportForm #buttons {
        height: auto;
        align-horizontal: right;
        margin-top: 1;
    }
    ImportForm Button {
        margin-left: 2;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._headers: list[str] = []

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("[b]Import CSV[/b]")
            yield Label("CSV file", classes="field-label")
            with Horizontal(id="path-row"):
                yield Input(placeholder="/path/to/export.csv", id="path")
                yield Button("Load preview", id="load")
            yield DataTable(id="preview", show_cursor=False)
            yield Label("Column mapping", classes="field-label")
            with Horizontal(id="mapping-row"):
                yield Select([], allow_blank=True, prompt="Date column", id="col-date")
                yield Select([], allow_blank=True, prompt="Amount column", id="col-amount")
                yield Select(
                    [], allow_blank=True, prompt="Payee column (optional)", id="col-payee"
                )
                yield Select(
                    [],
                    allow_blank=True,
                    prompt="Narration column (optional)",
                    id="col-narration",
                )
            yield Label(
                "Target account (the account this CSV represents, e.g. the bank account)",
                classes="field-label",
            )
            yield Input(placeholder="Assets:Checking", id="account")
            yield Static("", id="error")
            with Horizontal(id="buttons"):
                yield Button("Cancel", id="cancel")
                yield Button("Import", id="import", variant="primary")

    def _error(self, message: str) -> None:
        self.query_one("#error", Static).update(message)

    def _load_preview(self) -> None:
        path_text = self.query_one("#path", Input).value.strip()
        if not path_text:
            self._error("Enter a CSV file path.")
            return
        path = Path(path_text)
        if not path.is_file():
            self._error(f"No such file: {path}")
            return
        try:
            headers, rows = preview_csv(path)
        except (OSError, UnicodeDecodeError) as exc:
            self._error(f"Could not read {path}: {exc}")
            return
        if not headers:
            self._error(f"{path} has no header row.")
            return

        self._headers = headers
        self._error("")

        table = self.query_one("#preview", DataTable)
        table.clear(columns=True)
        table.add_columns(*headers)
        for row in rows:
            table.add_row(*(row.get(h, "") for h in headers))

        blank_options = [(h, h) for h in headers]
        for select_id in ("#col-date", "#col-amount", "#col-payee", "#col-narration"):
            select = self.query_one(select_id, Select)
            select.set_options(blank_options)

    def _do_import(self) -> None:
        path_text = self.query_one("#path", Input).value.strip()
        if not path_text:
            self._error("Enter a CSV file path.")
            return
        path = Path(path_text)
        if not path.is_file():
            self._error(f"No such file: {path}")
            return

        date_col = self.query_one("#col-date", Select).value
        amount_col = self.query_one("#col-amount", Select).value
        if date_col is Select.BLANK or amount_col is Select.BLANK:
            self._error("Load a preview and map the date and amount columns.")
            return
        payee_col = self.query_one("#col-payee", Select).value
        narration_col = self.query_one("#col-narration", Select).value
        account = self.query_one("#account", Input).value.strip()
        if not account:
            self._error("Enter the target account.")
            return

        mapping = CsvColumnMapping(
            date=str(date_col),
            amount=str(amount_col),
            payee=None if payee_col is Select.BLANK else str(payee_col),
            narration=None if narration_col is Select.BLANK else str(narration_col),
        )
        try:
            candidates = parse_csv(path, mapping, account)
        except (OSError, UnicodeDecodeError) as exc:
            self._error(f"Could not read {path}: {exc}")
            return
        self.dismiss(candidates)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "load":
            self._load_preview()
        elif event.button.id == "import":
            self._do_import()
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)
