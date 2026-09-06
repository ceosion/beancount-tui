"""Modal review screen for CSV import candidates.

Lists every :class:`~beancount_tui.importer.ImportCandidate` produced by
:class:`~beancount_tui.widgets.import_form.ImportForm`, each behind a
checkbox (checked by default; rows with a parse ``error`` from IMP-01 start
unchecked, since they can't be cleanly imported without a fix first). Any
row can be opened in :class:`~beancount_tui.widgets.transaction_form.TransactionForm`
for edits before import — most CSV exports only tell you one side of the
posting, so each candidate is seeded with a placeholder balancing leg
(``Expenses:FIXME``, mirroring the ``Assets:FIXME`` convention used for new
directive templates elsewhere in the app) that the user is expected to fill
in either here or after import.

Confirming validates every still-checked row's current (possibly edited)
source text with the real Beancount parser and dismisses with the list of
texts to append; nothing is written to the ledger here — that happens in
the caller (``app.py``), consistent with every other write path.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from decimal import Decimal

from textual.app import ComposeResult
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Label, Static

from beancount_tui.editor import TransactionParseError, format_entry, parse_transaction_text
from beancount_tui.importer import ImportCandidate
from beancount_tui.widgets.transaction_form import TransactionForm, TransactionFormResult


def _assemble_transaction_text(
    date: str, flag: str, payee: str, narration: str, tags_links: str, postings_text: str
) -> str:
    """Build transaction source text from fields, matching ``TransactionForm``'s assembly."""
    quoted_payee = f' "{payee}"' if payee else ""
    header = f'{date} {flag}{quoted_payee} "{narration}"'
    if tags_links:
        header += f" {tags_links}"
    body = "\n".join("  " + line.strip() for line in postings_text.splitlines() if line.strip())
    return f"{header}\n{body}\n"


def _postings_text(txn) -> str:  # noqa: ANN001 - beancount data.Transaction
    lines = format_entry(txn).rstrip("\n").split("\n")
    return "\n".join(line.strip() for line in lines[1:])


def _tags_links_text(txn) -> str:  # noqa: ANN001 - beancount data.Transaction
    tokens = [f"#{tag}" for tag in sorted(txn.tags or ())]
    tokens += [f"^{link}" for link in sorted(txn.links or ())]
    return " ".join(tokens)


def _candidate_label(candidate: ImportCandidate, *, edited: bool = False) -> str:
    date = candidate.date.isoformat() if candidate.date else "????-??-??"
    amount = f"{candidate.amount} " if candidate.amount is not None else "? "
    payee = f'"{candidate.payee}" ' if candidate.payee else ""
    label = f"{date}  {payee}{candidate.narration}  {amount}-> {candidate.account}"
    if edited:
        label += "  (edited)"
    if candidate.error:
        label += f"  [error: {candidate.error}]"
    return label


@dataclass
class _Row:
    """Mutable per-candidate state: whether it's checked, and its current
    (possibly user-edited) field values / assembled source text."""

    candidate: ImportCandidate
    checked: bool
    date: str
    flag: str
    payee: str
    narration: str
    tags_links: str
    postings_text: str
    text: str
    edited: bool = field(default=False)


def _row_from_candidate(candidate: ImportCandidate) -> _Row:
    date = candidate.date.isoformat() if candidate.date else datetime.date.today().isoformat()
    flag = "*"
    payee = candidate.payee
    narration = candidate.narration
    tags_links = ""
    amount = candidate.amount if candidate.amount is not None else Decimal("0.00")
    postings_text = f"{candidate.account}  {amount} USD\nExpenses:FIXME"
    text = _assemble_transaction_text(date, flag, payee, narration, tags_links, postings_text)
    return _Row(
        candidate=candidate,
        checked=candidate.error is None,
        date=date,
        flag=flag,
        payee=payee,
        narration=narration,
        tags_links=tags_links,
        postings_text=postings_text,
        text=text,
    )


