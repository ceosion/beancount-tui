"""Table of ledger entries for the selected account.

Shows transactions and, when the app's directives toggle is on, the
account-level directives (open, close, balance, pad, note) as well.
"""

from __future__ import annotations

from beancount.core import data
from textual.widgets import DataTable

from beancount_tui.ledger import transaction_amount


class TransactionTable(DataTable):
    """Lists entries; each row's key is an index into ``self.shown``."""

    def __init__(self, **kwargs) -> None:
        super().__init__(cursor_type="row", zebra_stripes=True, **kwargs)
        self.shown: list[data.Directive] = []

    def on_mount(self) -> None:
        self.add_columns("Date", "Flag", "Payee", "Narration", "Amount")

    def update_entries(self, entries: list[data.Directive]) -> None:
        self.clear()
        self.shown = entries
        for index, entry in enumerate(entries):
            self.add_row(*_entry_row(entry), key=str(index))
        if entries:
            self.move_cursor(row=len(entries) - 1)

    @property
    def selected_entry(self) -> data.Directive | None:
        if not self.shown or self.cursor_row is None:
            return None
        if 0 <= self.cursor_row < len(self.shown):
            return self.shown[self.cursor_row]
        return None


def _entry_row(entry: data.Directive) -> tuple[str, str, str, str, str]:
    """The (date, flag, payee, narration, amount) cells for an entry.

    Non-transaction directives show their keyword in the flag column and a
    summary in the narration column.
    """
    date = str(entry.date)
    if isinstance(entry, data.Transaction):
        return (date, entry.flag, entry.payee or "", entry.narration or "",
                transaction_amount(entry))
    if isinstance(entry, data.Open):
        return (date, "open", "", entry.account, ", ".join(entry.currencies or []))
    if isinstance(entry, data.Close):
        return (date, "close", "", entry.account, "")
    if isinstance(entry, data.Balance):
        return (date, "balance", "", entry.account,
                f"{entry.amount.number} {entry.amount.currency}")
    if isinstance(entry, data.Pad):
        return (date, "pad", "", f"{entry.account} from {entry.source_account}", "")
    if isinstance(entry, data.Note):
        return (date, "note", "", f"{entry.account}: {entry.comment}", "")
    return (date, type(entry).__name__.lower(), "", "", "")
