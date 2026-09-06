"""The main Textual application."""

from __future__ import annotations

import argparse
import datetime
import sys
from collections import deque
from pathlib import Path

from beancount.core import data, getters, realization
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Static

from beancount_tui.editor import append_entry, delete_entry, format_entry, replace_entry
from beancount_tui.importer import ImportCandidate
from beancount_tui.ledger import Ledger, filter_transactions
from beancount_tui.widgets.account_tree import AccountTree
from beancount_tui.widgets.balance_sheet import BalanceSheetScreen
from beancount_tui.widgets.confirm_dialog import ConfirmDialog
from beancount_tui.widgets.directive_form import DirectiveForm, DirectiveFormResult
from beancount_tui.widgets.directive_type_picker import DirectiveTypePicker
from beancount_tui.widgets.filter_bar import FilterBar
from beancount_tui.widgets.help_screen import HelpScreen
from beancount_tui.widgets.import_form import ImportForm
from beancount_tui.widgets.import_review import ImportReviewScreen
from beancount_tui.widgets.income_statement import IncomeStatementScreen
from beancount_tui.widgets.ledger_info import LedgerInfoScreen
from beancount_tui.widgets.register import RegisterScreen
from beancount_tui.widgets.transaction_form import TransactionForm, TransactionFormResult
from beancount_tui.widgets.transaction_table import TransactionTable
from beancount_tui.widgets.trial_balance import TrialBalanceScreen

# Minimal valid source text for each creatable non-transaction directive type,
# ready for the user to fill in the placeholder account(s)/amount.
_DIRECTIVE_TEMPLATES = {
    "open": "{date} open Assets:FIXME",
    "close": "{date} close Assets:FIXME",
    "balance": "{date} balance Assets:FIXME  0.00 USD",
    "pad": "{date} pad Assets:FIXME Equity:Opening-Balances",
    "note": '{date} note Assets:FIXME "FIXME"',
    "price": "{date} price FIXME  0.00 USD",
    "event": '{date} event "location" "FIXME"',
    "custom": '{date} custom "budget" "FIXME"',
    "query": '{date} query "FIXME" "SELECT account, sum(position) GROUP BY account"',
    "document": '{date} document Assets:FIXME "path/to/file.pdf"',
    "commodity": "{date} commodity HOOL",
}


def _directive_template(keyword: str, date: str) -> str:
    return _DIRECTIVE_TEMPLATES[keyword].format(date=date)


# How many writes back the undo history reaches (per acceptance criterion:
# "at least the last 20 writes ... can be undone in sequence").
UNDO_HISTORY_LIMIT = 20


