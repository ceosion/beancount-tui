"""Modal trial balance: every account with a nonzero balance as of a date."""

from __future__ import annotations

import datetime
from typing import Any

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Input, Label, Static

from beancount_tui.ledger import Ledger, format_inventory
from beancount_tui.widgets.date_input import DateInput
from beancount_tui.widgets.export_mixin import ExportMixin


class TrialBalanceScreen(ExportMixin, ModalScreen[None]):
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
    TrialBalanceScreen #export-row {
        height: auto;
        margin-top: 1;
    }
    TrialBalanceScreen #export-row Input {
        width: 1fr;
    }
    TrialBalanceScreen #export-row Select {
        width: 14;
    }
    TrialBalanceScreen #export-error {
        color: $error;
        height: auto;
    }
    """

    def __init__(self, ledger: Ledger) -> None:
        super().__init__()
        self._ledger = ledger
        # Populated by ``_render_report`` in the flat ``(columns, rows)``
        # shape ``ExportMixin``/``write_csv``/``write_json`` expect --
        # one row per account, mirroring the ``DataTable`` exactly, just
        # with raw ``Inventory`` balances instead of display-formatted text.
        self._export_columns: list[str] = ["Account", "Balance"]
        self._export_rows: list[list[Any]] = []

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
            yield from self.compose_export_row()

    def on_mount(self) -> None:
        table = self.query_one("#report", DataTable)
        table.add_columns("Account", "Balance")
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
        balances = self._ledger.trial_balance(as_of)
        table = self.query_one("#report", DataTable)
        table.clear()
        self._export_rows = []
        for account, balance in balances:
            table.add_row(account, format_inventory(balance))
            self._export_rows.append([account, balance])

    def _export_columns_rows(self) -> tuple[list[str], list[list[Any]]]:
        return self._export_columns, self._export_rows

    def action_close(self) -> None:
        self.dismiss(None)
