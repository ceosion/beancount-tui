"""Sidebar tree of the account hierarchy with balances."""

from __future__ import annotations

from beancount.core import realization
from beancount.core.inventory import Inventory
from rich.cells import cell_len
from rich.style import Style
from rich.text import Text
from textual.message import Message
from textual.widgets import Tree
from textual.widgets.tree import TreeNode

from beancount_tui.ledger import Ledger


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
        # Whether ``update_accounts`` has ever run before. The very first
        # rebuild (a freshly opened ledger) should start fully expanded;
        # later rebuilds (reload/filter/selection) should preserve whatever
        # the user manually collapsed instead of wiping it out.
        self._loaded = False

    def update_accounts(self, real_root: realization.RealAccount, ledger: Ledger) -> None:
        collapsed_paths: set[str] = set()
        root_was_collapsed = False
        if self._loaded:
            collapsed_paths = self._collapsed_account_paths()
            root_was_collapsed = not self.root.is_expanded
        self.clear()
        self._amounts.clear()
        self._add_account_nodes(self.root, real_root, ledger)
        self.root.expand()
        if collapsed_paths:
            self._restore_collapsed_account_paths(self.root, collapsed_paths)
        if root_was_collapsed:
            self.root.collapse()
        self._loaded = True

    def _collapsed_account_paths(self) -> set[str]:
        """Account names of every currently-collapsed node, before a rebuild."""
        paths: set[str] = set()

        def visit(node: TreeNode) -> None:
            if node.data is not None and not node.is_expanded:
                paths.add(node.data)
            for child in node.children:
                visit(child)

        visit(self.root)
        return paths

    def _restore_collapsed_account_paths(self, node: TreeNode, paths: set[str]) -> None:
        """Re-collapse nodes (added expanded by ``_add_account_nodes``) whose
        account name was collapsed before the rebuild."""
        for child in node.children:
            if child.data in paths:
                child.collapse()
            self._restore_collapsed_account_paths(child, paths)

    def _add_account_nodes(
        self, node: TreeNode, real_account: realization.RealAccount, ledger: Ledger
    ) -> None:
        for name in sorted(real_account):
            child = real_account[name]
            # Cumulative balance: the account's own postings plus all children.
            balance = realization.compute_balance(child).reduce(lambda pos: pos.units)
            positions = sorted(balance.get_positions(), key=lambda pos: pos.units.currency)
            amounts = ", ".join(
                f"{pos.units.number:,} {pos.units.currency}" for pos in positions
            )
            amounts += _conversion_note(ledger, balance)
            child_node = node.add(name, data=child.account, expand=True)
            if amounts:
                self._amounts[child_node.id] = amounts
            self._add_account_nodes(child_node, child, ledger)
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


def _conversion_note(ledger: Ledger, balance: Inventory) -> str:
    """A trailing ``  (≈ 175.32 USD)``-style note for a converted total.

    Empty if no operating currency is configured, or if the balance is
    already entirely denominated in it (nothing to convert). Currencies that
    couldn't be priced are called out by name rather than silently dropped.
    """
    operating_currencies = ledger.options.get("operating_currency") or []
    if not operating_currencies:
        return ""
    target = operating_currencies[0]
    currencies = {pos.units.currency for pos in balance.get_positions()}
    if currencies <= {target}:
        return ""
    total, unpriced = ledger.converted_total(balance)
    parts = []
    if total is not None:
        parts.append(f"≈ {total:,.2f} {target}")
    if unpriced:
        parts.append(f"no price available for {', '.join(unpriced)}")
    if not parts:
        return ""
    return "  (" + ", ".join(parts) + ")"