class ImportReviewScreen(ModalScreen[list[str] | None]):
    """Returns the list of confirmed transaction source texts, or ``None`` if cancelled."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    DEFAULT_CSS = """
    ImportReviewScreen {
        align: center middle;
    }
    ImportReviewScreen > Vertical {
        width: 100;
        height: auto;
        max-height: 90%;
        border: round $primary;
        padding: 1 2;
        background: $surface;
    }
    ImportReviewScreen #rows {
        height: auto;
        max-height: 20;
        margin-top: 1;
    }
    ImportReviewScreen .row {
        height: auto;
    }
    ImportReviewScreen .row Checkbox {
        width: 1fr;
    }
    ImportReviewScreen #error {
        color: $error;
        height: auto;
    }
    ImportReviewScreen #buttons {
        height: auto;
        align-horizontal: right;
        margin-top: 1;
    }
    ImportReviewScreen Button {
        margin-left: 2;
    }
    """

    def __init__(
        self, candidates: list[ImportCandidate], *, accounts: list[str] | None = None
    ) -> None:
        super().__init__()
        self._accounts = accounts or []
        self._rows: list[_Row] = [_row_from_candidate(c) for c in candidates]

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(f"[b]Review import ({len(self._rows)} candidate(s))[/b]")
            with ScrollableContainer(id="rows"):
                for i, row in enumerate(self._rows):
                    with Horizontal(classes="row"):
                        yield Checkbox(
                            _candidate_label(row.candidate),
                            value=row.checked,
                            id=f"check-{i}",
                        )
                        yield Button("Edit", id=f"edit-{i}")
            yield Static("", id="error")
            with Horizontal(id="buttons"):
                yield Button("Cancel", id="cancel")
                yield Button("Import", id="import", variant="primary")

    def _error(self, message: str) -> None:
        self.query_one("#error", Static).update(message)

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        checkbox_id = event.checkbox.id or ""
        if not checkbox_id.startswith("check-"):
            return
        index = int(checkbox_id.removeprefix("check-"))
        self._rows[index].checked = event.value

    def _open_edit(self, index: int) -> None:
        row = self._rows[index]

        def on_result(result: TransactionFormResult | None) -> None:
            if result is None:
                return
            row.text = result.text
            row.checked = True
            row.edited = True
            try:
                txn = parse_transaction_text(result.text)
            except TransactionParseError:
                pass
            else:
                row.date = txn.date.isoformat()
                row.flag = txn.flag or "*"
                row.payee = txn.payee or ""
                row.narration = txn.narration or ""
                row.tags_links = _tags_links_text(txn)
                row.postings_text = _postings_text(txn)
            checkbox = self.query_one(f"#check-{index}", Checkbox)
            checkbox.value = True
            checkbox.label = _candidate_label(row.candidate, edited=True)

        self.app.push_screen(
            TransactionForm(
                date=row.date,
                flag=row.flag,
                payee=row.payee,
                narration=row.narration,
                tags_links=row.tags_links,
                postings_text=row.postings_text,
                title=f"Edit import row {row.candidate.row_number}",
                accounts=self._accounts,
            ),
            on_result,
        )

    def _do_import(self) -> None:
        confirmed: list[str] = []
        problems: list[str] = []
        for row in self._rows:
            if not row.checked:
                continue
            try:
                parse_transaction_text(row.text)
            except TransactionParseError as exc:
                problems.append(f"Row {row.candidate.row_number}: {exc}")
                continue
            confirmed.append(row.text)
        if problems:
            self._error("\n".join(problems))
            return
        self.dismiss(confirmed)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id == "import":
            self._do_import()
        elif button_id == "cancel":
            self.dismiss(None)
        elif button_id.startswith("edit-"):
            self._open_edit(int(button_id.removeprefix("edit-")))

    def action_cancel(self) -> None:
        self.dismiss(None)
