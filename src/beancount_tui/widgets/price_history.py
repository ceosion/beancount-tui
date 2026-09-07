"""Modal commodity price-history report: a date-ordered table of ``Price``
directives for one commodity (RPT-10).

A chart is out of scope (Textual has no native charting widget, and a
plotting dependency would be disproportionate for a TUI); a table is the
pragmatic equivalent here, unlike Fava's price chart.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Label, Select, Static

from beancount_tui.ledger import Ledger


class PriceHistoryScreen(ModalScreen[None]):
    """Read-only report over the ledger; Escape closes it.

    Only commodities with at least one ``Price`` directive
    (``Ledger.price_commodities``) are offered in the picker.
    """

    BINDINGS = [("escape", "close", "Close")]

    DEFAULT_CSS = """
    PriceHistoryScreen {
        align: center middle;
    }
    PriceHistoryScreen > Vertical {
        width: 60;
        height: auto;
        max-height: 90%;
        border: round $primary;
        padding: 1 2;
        background: $surface;
    }
    PriceHistoryScreen #commodity {
        margin-top: 1;
    }
    PriceHistoryScreen #report {
        height: auto;
        max-height: 24;
        margin-top: 1;
    }
    PriceHistoryScreen #empty {
        color: $text-muted;
        height: auto;
        margin-top: 1;
    }
    """

    def __init__(self, ledger: Ledger) -> None:
        super().__init__()
        self._ledger = ledger

    def compose(self) -> ComposeResult:
        commodities = self._ledger.price_commodities
        with Vertical():
            yield Label("[b]Commodity price history[/b]")
            if commodities:
                yield Select(
                    ((commodity, commodity) for commodity in commodities),
                    allow_blank=False,
                    value=commodities[0],
                    id="commodity",
                )
                yield DataTable(id="report", cursor_type="none")
            else:
                yield Static("No commodities have Price directives.", id="empty")

    def on_mount(self) -> None:
        if not self._ledger.price_commodities:
            return
        table = self.query_one("#report", DataTable)
        table.add_columns("Date", "Rate", "Quote currency")
        self._render_report(self.query_one("#commodity", Select).value)

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id != "commodity":
            return
        event.stop()
        if event.value is Select.BLANK:
            return
        self._render_report(str(event.value))

    def _render_report(self, commodity: str) -> None:
        table = self.query_one("#report", DataTable)
        table.clear()
        for entry_date, rate, quote_currency in self._ledger.price_history(commodity):
            table.add_row(entry_date.isoformat(), f"{rate:,}", quote_currency)

    def action_close(self) -> None:
        self.dismiss(None)
