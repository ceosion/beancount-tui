"""Visual-regression tests: one snapshot per top-level screen and modal.

These use `pytest-textual-snapshot`'s `snap_compare` fixture, which renders an
app (optionally after some key presses / a `run_before` interaction) to an
SVG and compares it against a committed baseline under
`tests/__snapshots__/test_snapshots/`.

After an intentional UI change, regenerate the baselines with:

    uv run pytest --snapshot-update

then review the diffs (e.g. via `git diff`) before committing.

Determinism notes:
- The ledger is opened via the fixed relative path `examples/example.beancount`
  (the same path used in CLAUDE.md's example invocation), not the tmp_path-based
  `ledger_path` fixture, so the header/subtitle text is identical on every
  machine and in CI. None of these tests submit a form, so the checked-in
  ledger is never mutated.
- `datetime.date.today()` is frozen for the duration of each test (via the
  autouse `_fixed_today` fixture below), because the "new transaction" and
  "new directive" forms default their date field to today's date.
- `Ledger.files` is patched in the ledger-info test to avoid embedding an
  environment-specific absolute path (that property always resolves to an
  absolute path, unlike `Ledger.path`).
"""

from __future__ import annotations

import datetime
from pathlib import Path

import pytest
from textual.widgets import OptionList

from beancount_tui.app import BeancountTUI
from beancount_tui.ledger import Ledger
from beancount_tui.widgets.transaction_table import TransactionTable

# Relative to the repo root (matching `uv run beancount-tui
# examples/example.beancount` from CLAUDE.md), so the rendered path text is
# stable across machines. Read-only: these tests never save a form.
LEDGER = "examples/example.beancount"


class _FixedDate(datetime.date):
    """A `datetime.date` whose `.today()` always returns a fixed date."""

    @classmethod
    def today(cls) -> "_FixedDate":
        return cls(2026, 1, 15)


@pytest.fixture(autouse=True)
def _fixed_today(monkeypatch: pytest.MonkeyPatch) -> None:
    """Freeze "today" for new-transaction/new-directive form defaults."""
    monkeypatch.setattr(datetime, "date", _FixedDate)


def test_main_screen(snap_compare) -> None:
    app = BeancountTUI(LEDGER)
    assert snap_compare(app)


def test_transaction_form(snap_compare) -> None:
    app = BeancountTUI(LEDGER)
    assert snap_compare(app, press=["n"])


def test_directive_type_picker(snap_compare) -> None:
    app = BeancountTUI(LEDGER)
    assert snap_compare(app, press=["a"])


async def _open_note_directive_form(pilot) -> None:
    await pilot.press("a")
    await pilot.pause()
    picker = pilot.app.screen
    option_list = picker.query_one(OptionList)
    option_list.highlighted = option_list.get_option_index("note")
    await pilot.press("enter")
    await pilot.pause()


def test_directive_form(snap_compare) -> None:
    app = BeancountTUI(LEDGER)
    assert snap_compare(app, run_before=_open_note_directive_form)


async def _select_first_row(pilot) -> None:
    pilot.app.query_one(TransactionTable).move_cursor(row=0)
    await pilot.pause()


def test_confirm_dialog(snap_compare) -> None:
    app = BeancountTUI(LEDGER)
    assert snap_compare(app, run_before=_select_first_row, press=["d"])


def test_income_statement_screen(snap_compare) -> None:
    app = BeancountTUI(LEDGER)
    assert snap_compare(app, press=["i"])


def test_ledger_info_screen(snap_compare, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        Ledger, "files", property(lambda self: [Path("examples/example.beancount")])
    )
    app = BeancountTUI(LEDGER)
    assert snap_compare(app, press=["L"])
