"""Single-line tags/links input with Tab-completion of ``#tag`` tokens
against tags already used in the ledger (UX-07)."""

from __future__ import annotations

import os

from textual import events
from textual.widgets import Input


class TagsInput(Input):
    """An ``Input`` that Tab-completes the ``#tag`` token under the cursor.

    The field mixes ``#tag`` and ``^link`` tokens (e.g.
    ``"#vacation ^receipt-123"``) as free-form space-separated text, so
    completion can't apply to the whole value the way ``AccountInput``/
    ``PayeeInput`` do -- instead it targets just the current token: Tab
    extends a ``#``-prefixed token to the longest common prefix of the
    matching known tags (``Ledger.tags``), completing it fully on a unique
    match. Tab keeps its default behavior (moving focus) when the cursor
    isn't inside a ``#`` token (e.g. it's in a ``^link`` token, plain text,
    or whitespace) or when there's no match.
    """

    def __init__(self, value: str = "", *, tags: list[str] | None = None, **kwargs) -> None:
        super().__init__(value, **kwargs)
        self.tags = tags or []

    def _current_token_start(self) -> int:
        """Index into ``self.value`` where the token under the cursor
        begins -- scanning back from the cursor to the previous whitespace,
        or the start of the value."""
        pos = self.cursor_position
        while pos > 0 and not self.value[pos - 1].isspace():
            pos -= 1
        return pos

    async def _on_key(self, event: events.Key) -> None:
        if event.key != "tab":
            return
        start = self._current_token_start()
        token = self.value[start : self.cursor_position]
        if not token.startswith("#"):
            return
        prefix = token[1:]
        if not prefix:
            return
        candidates = [t for t in self.tags if t.lower().startswith(prefix.lower())]
        if not candidates:
            return
        completion = os.path.commonprefix(candidates)
        if completion == prefix:
            return
        new_token = "#" + completion
        rest = self.value[self.cursor_position :]
        self.value = self.value[:start] + new_token + rest
        self.cursor_position = start + len(new_token)
        event.prevent_default()
        event.stop()
