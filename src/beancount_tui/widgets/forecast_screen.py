"""Modal cash-flow forecast: real actuals blended with projected activity."""

from __future__ import annotations

import calendar
import datetime
from decimal import Decimal
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Input, Label, Static

from beancount_tui.ledger import ForecastReportRow, Ledger, parse_date_range
from beancount_tui.widgets.date_input import DateRangeInput
from beancount_tui.widgets.export_mixin import ExportMixin

# One style per ``ForecastReportRow.status`` value so a mixed-composition
# report stays scannable, the same convention ``transaction_table.py``'s
# ``_DIRECTIVE_STYLES`` uses for directive keywords. "actual" (no projected
# component at all for this row) is deliberately absent -- it renders as a
# plain, unstyled "-" rather than a colored label, since there's nothing
# speculative to flag.
_STATUS_STYLES: dict[str, str] = {
    "explicit": "cyan",
    "assumed": "yellow",
    "mixed": "magenta",
}
_STATUS_LABELS: dict[str, str] = {
    "explicit": "Explicit",
    "assumed": "Assumed",
    "mixed": "Mixed",
}


def _format_amount(value: Decimal, currency: str) -> str:
    return f"{value:,.2f} {currency}"


def _add_months(day: datetime.date, months: int) -> datetime.date:
    """``day`` advanced by ``months`` calendar months, clamped to the target
    month's actual last day (e.g. Jan 31 + 1 month -> Feb 28/29).

    Small, self-contained mirror of ``Ledger``'s private ``_advance_date``
    month-stepping math -- that helper is specific to walking a
    ``RecurringTemplate`` forward one *interval* at a time and isn't part of
    ``Ledger``'s public surface, so this screen's much narrower need (a
    single one-shot "N months from today" default) gets its own tiny copy
    rather than reaching into module-private internals.
    """
    total_months = day.year * 12 + (day.month - 1) + months
    year, zero_based_month = divmod(total_months, 12)
    month = zero_based_month + 1
    last_day_of_month = calendar.monthrange(year, month)[1]
    return datetime.date(year, month, min(day.day, last_day_of_month))


