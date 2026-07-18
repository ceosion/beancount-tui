"""Read-only access to a Beancount ledger via the beancount library."""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from beancount import loader
from beancount.core import data, getters, realization
from beancount.core.inventory import Inventory


@dataclass
class Ledger:
    """A loaded Beancount ledger.

    Wraps ``beancount.loader`` and exposes the pieces the UI needs:
    transactions, the account hierarchy with balances, and validation errors.
    """

    path: Path
    entries: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    options: dict = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path) -> "Ledger":
        path = Path(path)
        entries, errors, options = loader.load_file(str(path))
        return cls(path=path, entries=entries, errors=errors, options=options)

    def reload(self) -> None:
        self.entries, self.errors, self.options = loader.load_file(str(self.path))

    @property
    def transactions(self) -> list[data.Transaction]:
        return [e for e in self.entries if isinstance(e, data.Transaction)]

    @property
    def accounts(self) -> list[str]:
        """All account names that appear in the ledger, sorted."""
        return sorted(getters.get_accounts(self.entries))

    def transactions_for_account(self, account: str | None) -> list[data.Transaction]:
        """Transactions posting to ``account`` or any of its sub-accounts."""
        if account is None:
            return self.transactions
        prefix = account + ":"
        return [
            txn
            for txn in self.transactions
            if any(p.account == account or p.account.startswith(prefix) for p in txn.postings)
        ]

    def root_account(self) -> realization.RealAccount:
        """The realized account tree, with balances, for the account sidebar."""
        return realization.realize(self.entries)


def filter_transactions(
    transactions: list[data.Transaction], query: str
) -> list[data.Transaction]:
    """Filter transactions by payee/narration text or by date range.

    A query of the form ``START..END`` — ISO dates, either side optional
    (``2026-01-01..2026-01-31``, ``2026-01-15..``, ``..2026-01-10``) —
    selects a date range, inclusive on both ends. Any other query is a
    case-insensitive substring match against payee and narration.
    """
    query = query.strip()
    if not query:
        return transactions
    date_range = _parse_date_range(query)
    if date_range is not None:
        start, end = date_range
        return [
            txn
            for txn in transactions
            if (start is None or txn.date >= start) and (end is None or txn.date <= end)
        ]
    needle = query.lower()
    return [
        txn
        for txn in transactions
        if needle in (txn.payee or "").lower() or needle in (txn.narration or "").lower()
    ]


def _parse_date_range(
    query: str,
) -> tuple[datetime.date | None, datetime.date | None] | None:
    """Parse ``START..END`` into dates, or ``None`` if it isn't a date range."""
    if ".." not in query:
        return None
    start_text, _, end_text = query.partition("..")
    try:
        start = datetime.date.fromisoformat(start_text.strip()) if start_text.strip() else None
        end = datetime.date.fromisoformat(end_text.strip()) if end_text.strip() else None
    except ValueError:
        return None
    if start is None and end is None:
        return None
    return start, end


def transaction_amount(txn: data.Transaction) -> str:
    """A one-line summary of a transaction's magnitude, e.g. ``120.50 USD``.

    Sums the absolute value of positive postings per currency; transactions
    always balance, so this is the amount that changed hands.
    """
    inventory = Inventory()
    for posting in txn.postings:
        if posting.units is not None and posting.units.number is not None:
            if posting.units.number > Decimal(0):
                inventory.add_amount(posting.units)
    positions = sorted(inventory, key=lambda pos: pos.units.currency)
    return ", ".join(f"{pos.units.number} {pos.units.currency}" for pos in positions)
