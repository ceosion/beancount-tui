"""Modal income statement: Income and Expenses over a selectable period."""

from __future__ import annotations

import datetime
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Input, Label, Static

from beancount_tui.ledger import Ledger, format_inventory, parse_date_range, parse_periods
from beancount_tui.widgets.date_input import DateRangeInput
from beancount_tui.widgets.export_mixin import ExportMixin


class IncomeStatementScreen(ExportMixin, ModalScreen[None]):
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
    IncomeStatementScreen #export-row {
        height: auto;
        margin-top: 1;
    }
    IncomeStatementScreen #export-row Input {
        width: 1fr;
    }
    IncomeStatementScreen #export-row Select {
        width: 14;
    }
    IncomeStatementScreen #export-error {
        color: $error;
        height: auto;
    }
    """

    def __init__(self, ledger: Ledger) -> None:
        super().__init__()
        self._ledger = ledger
        # Populated by ``_render_report``/``_render_comparison``, whichever
        # ran last -- see ``BalanceSheetScreen`` for the "Section" column
        # rationale (shared here, the other sectioned report). In
        # comparison mode there's one amount column per period instead of a
        # single "Amount" column, so ``_export_columns`` itself changes
        # shape depending on the last-rendered mode, unlike the single-shape
        # flat/other-sectioned screens.
        self._export_columns: list[str] = ["Section", "Account", "Amount"]
        self._export_rows: list[list[Any]] = []

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("[b]Income statement[/b]")
            yield DateRangeInput(
                placeholder=(
                    "Period YYYY-MM-DD..YYYY-MM-DD, or compare periods "
                    "comma-separated: month,last-month"
                ),
                id="period",
            )
            yield DataTable(id="report", cursor_type="none")
            yield Static("", id="period-error")
            yield from self.compose_export_row()

    def on_mount(self) -> None:
        self._render_report(None, None)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "period":
            return
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

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "export-path":
            event.stop()
            self._do_export()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "export":
            self._do_export()

    def _render_report(
        self, start: datetime.date | None, end: datetime.date | None
    ) -> None:
        stmt = self._ledger.income_statement(start, end)
        table = self.query_one("#report", DataTable)
        table.clear(columns=True)
        table.add_columns("Account", "Amount")
        export_rows: list[list[Any]] = []

        def header(label: str) -> Text:
            return Text(label, style="bold")

        table.add_row(header("Income"), "")
        for account, balance in stmt.income:
            table.add_row("  " + account, format_inventory(balance))
            export_rows.append(["Income", account, balance])
        table.add_row(header("Total income"), header(format_inventory(stmt.income_total)))
        export_rows.append(["Income", "Total income", stmt.income_total])
        table.add_row("", "")
        table.add_row(header("Expenses"), "")
        for account, balance in stmt.expenses:
            table.add_row("  " + account, format_inventory(balance))
            export_rows.append(["Expenses", account, balance])
        table.add_row(header("Total expenses"), header(format_inventory(stmt.expenses_total)))
        export_rows.append(["Expenses", "Total expenses", stmt.expenses_total])
        table.add_row("", "")
        table.add_row(header("Net"), header(format_inventory(stmt.net)))
        export_rows.append(["Summary", "Net", stmt.net])

        self._export_columns = ["Section", "Account", "Amount"]
        self._export_rows = export_rows

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
        export_rows: list[list[Any]] = []

        def header(label: str) -> Text:
            return Text(label, style="bold")

        blank_row = [""] * len(comparison.periods)

        table.add_row(header("Income"), *blank_row)
        for account, balances in comparison.income:
            table.add_row("  " + account, *(format_inventory(b) for b in balances))
            export_rows.append(["Income", account, *balances])
        table.add_row(
            header("Total income"),
            *(header(format_inventory(b)) for b in comparison.income_total),
        )
        export_rows.append(["Income", "Total income", *comparison.income_total])
        table.add_row("", *blank_row)
        table.add_row(header("Expenses"), *blank_row)
        for account, balances in comparison.expenses:
            table.add_row("  " + account, *(format_inventory(b) for b in balances))
            export_rows.append(["Expenses", account, *balances])
        table.add_row(
            header("Total expenses"),
            *(header(format_inventory(b)) for b in comparison.expenses_total),
        )
        export_rows.append(["Expenses", "Total expenses", *comparison.expenses_total])
        table.add_row("", *blank_row)
        table.add_row(header("Net"), *(header(format_inventory(b)) for b in comparison.net))
        export_rows.append(["Summary", "Net", *comparison.net])

        self._export_columns = ["Section", "Account", *comparison.periods]
        self._export_rows = export_rows

    def _export_columns_rows(self) -> tuple[list[str], list[list[Any]]]:
        return self._export_columns, self._export_rows

    def action_close(self) -> None:
        self.dismiss(None)
