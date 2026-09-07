"""Input bar for filtering the transaction table."""

from __future__ import annotations

from textual.message import Message
from textual.widgets import Input

from beancount_tui.widgets.date_input import DateRangeInput


class FilterBar(DateRangeInput):
    """Filters as the user types.

    Posts :class:`FilterChanged` on every keystroke, :class:`FilterAccepted`
    on Enter (keep the filter, leave the bar), and :class:`FilterClosed` on
    Escape (drop the filter). Also inherits `DateRangeInput`'s `ctrl+p`
    calendar picker (UX-06) for the `YYYY-MM-DD..YYYY-MM-DD` range half of
    its syntax; a plain text filter or a preset token (``month``, etc.) is
    unaffected.
    """

    BINDINGS = [("escape", "close", "Close filter")]

    class FilterChanged(Message):
        def __init__(self, query: str) -> None:
            self.query = query
            super().__init__()

    class FilterAccepted(Message):
        pass

    class FilterClosed(Message):
        pass

    def __init__(self, **kwargs) -> None:
        super().__init__(
            placeholder=(
                "text, YYYY-MM-DD..YYYY-MM-DD, or month/last-month/year/last-year"
            ),
            **kwargs,
        )

    def on_input_changed(self, event: Input.Changed) -> None:
        event.stop()
        self.post_message(self.FilterChanged(event.value))

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self.post_message(self.FilterAccepted())

    def action_close(self) -> None:
        self.post_message(self.FilterClosed())
