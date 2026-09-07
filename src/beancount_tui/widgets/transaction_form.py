"""Modal form for creating or editing a transaction.

The form assembles Beancount source text and validates it with the real
Beancount parser before handing it back to the app, so anything the form
accepts is guaranteed to be syntactically valid.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, Label, Select, Static, TextArea

from beancount_tui.editor import TransactionParseError, parse_transaction_text
from beancount_tui.widgets.budget_form import INTERVALS
from beancount_tui.widgets.date_input import DateInput
from beancount_tui.widgets.postings_area import PostingsArea


@dataclass
class TransactionFormResult:
    """What the form hands back on save."""

    text: str
    filename: str | None = None  # target file for a new transaction; None = caller's default


class TransactionForm(ModalScreen[TransactionFormResult | None]):
    """Returns a :class:`TransactionFormResult`, or ``None`` if cancelled."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    DEFAULT_CSS = """
    TransactionForm {
        align: center middle;
    }
    TransactionForm > Vertical {
        width: 80;
        height: auto;
        max-height: 90%;
        border: round $primary;
        padding: 1 2;
        background: $surface;
    }
    TransactionForm .field-label {
        margin-top: 1;
        color: $text-muted;
    }
    TransactionForm #postings {
        height: 8;
    }
    TransactionForm #error {
        color: $error;
        height: auto;
    }
    TransactionForm #buttons {
        height: auto;
        align-horizontal: right;
        margin-top: 1;
    }
    TransactionForm Button {
        margin-left: 2;
    }
    """

    def __init__(
        self,
        *,
        date: str | None = None,
        flag: str = "*",
        payee: str = "",
        narration: str = "",
        tags_links: str = "",
        postings_text: str = "",
        title: str = "New transaction",
        files: list[Path] | None = None,
        accounts: list[str] | None = None,
        recurring: bool = False,
        recurring_interval: str = "monthly",
        recurring_until: str = "",
        selected_file: str | None = None,
    ) -> None:
        super().__init__()
        self._accounts = accounts or []
        self._date = date or datetime.date.today().isoformat()
        self._flag = flag
        self._payee = payee
        self._narration = narration
        self._tags_links = tags_links
        self._postings_text = postings_text
        self._title = title
        # Offer a target-file picker only when there is a real choice.
        self._files = files if files and len(files) > 1 else None
        # EDIT-05: which file's Select entry to preselect when reopening the
        # form after a declined missing-account prompt, so the user's
        # previously-chosen target file isn't silently reset to the first
        # one. Ignored (falls back to the first file) if it isn't one of
        # `files`.
        self._selected_file = selected_file
        # FORECAST-03: guided "recurring template" fields layered on top of
        # the free-text tags/links input above, rather than replacing it —
        # see ``_with_recurring_tag`` for how the two are reconciled at save
        # time.
        self._recurring = recurring
        self._recurring_interval = recurring_interval
        self._recurring_until = recurring_until

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(f"[b]{self._title}[/b]")
            yield Label("Date", classes="field-label")
            yield DateInput(value=self._date, id="date", placeholder="YYYY-MM-DD")
            yield Label("Flag (* = cleared, ! = pending)", classes="field-label")
            yield Input(value=self._flag, id="flag")
            yield Label("Payee", classes="field-label")
            yield Input(value=self._payee, id="payee", placeholder="(optional)")
            yield Label("Narration", classes="field-label")
            yield Input(value=self._narration, id="narration")
            yield Label("Tags / links (e.g. #vacation ^receipt-123)", classes="field-label")
            yield Input(value=self._tags_links, id="tags_links", placeholder="(optional)")
            yield Checkbox("Recurring template", value=self._recurring, id="recurring")
            interval_label = Label(
                "Recurring interval", classes="field-label", id="recurring-interval-label"
            )
            interval_select = Select(
                INTERVALS, value=self._recurring_interval, allow_blank=False, id="recurring-interval"
            )
            until_label = Label(
                "Repeat until (optional)", classes="field-label", id="recurring-until-label"
            )
            until_input = DateInput(
                value=self._recurring_until,
                id="recurring-until",
                placeholder="YYYY-MM-DD (optional)",
            )
            for widget in (interval_label, interval_select, until_label, until_input):
                widget.display = self._recurring
            yield interval_label
            yield interval_select
            yield until_label
            yield until_input
            yield Label(
                "Postings (one per line: ACCOUNT  AMOUNT CURRENCY; Tab completes accounts)",
                classes="field-label",
            )
            yield PostingsArea(self._postings_text, id="postings", accounts=self._accounts)
            if self._files:
                yield Label("File", classes="field-label")
                file_values = [str(f) for f in self._files]
                default_file = (
                    self._selected_file if self._selected_file in file_values else file_values[0]
                )
                yield Select(
                    [(self._file_label(f), value) for f, value in zip(self._files, file_values)],
                    value=default_file,
                    allow_blank=False,
                    id="target-file",
                )
            yield Static("", id="error")
            with Horizontal(id="buttons"):
                yield Button("Cancel", id="cancel")
                yield Button("Save", id="save", variant="primary")

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        if event.checkbox.id != "recurring":
            return
        self._set_recurring_fields_visible(event.value)

    def _set_recurring_fields_visible(self, visible: bool) -> None:
        for widget_id in (
            "#recurring-interval-label",
            "#recurring-interval",
            "#recurring-until-label",
            "#recurring-until",
        ):
            self.query_one(widget_id).display = visible

    def _assemble_text(self) -> str:
        date = self.query_one("#date", Input).value.strip()
        flag = self.query_one("#flag", Input).value.strip() or "*"
        payee = self.query_one("#payee", Input).value.strip()
        narration = self.query_one("#narration", Input).value.strip()
        tags_links = self.query_one("#tags_links", Input).value.strip()
        postings = self.query_one("#postings", TextArea).text
        recurring = self.query_one("#recurring", Checkbox).value

        if recurring:
            tags_links = _with_recurring_tag(tags_links)

        quoted_payee = f' "{payee}"' if payee else ""
        header = f'{date} {flag}{quoted_payee} "{narration}"'
        if tags_links:
            header += f" {tags_links}"

        # Transaction-level metadata (``recurring-freq``/``recurring-until``)
        # must appear immediately after the header and before any posting
        # lines — Beancount attaches metadata that follows a posting to that
        # posting instead of the transaction (see module/FORECAST-03 notes).
        meta_lines: list[str] = []
        if recurring:
            interval = str(self.query_one("#recurring-interval", Select).value)
            meta_lines.append(f'  recurring-freq: "{interval}"')
            until = self.query_one("#recurring-until", Input).value.strip()
            if until:
                meta_lines.append(f'  recurring-until: "{until}"')

        body = "\n".join(
            "  " + line.strip() for line in postings.splitlines() if line.strip()
        )
        lines = [header, *meta_lines]
        if body:
            lines.append(body)
        return "\n".join(lines) + "\n"

    def _file_label(self, file: Path) -> str:
        assert self._files
        top_dir = self._files[0].parent
        try:
            return str(file.relative_to(top_dir))
        except ValueError:
            return str(file)

    def _save(self) -> None:
        if self.query_one("#recurring", Checkbox).value:
            until = self.query_one("#recurring-until", Input).value.strip()
            if until:
                try:
                    datetime.date.fromisoformat(until)
                except ValueError:
                    self.query_one("#error", Static).update(
                        f'Invalid "repeat until" date "{until}": expected YYYY-MM-DD.'
                    )
                    return
        text = self._assemble_text()
        try:
            parse_transaction_text(text)
        except TransactionParseError as exc:
            self.query_one("#error", Static).update(str(exc))
            return
        filename = None
        if self._files:
            filename = str(self.query_one("#target-file", Select).value)
        self.dismiss(TransactionFormResult(text=text, filename=filename))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save":
            self._save()
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


def _with_recurring_tag(tags_links: str) -> str:
    """Ensure ``#recurring`` is present in ``tags_links``, without duplicating it.

    The recurring toggle always wants ``#recurring`` in the final tags, but
    the free-text tags/links field (``tags_links``) may already have it —
    typed manually, or pre-filled from an existing recurring transaction's
    own tags (see ``app._tags_links_text``). De-duping on the token itself
    (rather than e.g. always appending) means toggling recurring on for a
    transaction that already has ``#recurring`` typed doesn't produce
    ``#recurring #recurring`` in the assembled header.
    """
    tokens = tags_links.split()
    if "#recurring" in tokens:
        return tags_links
    return (tags_links + " #recurring").strip()
