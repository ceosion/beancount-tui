"""Input bar for filtering the transaction table."""

from __future__ import annotations

from textual.message import Message
from textual.widgets import Input


class FilterBar(Input):
    """Filters as the user types.

    Posts :class:`FilterChanged` on every keystroke, :class:`FilterAccepted`
    on Enter (keep the filter, leave the bar), and :class:`FilterClosed` on
    Escape (drop the filter).
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
            placeholder="payee/narration text, or date range YYYY-MM-DD..YYYY-MM-DD",
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
