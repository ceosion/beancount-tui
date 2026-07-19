"""The main Textual application."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from beancount.core import data, getters
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Static

from beancount_tui.editor import append_transaction, delete_entry, format_entry, replace_entry
from beancount_tui.ledger import Ledger, filter_transactions
from beancount_tui.widgets.account_tree import AccountTree
from beancount_tui.widgets.confirm_dialog import ConfirmDialog
from beancount_tui.widgets.directive_form import DirectiveForm
from beancount_tui.widgets.filter_bar import FilterBar
from beancount_tui.widgets.transaction_form import TransactionForm, TransactionFormResult
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
    #filter {
        display: none;
    }
    #filter.visible {
        display: block;
    }
    """

    BINDINGS = [
        ("n", "new_transaction", "New"),
        ("e", "edit_transaction", "Edit"),
        ("c", "duplicate_transaction", "Duplicate"),
        ("d", "delete_transaction", "Delete"),
        ("t", "toggle_directives", "Directives"),
        ("u", "undo", "Undo"),
        ("/", "filter", "Filter"),
        ("r", "reload", "Reload"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self, ledger_path: str | Path, watch_interval: float = 1.0) -> None:
        super().__init__()
        self.ledger = Ledger.load(ledger_path)
        self.selected_account: str | None = None
        self.filter_query: str = ""
        self.show_directives: bool = False
        self._watch_interval = watch_interval
        self._watched_mtimes = self.ledger.file_mtimes()
        # Single-level undo: the affected file and its content before the last write.
        self._undo: tuple[Path, str] | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            yield AccountTree(id="sidebar")
            with Vertical():
                yield FilterBar(id="filter")
                yield TransactionTable(id="transactions")
                yield Static(id="errors")
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = str(self.ledger.path)
        self.refresh_views()
        self.set_interval(self._watch_interval, self._check_external_changes)

    def _visible_entries(self) -> list[data.Directive]:
        if self.show_directives:
            entries: list[data.Directive] = self.ledger.entries_for_account(
                self.selected_account
            )
        else:
            entries = list(self.ledger.transactions_for_account(self.selected_account))
        return filter_transactions(entries, self.filter_query)

    def refresh_views(self) -> None:
        self.query_one(AccountTree).update_accounts(self.ledger.root_account())
        self.query_one(TransactionTable).update_entries(self._visible_entries())
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
        self.query_one(TransactionTable).update_entries(self._visible_entries())

    def action_toggle_directives(self) -> None:
        self.show_directives = not self.show_directives
        self.query_one(TransactionTable).update_entries(self._visible_entries())

    def action_filter(self) -> None:
        bar = self.query_one(FilterBar)
        bar.add_class("visible")
        bar.focus()

    def on_filter_bar_filter_changed(self, event: FilterBar.FilterChanged) -> None:
        self.filter_query = event.query
        self.query_one(TransactionTable).update_entries(self._visible_entries())

    def on_filter_bar_filter_accepted(self, event: FilterBar.FilterAccepted) -> None:
        self.query_one(TransactionTable).focus()

    def on_filter_bar_filter_closed(self, event: FilterBar.FilterClosed) -> None:
        bar = self.query_one(FilterBar)
        bar.value = ""
        bar.remove_class("visible")
        self.filter_query = ""
        self.query_one(TransactionTable).update_entries(self._visible_entries())
        self.query_one(TransactionTable).focus()

    def _snapshot_for_undo(self, path: str | Path) -> None:
        path = Path(path)
        self._undo = (path, path.read_text(encoding="utf-8"))

    def action_undo(self) -> None:
        if self._undo is None:
            self.notify("Nothing to undo.", severity="warning")
            return
        path, content = self._undo
        path.write_text(content, encoding="utf-8")
        self._undo = None
        self.ledger.reload()
        self._watched_mtimes = self.ledger.file_mtimes()
        self.refresh_views()
        self.notify(f"Undid last change to {path.name}.")

    def action_reload(self) -> None:
        self.ledger.reload()
        self._watched_mtimes = self.ledger.file_mtimes()
        self.refresh_views()
        self.notify("Ledger reloaded.")

    def _check_external_changes(self) -> None:
        # Leave the ledger alone while a modal (form/dialog) is open: a reload
        # under an in-progress edit would let it write back to stale locations.
        if len(self.screen_stack) > 1:
            return
        current = self.ledger.file_mtimes()
        if current != self._watched_mtimes:
            self.ledger.reload()
            self._watched_mtimes = self.ledger.file_mtimes()
            self.refresh_views()
            self.notify("Ledger changed on disk; reloaded.")

    def action_new_transaction(self) -> None:
        def on_result(result: TransactionFormResult | None) -> None:
            if result is None:
                return
            target = result.filename or self.ledger.path
            self._snapshot_for_undo(target)
            append_transaction(target, result.text)
            self.action_reload()

        self.push_screen(
            TransactionForm(files=self.ledger.files, accounts=self.ledger.accounts), on_result
        )

    def action_edit_transaction(self) -> None:
        entry = self.query_one(TransactionTable).selected_entry
        if entry is None:
            self.notify("No entry selected.", severity="warning")
            return

        if isinstance(entry, data.Transaction):

            def on_form_result(result: TransactionFormResult | None) -> None:
                if result is None:
                    return
                self._snapshot_for_undo(entry.meta["filename"])
                replace_entry(entry, result.text)
                self.action_reload()

            self.push_screen(_edit_form(entry, self.ledger.accounts), on_form_result)
            return

        def on_text_result(text: str | None) -> None:
            if text is None:
                return
            self._snapshot_for_undo(entry.meta["filename"])
            replace_entry(entry, text)
            self.action_reload()

        keyword = type(entry).__name__.lower()
        self.push_screen(
            DirectiveForm(format_entry(entry).rstrip("\n"), title=f"Edit {keyword} directive"),
            on_text_result,
        )

    def action_duplicate_transaction(self) -> None:
        entry = self.query_one(TransactionTable).selected_entry
        if not isinstance(entry, data.Transaction):
            self.notify("No transaction selected.", severity="warning")
            return

        def on_result(result: TransactionFormResult | None) -> None:
            if result is None:
                return
            target = result.filename or self.ledger.path
            self._snapshot_for_undo(target)
            append_transaction(target, result.text)
            self.action_reload()

        self.push_screen(
            _duplicate_form(entry, self.ledger.files, self.ledger.accounts), on_result
        )

    def action_delete_transaction(self) -> None:
        entry = self.query_one(TransactionTable).selected_entry
        if entry is None:
            self.notify("No entry selected.", severity="warning")
            return

        def on_result(confirmed: bool | None) -> None:
            if not confirmed:
                return
            self._snapshot_for_undo(entry.meta["filename"])
            delete_entry(entry)
            self.action_reload()

        self.push_screen(
            ConfirmDialog(f"Delete {_entry_summary(entry)}?", confirm_label="Delete"),
            on_result,
        )


def _entry_summary(entry: data.Directive) -> str:
    """A short human-readable description for confirmation prompts."""
    if isinstance(entry, data.Transaction):
        parts = (str(entry.date), entry.payee, entry.narration)
        return "transaction " + " ".join(p for p in parts if p)
    keyword = type(entry).__name__.lower()
    accounts = ", ".join(sorted(getters.get_entry_accounts(entry)))
    return f"{keyword} directive {entry.date} {accounts}"


def _postings_text(txn: data.Transaction) -> str:
    lines = format_entry(txn).rstrip("\n").split("\n")
    return "\n".join(line.strip() for line in lines[1:])


def _edit_form(txn: data.Transaction, accounts: list[str]) -> TransactionForm:
    """Build a form pre-filled from an existing transaction."""
    return TransactionForm(
        date=txn.date.isoformat(),
        flag=txn.flag or "*",
        payee=txn.payee or "",
        narration=txn.narration or "",
        postings_text=_postings_text(txn),
        title="Edit transaction",
        accounts=accounts,
    )


def _duplicate_form(
    txn: data.Transaction, files: list[Path], accounts: list[str]
) -> TransactionForm:
    """Build a form for a copy of ``txn``, dated today and appended on save."""
    return TransactionForm(
        flag=txn.flag or "*",
        payee=txn.payee or "",
        narration=txn.narration or "",
        postings_text=_postings_text(txn),
        title="Duplicate transaction",
        files=files,
        accounts=accounts,
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
