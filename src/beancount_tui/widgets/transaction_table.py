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
from beancount.core.inventory import Inventory
from rich.text import Text
from textual.widgets import DataTable

# PERF-04: ``DataTable`` (textual==8.2.8, pinned via pyproject.toml's
# "textual>=0.80.0") has no public ``move_row``-style API, and its one public
# reordering method -- ``DataTable.sort(columns=..., key=...)`` -- only ever
# hands the key function *rendered cell values* for the row (see its
# ``key_wrapper`` closure in ``textual/widgets/_data_table.py``), never the
# row's original domain object. That can't reproduce this table's sort
# semantics: payee sort is case-insensitive but the Payee cell preserves
# case, amount sort is numeric (``Decimal``) but the Amount cell is a
# formatted currency string ("1,200.00 USD" sorts before "200.00 USD"
# lexicographically), and non-Transaction directives need a synthetic zero
# amount that isn't in any cell at all. So a genuine reorder-in-place has to
# go around ``sort()`` and touch what it touches internally: swap the
# ``_row_locations`` two-way map (row key -> display index) for a new one,
# leaving ``_data`` (the per-row rendered cell content, the expensive part of
# ``add_row``) completely untouched. That's exactly what ``sort()`` itself
# does (see its source), so this reaches for the same private map rather
# than reimplementing something riskier of its own.
from textual._two_way_dict import TwoWayDict

