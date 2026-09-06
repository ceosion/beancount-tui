"""Table of ledger entries for the selected account.

Shows transactions and, when the app's directives toggle is on, the
account-level directives (open, close, balance, pad, note, price, event,
custom, query, commodity, document) as well. Each directive keyword is
colored distinctly (see ``_DIRECTIVE_STYLES``) so a mixed-directive table
stays scannable.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Callable, Literal

from beancount.core import data
from rich.text import Text
from textual.widgets import DataTable

from beancount_tui.ledger import has_user_metadata, transaction_amount, transaction_amount_value

# One color per non-Transaction directive keyword, so a mixed-directive table
# (with the ``t`` toggle on) stays scannable instead of reading as a wall of
# similarly-styled rows. Kept loosely grouped by theme (account lifecycle,
# reconciliation, pricing, annotation) but each keyword still gets its own
# distinct hue.
_DIRECTIVE_STYLES: dict[str, str] = {
    "open": "green",
    "close": "red",
    "balance": "yellow",
    "pad": "dark_orange",
    "note": "bright_black",
    "price": "magenta",
    "commodity": "purple",
    "event": "blue",
    "document": "cyan",
    "custom": "bright_magenta",
    "query": "bright_blue",
}


def _keyword(label: str) -> Text:
    """Style ``label`` (a directive keyword) per ``_DIRECTIVE_STYLES``."""
    return Text(label, style=_DIRECTIVE_STYLES.get(label, ""))

SortField = Literal["date", "payee", "amount"]

# Maps a header's column index (as added in ``on_mount``) to the sort field it
# controls. Flag (1) and Narration (3) aren't sortable.
_COLUMN_SORT_FIELDS: dict[int, SortField] = {0: "date", 2: "payee", 4: "amount"}

# The ``o`` key steps through these (field, reverse) pairs in order, wrapping
# around: date asc -> date desc -> payee asc -> payee desc -> amount asc ->
# amount desc -> date asc -> ...
_SORT_STEPS: tuple[tuple[SortField, bool], ...] = (
    ("date", False),
    ("date", True),
    ("payee", False),
    ("payee", True),
    ("amount", False),
    ("amount", True),
)


def _sort_key_date(entry: data.Directive):
    return entry.date


def _sort_key_payee(entry: data.Directive) -> str:
    return (getattr(entry, "payee", None) or "").lower()


def _sort_key_amount(entry: data.Directive) -> Decimal:
    if isinstance(entry, data.Transaction):
        return transaction_amount_value(entry)
    return Decimal(0)


_SORT_KEYS: dict[SortField, Callable[[data.Directive], object]] = {
    "date": _sort_key_date,
    "payee": _sort_key_payee,
    "amount": _sort_key_amount,
}


class TransactionTable(DataTable):
    """Lists entries; each row's key is an index into ``self.shown``."""

    BINDINGS = [("o", "cycle_sort", "Sort")]

    def __init__(self, **kwargs) -> None:
        super().__init__(cursor_type="row", zebra_stripes=True, **kwargs)
        self.shown: list[data.Directive] = []
        # Sort state persists across ``update_entries`` calls (filter changes,
        # account selection, etc.) until explicitly changed by the user.
        self._sort_field: SortField | None = None
        self._sort_reverse: bool = False

    def on_mount(self) -> None:
        self.add_columns("Date", "Flag", "Payee", "Narration", "Amount")

    def update_entries(self, entries: list[data.Directive]) -> None:
        self.clear()
        self.shown = self._sorted(entries)
        for index, entry in enumerate(self.shown):
            self.add_row(*_entry_row(entry), key=str(index))
        if self.shown:
            self.move_cursor(row=len(self.shown) - 1)

    def _sorted(self, entries: list[data.Directive]) -> list[data.Directive]:
        if self._sort_field is None:
            return list(entries)
        key_func = _SORT_KEYS[self._sort_field]
        return sorted(entries, key=key_func, reverse=self._sort_reverse)

    def _set_sort(self, field: SortField) -> None:
        """Apply ``field`` as the active sort, toggling direction on repeat."""
        if self._sort_field == field:
            self._sort_reverse = not self._sort_reverse
        else:
            self._sort_field = field
            self._sort_reverse = False
        self.update_entries(self.shown)

    def action_cycle_sort(self) -> None:
        """Step through ``_SORT_STEPS``: cycling field and, per field, direction."""
        current = (self._sort_field, self._sort_reverse)
        try:
            index = _SORT_STEPS.index(current)
            next_step = _SORT_STEPS[(index + 1) % len(_SORT_STEPS)]
        except ValueError:
            next_step = _SORT_STEPS[0]
        self._sort_field, self._sort_reverse = next_step
        self.update_entries(self.shown)

    def on_data_table_header_selected(self, event: DataTable.HeaderSelected) -> None:
        field = _COLUMN_SORT_FIELDS.get(event.column_index)
        if field is not None:
            self._set_sort(field)

    @property
    def selected_entry(self) -> data.Directive | None:
        if not self.shown or self.cursor_row is None:
            return None
        if 0 <= self.cursor_row < len(self.shown):
            return self.shown[self.cursor_row]
        return None


