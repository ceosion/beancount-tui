"""Modal form for creating a `custom "budget"` directive (Fava's convention,
see `BUDGET-01`'s `ledger.BudgetEntry`) with guided fields instead of raw
text.

Assembles the structured input into
`YYYY-MM-DD custom "budget" Account "interval" NN.NN CCY` and validates it
through the exact same path as the generic `DirectiveForm`
(`parse_directives_text`, `DirectiveFormResult`), so it carries identical
validation guarantees while guiding account/interval/amount/currency entry
instead of leaving them to raw text.
"""

from __future__ import annotations

import datetime
from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Select, Static

from beancount_tui.editor import TransactionParseError, parse_directives_text
from beancount_tui.widgets.account_input import AccountInput
from beancount_tui.widgets.directive_form import DirectiveFormResult

# Fava's five accepted intervals, canonical long form (matches
# ``ledger._BUDGET_INTERVALS``'s long-form spellings, which is what
# ``ledger.Ledger._parse_budgets`` canonicalizes both long and short forms
# to). Assembling the directive with one of these means it round-trips
# through ``Ledger.budgets`` without ever hitting the invalid-interval path.
INTERVALS: tuple[tuple[str, str], ...] = (
    ("Daily", "daily"),
    ("Weekly", "weekly"),
    ("Monthly", "monthly"),
    ("Quarterly", "quarterly"),
    ("Yearly", "yearly"),
)


class BudgetForm(ModalScreen[DirectiveFormResult | None]):
    """Returns a :class:`DirectiveFormResult`, or ``None`` if cancelled.

    Same result type as ``DirectiveForm``, so the app's save/undo/reload
    handling for a new directive doesn't need to know or care which form
    produced it.
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    DEFAULT_CSS = """
    BudgetForm {
        align: center middle;
    }
    BudgetForm > Vertical {
        width: 60;
        height: auto;
        border: round $primary;
        padding: 1 2;
        background: $surface;
    }
    BudgetForm .field-label {
        margin-top: 1;
        color: $text-muted;
    }
    BudgetForm #error {
        color: $error;
        height: auto;
    }
    BudgetForm #buttons {
        height: auto;
        align-horizontal: right;
        margin-top: 1;
    }
    BudgetForm Button {
        margin-left: 2;
    }
    """

    def __init__(
        self,
        *,
        date: str | None = None,
        files: list[Path] | None = None,
        accounts: list[str] | None = None,
    ) -> None:
        super().__init__()
        self._date = date or datetime.date.today().isoformat()
        self._accounts = accounts or []
        # Offer a target-file picker only when there is a real choice.
        self._files = files if files and len(files) > 1 else None

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label('[b]New budget[/b]')
            yield Label("Date", classes="field-label")
            yield Input(value=self._date, id="date", placeholder="YYYY-MM-DD")
            yield Label("Account (Tab completes)", classes="field-label")
            yield AccountInput(
                id="account", accounts=self._accounts, placeholder="Expenses:FIXME"
            )
            yield Label("Interval", classes="field-label")
            yield Select(INTERVALS, value="monthly", allow_blank=False, id="interval")
            yield Label("Amount", classes="field-label")
            yield Input(id="amount", placeholder="0.00", restrict=r"-?[0-9]*\.?[0-9]*")
            yield Label("Currency", classes="field-label")
            yield Input(value="USD", id="currency", restrict=r"[A-Za-z]*")
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

    def _assemble_text(self) -> str:
        date = self.query_one("#date", Input).value.strip()
        account = self.query_one("#account", AccountInput).value.strip()
        interval = str(self.query_one("#interval", Select).value)
        amount = self.query_one("#amount", Input).value.strip()
        currency = self.query_one("#currency", Input).value.strip().upper()
        return f'{date} custom "budget" {account} "{interval}" {amount} {currency}\n'

    def _save(self) -> None:
        text = self._assemble_text()
        try:
            entries = parse_directives_text(text)
        except TransactionParseError as exc:
            self.query_one("#error", Static).update(str(exc))
            return
        if len(entries) != 1:
            self.query_one("#error", Static).update("Expected exactly one directive.")
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
