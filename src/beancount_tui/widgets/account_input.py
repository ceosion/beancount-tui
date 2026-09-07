"""Single-line account name input with the same Tab-completion behavior as
``PostingsArea`` (see ``postings_area.py``), for forms that have a dedicated
account field rather than an inline postings block."""

from __future__ import annotations

import os

from textual import events
from textual.widgets import Input


class AccountInput(Input):
    """An ``Input`` that Tab-completes account names.

    Tab extends the current value to the longest common prefix of the
    matching accounts; a unique match completes fully. With no match, Tab
    keeps its default behavior (moving focus). Mirrors ``PostingsArea``'s
    completion logic, adapted to a single-line ``Input`` (whole value
    instead of the current line's first token).
    """

    def __init__(self, value: str = "", *, accounts: list[str] | None = None, **kwargs) -> None:
        super().__init__(value, **kwargs)
        self.accounts = accounts or []

    async def _on_key(self, event: events.Key) -> None:
        if event.key != "tab":
            return
        prefix = self.value[: self.cursor_position]
        if not prefix:
            return
        candidates = [a for a in self.accounts if a.lower().startswith(prefix.lower())]
        if not candidates:
            return
        completion = os.path.commonprefix(candidates)
        if completion == prefix:
            return
        rest = self.value[self.cursor_position :]
        self.value = completion + rest
        self.cursor_position = len(completion)
        event.prevent_default()
        event.stop()
