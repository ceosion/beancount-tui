"""Shared CSV/JSON export UI wiring for report screens (``EXPORT-02``).

``EXPORT-01`` added ``beancount_tui.export``'s ``write_csv``/``write_json``
plus a hand-wired export row (path ``Input`` + CSV/JSON ``Select`` + button
+ inline error ``Static``, with overwrite confirmation via the app-wide
``ConfirmDialog``) to ``QueryRunnerScreen``. Every other report screen
(income statement, balance sheet, trial balance, holdings, budget, forecast)
wants the *exact* same action -- only what counts as "the current
columns/rows" differs per screen. Rather than re-paste that plumbing six
more times nearly verbatim, this mixin owns it once; each host screen only
has to say what its current export data is.

Usage on a host ``ModalScreen``:

- Mix it in: ``class FooScreen(ExportMixin, ModalScreen[None]):``.
- Add the same four ``#export-row``/``#export-error`` rules
  ``QueryRunnerScreen``'s ``DEFAULT_CSS`` already has, scoped to the host
  screen's own class name (this codebase always prefixes screen CSS with
  the class name rather than relying on any implicit scoping -- see every
  existing screen's ``DEFAULT_CSS`` -- so there's no single CSS snippet to
  share here, just the same four rules re-prefixed per host).
- Add ``yield from self.compose_export_row()`` at the end of the host's
  ``compose()``.
- Implement ``_export_columns_rows()`` returning the *current* raw
  ``(columns, rows)`` -- typically built alongside the on-screen
  ``DataTable`` at render time and cached on ``self``, so export always
  matches what's currently displayed without recomputing/reformatting.
- Route ``Input.Submitted`` (for ``#export-path``) and ``Button.Pressed``
  (for ``#export``) to ``self._do_export()``. If the host already handles
  ``Input.Changed`` for its own date/period field, guard it by
  ``event.input.id`` -- Textual bubbles ``Input.Changed`` from *every*
  ``Input`` on the screen, so without the guard typing into the export path
  field would be misread as a date/period edit.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, Input, Select, Static

from beancount_tui.export import write_csv, write_json
from beancount_tui.widgets.confirm_dialog import ConfirmDialog

class ExportMixin:
    """Mixin providing the export-row UI and action for a report screen.

    See the module docstring for what a host class needs to provide.
    """

    def compose_export_row(self) -> ComposeResult:
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

    def _export_columns_rows(self) -> tuple[list[str], list[list[Any]]]:
        """Return the current ``(columns, rows)`` to export.

        Must be overridden by the host screen; raw values (``Decimal``,
        ``Inventory``, ``Amount``, ``None`` for a blank cell, ...), not
        display-formatted strings -- ``write_csv``/``write_json`` render
        each cell for its target format themselves.
        """
        raise NotImplementedError

    def _export_error(self, message: str) -> None:
        self.query_one("#export-error", Static).update(message)

    def _do_export(self) -> None:
        """Validate the export path, confirm overwrite if needed, and write.

        Mirrors ``QueryRunnerScreen``'s ``_do_export``: a plain ``Input``
        validated on submit (parent directory must exist), an inline error
        ``Static`` for problems, and the shared ``ConfirmDialog`` for "this
        would overwrite an existing file" rather than silently clobbering it.
        """
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
        columns, rows = self._export_columns_rows()

        if path.exists():

            def on_confirm(confirmed: bool | None) -> None:
                if confirmed:
                    self._write_export(columns, rows, path, format_)

            self.app.push_screen(
                ConfirmDialog(f"{path} already exists. Overwrite?", confirm_label="Overwrite"),
                on_confirm,
            )
            return

        self._write_export(columns, rows, path, format_)

    def _write_export(
        self, columns: list[str], rows: list[list[Any]], path: Path, format_: object
    ) -> None:
        try:
            if format_ == "json":
                write_json(columns, rows, path)
            else:
                write_csv(columns, rows, path)
        except OSError as exc:
            self._export_error(f"Could not write {path}: {exc}")
            return
        self._export_error("")
        self.notify(f"Exported to {path}.")
