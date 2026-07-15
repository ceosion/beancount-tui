"""Read-only access to a Beancount ledger via the beancount library."""

from __future__ import annotations

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
