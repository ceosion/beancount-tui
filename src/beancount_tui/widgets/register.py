"""Modal register view: postings to one account plus running balance."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Label

from beancount_tui.ledger import Ledger, format_inventory


class RegisterScreen(ModalScreen[None]):
    """Read-only report for one account; Escape closes it."""

    BINDINGS = [("escape", "close", "Close")]

    DEFAULT_CSS = """
    RegisterScreen {
        align: center middle;
    }
    RegisterScreen > Vertical {
        width: 90;
        height: auto;
        max-height: 90%;
        border: round $primary;
        padding: 1 2;
        background: $surface;
    }
    RegisterScreen #report {
        height: auto;
        max-height: 24;
        margin-top: 1;
    }
    """

    def __init__(self, ledger: Ledger, account: str) -> None:
        super().__init__()
        self._ledger = ledger
        self._account = account

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(f"[b]Register: {self._account}[/b]")
            yield DataTable(id="report", cursor_type="none")

    def on_mount(self) -> None:
        table = self.query_one("#report", DataTable)
        table.add_columns("Date", "Narration", "Amount", "Balance")
        for row in self._ledger.register(self._account):
            table.add_row(
                row.date.isoformat(),
                row.narration,
                format_inventory(row.posting_amount),
                format_inventory(row.running_balance),
            )

    def action_close(self) -> None:
        self.dismiss(None)
