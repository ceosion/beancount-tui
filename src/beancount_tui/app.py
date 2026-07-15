"""The main Textual application."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from beancount.core import data
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Static

from beancount_tui.editor import append_transaction, format_entry, replace_entry
from beancount_tui.ledger import Ledger
from beancount_tui.widgets.account_tree import AccountTree
from beancount_tui.widgets.transaction_form import TransactionForm
from beancount_tui.widgets.transaction_table import TransactionTable


class BeancountTUI(App):
    """Browse and edit a Beancount ledger."""

    TITLE = "beancount-tui"

    CSS = """
    #sidebar {
        width: 36;
        border-right: solid $primary;
    }
    #errors {
        dock: bottom;
        height: auto;
        max-height: 6;
        color: $error;
        padding: 0 1;
        display: none;
    }
    #errors.has-errors {
        display: block;
        border-top: solid $error;
    }
    """

    BINDINGS = [
        ("n", "new_transaction", "New"),
        ("e", "edit_transaction", "Edit"),
        ("r", "reload", "Reload"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self, ledger_path: str | Path) -> None:
        super().__init__()
        self.ledger = Ledger.load(ledger_path)
        self.selected_account: str | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            yield AccountTree(id="sidebar")
            with Vertical():
                yield TransactionTable(id="transactions")
                yield Static(id="errors")
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = str(self.ledger.path)
        self.refresh_views()

    def refresh_views(self) -> None:
        self.query_one(AccountTree).update_accounts(self.ledger.root_account())
        self.query_one(TransactionTable).update_transactions(
            self.ledger.transactions_for_account(self.selected_account)
        )
        error_panel = self.query_one("#errors", Static)
        if self.ledger.errors:
            messages = "\n".join(
                f"{Path(e.source.get('filename', '?')).name}:{e.source.get('lineno', '?')}: "
                f"{e.message}"
                for e in self.ledger.errors[:5]
            )
            more = len(self.ledger.errors) - 5
            if more > 0:
                messages += f"\n… and {more} more"
            error_panel.update(messages)
            error_panel.add_class("has-errors")
        else:
            error_panel.update("")
            error_panel.remove_class("has-errors")

    def on_account_tree_account_selected(self, event: AccountTree.AccountSelected) -> None:
        self.selected_account = event.account
        self.query_one(TransactionTable).update_transactions(
            self.ledger.transactions_for_account(self.selected_account)
        )

    def action_reload(self) -> None:
        self.ledger.reload()
        self.refresh_views()
        self.notify("Ledger reloaded.")

    def action_new_transaction(self) -> None:
        def on_result(text: str | None) -> None:
            if text is None:
                return
            append_transaction(self.ledger.path, text)
            self.action_reload()

        self.push_screen(TransactionForm(), on_result)

    def action_edit_transaction(self) -> None:
        txn = self.query_one(TransactionTable).selected_transaction
        if txn is None:
            self.notify("No transaction selected.", severity="warning")
            return

        def on_result(text: str | None) -> None:
            if text is None:
                return
            replace_entry(txn, text)
            self.action_reload()

        self.push_screen(_edit_form(txn), on_result)


def _edit_form(txn: data.Transaction) -> TransactionForm:
    """Build a form pre-filled from an existing transaction."""
    lines = format_entry(txn).rstrip("\n").split("\n")
    postings_text = "\n".join(line.strip() for line in lines[1:])
    return TransactionForm(
        date=txn.date.isoformat(),
        payee=txn.payee or "",
        narration=txn.narration or "",
        postings_text=postings_text,
        title="Edit transaction",
    )


def main() -> None:
    arg_parser = argparse.ArgumentParser(
        prog="beancount-tui", description="A terminal UI for editing Beancount ledgers."
    )
    arg_parser.add_argument("ledger", help="Path to the Beancount ledger file")
    args = arg_parser.parse_args()
    if not Path(args.ledger).is_file():
        sys.exit(f"error: no such file: {args.ledger}")
    BeancountTUI(args.ledger).run()


if __name__ == "__main__":
    main()
