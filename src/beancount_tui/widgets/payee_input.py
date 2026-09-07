"""Single-line payee input with the same Tab-completion behavior as
``AccountInput`` (see ``account_input.py``), completing against payees
already used in the ledger (UX-07)."""

from __future__ import annotations

import os

from textual import events
from textual.widgets import Input


class PayeeInput(Input):
    """An ``Input`` that Tab-completes payee names.

    Tab extends the current value to the longest common prefix of the
    matching payees; a unique match completes fully. With no match, Tab
    keeps its default behavior (moving focus). Identical logic to
    ``AccountInput``, adapted to a list of known payees (``Ledger.payees``)
    instead of accounts.
    """

    def __init__(self, value: str = "", *, payees: list[str] | None = None, **kwargs) -> None:
        super().__init__(value, **kwargs)
        self.payees = payees or []

    async def _on_key(self, event: events.Key) -> None:
        if event.key != "tab":
            return
        prefix = self.value[: self.cursor_position]
        if not prefix:
            return
        candidates = [p for p in self.payees if p.lower().startswith(prefix.lower())]
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
