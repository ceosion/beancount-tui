"""Modal holdings/net-worth report: costed lots aggregated by commodity/account."""

from __future__ import annotations

import datetime
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Input, Label, Static

from beancount_tui.ledger import Ledger, format_inventory
from beancount_tui.widgets.date_input import DateInput
from beancount_tui.widgets.export_mixin import ExportMixin


class HoldingsScreen(ExportMixin, ModalScreen[None]):
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
    HoldingsScreen #export-row {
        height: auto;
        margin-top: 1;
    }
    HoldingsScreen #export-row Input {
        width: 1fr;
    }
    HoldingsScreen #export-row Select {
        width: 14;
    }
    HoldingsScreen #export-error {
        color: $error;
        height: auto;
    }
    """

    def __init__(self, ledger: Ledger) -> None:
        super().__init__()
        self._ledger = ledger
        # Populated by ``_render_report``: one row per holding, plus a
        # trailing net-worth summary row (see ``_export_columns_rows``) --
        # raw ``Decimal``/``Inventory``/``Amount`` values rather than the
        # on-screen comma-grouped/"no price available" display text.
        self._export_columns: list[str] = [
            "Commodity",
            "Account",
            "Quantity",
            "Cost basis",
            "Market value",
        ]
        self._export_rows: list[list[Any]] = []

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
            yield from self.compose_export_row()

    def on_mount(self) -> None:
        table = self.query_one("#report", DataTable)
        table.add_columns("Commodity", "Account", "Quantity", "Cost basis", "Market value")
        self._render_report(datetime.date.today())

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "as-of":
            return
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

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "export-path":
            event.stop()
            self._do_export()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "export":
            self._do_export()

    def _render_report(self, as_of: datetime.date) -> None:
        report = self._ledger.holdings(as_of)
        table = self.query_one("#report", DataTable)
        table.clear()
        export_rows: list[list[Any]] = []

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
            export_rows.append(
                [
                    holding.commodity,
                    holding.account,
                    holding.quantity,
                    holding.cost_basis,
                    holding.market_value,
                ]
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
        # The blank separator row above is purely visual on screen; the
        # export gets the net-worth summary as its own trailing row with no
        # equivalent blank line.
        export_rows.append([f"Net worth{currency_label}", "", "", "", report.net_worth])
        self._export_rows = export_rows

    def _export_columns_rows(self) -> tuple[list[str], list[list[Any]]]:
        return self._export_columns, self._export_rows

    def action_close(self) -> None:
        self.dismiss(None)
