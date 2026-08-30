"""Sidebar tree of the account hierarchy with balances."""

from __future__ import annotations

from beancount.core import realization
from rich.cells import cell_len
from rich.style import Style
from rich.text import Text
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
        # Node id -> balance text, rendered right-aligned by ``render_label``.
        self._amounts: dict[int, str] = {}

    def update_accounts(self, real_root: realization.RealAccount) -> None:
        self.clear()
        self._amounts.clear()
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
            child_node = node.add(name, data=child.account, expand=True)
            if amounts:
                self._amounts[child_node.id] = amounts
            self._add_account_nodes(child_node, child)
            if not child:
                child_node.allow_expand = False

    def _guide_prefix_width(self, node: TreeNode) -> int:
        """Cells the tree guides occupy before this node's label."""
        depth = 0
        current = node.parent
        while current is not None:
            depth += 1
            current = current.parent
        return depth * self.guide_depth

    def render_label(
        self, node: TreeNode, base_style: Style, style: Style
    ) -> Text:
        text = super().render_label(node, base_style, style)
        amount = self._amounts.get(node.id)
        if amount:
            available = self.size.width - self._guide_prefix_width(node)
            pad = max(1, available - text.cell_len - cell_len(amount))
            text.append(" " * pad)
            text.append(amount, style=base_style + Style(dim=True))
        return text

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        event.stop()
        self.post_message(self.AccountSelected(event.node.data))
