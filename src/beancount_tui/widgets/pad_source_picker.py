"""Modal picker for choosing an account's pad-source account.

Shown by `action_pad_and_verify` when no prior `pad` directive for the
selected account lets it infer one automatically.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList
from textual.widgets.option_list import Option


class PadSourcePicker(ModalScreen[str | None]):
    """Returns the chosen source account name, or ``None`` if cancelled."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    DEFAULT_CSS = """
    PadSourcePicker {
        align: center middle;
    }
    PadSourcePicker > Vertical {
        width: 60;
        height: auto;
        max-height: 90%;
        border: round $primary;
        padding: 1 2;
        background: $surface;
    }
    PadSourcePicker OptionList {
        height: auto;
        max-height: 20;
        margin-top: 1;
    }
    """

    def __init__(self, accounts: list[str], *, account: str) -> None:
        super().__init__()
        self._accounts = accounts
        self._account = account

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(
                f"[b]Pad source for {self._account}[/b]\n"
                "No prior pad directive found for this account — pick the "
                "account to pad from."
            )
            yield OptionList(*(Option(account, id=account) for account in self._accounts))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option_id)

    def action_cancel(self) -> None:
        self.dismiss(None)