def _entry_row(entry: data.Directive) -> tuple[str, str | Text, str, str, str]:
    """The (date, flag, payee, narration, amount) cells for an entry.

    Non-transaction directives show their keyword in the flag column,
    colored per ``_DIRECTIVE_STYLES`` so a mixed-directive table stays
    scannable, and a summary in the narration column.
    """
    date = str(entry.date)
    if isinstance(entry, data.Transaction):
        narration = entry.narration or ""
        tags_links = _tags_links_summary(entry)
        if tags_links:
            narration = f"{narration} {tags_links}".strip()
        if has_user_metadata(entry):
            narration = f"{narration} +".strip()
        return (date, entry.flag or "*", entry.payee or "", narration,
                transaction_amount(entry))
    if isinstance(entry, data.Open):
        return (date, _keyword("open"), "", entry.account, ", ".join(entry.currencies or []))
    if isinstance(entry, data.Close):
        return (date, _keyword("close"), "", entry.account, "")
    if isinstance(entry, data.Balance):
        return (date, _keyword("balance"), "", entry.account,
                f"{entry.amount.number} {entry.amount.currency}")
    if isinstance(entry, data.Pad):
        return (date, _keyword("pad"), "", f"{entry.account} from {entry.source_account}", "")
    if isinstance(entry, data.Note):
        return (date, _keyword("note"), "", f"{entry.account}: {entry.comment}", "")
    if isinstance(entry, data.Price):
        return (date, _keyword("price"), "", entry.currency,
                f"{entry.amount.number} {entry.amount.currency}")
    if isinstance(entry, data.Event):
        return (date, _keyword("event"), "", f'"{entry.type}": "{entry.description}"', "")
    if isinstance(entry, data.Custom):
        values = ", ".join(str(v.value) for v in entry.values)
        return (date, _keyword("custom"), "", f"{entry.type}: {values}", "")
    if isinstance(entry, data.Query):
        query_text = entry.query_string
        if len(query_text) > 40:
            query_text = f"{query_text[:40]}..."
        return (date, _keyword("query"), "", f"{entry.name}: {query_text}", "")
    if isinstance(entry, data.Commodity):
        name = entry.meta.get("name") if entry.meta else None
        summary = f"{entry.currency} ({name})" if name else entry.currency
        return (date, _keyword("commodity"), "", summary, "")
    if isinstance(entry, data.Document):
        summary = f"{entry.account}: {entry.filename}"
        # Beancount resolves ``filename`` to an absolute path (relative to the
        # directory of the file that declared the directive) before this ever
        # reaches us, so a plain existence check is all that's needed here.
        if not Path(entry.filename).exists():
            summary = f"! {summary}"
        return (date, _keyword("document"), "", summary, "")
    return (date, _keyword(type(entry).__name__.lower()), "", "", "")


def _tags_links_summary(entry: data.Transaction) -> str:
    """Render a transaction's tags/links as ``#tag ^link`` text for display."""
    tokens = [f"#{tag}" for tag in sorted(entry.tags or ())]
    tokens += [f"^{link}" for link in sorted(entry.links or ())]
    return " ".join(tokens)
