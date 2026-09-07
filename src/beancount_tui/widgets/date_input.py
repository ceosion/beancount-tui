"""Date `Input` widgets with an inline calendar-picker overlay (UX-06).

`DateInput` is a drop-in replacement for a plain `Input` used for a single
ISO date value (`TransactionForm`'s "Date" field, `BudgetForm`'s "Date"
field, the as-of-date report screens, ...): pressing `ctrl+g` while the
field has focus opens `DatePickerScreen`, a month-grid calendar overlay,
and confirming a day there sets `self.value` to the chosen `YYYY-MM-DD`
string -- the same shape a direct typed entry produces. Typing a date
directly still works exactly as it did before; the picker is purely an
additional way in, never a replacement.

`DateRangeInput` extends this for the `START..END` range fields (the
report period pickers, `FilterBar`): opening the picker edits only the
half of the range nearest the cursor, leaving the other bound (and the
`..` itself) untouched, so picking one side of a range doesn't clobber
the other.
"""

from __future__ import annotations

import calendar
import datetime

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label, Static

_WEEKDAY_HEADER = "Mo Tu We Th Fr Sa Su"


def _add_months(day: datetime.date, months: int) -> datetime.date:
    """``day`` advanced by ``months`` calendar months, clamped to the target
    month's actual last day (e.g. Jan 31 + 1 month -> Feb 28/29)."""
    month_index = day.year * 12 + (day.month - 1) + months
    year, zero_based_month = divmod(month_index, 12)
    month = zero_based_month + 1
    last_day_of_month = calendar.monthrange(year, month)[1]
    return datetime.date(year, month, min(day.day, last_day_of_month))


def _month_grid(selected: datetime.date) -> str:
    """Render ``selected``'s month as a fixed-width grid, Monday-first.

    ``calendar.Calendar.monthdatescalendar`` pads the first/last week with
    days from the adjacent month so every row is a full week; those are
    dimmed so the current month's days stand out. The selected day is
    rendered reversed.
    """
    weeks = calendar.Calendar(firstweekday=0).monthdatescalendar(
        selected.year, selected.month
    )
    lines = [_WEEKDAY_HEADER]
    for week in weeks:
        cells = []
        for day in week:
            text = f"{day.day:2d}"
            if day == selected:
                cells.append(f"[reverse]{text}[/reverse]")
            elif day.month != selected.month:
                cells.append(f"[dim]{text}[/dim]")
            else:
                cells.append(text)
        lines.append(" ".join(cells))
    return "\n".join(lines)


def _parse_iso_or_today(value: str | None) -> datetime.date:
    """``value`` parsed as an ISO date, or today's date if ``value`` is
    empty/``None``/not a valid ISO date (e.g. a range preset like
    ``"month"``) -- the picker always has to open on *some* day."""
    if value:
        try:
            return datetime.date.fromisoformat(value.strip())
        except ValueError:
            pass
    return datetime.date.today()


