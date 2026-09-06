"""Table of ledger entries for the selected account.

Shows transactions and, when the app's directives toggle is on, the
account-level directives (open, close, balance, pad, note, query) as well.
"""

from __future__ import annotations

from pathlib import Path

from beancount.core import data
from textual.widgets import DataTable

from beancount_tui.ledger import has_user_metadata, transaction_amount


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
        narration = entry.narration or ""
        if has_user_metadata(entry):
            narration = f"{narration} +".strip()
        return (date, entry.flag or "*", entry.payee or "", narration,
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
    if isinstance(entry, data.Price):
        return (date, "price", "", entry.currency,
                f"{entry.amount.number} {entry.amount.currency}")
    if isinstance(entry, data.Event):
        return (date, "event", "", f'"{entry.type}": "{entry.description}"', "")
    if isinstance(entry, data.Custom):
        values = ", ".join(str(v.value) for v in entry.values)
        return (date, "custom", "", f"{entry.type}: {values}", "")
    if isinstance(entry, data.Query):
        query_text = entry.query_string
        if len(query_text) > 40:
            query_text = f"{query_text[:40]}..."
        return (date, "query", "", f"{entry.name}: {query_text}", "")
    if isinstance(entry, data.Document):
        summary = f"{entry.account}: {entry.filename}"
        # Beancount resolves ``filename`` to an absolute path (relative to the
        # directory of the file that declared the directive) before this ever
        # reaches us, so a plain existence check is all that's needed here.
        if not Path(entry.filename).exists():
            summary = f"! {summary}"
        return (date, "document", "", summary, "")
    return (date, type(entry).__name__.lower(), "", "", "")
