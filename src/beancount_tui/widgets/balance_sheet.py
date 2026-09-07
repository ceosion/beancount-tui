"""Modal balance sheet: Assets, Liabilities, and Equity as of a chosen date."""

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


class BalanceSheetScreen(ExportMixin, ModalScreen[None]):
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
    BalanceSheetScreen #export-row {
        height: auto;
        margin-top: 1;
    }
    BalanceSheetScreen #export-row Input {
        width: 1fr;
    }
    BalanceSheetScreen #export-row Select {
        width: 14;
    }
    BalanceSheetScreen #export-error {
        color: $error;
        height: auto;
    }
    """

    def __init__(self, ledger: Ledger) -> None:
        super().__init__()
        self._ledger = ledger
        # Populated by ``_render_report``. Sectioned reports (this one and
        # ``IncomeStatementScreen``) flatten to one row per line item
        # (including subtotal rows) with a leading "Section" column instead
        # of the on-screen bold section-header/blank-separator rows -- a
        # spreadsheet/JSON consumer can filter/group on a real "Assets" /
        # "Liabilities" / "Equity" value far more easily than on a visual
        # separator, and repeating it per row is more faithful to "this
        # line belongs to this section" than a header row would be. The
        # one row that spans both sides (Total liabilities + equity) gets
        # "Summary" rather than being forced into either section.
        self._export_columns: list[str] = ["Section", "Account", "Amount"]
        self._export_rows: list[list[Any]] = []

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("[b]Balance sheet[/b]")
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
        table.add_columns("Account", "Amount")
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
        sheet = self._ledger.balance_sheet(as_of)
        table = self.query_one("#report", DataTable)
        table.clear()
        export_rows: list[list[Any]] = []

        def header(label: str) -> Text:
            return Text(label, style="bold")

        table.add_row(header("Assets"), "")
        for account, balance in sheet.assets:
            table.add_row("  " + account, format_inventory(balance))
            export_rows.append(["Assets", account, balance])
        table.add_row(header("Total assets"), header(format_inventory(sheet.assets_total)))
        export_rows.append(["Assets", "Total assets", sheet.assets_total])
        table.add_row("", "")
        table.add_row(header("Liabilities"), "")
        for account, balance in sheet.liabilities:
            table.add_row("  " + account, format_inventory(balance))
            export_rows.append(["Liabilities", account, balance])
        table.add_row(
            header("Total liabilities"), header(format_inventory(sheet.liabilities_total))
        )
        export_rows.append(["Liabilities", "Total liabilities", sheet.liabilities_total])
        table.add_row("", "")
        table.add_row(header("Equity"), "")
        for account, balance in sheet.equity:
            table.add_row("  " + account, format_inventory(balance))
            export_rows.append(["Equity", account, balance])
        table.add_row("  Net income (current period)", format_inventory(sheet.net_income))
        export_rows.append(["Equity", "Net income (current period)", sheet.net_income])
        equity_total = sheet.equity_total + sheet.net_income
        table.add_row(header("Total equity"), header(format_inventory(equity_total)))
        export_rows.append(["Equity", "Total equity", equity_total])
        table.add_row("", "")
        table.add_row(
            header("Total liabilities + equity"),
            header(format_inventory(sheet.liabilities_total + equity_total)),
        )
        export_rows.append(
            ["Summary", "Total liabilities + equity", sheet.liabilities_total + equity_total]
        )
        self._export_rows = export_rows

    def _export_columns_rows(self) -> tuple[list[str], list[list[Any]]]:
        return self._export_columns, self._export_rows

    def action_close(self) -> None:
        self.dismiss(None)
