"""Table of transactions for the selected account."""

from __future__ import annotations

from beancount.core import data
from textual.widgets import DataTable

from beancount_tui.ledger import transaction_amount


class TransactionTable(DataTable):
    """Lists transactions; each row's key is an index into ``self.shown``."""

    def __init__(self, **kwargs) -> None:
        super().__init__(cursor_type="row", zebra_stripes=True, **kwargs)
        self.shown: list[data.Transaction] = []

    def on_mount(self) -> None:
        self.add_columns("Date", "Flag", "Payee", "Narration", "Amount")

    def update_transactions(self, transactions: list[data.Transaction]) -> None:
        self.clear()
        self.shown = transactions
        for index, txn in enumerate(transactions):
            self.add_row(
                str(txn.date),
                txn.flag,
                txn.payee or "",
                txn.narration or "",
                transaction_amount(txn),
                key=str(index),
            )
        if transactions:
            self.move_cursor(row=len(transactions) - 1)

    @property
    def selected_transaction(self) -> data.Transaction | None:
        if not self.shown or self.cursor_row is None:
            return None
        if 0 <= self.cursor_row < len(self.shown):
            return self.shown[self.cursor_row]
        return None