from beancount_tui.ledger import (
    format_inventory,
    has_user_metadata,
    transaction_amount,
    transaction_amount_value,
)

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
        # RPT-07: running/cleared running balance for the currently selected
        # single leaf account, keyed by ``id(transaction)`` (see
        # ``Ledger.running_balances``) -- ``None`` when no such balance is
        # available (no account selected, a parent/non-leaf account
        # selected, or "all accounts"). Set via ``update_entries``.
        self._running_balances: dict[int, Inventory] | None = None
        self._cleared_balances: dict[int, Inventory] | None = None
        self._balance_columns_visible: bool = False
        # PERF-04: maps id(entry) -> the row key it was given at the last
        # full rebuild, so a later call that only reorders the *same* set of
        # entries (a sort toggle) can look up each entry's existing row
        # instead of clearing and re-adding every row. Reset (and
        # repopulated) on every full rebuild; see ``_can_reorder_in_place``.
        self._row_key_by_id: dict[int, str] = {}

    def on_mount(self) -> None:
        self.add_columns("Date", "Flag", "Payee", "Narration", "Amount")

    def update_entries(
        self,
        entries: list[data.Directive],
        running_balances: dict[int, Inventory] | None = None,
        cleared_balances: dict[int, Inventory] | None = None,
    ) -> None:
        if self._can_reorder_in_place(entries, running_balances, cleared_balances):
            self._reorder_rows(entries)
            return
        self._rebuild_rows(entries, running_balances, cleared_balances)

    def _can_reorder_in_place(
        self,
        entries: list[data.Directive],
        running_balances: dict[int, Inventory] | None,
        cleared_balances: dict[int, Inventory] | None,
    ) -> bool:
        """Whether ``entries`` is the exact same *set* of entries already
        backing the table's rows (PERF-04's "sort toggle" case), so
        ``update_entries`` can reorder existing rows instead of a full
        ``clear()`` + rebuild.

        Deliberately conservative: any mismatch (a genuinely different
        entry set, a change to the running-balance dicts, or a sort change
        that would flip whether the Balance columns are shown -- which
        changes the column count per row, something a pure reorder can't
        express) falls back to a full rebuild rather than risk stale or
        malformed rows.
        """
        if not self._row_key_by_id:
            return False
        if running_balances is not self._running_balances:
            return False
        if cleared_balances is not self._cleared_balances:
            return False
        if len(entries) != len(self._row_key_by_id):
            return False
        if any(id(entry) not in self._row_key_by_id for entry in entries):
            return False
        return self._should_show_balance_columns() == self._balance_columns_visible

    def _reorder_rows(self, entries: list[data.Directive]) -> None:
        """Apply the current sort to ``entries`` (the same entries already
        shown) by moving existing rows to new positions, without touching
        any row's rendered content. See the ``TwoWayDict`` import comment
        above for why this is the genuine cheaper path here."""
        self.shown = self._sorted(entries)
        new_row_locations = {
            self._row_key_by_id[id(entry)]: new_index
            for new_index, entry in enumerate(self.shown)
        }
        self._row_locations = TwoWayDict(new_row_locations)
        self._update_count += 1
        self.refresh()
        if self.shown:
            self.move_cursor(row=len(self.shown) - 1)

    def _rebuild_rows(
        self,
        entries: list[data.Directive],
        running_balances: dict[int, Inventory] | None,
        cleared_balances: dict[int, Inventory] | None,
    ) -> None:
        self.clear()
        self._running_balances = running_balances
        self._cleared_balances = cleared_balances
        self.shown = self._sorted(entries)
        self._sync_balance_columns()
        self._row_key_by_id = {}
        for index, entry in enumerate(self.shown):
            row = _entry_row(entry)
            if self._balance_columns_visible:
                row = row + self._balance_cells(entry)
            key = str(index)
            self.add_row(*row, key=key)
            self._row_key_by_id[id(entry)] = key
        if self.shown:
            self.move_cursor(row=len(self.shown) - 1)

    def _sorted(self, entries: list[data.Directive]) -> list[data.Directive]:
        if self._sort_field is None:
            return list(entries)
        key_func = _SORT_KEYS[self._sort_field]
        return sorted(entries, key=key_func, reverse=self._sort_reverse)

    def _sort_is_date_based(self) -> bool:
        """Whether the current sort visually reads as date order (RPT-07).

        True for the table's untouched default (``_sort_field is None`` --
        Beancount's loader already yields entries in date order, so the
        default view reads as date-ascending even with no sort explicitly
        chosen) as well as either explicit ``date`` sort direction. False
        for payee/amount sorts, where a running balance wouldn't visually
        make sense against the displayed row order.
        """
        return self._sort_field is None or self._sort_field == "date"

    def _should_show_balance_columns(self) -> bool:
        return self._running_balances is not None and self._sort_is_date_based()

    def _sync_balance_columns(self) -> None:
        """Add/remove the Balance/Cleared Balance columns to match visibility.

        Columns are added/removed from the underlying ``DataTable`` rather
        than kept always-present with blank cells, so an "all accounts" or
        non-leaf-account view doesn't carry permanently empty columns.
        """
        should_show = self._should_show_balance_columns()
        if should_show and not self._balance_columns_visible:
            self.add_column("Balance", key="balance")
            self.add_column("Cleared Balance", key="cleared_balance")
            self._balance_columns_visible = True
        elif not should_show and self._balance_columns_visible:
            self.remove_column("balance")
            self.remove_column("cleared_balance")
            self._balance_columns_visible = False

    def _balance_cells(self, entry: data.Directive) -> tuple[str, str]:
        """The (Balance, Cleared Balance) cell text for ``entry``.

        Blank for anything that doesn't contribute a running balance:
        non-``Transaction`` directives, ``#recurring`` templates (already
        excluded from ``self._running_balances``/``self._cleared_balances``
        since ``Ledger.running_balances`` walks ``_actual_transactions``),
        and, for Cleared Balance only, a transaction whose flag isn't
        ``"*"`` (present in ``self._running_balances`` but absent from
        ``self._cleared_balances`` -- see ``Ledger.running_balances``'s
        ``only_cleared`` filter).
        """
        if not isinstance(entry, data.Transaction):
            return "", ""
        running = ""
        if self._running_balances is not None:
            balance = self._running_balances.get(id(entry))
            if balance is not None:
                running = format_inventory(balance)
        cleared = ""
        if self._cleared_balances is not None:
            balance = self._cleared_balances.get(id(entry))
            if balance is not None:
                cleared = format_inventory(balance)
        return running, cleared

    def _set_sort(self, field: SortField) -> None:
        """Apply ``field`` as the active sort, toggling direction on repeat."""
        if self._sort_field == field:
            self._sort_reverse = not self._sort_reverse
        else:
            self._sort_field = field
            self._sort_reverse = False
        self.update_entries(self.shown, self._running_balances, self._cleared_balances)

    def action_cycle_sort(self) -> None:
        """Step through ``_SORT_STEPS``: cycling field and, per field, direction."""
        current = (self._sort_field, self._sort_reverse)
        try:
            index = _SORT_STEPS.index(current)
            next_step = _SORT_STEPS[(index + 1) % len(_SORT_STEPS)]
        except ValueError:
            next_step = _SORT_STEPS[0]
        self._sort_field, self._sort_reverse = next_step
        self.update_entries(self.shown, self._running_balances, self._cleared_balances)

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
        if "recurring" in (entry.tags or set()):
            # A #recurring transaction is a template, not actual activity
            # (see Ledger._actual_transactions) -- it's excluded from every
            # report but stays visible/editable here, so mark it clearly.
            narration = f"↻ {narration}".strip()
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
