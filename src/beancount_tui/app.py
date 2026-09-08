"""The main Textual application."""

from __future__ import annotations

import argparse
import datetime
import sys
from collections import deque
from collections.abc import Callable
from pathlib import Path

from beancount.core import data, getters, realization
from beancount.core.inventory import Inventory
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, Footer, Header, Static

from beancount_tui.config import (
    DEFAULT_WATCH_INTERVAL,
    default_config_path,
    load_config,
    resolve_bindings,
    set_theme,
)
from beancount_tui.editor import (
    append_entry,
    delete_entry,
    format_entry,
    parse_transaction_text,
    replace_entry,
    replace_flag,
)
from beancount_tui.importer import ImportCandidate
from beancount_tui.ledger import Ledger, RecurringTemplate, filter_transactions
from beancount_tui.widgets.account_tree import AccountTree
from beancount_tui.widgets.balance_sheet import BalanceSheetScreen
from beancount_tui.widgets.beangulp_import_form import BeangulpImportForm
from beancount_tui.widgets.budget_form import BudgetForm
from beancount_tui.widgets.budget_screen import BudgetScreen
from beancount_tui.widgets.confirm_dialog import ConfirmDialog
from beancount_tui.widgets.directive_form import DirectiveForm, DirectiveFormResult
from beancount_tui.widgets.directive_type_picker import DirectiveTypePicker
from beancount_tui.widgets.document_preview import DocumentPreviewScreen
from beancount_tui.widgets.filter_bar import FilterBar
from beancount_tui.widgets.forecast_screen import ForecastScreen
from beancount_tui.widgets.help_screen import HelpScreen
from beancount_tui.widgets.holdings import HoldingsScreen
from beancount_tui.widgets.import_form import ImportForm
from beancount_tui.widgets.import_review import ImportReviewScreen
from beancount_tui.widgets.income_statement import IncomeStatementScreen
from beancount_tui.widgets.ledger_info import LedgerInfoScreen
from beancount_tui.widgets.pad_source_picker import PadSourcePicker
from beancount_tui.widgets.price_history import PriceHistoryScreen
from beancount_tui.widgets.query_runner import QueryRunnerScreen
from beancount_tui.widgets.register import RegisterScreen
from beancount_tui.widgets.transaction_form import TransactionForm, TransactionFormResult
from beancount_tui.widgets.transaction_table import TransactionTable
from beancount_tui.widgets.trial_balance import TrialBalanceScreen

# PERF-03: appended to `App.sub_title` (already used to show the ledger
# path -- see `on_mount`) while a background reload is in flight, so the
# always-visible `Header` widget doubles as the "reload in progress"
# indicator without any new widget/CSS. Restored to the bare path once the
# reload finishes (or fails).
_RELOADING_SUFFIX = "  ⏳ reloading…"

# Minimal valid source text for each creatable non-transaction directive type,
# ready for the user to fill in the placeholder account(s)/amount.
#
# "plugin" has no `{date}` placeholder, unlike every other entry here: a
# `plugin "module"` directive is undated in Beancount's own grammar (it's
# parsed into `options_map["plugin"]`, not a dated `data.*` entry) -- an
# `{date}` prefix in front of it is a parse error, not just an unused field.
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
    "plugin": 'plugin "beancount.plugins.auto_accounts"',
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


# The hardcoded default key bindings, kept as a module-level constant
# (rather than only living as `BeancountTUI.BINDINGS`) so `CONFIG-02`'s
# `main()`-time rebuild always has the *true* defaults to apply overrides
# on top of -- even if `main()` (or a test) runs more than once in the same
# process and `BeancountTUI.BINDINGS` has already been overwritten by a
# previous call to `_rebuild_bindings`.
_DEFAULT_BINDINGS: list[tuple[str, str, str]] = [
    ("n", "new_transaction", "New"),
    ("a", "add_directive", "Add directive"),
    ("e", "edit_transaction", "Edit"),
    ("c", "duplicate_transaction", "Duplicate"),
    ("d", "delete_transaction", "Delete"),
    ("f", "cycle_flag", "Cycle flag"),
    ("t", "toggle_directives", "Directives"),
    ("v", "toggle_detail", "Detail"),
    ("u", "undo", "Undo"),
    ("U", "redo", "Redo"),
    ("i", "income_statement", "Income stmt"),
    ("b", "trial_balance", "Trial balance"),
    ("B", "balance_directive", "Balance now"),
    ("p", "pad_and_verify", "Pad and verify"),
    ("P", "preview_document", "Preview document"),
    ("g", "register", "Register"),
    ("s", "balance_sheet", "Balance sheet"),
    ("G", "budget", "Budget vs actual"),
    ("F", "forecast", "Cash-flow forecast"),
    ("w", "holdings", "Holdings"),
    ("H", "price_history", "Price history"),
    ("L", "ledger_info", "Ledger info"),
    ("Q", "query_runner", "Query"),
    ("m", "import_csv", "Import CSV"),
    ("M", "import_beangulp", "Import (beangulp)"),
    ("/", "filter", "Filter"),
    ("r", "reload", "Reload"),
    ("q", "quit", "Quit"),
    ("question_mark", "help", "Help"),
]


