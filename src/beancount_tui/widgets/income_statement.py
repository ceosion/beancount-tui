"""Modal income statement: Income and Expenses over a selectable period."""

from __future__ import annotations

import datetime

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Input, Label, Static

from beancount_tui.ledger import Ledger, format_inventory, parse_date_range


class IncomeStatementScreen(ModalScreen[None]):
    """Read-only report over the ledger; Escape closes it."""

    BINDINGS = [("escape", "close", "Close")]

    DEFAULT_CSS = """
    IncomeStatementScreen {
        align: center middle;
    }
    IncomeStatementScreen > Vertical {
        width: 70;
        height: auto;
        max-height: 90%;
        border: round $primary;
        padding: 1 2;
        background: $surface;
    }
    IncomeStatementScreen #period {
        margin-top: 1;
    }
    IncomeStatementScreen #report {
        height: auto;
        max-height: 24;
        margin-top: 1;
    }
    IncomeStatementScreen #period-error {
        color: $error;
        height: auto;
    }
    """

    def __init__(self, ledger: Ledger) -> None:
        super().__init__()
        self._ledger = ledger

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("[b]Income statement[/b]")
            yield Input(
                placeholder="Period YYYY-MM-DD..YYYY-MM-DD (either side optional; empty = all)",
                id="period",
            )
            yield DataTable(id="report", cursor_type="none")
            yield Static("", id="period-error")

    def on_mount(self) -> None:
        table = self.query_one("#report", DataTable)
        table.add_columns("Account", "Amount")
        self._render_report(None, None)

    def on_input_changed(self, event: Input.Changed) -> None:
        event.stop()
        error = self.query_one("#period-error", Static)
        query = event.value.strip()
        if not query:
            error.update("")
            self._render_report(None, None)
            return
        date_range = parse_date_range(query)
        if date_range is None:
            error.update("Not a date range; use YYYY-MM-DD..YYYY-MM-DD.")
            return
        error.update("")
        self._render_report(*date_range)

    def _render_report(
        self, start: datetime.date | None, end: datetime.date | None
    ) -> None:
        stmt = self._ledger.income_statement(start, end)
        table = self.query_one("#report", DataTable)
        table.clear()

        def header(label: str) -> Text:
            return Text(label, style="bold")

        table.add_row(header("Income"), "")
        for account, balance in stmt.income:
            table.add_row("  " + account, format_inventory(balance))
        table.add_row(header("Total income"), header(format_inventory(stmt.income_total)))
        table.add_row("", "")
        table.add_row(header("Expenses"), "")
        for account, balance in stmt.expenses:
            table.add_row("  " + account, format_inventory(balance))
        table.add_row(header("Total expenses"), header(format_inventory(stmt.expenses_total)))
        table.add_row("", "")
        table.add_row(header("Net"), header(format_inventory(stmt.net)))

    def action_close(self) -> None:
        self.dismiss(None)
