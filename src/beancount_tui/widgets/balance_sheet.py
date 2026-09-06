"""Modal balance sheet: Assets, Liabilities, and Equity as of a chosen date."""

from __future__ import annotations

import datetime

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Input, Label, Static

from beancount_tui.ledger import Ledger, format_inventory


class BalanceSheetScreen(ModalScreen[None]):
    """Read-only report over the ledger; Escape closes it."""

    BINDINGS = [("escape", "close", "Close")]

    DEFAULT_CSS = """
    BalanceSheetScreen {
        align: center middle;
    }
    BalanceSheetScreen > Vertical {
        width: 70;
        height: auto;
        max-height: 90%;
        border: round $primary;
        padding: 1 2;
        background: $surface;
    }
    BalanceSheetScreen #as-of {
        margin-top: 1;
    }
    BalanceSheetScreen #report {
        height: auto;
        max-height: 24;
        margin-top: 1;
    }
    BalanceSheetScreen #as-of-error {
        color: $error;
        height: auto;
    }
    """

    def __init__(self, ledger: Ledger) -> None:
        super().__init__()
        self._ledger = ledger

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("[b]Balance sheet[/b]")
            yield Input(
                value=datetime.date.today().isoformat(),
                placeholder="As-of date YYYY-MM-DD",
                id="as-of",
            )
            yield DataTable(id="report", cursor_type="none")
            yield Static("", id="as-of-error")

    def on_mount(self) -> None:
        table = self.query_one("#report", DataTable)
        table.add_columns("Account", "Amount")
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
        sheet = self._ledger.balance_sheet(as_of)
        table = self.query_one("#report", DataTable)
        table.clear()

        def header(label: str) -> Text:
            return Text(label, style="bold")

        table.add_row(header("Assets"), "")
        for account, balance in sheet.assets:
            table.add_row("  " + account, format_inventory(balance))
        table.add_row(header("Total assets"), header(format_inventory(sheet.assets_total)))
        table.add_row("", "")
        table.add_row(header("Liabilities"), "")
        for account, balance in sheet.liabilities:
            table.add_row("  " + account, format_inventory(balance))
        table.add_row(
            header("Total liabilities"), header(format_inventory(sheet.liabilities_total))
        )
        table.add_row("", "")
        table.add_row(header("Equity"), "")
        for account, balance in sheet.equity:
            table.add_row("  " + account, format_inventory(balance))
        table.add_row("  Net income (current period)", format_inventory(sheet.net_income))
        equity_total = sheet.equity_total + sheet.net_income
        table.add_row(header("Total equity"), header(format_inventory(equity_total)))
        table.add_row("", "")
        table.add_row(
            header("Total liabilities + equity"),
            header(format_inventory(sheet.liabilities_total + equity_total)),
        )

    def action_close(self) -> None:
        self.dismiss(None)
