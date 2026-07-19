"""Postings editor with Tab-completion of account names."""

from __future__ import annotations

import os

from textual import events
from textual.widgets import TextArea


class PostingsArea(TextArea):
    """A ``TextArea`` that completes account names on Tab.

    Completion applies only while typing the first token of a line (the
    account position of a posting). Tab extends the token to the longest
    common prefix of the matching accounts; a unique match is completed
    fully with two trailing spaces, ready for the amount. With no match,
    Tab keeps its default focus behavior.
    """

    def __init__(self, text: str = "", *, accounts: list[str] | None = None, **kwargs) -> None:
        super().__init__(text, **kwargs)
        self.accounts = accounts or []

    async def _on_key(self, event: events.Key) -> None:
        if event.key != "tab":
            return
        row, col = self.cursor_location
        before = self.document.get_line(row)[:col]
        prefix = before.lstrip()
        if not prefix or any(c.isspace() for c in prefix):
            return  # not in the account position
        candidates = [a for a in self.accounts if a.lower().startswith(prefix.lower())]
        if not candidates:
            return
        completion = os.path.commonprefix(candidates)
        if len(candidates) == 1:
            completion += "  "
        if completion == prefix:
            return
        indent = len(before) - len(prefix)
        self.replace(completion, (row, indent), (row, col))
        event.prevent_default()
        event.stop()
