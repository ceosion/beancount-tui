"""Modal holdings/net-worth report: costed lots aggregated by commodity/account."""

from __future__ import annotations

import datetime

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Input, Label, Static

from beancount_tui.ledger import Ledger, format_inventory
from beancount_tui.widgets.date_input import DateInput


class HoldingsScreen(ModalScreen[None]):
    """Read-only report over the ledger; Escape closes it."""

    BINDINGS = [("escape", "close", "Close")]

    DEFAULT_CSS = """
    HoldingsScreen {
        align: center middle;
    }
    HoldingsScreen > Vertical {
        width: 84;
        height: auto;
        max-height: 90%;
        border: round $primary;
        padding: 1 2;
        background: $surface;
    }
    HoldingsScreen #as-of {
        margin-top: 1;
    }
    HoldingsScreen #report {
        height: auto;
        max-height: 24;
        margin-top: 1;
    }
    HoldingsScreen #as-of-error {
        color: $error;
        height: auto;
    }
    """

    def __init__(self, ledger: Ledger) -> None:
        super().__init__()
        self._ledger = ledger

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("[b]Holdings / net worth[/b]")
            yield DateInput(
                value=datetime.date.today().isoformat(),
                placeholder="As-of date YYYY-MM-DD",
                id="as-of",
            )
            yield DataTable(id="report", cursor_type="none")
            yield Static("", id="as-of-error")

    def on_mount(self) -> None:
        table = self.query_one("#report", DataTable)
        table.add_columns("Commodity", "Account", "Quantity", "Cost basis", "Market value")
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
        report = self._ledger.holdings(as_of)
        table = self.query_one("#report", DataTable)
        table.clear()

        def header(label: str) -> Text:
            return Text(label, style="bold")

        if not report.holdings:
            table.add_row("(no costed holdings)", "", "", "", "")
        for holding in report.holdings:
            if holding.market_value is None:
                market_value_text = "no price available"
            else:
                market_value_text = (
                    f"{holding.market_value.number:,} {holding.market_value.currency}"
                )
                if not holding.priced_in_operating_currency:
                    market_value_text += " (not operating currency)"
            table.add_row(
                holding.commodity,
                holding.account,
                f"{holding.quantity:,}",
                format_inventory(holding.cost_basis),
                market_value_text,
            )

        table.add_row("", "", "", "", "")
        currency_label = f" ({report.operating_currency})" if report.operating_currency else ""
        net_worth_text = format_inventory(report.net_worth) or "no price available"
        table.add_row(
            header(f"Net worth{currency_label}"),
            "",
            "",
            "",
            header(net_worth_text),
        )

    def action_close(self) -> None:
        self.dismiss(None)
