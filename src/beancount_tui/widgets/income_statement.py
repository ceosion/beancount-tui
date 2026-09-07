"""Modal income statement: Income and Expenses over a selectable period."""

from __future__ import annotations

import datetime

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Input, Label, Static

from beancount_tui.ledger import Ledger, format_inventory, parse_date_range, parse_periods


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
                placeholder=(
                    "Period YYYY-MM-DD..YYYY-MM-DD, or compare periods "
                    "comma-separated: month,last-month"
                ),
                id="period",
            )
            yield DataTable(id="report", cursor_type="none")
            yield Static("", id="period-error")

    def on_mount(self) -> None:
        self._render_report(None, None)

    def on_input_changed(self, event: Input.Changed) -> None:
        event.stop()
        error = self.query_one("#period-error", Static)
        query = event.value.strip()
        if not query:
            error.update("")
            self._render_report(None, None)
            return
        if "," in query:
            periods = parse_periods(query)
            if periods is None:
                error.update(
                    "Not a valid period list; use 2+ comma-separated tokens/ranges, "
                    "e.g. month,last-month."
                )
                return
            error.update("")
            self._render_comparison(periods)
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
        table.clear(columns=True)
        table.add_columns("Account", "Amount")

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

    def _render_comparison(
        self, periods: list[tuple[str, datetime.date | None, datetime.date | None]]
    ) -> None:
        """Render RPT-09's multi-column comparison mode: one column per period."""
        labels = [label for label, _, _ in periods]
        ranges = [(start, end) for _, start, end in periods]
        comparison = self._ledger.income_statement_comparison(ranges, labels=labels)
        table = self.query_one("#report", DataTable)
        table.clear(columns=True)
        table.add_columns("Account", *comparison.periods)

        def header(label: str) -> Text:
            return Text(label, style="bold")

        blank_row = [""] * len(comparison.periods)

        table.add_row(header("Income"), *blank_row)
        for account, balances in comparison.income:
            table.add_row("  " + account, *(format_inventory(b) for b in balances))
        table.add_row(
            header("Total income"),
            *(header(format_inventory(b)) for b in comparison.income_total),
        )
        table.add_row("", *blank_row)
        table.add_row(header("Expenses"), *blank_row)
        for account, balances in comparison.expenses:
            table.add_row("  " + account, *(format_inventory(b) for b in balances))
        table.add_row(
            header("Total expenses"),
            *(header(format_inventory(b)) for b in comparison.expenses_total),
        )
        table.add_row("", *blank_row)
        table.add_row(header("Net"), *(header(format_inventory(b)) for b in comparison.net))

    def action_close(self) -> None:
        self.dismiss(None)