class UndoManager:
    """A bounded, chronological undo/redo history spanning every file in the
    ledger.

    Snapshots are ``(path, content)`` pairs recording a file's content
    immediately *before* a write to it. Both stacks are global (not one per
    file) so a single `undo`/`redo` keypress, which carries no file
    argument, always has an unambiguous "most recent change" to act on.
    Because each snapshot remembers its own path, popping one only ever
    touches the file it belongs to — so undoing a change to file A never
    disturbs file B, even if they're interleaved in the history.
    """

    def __init__(self, limit: int = UNDO_HISTORY_LIMIT) -> None:
        self._undo: deque[tuple[Path, str]] = deque(maxlen=limit)
        self._redo: deque[tuple[Path, str]] = deque(maxlen=limit)

    def record(self, path: Path, content: str) -> None:
        """Record `content` as the pre-write state of `path`.

        Called just before every mutating action. A new write invalidates
        any pending redo.
        """
        self._undo.append((path, content))
        self._redo.clear()

    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def pop_undo(self) -> tuple[Path, str] | None:
        """Pop and return the most recent undo snapshot, or ``None``."""
        return self._undo.pop() if self._undo else None

    def pop_redo(self) -> tuple[Path, str] | None:
        """Pop and return the most recent redo snapshot, or ``None``."""
        return self._redo.pop() if self._redo else None

    def push_redo(self, path: Path, content: str) -> None:
        """Save `content` (the state being overwritten by an undo) so a
        subsequent redo can restore it."""
        self._redo.append((path, content))

    def push_undo(self, path: Path, content: str) -> None:
        """Save `content` (the state being overwritten by a redo) back onto
        the undo stack, without touching the redo stack — so a redo can
        itself be undone."""
        self._undo.append((path, content))


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
        ("a", "add_directive", "Add directive"),
        ("e", "edit_transaction", "Edit"),
        ("c", "duplicate_transaction", "Duplicate"),
        ("d", "delete_transaction", "Delete"),
        ("t", "toggle_directives", "Directives"),
        ("u", "undo", "Undo"),
        ("U", "redo", "Redo"),
        ("i", "income_statement", "Income stmt"),
        ("b", "trial_balance", "Trial balance"),
        ("B", "balance_directive", "Balance now"),
        ("g", "register", "Register"),
        ("s", "balance_sheet", "Balance sheet"),
        ("L", "ledger_info", "Ledger info"),
        ("m", "import_csv", "Import CSV"),
        ("/", "filter", "Filter"),
        ("r", "reload", "Reload"),
        ("q", "quit", "Quit"),
        ("question_mark", "help", "Help"),
    ]

    def __init__(self, ledger_path: str | Path, watch_interval: float = 1.0) -> None:
        super().__init__()
        self.ledger = Ledger.load(ledger_path)
        self.selected_account: str | None = None
        self.filter_query: str = ""
        self.show_directives: bool = False
        self._watch_interval = watch_interval
        self._watched_mtimes = self.ledger.file_mtimes()
        # Bounded, chronological undo/redo history across every file touched.
        self._undo_manager = UndoManager()

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

    def action_income_statement(self) -> None:
        self.push_screen(IncomeStatementScreen(self.ledger))

    def action_trial_balance(self) -> None:
        self.push_screen(TrialBalanceScreen(self.ledger))

    def action_register(self) -> None:
        if self.selected_account is None:
            self.notify("No account selected.", severity="warning")
            return
        self.push_screen(RegisterScreen(self.ledger, self.selected_account))

    def action_balance_sheet(self) -> None:
        self.push_screen(BalanceSheetScreen(self.ledger))

    def action_ledger_info(self) -> None:
        self.push_screen(LedgerInfoScreen(self.ledger))

    def action_help(self) -> None:
        self.push_screen(HelpScreen(self.BINDINGS))

    def action_import_csv(self) -> None:
        def on_candidates(candidates: list[ImportCandidate] | None) -> None:
            if candidates is None:
                return

            def on_review(texts: list[str] | None) -> None:
                if texts is None:
                    return
                if texts:
                    self._snapshot_for_undo(self.ledger.path)
                    for text in texts:
                        append_entry(self.ledger.path, text)
                self.action_reload()
                skipped = len(candidates) - len(texts)
                summary = f"Imported {len(texts)} transaction(s)."
                if skipped:
                    summary += f" Skipped {skipped}."
                self.notify(summary)

            self.push_screen(
                ImportReviewScreen(candidates, accounts=self.ledger.accounts), on_review
            )

        self.push_screen(ImportForm(), on_candidates)

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
        self._undo_manager.record(path, path.read_text(encoding="utf-8"))

    def action_undo(self) -> None:
        entry = self._undo_manager.pop_undo()
        if entry is None:
            self.notify("Nothing to undo.", severity="warning")
            return
        path, content = entry
        self._undo_manager.push_redo(path, path.read_text(encoding="utf-8"))
        path.write_text(content, encoding="utf-8")
        self.ledger.reload()
        self._watched_mtimes = self.ledger.file_mtimes()
        self.refresh_views()
        self.notify(f"Undid last change to {path.name}.")

    def action_redo(self) -> None:
        entry = self._undo_manager.pop_redo()
        if entry is None:
            self.notify("Nothing to redo.", severity="warning")
            return
        path, content = entry
        self._undo_manager.push_undo(path, path.read_text(encoding="utf-8"))
        path.write_text(content, encoding="utf-8")
        self.ledger.reload()
        self._watched_mtimes = self.ledger.file_mtimes()
        self.refresh_views()
        self.notify(f"Redid last change to {path.name}.")

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
            append_entry(target, result.text)
            self.action_reload()

        self.push_screen(
            TransactionForm(files=self.ledger.files, accounts=self.ledger.accounts), on_result
        )

    def action_add_directive(self) -> None:
        def on_type_chosen(keyword: str | None) -> None:
            if keyword is None:
                return
            template = _directive_template(keyword, datetime.date.today().isoformat())

            def on_form_result(result: DirectiveFormResult | None) -> None:
                if result is None:
                    return
                target = result.filename or self.ledger.path
                self._snapshot_for_undo(target)
                append_entry(target, result.text)
                self.action_reload()

            self.push_screen(
                DirectiveForm(
                    template, title=f"New {keyword} directive", files=self.ledger.files
                ),
                on_form_result,
            )

        self.push_screen(DirectiveTypePicker(), on_type_chosen)

    def action_balance_directive(self) -> None:
        """Checkpoint the selected account: a `balance` directive for its
        current computed balance, dated today, skipping straight to
        `DirectiveForm` (no `DirectiveTypePicker` step).

        An account holding more than one currency needs one `balance`
        directive per currency (`parse_directive_text` only accepts exactly
        one directive per save), so multi-currency accounts are handled by
        chaining `DirectiveForm` screens, one per currency, in sequence.
        """
        if self.selected_account is None:
            self.notify("No account selected.", severity="warning")
            return
        account = self.selected_account
        node = realization.get(self.ledger.root_account(), account)
        if node is None:
            self.notify("No account selected.", severity="warning")
            return
        balance = realization.compute_balance(node).reduce(lambda pos: pos.units)
        positions = sorted(balance.get_positions(), key=lambda pos: pos.units.currency)
        date = datetime.date.today().isoformat()
        if positions:
            texts = [
                f"{date} balance {account}  {pos.units.number} {pos.units.currency}"
                for pos in positions
            ]
        else:
            currency = (self.ledger.options.get("operating_currency") or ["USD"])[0]
            texts = [f"{date} balance {account}  0.00 {currency}"]

        def push_form(index: int) -> None:
            def on_form_result(result: DirectiveFormResult | None) -> None:
                if result is None:
                    return
                target = result.filename or self.ledger.path
                self._snapshot_for_undo(target)
                append_entry(target, result.text)
                self.action_reload()
                if index + 1 < len(texts):
                    push_form(index + 1)

            title = "New balance directive"
            if len(texts) > 1:
                title += f" ({index + 1}/{len(texts)})"
            self.push_screen(
                DirectiveForm(texts[index], title=title, files=self.ledger.files),
                on_form_result,
            )

        push_form(0)

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

        def on_directive_result(result: DirectiveFormResult | None) -> None:
            if result is None:
                return
            self._snapshot_for_undo(entry.meta["filename"])
            replace_entry(entry, result.text)
            self.action_reload()

        keyword = type(entry).__name__.lower()
        self.push_screen(
            DirectiveForm(format_entry(entry).rstrip("\n"), title=f"Edit {keyword} directive"),
            on_directive_result,
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
            append_entry(target, result.text)
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


def _tags_links_text(txn: data.Transaction) -> str:
    """Render a transaction's tags/links as ``#tag ^link`` text for the form."""
    tokens = [f"#{tag}" for tag in sorted(txn.tags or ())]
    tokens += [f"^{link}" for link in sorted(txn.links or ())]
    return " ".join(tokens)


def _edit_form(txn: data.Transaction, accounts: list[str]) -> TransactionForm:
    """Build a form pre-filled from an existing transaction."""
    return TransactionForm(
        date=txn.date.isoformat(),
        flag=txn.flag or "*",
        payee=txn.payee or "",
        narration=txn.narration or "",
        tags_links=_tags_links_text(txn),
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
        tags_links=_tags_links_text(txn),
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