class DatePickerScreen(ModalScreen[str | None]):
    """Calendar overlay: arrow keys move by day, pageup/pagedown by month.

    Returns the chosen date as an ISO ``YYYY-MM-DD`` string on `enter`, or
    ``None`` if cancelled via `escape` -- the same shape a direct typed
    entry would produce, so callers can treat both the same way.
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("enter", "confirm", "Select"),
        ("left", "prev_day", "Prev day"),
        ("right", "next_day", "Next day"),
        ("up", "prev_week", "Prev week"),
        ("down", "next_week", "Next week"),
        ("pageup", "prev_month", "Prev month"),
        ("pagedown", "next_month", "Next month"),
    ]

    DEFAULT_CSS = """
    DatePickerScreen {
        align: center middle;
    }
    DatePickerScreen > Vertical {
        width: 26;
        height: auto;
        border: round $primary;
        padding: 1 2;
        background: $surface;
    }
    DatePickerScreen #month {
        margin-top: 1;
    }
    DatePickerScreen #calendar {
        height: auto;
    }
    DatePickerScreen #hint {
        color: $text-muted;
        height: auto;
        margin-top: 1;
    }
    """

    def __init__(self, initial: str | None = None) -> None:
        super().__init__()
        self._selected = _parse_iso_or_today(initial)

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("[b]Pick a date[/b]")
            yield Static(id="month")
            yield Static(id="calendar")
            yield Static(
                "←/→/↑/↓ day  ·  PgUp/PgDn month  ·  "
                "Enter select  ·  Esc cancel",
                id="hint",
            )

    def on_mount(self) -> None:
        self._refresh()

    def _refresh(self) -> None:
        self.query_one("#month", Static).update(f"[b]{self._selected:%B %Y}[/b]")
        self.query_one("#calendar", Static).update(_month_grid(self._selected))

    def action_prev_day(self) -> None:
        self._selected -= datetime.timedelta(days=1)
        self._refresh()

    def action_next_day(self) -> None:
        self._selected += datetime.timedelta(days=1)
        self._refresh()

    def action_prev_week(self) -> None:
        self._selected -= datetime.timedelta(days=7)
        self._refresh()

    def action_next_week(self) -> None:
        self._selected += datetime.timedelta(days=7)
        self._refresh()

    def action_prev_month(self) -> None:
        self._selected = _add_months(self._selected, -1)
        self._refresh()

    def action_next_month(self) -> None:
        self._selected = _add_months(self._selected, 1)
        self._refresh()

    def action_confirm(self) -> None:
        self.dismiss(self._selected.isoformat())

    def action_cancel(self) -> None:
        self.dismiss(None)


class DateInput(Input):
    """A single ISO-date `Input` with a calendar-picker fallback.

    ``ctrl+g`` opens `DatePickerScreen`, defaulting to this field's current
    value (or today, if empty/unparseable). Confirming a day there replaces
    the whole field value with the chosen ``YYYY-MM-DD`` string; cancelling
    (`escape`) leaves the field untouched. Typing a date directly is
    completely unaffected -- the picker is just an additional way in.
    """

    BINDINGS = [("ctrl+g", "open_date_picker", "Pick date")]

    def action_open_date_picker(self) -> None:
        def on_result(result: str | None) -> None:
            if result is None:
                return
            self.value = result
            self.cursor_position = len(result)

        self.app.push_screen(DatePickerScreen(self.value.strip() or None), on_result)


def _range_token_bounds(value: str, cursor: int) -> tuple[int, int]:
    """The ``(start, end)`` index bounds of the ``START``/``END`` half of a
    ``START..END`` value nearest ``cursor``.

    With no ``..`` present (an empty field, a bare preset like ``"month"``,
    or free text), the whole value is treated as one token -- only the
    *first* ``..`` in the value is considered, so a comma-separated
    comparison list (``"2026-01-01..2026-01-31,2026-02-01..2026-02-28"``)
    only gets picker support for its first range; later segments still
    accept direct typing exactly as before.
    """
    sep = value.find("..")
    if sep == -1:
        return 0, len(value)
    if cursor <= sep:
        return 0, sep
    return sep + 2, len(value)


class DateRangeInput(DateInput):
    """A ``START..END`` range `Input` (report periods, the filter bar) with
    the same calendar-picker fallback as `DateInput`.

    Opening the picker (``ctrl+g``) edits only the half of the range
    nearest the cursor -- the other bound, and the ``..`` itself, are left
    untouched -- so picking one side of a range doesn't clobber a bound the
    user already typed (or is half-way through typing) on the other side.
    """

    def action_open_date_picker(self) -> None:
        start, end = _range_token_bounds(self.value, self.cursor_position)
        token = self.value[start:end].strip()

        def on_result(result: str | None) -> None:
            if result is None:
                return
            new_value = self.value[:start] + result + self.value[end:]
            self.value = new_value
            self.cursor_position = start + len(result)

        self.app.push_screen(DatePickerScreen(token or None), on_result)
