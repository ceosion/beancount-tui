"""Sidebar tree of the account hierarchy with balances."""

from __future__ import annotations

from beancount.core import realization
from textual.message import Message
from textual.widgets import Tree
from textual.widgets.tree import TreeNode


class AccountTree(Tree[str]):
    """Displays the realized account hierarchy.

    Each node's data is the full account name (e.g. ``Expenses:Food``),
    or ``None`` for the synthetic root.
    """

    class AccountSelected(Message):
        def __init__(self, account: str | None) -> None:
            self.account = account
            super().__init__()

    def __init__(self, **kwargs) -> None:
        super().__init__("All accounts", data=None, **kwargs)

    def update_accounts(self, real_root: realization.RealAccount) -> None:
        self.clear()
        self._add_account_nodes(self.root, real_root)
        self.root.expand()

    def _add_account_nodes(
        self, node: TreeNode, real_account: realization.RealAccount
    ) -> None:
        for name in sorted(real_account):
            child = real_account[name]
            # Cumulative balance: the account's own postings plus all children.
            balance = realization.compute_balance(child).reduce(lambda pos: pos.units)
            positions = sorted(balance.get_positions(), key=lambda pos: pos.units.currency)
            amounts = ", ".join(
                f"{pos.units.number:,} {pos.units.currency}" for pos in positions
            )
            label = f"{name}  [dim]{amounts}[/dim]" if amounts else name
            child_node = node.add(label, data=child.account, expand=True)
            self._add_account_nodes(child_node, child)
            if not child:
                child_node.allow_expand = False

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        event.stop()
        self.post_message(self.AccountSelected(event.node.data))
