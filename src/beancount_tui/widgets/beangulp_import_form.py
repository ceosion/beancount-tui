"""Modal flow for importing via a user-supplied beangulp importer (IMP-04).

Asks for two paths: a Python module defining one or more `beangulp
<https://github.com/beancount/beangulp>`_ ``Importer`` subclasses (a "config
module", conventionally a top-level ``CONFIG`` or ``importers`` list — see
:mod:`beancount_tui.beangulp_importer`), and the source file to run through
it. An optional target-account field overrides the importer's own declared
account, which matters for IMP-03 dedup (matched by date+amount+account);
most beangulp importers already know their account, so it can usually be
left blank.

Submitting loads the module and runs
:func:`beancount_tui.beangulp_importer.extract_candidates`, producing the
same :class:`~beancount_tui.importer.ImportCandidate` list the CSV import
path produces (IMP-01/IMP-02), which is then handed to the same
``ImportReviewScreen`` — so preview, dedup, edit, and append are shared with
the CSV path, not reimplemented. Any failure to load the module or match an
importer is caught and shown inline rather than crashing the app.
"""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static

from beancount_tui.beangulp_importer import (
    BeangulpImportError,
    extract_candidates,
    load_importer_module,
)
from beancount_tui.importer import ImportCandidate


class BeangulpImportForm(ModalScreen[list[ImportCandidate] | None]):
    """Returns the parsed candidate list, or ``None`` if cancelled."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    DEFAULT_CSS = """
    BeangulpImportForm {
        align: center middle;
    }
    BeangulpImportForm > Vertical {
        width: 90;
        height: auto;
        max-height: 90%;
        border: round $primary;
        padding: 1 2;
        background: $surface;
    }
    BeangulpImportForm .field-label {
        margin-top: 1;
        color: $text-muted;
    }
    BeangulpImportForm #error {
        color: $error;
        height: auto;
    }
    BeangulpImportForm #buttons {
        height: auto;
        align-horizontal: right;
        margin-top: 1;
    }
    BeangulpImportForm Button {
        margin-left: 2;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("[b]Import via beangulp importer[/b]")
            yield Label(
                "Importer module (.py defining a CONFIG/importers list)",
                classes="field-label",
            )
            yield Input(placeholder="/path/to/my_importers.py", id="module-path")
            yield Label("Source file to import", classes="field-label")
            yield Input(placeholder="/path/to/statement.ofx", id="source-path")
            yield Label(
                "Target account (optional — overrides the importer's own account)",
                classes="field-label",
            )
            yield Input(placeholder="Assets:Checking", id="account")
            yield Static("", id="error")
            with Horizontal(id="buttons"):
                yield Button("Cancel", id="cancel")
                yield Button("Import", id="import", variant="primary")

    def _error(self, message: str) -> None:
        self.query_one("#error", Static).update(message)

    def _do_import(self) -> None:
        module_text = self.query_one("#module-path", Input).value.strip()
        source_text = self.query_one("#source-path", Input).value.strip()
        account = self.query_one("#account", Input).value.strip() or None

        if not module_text:
            self._error("Enter a path to the importer module.")
            return
        if not source_text:
            self._error("Enter a path to the source file.")
            return

        source_path = Path(source_text)
        if not source_path.is_file():
            self._error(f"No such file: {source_path}")
            return

        try:
            module = load_importer_module(Path(module_text))
            candidates = extract_candidates(module, source_path, account=account)
        except BeangulpImportError as exc:
            self._error(str(exc))
            return

        if not candidates:
            self._error("The importer matched the file but extracted no transactions.")
            return

        self.dismiss(candidates)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "import":
            self._do_import()
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)
