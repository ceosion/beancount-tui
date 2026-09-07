"""Modal ad hoc BQL query runner: type (or pick a saved) query, see a table.

Runs against the loaded ledger via ``beanquery`` — the package that provides
the ``bean-query`` BQL engine in Beancount 3.x (split out of the
``beancount`` package itself, which no longer ships ``beancount.query``).
"""

from __future__ import annotations

from pathlib import Path

import beanquery
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Input, Label, Select, Static

from beancount_tui.export import write_csv, write_json
from beancount_tui.ledger import Ledger, QueryResult, format_query_value
from beancount_tui.widgets.confirm_dialog import ConfirmDialog


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
    QueryRunnerScreen #export-row {
        height: auto;
        margin-top: 1;
    }
    QueryRunnerScreen #export-row Input {
        width: 1fr;
    }
    QueryRunnerScreen #export-row Select {
        width: 14;
    }
    QueryRunnerScreen #export-error {
        color: $error;
        height: auto;
    }
    """

    def __init__(self, ledger: Ledger) -> None:
        super().__init__()
        self._ledger = ledger
        self._last_result: QueryResult | None = None

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
            with Horizontal(id="export-row"):
                yield Input(placeholder="/path/to/export.csv", id="export-path")
                yield Select(
                    [("CSV", "csv"), ("JSON", "json")],
                    value="csv",
                    allow_blank=False,
                    id="export-format",
                )
                yield Button("Export", id="export")
            yield Static("", id="export-error")

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
        if event.input.id == "query":
            event.stop()
            self._run_query()
        elif event.input.id == "export-path":
            event.stop()
            self._do_export()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "run":
            self._run_query()
        elif event.button.id == "export":
            self._do_export()

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
        self._last_result = result
        table = self.query_one("#results", DataTable)
        table.clear(columns=True)
        table.add_columns(*result.columns)
        for row in result.rows:
            table.add_row(*(format_query_value(cell) for cell in row))

    def _export_error(self, message: str) -> None:
        self.query_one("#export-error", Static).update(message)

    def _do_export(self) -> None:
        """Export the last-run query's raw ``columns``/``rows`` (not the
        display-formatted table contents) to a user-supplied path, as CSV
        or JSON per the ``#export-format`` toggle.

        Mirrors the path-input UX already used by ``ImportForm``/
        ``BeangulpImportForm``: a plain ``Input`` validated on submit, with
        an inline error ``Static`` for problems, rather than a directory
        browser. An existing target path is confirmed via the same
        ``ConfirmDialog`` used elsewhere (e.g. deleting a transaction)
        instead of silently overwriting.
        """
        result = self._last_result
        if result is None:
            self._export_error("Run a query first.")
            return

        path_text = self.query_one("#export-path", Input).value.strip()
        if not path_text:
            self._export_error("Enter an export file path.")
            return
        path = Path(path_text)

        parent = path.parent
        if not parent.is_dir():
            self._export_error(f"No such directory: {parent}")
            return

        self._export_error("")
        format_ = self.query_one("#export-format", Select).value

        if path.exists():

            def on_confirm(confirmed: bool | None) -> None:
                if confirmed:
                    self._write_export(result, path, format_)

            self.app.push_screen(
                ConfirmDialog(f"{path} already exists. Overwrite?", confirm_label="Overwrite"),
                on_confirm,
            )
            return

        self._write_export(result, path, format_)

    def _write_export(self, result: QueryResult, path: Path, format_: object) -> None:
        try:
            if format_ == "json":
                write_json(result.columns, result.rows, path)
            else:
                write_csv(result.columns, result.rows, path)
        except OSError as exc:
            self._export_error(f"Could not write {path}: {exc}")
            return
        self._export_error("")
        self.notify(f"Exported to {path}.")

    def action_close(self) -> None:
        self.dismiss(None)
