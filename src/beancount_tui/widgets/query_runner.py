"""Modal ad hoc BQL query runner: type (or pick a saved) query, see a table.

Runs against the loaded ledger via ``beanquery`` — the package that provides
the ``bean-query`` BQL engine in Beancount 3.x (split out of the
``beancount`` package itself, which no longer ships ``beancount.query``).
"""

from __future__ import annotations

import beanquery
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Input, Label, Select, Static

from beancount_tui.ledger import Ledger, format_query_value


class QueryRunnerScreen(ModalScreen[None]):
    """Read-only BQL query runner over the ledger; Escape closes it."""

    BINDINGS = [("escape", "close", "Close")]

    DEFAULT_CSS = """
    QueryRunnerScreen {
        align: center middle;
    }
    QueryRunnerScreen > Vertical {
        width: 96;
        height: auto;
        max-height: 90%;
        border: round $primary;
        padding: 1 2;
        background: $surface;
    }
    QueryRunnerScreen #saved-query {
        margin-top: 1;
    }
    QueryRunnerScreen #input-row {
        height: auto;
        margin-top: 1;
    }
    QueryRunnerScreen #input-row Input {
        width: 1fr;
    }
    QueryRunnerScreen #results {
        height: auto;
        max-height: 20;
        margin-top: 1;
    }
    QueryRunnerScreen #error {
        color: $error;
        height: auto;
    }
    """

    def __init__(self, ledger: Ledger) -> None:
        super().__init__()
        self._ledger = ledger

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("[b]BQL query[/b]")
            queries = self._ledger.queries
            if queries:
                options = [
                    (f"{q.name}: {q.query_string}", q.query_string) for q in queries
                ]
                yield Select(
                    options, allow_blank=True, prompt="Saved query", id="saved-query"
                )
            with Horizontal(id="input-row"):
                yield Input(
                    placeholder='SELECT account, sum(position) GROUP BY account', id="query"
                )
                yield Button("Run", id="run", variant="primary")
            yield DataTable(id="results", cursor_type="none")
            yield Static("", id="error")

    def on_select_changed(self, event: Select.Changed) -> None:
        event.stop()
        if event.select.id != "saved-query":
            return
        if event.value is Select.BLANK:
            return
        query_input = self.query_one("#query", Input)
        query_input.value = str(event.value)
        self._run_query()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "query":
            return
        event.stop()
        self._run_query()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "run":
            self._run_query()

    def _run_query(self) -> None:
        query_string = self.query_one("#query", Input).value.strip()
        error = self.query_one("#error", Static)
        if not query_string:
            error.update("Enter a query.")
            return
        try:
            result = self._ledger.run_query(query_string)
        except beanquery.Error as exc:
            error.update(str(exc))
            return
        error.update("")
        table = self.query_one("#results", DataTable)
        table.clear(columns=True)
        table.add_columns(*result.columns)
        for row in result.rows:
            table.add_row(*(format_query_value(cell) for cell in row))

    def action_close(self) -> None:
        self.dismiss(None)
