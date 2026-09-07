"""Modal trial balance: every account with a nonzero balance as of a date."""

from __future__ import annotations

import datetime

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Input, Label, Static

from beancount_tui.ledger import Ledger, format_inventory
from beancount_tui.widgets.date_input import DateInput


class TrialBalanceScreen(ModalScreen[None]):
    """Read-only report over the ledger; Escape closes it."""

    BINDINGS = [("escape", "close", "Close")]

    DEFAULT_CSS = """
    TrialBalanceScreen {
        align: center middle;
    }
    TrialBalanceScreen > Vertical {
        width: 70;
        height: auto;
        max-height: 90%;
        border: round $primary;
        padding: 1 2;
        background: $surface;
    }
    TrialBalanceScreen #as-of {
        margin-top: 1;
    }
    TrialBalanceScreen #report {
        height: auto;
        max-height: 24;
        margin-top: 1;
    }
    TrialBalanceScreen #as-of-error {
        color: $error;
        height: auto;
    }
    """

    def __init__(self, ledger: Ledger) -> None:
        super().__init__()
        self._ledger = ledger

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("[b]Trial balance[/b]")
            yield DateInput(
                value=datetime.date.today().isoformat(),
                placeholder="As-of date YYYY-MM-DD",
                id="as-of",
            )
            yield DataTable(id="report", cursor_type="none")
            yield Static("", id="as-of-error")

    def on_mount(self) -> None:
        table = self.query_one("#report", DataTable)
        table.add_columns("Account", "Balance")
        self._render_report(datetime.date.today())

    def on_input_changed(self, event: Input.Changed) -> None:
        event.stop()
        error = self.query_one("#as-of-error", Static)
        query = event.value.strip()
        if not query:
            error.update("")
            self._render_report(datetime.date.today())
            return
        try:
            as_of = datetime.date.fromisoformat(query)
        except ValueError:
            error.update("Not a date; use YYYY-MM-DD.")
            return
        error.update("")
        self._render_report(as_of)

    def _render_report(self, as_of: datetime.date) -> None:
        balances = self._ledger.trial_balance(as_of)
        table = self.query_one("#report", DataTable)
        table.clear()
        for account, balance in balances:
            table.add_row(account, format_inventory(balance))

    def action_close(self) -> None:
        self.dismiss(None)