def _rebuild_bindings(app_cls: type, overrides: dict[str, object]) -> None:
    """Apply `CONFIG-02`'s `[bindings]` config-file overrides to `app_cls`
    (normally `BeancountTUI`) *before* it's instantiated.

    This must run before construction: Textual resolves `BINDINGS` into a
    cached `cls._merged_bindings` exactly once, in `DOMNode.__init_subclass__`
    at class-definition (i.e. module-import) time, and every instance's
    actual key-dispatch table is built from that cache in `__init__` --
    simply reassigning `app_cls.BINDINGS` afterwards has no effect on key
    dispatch by itself. Recomputing `app_cls._merged_bindings` via the
    private `_merge_bindings()` classmethod (confirmed by direct testing
    against the installed Textual version to pick up a reassigned `BINDINGS`
    correctly) is what actually makes overrides take effect. There's no
    public Textual API for this because remapping an app's whole bindings
    table at runtime isn't a case Textual itself anticipates -- its
    supported `refresh_bindings()` is for enabling/disabling *existing*
    bindings via `check_action`, not changing which key maps to which
    action.

    The `hasattr` guard below is only there for tests that substitute a
    plain (non-Textual) recording stand-in for `BeancountTUI` -- such a
    stand-in has no `_merge_bindings` to refresh, but still gets its
    `BINDINGS` attribute set for inspection.
    """
    app_cls.BINDINGS = resolve_bindings(_DEFAULT_BINDINGS, overrides)
    if hasattr(app_cls, "_merge_bindings"):
        app_cls._merged_bindings = app_cls._merge_bindings()


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
    #detail {
        dock: bottom;
        height: auto;
        max-height: 12;
        border-top: solid $primary;
        padding: 0 1;
        display: none;
    }
    #detail.visible {
        display: block;
    }
    """

    BINDINGS = _DEFAULT_BINDINGS

    def __init__(
        self,
        ledger_path: str | Path,
        watch_interval: float = DEFAULT_WATCH_INTERVAL,
        theme: str | None = None,
        config_path: Path | None = None,
    ) -> None:
        super().__init__()
        self.ledger = Ledger.load(ledger_path)
        self.selected_account: str | None = None
        self.filter_query: str = ""
        self.show_directives: bool = False
        self.show_detail: bool = False
        self._watch_interval = watch_interval
        self._watched_mtimes = self.ledger.file_mtimes()
        # Bounded, chronological undo/redo history across every file touched.
        self._undo_manager = UndoManager()
        # PERF-03: guards every reload path (`action_reload`, `action_undo`/
        # `action_redo`, the polling `_check_external_changes`) against
        # stacking a second background reload on top of one already in
        # flight -- see `_start_reload`. `_pending_reload_notify` carries
        # the completion message (if any) from whichever call kicked off
        # the in-flight reload through to `_finish_reload`, since the
        # worker itself has no way to know which of the four call sites
        # started it.
        self._reload_in_progress: bool = False
        self._pending_reload_notify: str | None = None
        # CONFIG-03: the theme named in the config file (if any), applied
        # once on mount -- see `_apply_startup_theme`. `_config_path` is
        # whichever config file was actually resolved for this run (the
        # `--config` override, if given, else the XDG default), since
        # that's the file any later theme change gets written back to, not
        # necessarily `default_config_path()` itself.
        self._configured_theme = theme
        self._config_path = config_path if config_path is not None else default_config_path()
        # Set while `_apply_startup_theme` assigns `self.theme` from the
        # config file, so `watch_theme` (below) knows not to treat that
        # initial assignment as a *user* change worth writing back out --
        # only a genuine change (e.g. via the command palette's theme
        # picker) should persist.
        self._suppress_theme_persist = False

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            yield AccountTree(id="sidebar")
            with Vertical():
                yield FilterBar(id="filter")
                yield TransactionTable(id="transactions")
                yield Static(id="detail")
                yield Static(id="errors")
        yield Footer()

    def on_mount(self) -> None:
        self._apply_startup_theme()
        self.sub_title = str(self.ledger.path)
        self.refresh_views()
        self.set_interval(self._watch_interval, self._check_external_changes)

    def _apply_startup_theme(self) -> None:
        """Apply the `theme` configured in the config file, if any (`CONFIG-03`).

        `App.theme` is a validated Textual reactive: assigning a name that
        isn't a registered theme raises `InvalidThemeError` rather than just
        being ignored, so an unknown/invalid name is checked against
        `self.available_themes` *before* assigning, falling back to
        Textual's own default (whatever `self.theme` already is at this
        point) with a warning notification instead of crashing.
        """
        theme_name = self._configured_theme
        if not theme_name:
            return
        if theme_name not in self.available_themes:
            self.notify(
                f"Unknown theme {theme_name!r} in config file; using default.",
                severity="warning",
            )
            return
        self._suppress_theme_persist = True
        self.theme = theme_name

    def watch_theme(self, old_theme: str, new_theme: str) -> None:
        """Persist a theme change back to the config file (`CONFIG-03`), so
        a choice made via Textual's built-in command-palette theme picker
        sticks across restarts instead of resetting to the default every
        launch.

        Skipped once for the initial assignment `_apply_startup_theme`
        makes from the config file itself -- there's no need to rewrite the
        file with the same value it was just read from.
        """
        if self._suppress_theme_persist:
            self._suppress_theme_persist = False
            return
        set_theme(self._config_path, new_theme)

    def _visible_entries(self) -> list[data.Directive]:
        if self.show_directives:
            entries: list[data.Directive] = self.ledger.entries_for_account(
                self.selected_account
            )
        else:
            entries = list(self.ledger.transactions_for_account(self.selected_account))
        return filter_transactions(entries, self.filter_query)

    def _account_running_balances(
        self,
    ) -> tuple[dict[int, Inventory] | None, dict[int, Inventory] | None]:
        """Running/Cleared running balance dicts for ``self.selected_account``
        (RPT-07), or ``(None, None)`` when neither applies.

        Only meaningful for a single leaf account: "all accounts" (``None``)
        and any account with descendants (a parent/non-leaf account, per
        ``self.ledger.accounts``) both return ``(None, None)`` -- a running
        balance across multiple accounts, or a whole subtree, isn't a single
        coherent figure the way it is for one leaf account.
        """
        account = self.selected_account
        if account is None:
            return None, None
        prefix = account + ":"
        if any(a.startswith(prefix) for a in self.ledger.accounts):
            return None, None
        return (
            self.ledger.running_balances(account),
            self.ledger.running_balances(account, only_cleared=True),
        )

    def refresh_views(self) -> None:
        self.query_one(AccountTree).update_accounts(self.ledger.root_account(), self.ledger)
        running_balances, cleared_balances = self._account_running_balances()
        self.query_one(TransactionTable).update_entries(
            self._visible_entries(), running_balances, cleared_balances
        )
        self._update_detail_panel()
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
        running_balances, cleared_balances = self._account_running_balances()
        self.query_one(TransactionTable).update_entries(
            self._visible_entries(), running_balances, cleared_balances
        )
        self._update_detail_panel()

    def action_toggle_directives(self) -> None:
        self.show_directives = not self.show_directives
        running_balances, cleared_balances = self._account_running_balances()
        self.query_one(TransactionTable).update_entries(
            self._visible_entries(), running_balances, cleared_balances
        )
        self._update_detail_panel()

    def action_toggle_detail(self) -> None:
        self.show_detail = not self.show_detail
        panel = self.query_one("#detail", Static)
        panel.set_class(self.show_detail, "visible")
        if self.show_detail:
            self._update_detail_panel()

    def _update_detail_panel(self) -> None:
        """Refresh the detail panel with the currently highlighted entry's
        full formatted source text, keyed off ``TransactionTable``'s cursor
        (its ``selected_entry`` property)."""
        entry = self.query_one(TransactionTable).selected_entry
        panel = self.query_one("#detail", Static)
        panel.update(format_entry(entry) if entry is not None else "")

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        self._update_detail_panel()

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

    def action_budget(self) -> None:
        self.push_screen(BudgetScreen(self.ledger))

    def action_forecast(self) -> None:
        self.push_screen(ForecastScreen(self.ledger))

    def action_holdings(self) -> None:
        self.push_screen(HoldingsScreen(self.ledger))

    def action_price_history(self) -> None:
        self.push_screen(PriceHistoryScreen(self.ledger))

    def action_ledger_info(self) -> None:
        self.push_screen(LedgerInfoScreen(self.ledger))

    def action_query_runner(self) -> None:
        self.push_screen(QueryRunnerScreen(self.ledger))

    def action_help(self) -> None:
        self.push_screen(HelpScreen(self.BINDINGS))

    def action_import_csv(self) -> None:
        self.push_screen(ImportForm(), self._on_import_candidates)

    def action_import_beangulp(self) -> None:
        self.push_screen(BeangulpImportForm(), self._on_import_candidates)

    def _on_import_candidates(self, candidates: list[ImportCandidate] | None) -> None:
        """Shared continuation for both import entry points (CSV, IMP-04
        beangulp): push the same review/dedup/append screen either produced."""
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
            ImportReviewScreen(
                candidates,
                accounts=self.ledger.accounts,
                payees=self.ledger.payees,
                narrations=self.ledger.narrations,
                tags=self.ledger.tags,
                existing_transactions=self.ledger.transactions_for_account(None),
            ),
            on_review,
        )

    def action_filter(self) -> None:
        bar = self.query_one(FilterBar)
        bar.add_class("visible")
        bar.focus()

    def on_filter_bar_filter_changed(self, event: FilterBar.FilterChanged) -> None:
        self.filter_query = event.query
        running_balances, cleared_balances = self._account_running_balances()
        self.query_one(TransactionTable).update_entries(
            self._visible_entries(), running_balances, cleared_balances
        )
        self._update_detail_panel()

    def on_filter_bar_filter_accepted(self, event: FilterBar.FilterAccepted) -> None:
        self.query_one(TransactionTable).focus()

    def on_filter_bar_filter_closed(self, event: FilterBar.FilterClosed) -> None:
        bar = self.query_one(FilterBar)
        bar.value = ""
        bar.remove_class("visible")
        self.filter_query = ""
        running_balances, cleared_balances = self._account_running_balances()
        self.query_one(TransactionTable).update_entries(
            self._visible_entries(), running_balances, cleared_balances
        )
        self._update_detail_panel()
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
        self._start_reload(notify_message=f"Undid last change to {path.name}.")

    def action_redo(self) -> None:
        entry = self._undo_manager.pop_redo()
        if entry is None:
            self.notify("Nothing to redo.", severity="warning")
            return
        path, content = entry
        self._undo_manager.push_undo(path, path.read_text(encoding="utf-8"))
        path.write_text(content, encoding="utf-8")
        self._start_reload(notify_message=f"Redid last change to {path.name}.")

    def action_reload(self) -> None:
        self._start_reload(notify_message="Ledger reloaded.")

    def _start_reload(self, notify_message: str | None = None) -> None:
        """Kick off a background reload (``PERF-03``), coalescing with one
        already in flight rather than stacking a second concurrent
        ``Ledger.reload_data()`` call.

        Every reload path in the app -- ``action_reload`` (the ``r`` key
        and every write-commit closure that calls it), ``action_undo``/
        ``action_redo``, and the polling ``_check_external_changes`` --
        routes through here, so the in-flight guard and the "reloading"
        indicator only need to live in one place.

        A reload triggered while ``self._reload_in_progress`` is already
        ``True`` is silently dropped: the in-flight reload will finish and
        pick up whatever's on disk at the moment it started reading, and
        the next tick of ``_check_external_changes`` (or the next
        keypress) will notice if disk state has moved again since. This is
        the "simple in-flight boolean flag guard" the task calls out as
        sufficient, rather than a queue that replays every dropped
        request.

        ``notify_message``, if given, is shown via ``self.notify`` once
        the reload actually completes (not immediately) -- since the
        reload itself is now asynchronous, the message has to wait for
        ``_finish_reload`` rather than firing right after this call
        returns.
        """
        if self._reload_in_progress:
            return
        self._reload_in_progress = True
        self._pending_reload_notify = notify_message
        self.sub_title = str(self.ledger.path) + _RELOADING_SUFFIX
        self.run_worker(self._reload_worker, thread=True, exclusive=False)

    def _reload_worker(self) -> None:
        """Runs on a background thread (``run_worker(..., thread=True)``):
        the actual CPU-bound ``loader.load_file`` reparse (via
        ``Ledger.reload_data``), kept off the UI thread so the app stays
        responsive (cursor movement, scrolling, etc.) for the whole
        duration of a large-ledger reload.

        Thread-mode, not asyncio mode, because ``beancount.loader`` is
        synchronous CPU-bound code with no ``await`` points of its own --
        an asyncio worker would just block the event loop exactly like the
        old inline call did.

        Only ever reads ``self.ledger.path`` (via ``reload_data``, which
        is itself read-only with respect to ``self.ledger``) -- it never
        mutates ``self.ledger`` or touches any widget directly, since
        those aren't safe to touch off the UI thread. The result is handed
        back via ``call_from_thread``, which schedules ``_finish_reload``
        to run on the main/UI thread, where mutating ``self.ledger`` and
        the widgets is safe.
        """
        try:
            loaded = self.ledger.reload_data()
        except Exception as exc:  # noqa: BLE001 - see docstring: must not
            # crash the app or vanish silently off a background thread.
            # `Ledger.reload_data` doesn't normally raise (LANG-13 already
            # turns load-time failures, including a misbehaving plugin's
            # `sys.exit()`, into `errors` entries instead), but an
            # unexpected exception here (e.g. the file disappearing
            # mid-read) must still degrade gracefully rather than take the
            # whole app down.
            self.call_from_thread(self._reload_failed, exc)
            return
        self.call_from_thread(self._finish_reload, loaded)

    def _finish_reload(self, loaded: tuple[list, list, dict]) -> None:
        """Main-thread completion callback for ``_reload_worker``, invoked
        via ``call_from_thread``: applies the freshly loaded data to
        ``self.ledger``, refreshes the views, and clears the in-flight
        guard/indicator so a subsequent reload can proceed.
        """
        self.ledger.apply_reload(loaded)
        self._watched_mtimes = self.ledger.file_mtimes()
        self.refresh_views()
        self._clear_reload_indicator()
        message, self._pending_reload_notify = self._pending_reload_notify, None
        if message:
            self.notify(message)

    def _reload_failed(self, exc: BaseException) -> None:
        """Main-thread completion callback for a ``_reload_worker`` that
        raised -- clears the in-flight guard/indicator (without touching
        ``self.ledger``, which is untouched since ``reload_data`` never
        got as far as returning) and surfaces the failure instead of the
        pending success message."""
        self._clear_reload_indicator()
        self._pending_reload_notify = None
        self.notify(f"Reload failed: {exc}", severity="error")

    def _clear_reload_indicator(self) -> None:
        self.sub_title = str(self.ledger.path)
        self._reload_in_progress = False

    def _check_external_changes(self) -> None:
        # Leave the ledger alone while a modal (form/dialog) is open: a reload
        # under an in-progress edit would let it write back to stale locations.
        if len(self.screen_stack) > 1:
            return
        # PERF-03: also leave it alone while a previous reload (from this
        # same timer, a keypress, or a write-commit) is still in flight --
        # otherwise a slow reload on a large ledger could still be running
        # when the next `set_interval` tick fires and would stack a second
        # concurrent `Ledger.reload_data()` call against the same
        # not-thread-safe-for-concurrent-reload `Ledger` instance.
        if self._reload_in_progress:
            return
        current = self.ledger.file_mtimes()
        if current != self._watched_mtimes:
            self._start_reload(notify_message="Ledger changed on disk; reloaded.")


    def _save_transaction(
        self,
        text: str,
        *,
        file_for_writes: str | Path,
        commit: Callable[[], None],
        reopen: Callable[[], None],
    ) -> None:
        """Shared save gate for the new/edit/duplicate transaction flows
        (`EDIT-05`): before a transaction is actually written, diff its
        posting accounts against ``self.ledger.accounts`` and offer to
        create matching ``open`` directives for any that aren't already
        declared, rather than silently saving a transaction Beancount would
        flag as an error on next load.

        ``text`` is assumed already validated by `TransactionForm` (a single
        parseable transaction). If every posting account is already
        declared, this is a no-op gate: `file_for_writes` is snapshotted for
        undo and `commit` (the caller's actual `append_entry`/
        `replace_entry`) runs immediately.

        Otherwise a `ConfirmDialog` lists the missing accounts and the
        ``open`` directive(s) that would be created for them — synthesized
        from `LANG-01`'s own `_directive_template`, dated today or the
        transaction's own date if that's earlier (so the open always
        predates or matches it). Accepting appends those opens to
        `file_for_writes` and then runs `commit`; declining runs `reopen`
        instead (expected to hand the user's entered content back to them)
        and leaves the ledger untouched.

        Only one `_snapshot_for_undo` is taken for the whole operation,
        covering the open(s) and the transaction together, so a single undo
        reverts both — the same "one user action, one undo step" convention
        `action_pad_and_verify` already follows for its own two-directive
        write.
        """
        txn = parse_transaction_text(text)
        missing = sorted({posting.account for posting in txn.postings} - set(self.ledger.accounts))
        if not missing:
            self._snapshot_for_undo(file_for_writes)
            commit()
            return

        open_date = min(datetime.date.today(), txn.date)
        open_lines = [
            _directive_template("open", open_date.isoformat()).replace("Assets:FIXME", account)
            for account in missing
        ]
        plural = "s" if len(missing) > 1 else ""

        def on_confirm(confirmed: bool | None) -> None:
            if not confirmed:
                reopen()
                return
            self._snapshot_for_undo(file_for_writes)
            for open_line in open_lines:
                append_entry(file_for_writes, open_line)
            commit()

        self.push_screen(
            ConfirmDialog(
                f"Account{plural} not yet declared:\n"
                + "\n".join(open_lines)
                + "\n\nCreate the above and save the transaction?",
                confirm_label="Create & save",
            ),
            on_confirm,
        )

    def action_new_transaction(self) -> None:
        def on_result(result: TransactionFormResult | None) -> None:
            if result is None:
                return
            target = result.filename or self.ledger.path

            def commit() -> None:
                append_entry(target, result.text)
                self.action_reload()

            def reopen() -> None:
                self.push_screen(
                    _reopen_transaction_form(
                        result.text,
                        title="New transaction",
                        files=self.ledger.files,
                        accounts=self.ledger.accounts,
                        payees=self.ledger.payees,
                        narrations=self.ledger.narrations,
                        tags=self.ledger.tags,
                        selected_file=str(target),
                    ),
                    on_result,
                )

            self._save_transaction(
                result.text, file_for_writes=target, commit=commit, reopen=reopen
            )

        self.push_screen(
            TransactionForm(
                files=self.ledger.files,
                accounts=self.ledger.accounts,
                payees=self.ledger.payees,
                narrations=self.ledger.narrations,
                tags=self.ledger.tags,
            ),
            on_result,
        )

    def action_add_directive(self) -> None:
        def on_form_result(result: DirectiveFormResult | None) -> None:
            if result is None:
                return
            target = result.filename or self.ledger.path
            self._snapshot_for_undo(target)
            append_entry(target, result.text)
            self.action_reload()

        def on_type_chosen(keyword: str | None) -> None:
            if keyword is None:
                return
            if keyword == "budget":
                # Guided structured-field form (BUDGET-05) instead of the
                # generic raw-text template, specifically for budget
                # entries; every other keyword (including plain "custom")
                # keeps using the generic DirectiveForm flow unchanged.
                self.push_screen(
                    BudgetForm(files=self.ledger.files, accounts=self.ledger.accounts),
                    on_form_result,
                )
                return
            template = _directive_template(keyword, datetime.date.today().isoformat())
            # A "plugin" line parses to zero `data.Directive` entries (it's
            # options-only, not an entry -- see `Ledger.plugins`), so its
            # save-time validation must expect 0 entries, not the default 1
            # every dated directive type here produces.
            expected_directives = 0 if keyword == "plugin" else 1
            self.push_screen(
                DirectiveForm(
                    template,
                    title=f"New {keyword} directive",
                    files=self.ledger.files,
                    expected_directives=expected_directives,
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

    def _infer_pad_source(self, account: str) -> str | None:
        """The source account of `account`'s most recent prior `pad`
        directive, or ``None`` if it has never been padded before."""
        pads = [
            entry
            for entry in self.ledger.entries
            if isinstance(entry, data.Pad) and entry.account == account
        ]
        if not pads:
            return None
        return max(pads, key=lambda pad: pad.date).source_account

    def action_pad_and_verify(self) -> None:
        """Reconcile the selected account against a statement in one action:
        a `pad` directive from its usual pad-source account, immediately
        followed by the same `balance` assertion `action_balance_directive`
        produces, both dated today.

        The source account is inferred from the account's most recent prior
        `pad` directive (see `_infer_pad_source`); if it has never been
        padded before, the user is prompted to pick one via
        `PadSourcePicker`.

        Like `action_balance_directive`, a multi-currency account needs one
        pad+balance pair per currency, chained through `DirectiveForm`
        screens in sequence. Each screen's text box holds *two* directives
        (the pad line then the balance line) rather than one, so
        `DirectiveForm` is given `expected_directives=2`: both lines are
        still validated with the real Beancount parser, just not forced
        through the single-directive path `action_balance_directive` uses.
        `append_entry` itself doesn't validate content — it only writes
        text — so the already-validated two-line block is appended as-is,
        which also keeps the pad correctly ordered before its balance.
        """
        if self.selected_account is None:
            self.notify("No account selected.", severity="warning")
            return
        account = self.selected_account

        def push_pad_and_verify(source_account: str) -> None:
            node = realization.get(self.ledger.root_account(), account)
            if node is None:
                self.notify("No account selected.", severity="warning")
                return
            balance = realization.compute_balance(node).reduce(lambda pos: pos.units)
            positions = sorted(balance.get_positions(), key=lambda pos: pos.units.currency)
            date = datetime.date.today().isoformat()
            if positions:
                balance_lines = [
                    f"{date} balance {account}  {pos.units.number} {pos.units.currency}"
                    for pos in positions
                ]
            else:
                currency = (self.ledger.options.get("operating_currency") or ["USD"])[0]
                balance_lines = [f"{date} balance {account}  0.00 {currency}"]
            pad_line = f"{date} pad {account} {source_account}"
            texts = [f"{pad_line}\n{balance_line}" for balance_line in balance_lines]

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

                title = "New pad + balance directives"
                if len(texts) > 1:
                    title += f" ({index + 1}/{len(texts)})"
                self.push_screen(
                    DirectiveForm(
                        texts[index],
                        title=title,
                        files=self.ledger.files,
                        expected_directives=2,
                    ),
                    on_form_result,
                )

            push_form(0)

        inferred_source = self._infer_pad_source(account)
        if inferred_source is not None:
            push_pad_and_verify(inferred_source)
            return

        def on_source_chosen(source_account: str | None) -> None:
            if source_account is None:
                return
            push_pad_and_verify(source_account)

        self.push_screen(
            PadSourcePicker(
                [a for a in self.ledger.accounts if a != account], account=account
            ),
            on_source_chosen,
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
                target = entry.meta["filename"]

                def commit() -> None:
                    replace_entry(entry, result.text)
                    self.action_reload()

                def reopen() -> None:
                    self.push_screen(
                        _reopen_transaction_form(
                            result.text,
                            title="Edit transaction",
                            files=None,
                            accounts=self.ledger.accounts,
                            payees=self.ledger.payees,
                            narrations=self.ledger.narrations,
                            tags=self.ledger.tags,
                        ),
                        on_form_result,
                    )

                self._save_transaction(
                    result.text, file_for_writes=target, commit=commit, reopen=reopen
                )

            # If this transaction is itself a FORECAST-01 recurring template,
            # pre-fill the form's guided recurring fields from its already
            # -parsed ``RecurringTemplate`` rather than re-deriving
            # interval/until from raw tags/metadata here.
            recurring_template = next(
                (t for t in self.ledger.recurring_templates if t.transaction is entry), None
            )
            self.push_screen(
                _edit_form(
                    entry,
                    self.ledger.accounts,
                    recurring_template,
                    payees=self.ledger.payees,
                    narrations=self.ledger.narrations,
                    tags=self.ledger.tags,
                ),
                on_form_result,
            )
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

            def commit() -> None:
                append_entry(target, result.text)
                self.action_reload()

            def reopen() -> None:
                self.push_screen(
                    _reopen_transaction_form(
                        result.text,
                        title="Duplicate transaction",
                        files=self.ledger.files,
                        accounts=self.ledger.accounts,
                        payees=self.ledger.payees,
                        narrations=self.ledger.narrations,
                        tags=self.ledger.tags,
                        selected_file=str(target),
                    ),
                    on_result,
                )

            self._save_transaction(
                result.text, file_for_writes=target, commit=commit, reopen=reopen
            )

        self.push_screen(
            _duplicate_form(
                entry,
                self.ledger.files,
                self.ledger.accounts,
                payees=self.ledger.payees,
                narrations=self.ledger.narrations,
                tags=self.ledger.tags,
            ),
            on_result,
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

    def action_preview_document(self) -> None:
        """Preview the file a highlighted `document` directive points at
        (RPT-11), without leaving the TUI.

        A no-op (with a warning notification) for anything other than a
        `data.Document` row -- there's no file to preview for a
        transaction or any other directive.
        """
        entry = self.query_one(TransactionTable).selected_entry
        if not isinstance(entry, data.Document):
            self.notify("No document selected.", severity="warning")
            return
        self.push_screen(DocumentPreviewScreen(Path(entry.filename)))

    def action_cycle_flag(self) -> None:
        """Toggle the highlighted transaction's flag between `*` (cleared)
        and `!` (pending) in place, without opening the full edit form.

        A no-op for a highlighted directive row (or no selection at all) --
        only ``data.Transaction`` has a meaningful flag to cycle. Uses
        `editor.replace_flag` rather than the `format_entry`/`replace_entry`
        pair the edit/duplicate flows use, since re-serializing the whole
        entry via `format_entry` fills in Beancount's interpolated posting
        amounts, which would change more than just the flag on disk.
        """
        entry = self.query_one(TransactionTable).selected_entry
        if not isinstance(entry, data.Transaction):
            return
        new_flag = "!" if entry.flag == "*" else "*"
        self._snapshot_for_undo(entry.meta["filename"])
        replace_flag(entry, new_flag)
        self.action_reload()


def _entry_summary(entry: data.Directive) -> str:
    """A short human-readable description for confirmation prompts."""
    if isinstance(entry, data.Transaction):
        parts = (str(entry.date), entry.payee, entry.narration)
        return "transaction " + " ".join(p for p in parts if p)
    keyword = type(entry).__name__.lower()
    accounts = ", ".join(sorted(getters.get_entry_accounts(entry)))
    return f"{keyword} directive {entry.date} {accounts}"


def _postings_text(txn: data.Transaction, exclude_meta_keys: tuple[str, ...] = ()) -> str:
    lines = format_entry(txn).rstrip("\n").split("\n")
    body_lines = [line.strip() for line in lines[1:]]
    if exclude_meta_keys:
        # Drop this transaction's own metadata lines (e.g. FORECAST-01's
        # ``recurring-freq``/``recurring-until``) from the postings text
        # when a guided field elsewhere in the form already owns them —
        # otherwise editing a recurring template would duplicate that
        # metadata (once from the raw copied line, once from the guided
        # field) when the form reassembles the transaction.
        body_lines = [
            line
            for line in body_lines
            if not any(line.startswith(f"{key}:") for key in exclude_meta_keys)
        ]
    return "\n".join(body_lines)


_RECURRING_META_KEYS = ("recurring-freq", "recurring-until")


def _tags_links_text(txn: data.Transaction, exclude_tags: frozenset[str] = frozenset()) -> str:
    """Render a transaction's tags/links as ``#tag ^link`` text for the form."""
    tokens = [f"#{tag}" for tag in sorted(txn.tags or ()) if tag not in exclude_tags]
    tokens += [f"^{link}" for link in sorted(txn.links or ())]
    return " ".join(tokens)


def _edit_form(
    txn: data.Transaction,
    accounts: list[str],
    recurring_template: RecurringTemplate | None = None,
    *,
    payees: list[str] | None = None,
    narrations: list[str] | None = None,
    tags: list[str] | None = None,
) -> TransactionForm:
    """Build a form pre-filled from an existing transaction.

    When ``txn`` is a FORECAST-01 recurring template, the guided recurring
    toggle/interval/until fields are pre-filled from ``recurring_template``
    and the ``#recurring`` tag / ``recurring-freq``/``recurring-until``
    metadata are excluded from the free-text tags/links field and postings
    text respectively, so the guided fields are the single source of truth
    for them (the toggle re-adds ``#recurring`` and the metadata lines at
    save time — see ``TransactionForm._assemble_text``).
    """
    exclude_tags = frozenset({"recurring"}) if recurring_template else frozenset()
    exclude_meta = _RECURRING_META_KEYS if recurring_template else ()
    return TransactionForm(
        date=txn.date.isoformat(),
        flag=txn.flag or "*",
        payee=txn.payee or "",
        narration=txn.narration or "",
        tags_links=_tags_links_text(txn, exclude_tags=exclude_tags),
        postings_text=_postings_text(txn, exclude_meta_keys=exclude_meta),
        title="Edit transaction",
        accounts=accounts,
        payees=payees,
        narrations=narrations,
        tags=tags,
        recurring=recurring_template is not None,
        recurring_interval=recurring_template.interval if recurring_template else "monthly",
        recurring_until=(
            recurring_template.until.isoformat()
            if recurring_template and recurring_template.until
            else ""
        ),
    )


def _duplicate_form(
    txn: data.Transaction,
    files: list[Path],
    accounts: list[str],
    *,
    payees: list[str] | None = None,
    narrations: list[str] | None = None,
    tags: list[str] | None = None,
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
        payees=payees,
        narrations=narrations,
        tags=tags,
    )


def _reopen_transaction_form(
    text: str,
    *,
    title: str,
    files: list[Path] | None,
    accounts: list[str],
    payees: list[str] | None = None,
    narrations: list[str] | None = None,
    tags: list[str] | None = None,
    selected_file: str | None = None,
) -> TransactionForm:
    """Rebuild a `TransactionForm` from already-entered `text` (`EDIT-05`):
    used to hand the user's content back to them when they decline
    `BeancountTUI._save_transaction`'s missing-account prompt, rather than
    just discarding it along with the rest of the form.

    `text` is guaranteed parseable here — it already passed
    `TransactionForm`'s own validation before the account check ran — so
    this only re-derives display fields from the parsed `Transaction`,
    reusing the same `_tags_links_text`/`_postings_text` helpers `_edit_form`
    and `_duplicate_form` already build on.

    Note this does not reconstruct the guided recurring-template
    checkbox/interval state: a ``#recurring`` tag or ``recurring-freq``/
    ``recurring-until`` metadata already present in `text` simply comes
    back as plain tags/postings-body text (toggle unchecked), which still
    round-trips identically on a second save.
    """
    txn = parse_transaction_text(text)
    return TransactionForm(
        date=txn.date.isoformat(),
        flag=txn.flag or "*",
        payee=txn.payee or "",
        narration=txn.narration or "",
        tags_links=_tags_links_text(txn),
        postings_text=_postings_text(txn),
        title=title,
        files=files,
        accounts=accounts,
        payees=payees,
        narrations=narrations,
        tags=tags,
        selected_file=selected_file,
    )


def main() -> None:
    arg_parser = argparse.ArgumentParser(
        prog="beancount-tui", description="A terminal UI for editing Beancount ledgers."
    )
    arg_parser.add_argument(
        "ledger",
        nargs="?",
        default=None,
        help=(
            "Path to the Beancount ledger file. Optional if a `default_ledger` is "
            "set in the config file."
        ),
    )
    arg_parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help=(
            "Path to a TOML config file (default: "
            "~/.config/beancount-tui/config.toml, if present)"
        ),
    )
    arg_parser.add_argument(
        "--watch-interval",
        type=float,
        default=None,
        help="Seconds between checks for external changes to the ledger (overrides config file)",
    )
    args = arg_parser.parse_args()

    config_path = args.config if args.config is not None else default_config_path()
    config = load_config(config_path)

    ledger = args.ledger or config.get("default_ledger")
    if not ledger:
        arg_parser.error(
            "no ledger path given, and no default_ledger configured in the config file"
        )

    watch_interval = (
        args.watch_interval if args.watch_interval is not None else config.get("watch_interval")
    )
    if watch_interval is None:
        watch_interval = DEFAULT_WATCH_INTERVAL

    if not Path(ledger).is_file():
        sys.exit(f"error: no such file: {ledger}")

    # Rebuild BINDINGS from any `[bindings]` config-file overrides before
    # constructing the app -- see `_rebuild_bindings` for why this must
    # happen here, prior to `BeancountTUI(...)` below, rather than after.
    _rebuild_bindings(BeancountTUI, config.get("bindings", {}))

    BeancountTUI(
        ledger,
        watch_interval=watch_interval,
        theme=config.get("theme"),
        config_path=config_path,
    ).run()


if __name__ == "__main__":
    main()
