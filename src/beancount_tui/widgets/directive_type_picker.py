"""Modal picker for choosing the type of a new directive to add."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList
from textual.widgets.option_list import Option

# Keyword, display label. Order shown matches typical usage frequency.
DIRECTIVE_TYPES: tuple[tuple[str, str], ...] = (
    ("balance", "Balance — assert an account's amount"),
    ("note", "Note — a dated comment on an account"),
    ("open", "Open — start using an account"),
    ("close", "Close — stop using an account"),
    ("pad", "Pad — auto-balance from another account"),
    ("price", "Price — record a price quote"),
    ("event", "Event — record a dated event value"),
    ("custom", "Custom — a user-defined directive"),
)


class DirectiveTypePicker(ModalScreen[str | None]):
    """Returns the chosen directive keyword, or ``None`` if cancelled."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    DEFAULT_CSS = """
    DirectiveTypePicker {
        align: center middle;
    }
    DirectiveTypePicker > Vertical {
        width: 60;
        height: auto;
        border: round $primary;
        padding: 1 2;
        background: $surface;
    }
    DirectiveTypePicker OptionList {
        height: auto;
        margin-top: 1;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("[b]Add directive[/b]")
            yield OptionList(*(Option(label, id=keyword) for keyword, label in DIRECTIVE_TYPES))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option_id)

    def action_cancel(self) -> None:
        self.dismiss(None)