class ForecastScreen(ExportMixin, ModalScreen[None]):
    """Read-only cash-flow forecast over the ledger; Escape closes it.

    Unlike the other report screens, this one defaults to a *forward*
    window (today through three months out) instead of an all-time or
    current-period default, since a forecast that doesn't already show
    projected data without the user typing a future range by hand would
    defeat its own purpose (``FORECAST-06``).

    Rows are per leaf account/currency (``Ledger.forecast_report``),
    blending real posted activity through today with projected activity
    (recurring-template instances, or budget-fallback assumptions where no
    template covers a day) for the rest of the period. The Projected column
    is visually marked -- colored by whether it's backed by explicit
    template data, assumed budget data, or a mix of both within the period
    -- so speculative figures are never mistaken for what already happened.
    """

    BINDINGS = [("escape", "close", "Close")]

    DEFAULT_CSS = """
    ForecastScreen {
        align: center middle;
    }
    ForecastScreen > Vertical {
        width: 90;
        height: auto;
        max-height: 90%;
        border: round $primary;
        padding: 1 2;
        background: $surface;
    }
    ForecastScreen #period {
        margin-top: 1;
    }
    ForecastScreen #report {
        height: auto;
        max-height: 24;
        margin-top: 1;
    }
    ForecastScreen #period-error {
        color: $error;
        height: auto;
    }
    ForecastScreen #export-row {
        height: auto;
        margin-top: 1;
    }
    ForecastScreen #export-row Input {
        width: 1fr;
    }
    ForecastScreen #export-row Select {
        width: 14;
    }
    ForecastScreen #export-error {
        color: $error;
        height: auto;
    }
    """

    def __init__(self, ledger: Ledger, today: datetime.date | None = None) -> None:
        super().__init__()
        self._ledger = ledger
        # Overridable only for deterministic tests (the real screen always
        # uses the real current date); mirrors ``resolve_date_preset``'s own
        # ``today`` parameter for the same reason.
        self._today = today if today is not None else datetime.date.today()
        # Populated by ``_render_report``. Adds a "Status" column beyond the
        # five on-screen columns: on screen, explicit/assumed/mixed
        # provenance for the Projected figure is conveyed purely by color
        # (see ``_STATUS_STYLES``), which has no equivalent in a CSV/JSON
        # cell, so it becomes its own explicit column instead of being
        # silently dropped.
        self._export_columns: list[str] = [
            "Account",
            "Currency",
            "Actual",
            "Projected",
            "Status",
            "Total",
        ]
        self._export_rows: list[list[Any]] = []

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("[b]Cash-flow forecast[/b]")
            yield DateRangeInput(
                placeholder=(
                    "Period YYYY-MM-DD..YYYY-MM-DD, or month/last-month/year/last-year "
                    "(empty = today through 3 months forward)"
                ),
                id="period",
            )
            yield DataTable(id="report", cursor_type="none")
            yield Static("", id="period-error")
            yield from self.compose_export_row()

    def on_mount(self) -> None:
        table = self.query_one("#report", DataTable)
        table.add_columns("Account", "Currency", "Actual", "Projected", "Total")
        self._render_report(*self._default_range())

    def _default_range(self) -> tuple[datetime.date, datetime.date]:
        """Today through three calendar months forward (``FORECAST-06``).

        Unlike every other report screen's backward-looking default (all
        time, or the current period-to-date), a forecast that required
        manually typing a future range would defeat its own purpose, so
        this is the one default that looks ahead instead of back.
        """
        return self._today, _add_months(self._today, 3)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "period":
            return
        event.stop()
        error = self.query_one("#period-error", Static)
        query = event.value.strip()
        if not query:
            error.update("")
            self._render_report(*self._default_range())
            return
        date_range = parse_date_range(query, today=self._today)
        if date_range is None:
            error.update("Not a date range; use YYYY-MM-DD..YYYY-MM-DD.")
            return
        start, end = date_range
        # forecast_report needs concrete bounds, same reasoning as
        # BudgetScreen's period handling -- an open-ended side falls back to
        # the forward-looking default's matching bound rather than an
        # unbounded scan.
        default_start, default_end = self._default_range()
        if start is None:
            start = default_start
        if end is None:
            end = default_end
        error.update("")
        self._render_report(start, end)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "export-path":
            event.stop()
            self._do_export()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "export":
            self._do_export()

    def _render_report(self, start: datetime.date, end: datetime.date) -> None:
        rows = self._ledger.forecast_report(start, end, today=self._today)
        table = self.query_one("#report", DataTable)
        table.clear()
        export_rows: list[list[Any]] = []
        for row in rows:
            table.add_row(
                row.account,
                row.currency,
                _format_amount(row.actual, row.currency),
                _projected_cell(row),
                _format_amount(row.total, row.currency),
            )
            export_rows.append(
                [row.account, row.currency, row.actual, row.projected, row.status, row.total]
            )
        self._export_rows = export_rows

    def _export_columns_rows(self) -> tuple[list[str], list[list[Any]]]:
        return self._export_columns, self._export_rows

    def action_close(self) -> None:
        self.dismiss(None)


def _projected_cell(row: ForecastReportRow) -> Text | str:
    """The Projected column's cell: plain "-" for a row with no forecast
    component at all, otherwise the amount plus its status label, styled by
    ``_STATUS_STYLES`` so explicit/assumed/mixed projected figures are never
    mistaken for real historical ones."""
    if row.status == "actual":
        return "-"
    amount = _format_amount(row.projected, row.currency)
    label = _STATUS_LABELS[row.status]
    return Text(f"{amount} ({label})", style=_STATUS_STYLES[row.status])
