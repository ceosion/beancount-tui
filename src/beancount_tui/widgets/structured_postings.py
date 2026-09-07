"""Row-based structured postings editor.

An alternative UX to the raw-text ``PostingsArea`` (see ``postings_area.py``)
for the common case: each posting is just an account plus an optional
amount/currency, with no cost basis, price annotation, posting flag, or
per-posting metadata. Each posting gets its own row -- an ``AccountInput``
(reusing its Tab-completion, see ``account_input.py``) plus a number field
and a currency field -- with buttons to add and remove rows.

Rows serialize to the exact same posting-line text ``PostingsArea`` produces
and ``editor.parse_transaction_text`` accepts (``ACCOUNT  AMOUNT CURRENCY``,
one per line), and load from that same text via
``editor.decompose_postings_text`` -- which classifies a posting as
structurally representable (or not) using the real Beancount parser rather
than a bespoke regex, so structured and raw agree exactly on what's valid.
This is what lets ``TransactionForm``'s toggle switch between the two views
without losing or corrupting already-entered postings.

Postings using syntax this widget doesn't model (cost basis, price
annotations, posting flags, per-posting metadata) can't be decomposed into
account/amount/currency; ``decompose_postings_text`` returns ``None`` for
such text, and ``StructuredPostingsArea.load_text`` reports that failure so
the caller (``TransactionForm``'s toggle action) can keep the raw-text
``PostingsArea`` as the active view instead -- the escape hatch called for
by UX-08.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Input

from beancount_tui.editor import SimplePosting, decompose_postings_text
from beancount_tui.widgets.account_input import AccountInput


class PostingsRow(Horizontal):
    """One posting: an account field plus optional amount and currency."""

    DEFAULT_CSS = """
    PostingsRow {
        height: 3;
        margin-bottom: 1;
    }
    PostingsRow .posting-account {
        width: 3fr;
    }
    PostingsRow .posting-amount {
        width: 1fr;
    }
    PostingsRow .posting-currency {
        width: 10;
    }
    PostingsRow .remove-row {
        width: 3;
        min-width: 3;
    }
    """

    def __init__(
        self,
        account: str = "",
        amount: str = "",
        currency: str = "",
        *,
        accounts: list[str] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._account = account
        self._amount = amount
        self._currency = currency
        self._accounts = accounts or []

    def compose(self) -> ComposeResult:
        yield AccountInput(
            self._account,
            accounts=self._accounts,
            placeholder="Account",
            classes="posting-account",
        )
        yield Input(self._amount, placeholder="Amount", classes="posting-amount")
        yield Input(self._currency, placeholder="Currency", classes="posting-currency")
        yield Button("−", classes="remove-row", variant="error")

    def to_posting(self) -> SimplePosting | None:
        """The `SimplePosting` this row represents, or ``None`` if empty
        (no account entered -- an empty row is dropped rather than
        serialized as a blank posting line)."""
        account = self.query_one(".posting-account", AccountInput).value.strip()
        if not account:
            return None
        amount = self.query_one(".posting-amount", Input).value.strip()
        currency = self.query_one(".posting-currency", Input).value.strip()
        return SimplePosting(account, amount, currency)


class StructuredPostingsArea(Vertical):
    """A list of `PostingsRow`s plus an "Add posting" control.

    See the module docstring for how rows relate to raw posting text.
    """

    DEFAULT_CSS = """
    StructuredPostingsArea {
        height: auto;
    }
    StructuredPostingsArea #add-posting-row {
        margin-top: 1;
        width: auto;
    }
    """

    def __init__(self, *, accounts: list[str] | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._accounts = accounts or []

    def compose(self) -> ComposeResult:
        yield Vertical(id="rows")
        yield Button("+ Add posting", id="add-posting-row")

    def on_mount(self) -> None:
        if not self.query("PostingsRow"):
            self.add_row()

    def add_row(self, account: str = "", amount: str = "", currency: str = "") -> None:
        row = PostingsRow(account, amount, currency, accounts=self._accounts)
        self.query_one("#rows", Vertical).mount(row)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "add-posting-row":
            self.add_row()
            event.stop()
        elif "remove-row" in event.button.classes:
            row = event.button.parent
            if isinstance(row, PostingsRow):
                rows = self.query("PostingsRow")
                if len(rows) > 1:
                    await row.remove()
                else:
                    # Keep at least one row visible; just clear its fields.
                    row.query_one(".posting-account", AccountInput).value = ""
                    row.query_one(".posting-amount", Input).value = ""
                    row.query_one(".posting-currency", Input).value = ""
            event.stop()

    def to_text(self) -> str:
        """Serialize all rows to posting-line text, in the same
        ``ACCOUNT  AMOUNT CURRENCY`` format `PostingsArea` uses."""
        lines = [
            posting.to_line()
            for row in self.query("PostingsRow")
            if (posting := row.to_posting()) is not None
        ]
        return "\n".join(lines)

    async def load_text(self, text: str) -> bool:
        """Replace all rows with the postings decomposed from ``text``.

        Returns ``True`` and updates the rows if every posting in ``text``
        decomposes into a plain account/amount/currency triple. Returns
        ``False`` and leaves the rows untouched if any posting uses syntax
        this widget can't represent (cost basis, price annotation, flag, or
        metadata) -- see ``editor.decompose_postings_text``.
        """
        decomposed = decompose_postings_text(text)
        if decomposed is None:
            return False
        rows_container = self.query_one("#rows", Vertical)
        await rows_container.remove_children()
        if not decomposed:
            decomposed = [SimplePosting("")]
        for posting in decomposed:
            row = PostingsRow(
                posting.account, posting.amount, posting.currency, accounts=self._accounts
            )
            await rows_container.mount(row)
        return True
