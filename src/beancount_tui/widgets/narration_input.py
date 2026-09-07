"""Narration input with a prefix-matched suggestion dropdown, rather than
forced completion (UX-07).

Narration is free text, unlike the closed candidate sets ``AccountInput``/
``PayeeInput``/``TagsInput`` Tab-complete against -- forcing a value the
way those do would fight a user typing a genuinely new narration. Instead
``NarrationInput`` narrows a small list of prior narrations
(``Ledger.narrations``, most recently used first) as the user types, and
only replaces the field's text if the user explicitly picks one.
"""

from __future__ import annotations

from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Input, OptionList

#: Cap on how many prior narrations are shown at once, so a large ledger
#: doesn't produce an unwieldy dropdown.
MAX_SUGGESTIONS = 8


class _NarrationField(Input):
    """The actual text field inside ``NarrationInput``.

    Key handling lives here (mirroring ``AccountInput``/``TagsInput``'s
    ``_on_key`` convention) rather than on the parent container, since key
    events are delivered to the focused widget -- this field, not
    ``NarrationInput`` itself.
    """

    async def _on_key(self, event: events.Key) -> None:
        parent = self.parent
        if not isinstance(parent, NarrationInput):
            return
        if event.key == "tab":
            if not parent.suggestions_visible():
                return
            parent.accept_highlighted()
        elif event.key == "down":
            if not parent.suggestions_visible():
                return
            parent.move_highlight(1)
        elif event.key == "up":
            if not parent.suggestions_visible():
                return
            parent.move_highlight(-1)
        elif event.key == "escape":
            if not parent.suggestions_visible():
                return
            parent.hide_suggestions()
        else:
            return
        event.prevent_default()
        event.stop()


class NarrationInput(Vertical):
    """An ``Input`` plus a dropdown of prior narrations underneath it.

    Typing narrows the dropdown to narrations (``Ledger.narrations``,
    already most-recently-used first) that start with the current text
    (case-insensitive), excluding the current text itself. ``Down``/``Up``
    moves the highlighted suggestion; ``Tab`` accepts it, replacing the
    field's value; ``Escape`` dismisses the list without changing anything.
    All four keys fall through to their normal behavior when the list isn't
    showing (e.g. an empty field, or no matches) -- the same "no match,
    unaffected" fallback ``AccountInput`` uses for Tab.

    The inner ``Input`` keeps whatever ``id`` is passed in (via
    ``input_id``), so callers that look it up by id (e.g.
    ``TransactionForm._assemble_text``'s
    ``self.query_one("#narration", Input)``) keep working unchanged --
    ``query_one`` searches descendants, not just direct children.
    """

    DEFAULT_CSS = """
    NarrationInput {
        height: auto;
    }
    NarrationInput OptionList {
        display: none;
        height: auto;
        max-height: 6;
    }
    NarrationInput OptionList.-visible {
        display: block;
    }
    """

    def __init__(
        self,
        value: str = "",
        *,
        narrations: list[str] | None = None,
        input_id: str | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._value = value
        self.narrations = narrations or []
        self._input_id = input_id

    def compose(self) -> ComposeResult:
        yield _NarrationField(self._value, id=self._input_id)
        yield OptionList(id="narration-suggestions")

    def _matches(self, text: str) -> list[str]:
        if not text:
            return []
        needle = text.lower()
        return [
            n for n in self.narrations if n != text and n.lower().startswith(needle)
        ][:MAX_SUGGESTIONS]

    def on_input_changed(self, event: Input.Changed) -> None:
        option_list = self.query_one(OptionList)
        matches = self._matches(event.value)
        option_list.clear_options()
        if not matches:
            option_list.remove_class("-visible")
            return
        option_list.add_options(matches)
        option_list.highlighted = 0
        option_list.add_class("-visible")

    def suggestions_visible(self) -> bool:
        return self.query_one(OptionList).has_class("-visible")

    def hide_suggestions(self) -> None:
        self.query_one(OptionList).remove_class("-visible")

    def move_highlight(self, delta: int) -> None:
        option_list = self.query_one(OptionList)
        if option_list.option_count == 0:
            return
        current = option_list.highlighted or 0
        option_list.highlighted = (current + delta) % option_list.option_count

    def accept_highlighted(self) -> None:
        option_list = self.query_one(OptionList)
        if option_list.highlighted is None:
            return
        option = option_list.get_option_at_index(option_list.highlighted)
        field = self.query_one(_NarrationField)
        field.value = str(option.prompt)
        field.cursor_position = len(field.value)
        self.hide_suggestions()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """A mouse click on a suggestion (Tab is the keyboard path above)."""
        field = self.query_one(_NarrationField)
        field.value = str(event.option.prompt)
        field.cursor_position = len(field.value)
        self.hide_suggestions()
        field.focus()
