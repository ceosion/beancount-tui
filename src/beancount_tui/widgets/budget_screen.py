"""Modal budget-vs-actual report: Budgeted/Actual/Remaining per leaf account."""

from __future__ import annotations

import datetime
from decimal import Decimal

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Input, Label, Static

from beancount_tui.ledger import Ledger, parse_date_range, resolve_date_preset
from beancount_tui.widgets.date_input import DateRangeInput


def _format_amount(value: Decimal, currency: str) -> str:
    return f"{value:,.2f} {currency}"


class BudgetScreen(ModalScreen[None]):
    """Read-only budget-vs-actual report over the ledger; Escape closes it.

    Rows are the leaf accounts (per currency) with an active budget
    somewhere in the selected period (see ``Ledger.budget_report`` —
    accounts with no budget defined at all are excluded). The ``r`` binding
    toggles an opt-in parent/child rollup (``Ledger.budget_report_rolled_up``,
    BUDGET-04) on top of the same period, off by default so this flat
    per-leaf view stays the default.
    """

    BINDINGS = [("escape", "close", "Close"), ("r", "toggle_rollup", "Rollup")]

    DEFAULT_CSS = """
    BudgetScreen {
        align: center middle;
    }
    BudgetScreen > Vertical {
        width: 70;
        height: auto;
        max-height: 90%;
        border: round $primary;
        padding: 1 2;
        background: $surface;
    }
    BudgetScreen #period {
        margin-top: 1;
    }
    BudgetScreen #report {
        height: auto;
        max-height: 24;
        margin-top: 1;
    }
    BudgetScreen #period-error {
        color: $error;
        height: auto;
    }
    """

    def __init__(self, ledger: Ledger) -> None:
        super().__init__()
        self._ledger = ledger
        self._rolled_up = False
        # Set by every ``_render_report`` call so ``action_toggle_rollup``
        # can re-render the same period's data under the other mode without
        # re-parsing (or resetting) the period input.
        self._current_range: tuple[datetime.date, datetime.date] | None = None

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("[b]Budget vs. actual[/b]", id="title")
            yield DateRangeInput(
                placeholder=(
                    "Period YYYY-MM-DD..YYYY-MM-DD, or month/last-month/year/last-year "
                    "(empty = current month)"
                ),
                id="period",
            )
            yield DataTable(id="report", cursor_type="none")
            yield Static("", id="period-error")

    def on_mount(self) -> None:
        table = self.query_one("#report", DataTable)
        table.add_columns("Account", "Budgeted", "Actual", "Remaining")
        self._render_report(*self._default_range())

    def _default_range(self) -> tuple[datetime.date, datetime.date]:
        """Current-month-to-date, unlike the other report screens' all-time
        default — an all-time budget report would mix years of unrelated
        monthly/weekly/etc. targets together, which is rarely useful (see
        BUDGET-03's acceptance criteria)."""
        return resolve_date_preset("month")

    def on_input_changed(self, event: Input.Changed) -> None:
        event.stop()
        error = self.query_one("#period-error", Static)
        query = event.value.strip()
        if not query:
            error.update("")
            self._render_report(*self._default_range())
            return
        date_range = parse_date_range(query)
        if date_range is None:
            error.update("Not a date range; use YYYY-MM-DD..YYYY-MM-DD.")
            return
        start, end = date_range
        # budget_target needs concrete bounds to walk day-by-day, so an
        # open-ended side (e.g. "2026-01-15..") falls back to the
        # current-month default's matching bound rather than an unbounded
        # (and, for a missing start, extremely slow) scan back to year one.
        default_start, default_end = self._default_range()
        if start is None:
            start = default_start
        if end is None:
            end = default_end
        error.update("")
        self._render_report(start, end)

    def _render_report(self, start: datetime.date, end: datetime.date) -> None:
        self._current_range = (start, end)
        rows = (
            self._ledger.budget_report_rolled_up(start, end)
            if self._rolled_up
            else self._ledger.budget_report(start, end)
        )
        table = self.query_one("#report", DataTable)
        table.clear()
        for row in rows:
            table.add_row(
                row.account,
                _format_amount(row.budgeted, row.currency),
                _format_amount(row.actual, row.currency),
                _format_amount(row.remaining, row.currency),
            )
        title = self.query_one("#title", Label)
        title.update(
            "[b]Budget vs. actual (rolled up)[/b]" if self._rolled_up else "[b]Budget vs. actual[/b]"
        )

    def action_toggle_rollup(self) -> None:
        """Toggle BUDGET-04's opt-in parent/child rollup, re-rendering the
        current period's data either way (flat per-leaf by default)."""
        self._rolled_up = not self._rolled_up
        if self._current_range is not None:
            self._render_report(*self._current_range)

    def action_close(self) -> None:
        self.dismiss(None)
