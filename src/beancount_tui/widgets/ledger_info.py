"""Modal ledger info screen: effective Beancount options not shown elsewhere."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, Static

from beancount_tui.ledger import Ledger

# Beancount's built-in defaults for the account-name-root options.
_DEFAULT_ACCOUNT_NAMES = {
    "name_assets": "Assets",
    "name_liabilities": "Liabilities",
    "name_equity": "Equity",
    "name_income": "Income",
    "name_expenses": "Expenses",
}


def _booking_method_text(options: dict) -> str:
    method = options.get("booking_method")
    if method is None:
        return "(default)"
    return getattr(method, "name", str(method))


def _render_ledger_info(ledger: Ledger) -> str:
    options = ledger.options

    title = options.get("title") or "(untitled)"

    currencies = options.get("operating_currency") or []
    currencies_text = ", ".join(currencies) if currencies else "(none set)"

    booking_text = _booking_method_text(options)

    account_lines = []
    for key, default in _DEFAULT_ACCOUNT_NAMES.items():
        label = key[len("name_") :].capitalize()
        value = options.get(key, default)
        account_lines.append(f"  {label}: {value}")

    file_lines = [f"  {f}" for f in ledger.files]

    lines = [
        f"[b]Title:[/b] {title}",
        f"[b]Operating currencies:[/b] {currencies_text}",
        f"[b]Booking method:[/b] {booking_text}",
        "",
        "[b]Account name roots:[/b]",
        *account_lines,
        "",
        "[b]Source files:[/b]",
        *file_lines,
    ]
    return "\n".join(lines)


class LedgerInfoScreen(ModalScreen[None]):
    """Read-only summary of effective ledger options; Escape closes it."""

    BINDINGS = [("escape", "cancel", "Close")]

    DEFAULT_CSS = """
    LedgerInfoScreen {
        align: center middle;
    }
    LedgerInfoScreen > Vertical {
        width: 80;
        height: auto;
        max-height: 90%;
        border: round $primary;
        padding: 1 2;
        background: $surface;
    }
    LedgerInfoScreen #info {
        margin-top: 1;
    }
    """

    def __init__(self, ledger: Ledger) -> None:
        super().__init__()
        self._ledger = ledger

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("[b]Ledger info[/b]")
            yield Static(_render_ledger_info(self._ledger), id="info")

    def action_cancel(self) -> None:
        self.dismiss(None)
