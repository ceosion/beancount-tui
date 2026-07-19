"""End-to-end smoke tests driving the Textual app."""

import datetime

from beancount.core import data
from textual.widgets import Select

from beancount_tui.app import BeancountTUI
from beancount_tui.editor import append_transaction
from beancount_tui.ledger import Ledger
from beancount_tui.widgets.account_tree import AccountTree
from beancount_tui.widgets.confirm_dialog import ConfirmDialog
from beancount_tui.widgets.directive_form import DirectiveForm
from beancount_tui.widgets.postings_area import PostingsArea
from beancount_tui.widgets.filter_bar import FilterBar
from beancount_tui.widgets.transaction_form import TransactionForm
from beancount_tui.widgets.transaction_table import TransactionTable


async def test_app_launches_and_shows_transactions(ledger_path):
    app = BeancountTUI(ledger_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one(TransactionTable)
        assert table.row_count == 6


async def test_new_transaction_via_form(ledger_path):
    app = BeancountTUI(ledger_path)
    async with app.run_test() as pilot:
        await pilot.press("n")
        await pilot.pause()
        form = app.screen
        assert isinstance(form, TransactionForm)

        form.query_one("#payee").value = "Corner Cafe"
        form.query_one("#narration").value = "Coffee"
        form.query_one("#postings").text = (
            "Expenses:Food:Restaurant  4.50 USD\nAssets:Checking"
        )
        await pilot.pause()
        form._save()
        await pilot.pause()

        table = app.query_one(TransactionTable)
        assert table.row_count == 7

    ledger = Ledger.load(ledger_path)
    assert not ledger.errors
    assert ledger.transactions[-1].payee == "Corner Cafe"


async def test_edit_transaction_via_form(ledger_path):
    app = BeancountTUI(ledger_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.query_one(TransactionTable).move_cursor(row=0)
        await pilot.press("e")
        await pilot.pause()
        form = app.screen
        assert isinstance(form, TransactionForm)
        assert form.query_one("#narration").value == "Opening balance"

        form.query_one("#narration").value = "Opening balance (edited)"
        form._save()
        await pilot.pause()

    ledger = Ledger.load(ledger_path)
    assert not ledger.errors
    assert ledger.transactions[0].narration == "Opening balance (edited)"


async def test_edit_preserves_pending_flag(ledger_path):
    append_transaction(
        ledger_path,
        '2026-01-16 ! "Pending Shop" "Awaiting confirmation"\n'
        "  Expenses:Food:Groceries  10.00 USD\n"
        "  Assets:Checking\n",
    )
    app = BeancountTUI(ledger_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one(TransactionTable)
        table.move_cursor(row=table.row_count - 1)
        await pilot.press("e")
        await pilot.pause()
        form = app.screen
        assert isinstance(form, TransactionForm)
        assert form.query_one("#flag").value == "!"

        form.query_one("#narration").value = "Awaiting confirmation (edited)"
        form._save()
        await pilot.pause()

    ledger = Ledger.load(ledger_path)
    assert not ledger.errors
    assert ledger.transactions[-1].flag == "!"
    assert ledger.transactions[-1].narration == "Awaiting confirmation (edited)"


async def test_delete_transaction_with_confirmation(ledger_path):
    app = BeancountTUI(ledger_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.query_one(TransactionTable).move_cursor(row=0)
        await pilot.press("d")
        await pilot.pause()
        dialog = app.screen
        assert isinstance(dialog, ConfirmDialog)

        dialog.query_one("#confirm").press()
        await pilot.pause()

        table = app.query_one(TransactionTable)
        assert table.row_count == 5

    ledger = Ledger.load(ledger_path)
    assert len(ledger.transactions) == 5
    assert all(t.narration != "Opening balance" for t in ledger.transactions)


async def test_delete_cancelled_keeps_transaction(ledger_path):
    app = BeancountTUI(ledger_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.query_one(TransactionTable).move_cursor(row=0)
        await pilot.press("d")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmDialog)
        await pilot.press("escape")
        await pilot.pause()
        assert app.query_one(TransactionTable).row_count == 6

    assert len(Ledger.load(ledger_path).transactions) == 6


async def test_single_file_form_has_no_file_picker(ledger_path):
    app = BeancountTUI(ledger_path)
    async with app.run_test() as pilot:
        await pilot.press("n")
        await pilot.pause()
        form = app.screen
        assert isinstance(form, TransactionForm)
        assert not form.query("#target-file")


async def test_new_transaction_into_included_file(multi_ledger_path):
    food = (multi_ledger_path.parent / "food.beancount").resolve()
    app = BeancountTUI(multi_ledger_path)
    async with app.run_test() as pilot:
        await pilot.press("n")
        await pilot.pause()
        form = app.screen
        assert isinstance(form, TransactionForm)

        form.query_one("#payee").value = "Corner Cafe"
        form.query_one("#narration").value = "Coffee"
        form.query_one("#postings").text = (
            "Expenses:Food:Groceries  4.50 USD\nAssets:Checking"
        )
        form.query_one("#target-file", Select).value = str(food)
        await pilot.pause()
        form._save()
        await pilot.pause()

        assert app.query_one(TransactionTable).row_count == 3

    assert "Corner Cafe" in food.read_text()
    ledger = Ledger.load(multi_ledger_path)
    assert not ledger.errors
    assert len(ledger.transactions) == 3


async def test_edit_transaction_in_included_file_writes_in_place(multi_ledger_path):
    food = (multi_ledger_path.parent / "food.beancount").resolve()
    app = BeancountTUI(multi_ledger_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        # Row 1 is the groceries transaction, which lives in food.beancount.
        app.query_one(TransactionTable).move_cursor(row=1)
        await pilot.press("e")
        await pilot.pause()
        form = app.screen
        assert isinstance(form, TransactionForm)
        assert form.query_one("#narration").value == "Weekly groceries"

        form.query_one("#narration").value = "Weekly groceries (edited)"
        form._save()
        await pilot.pause()

    assert "Weekly groceries (edited)" in food.read_text()
    assert "edited" not in multi_ledger_path.read_text()


async def test_filter_via_filter_bar(ledger_path):
    app = BeancountTUI(ledger_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("/")
        await pilot.pause()
        bar = app.query_one(FilterBar)
        assert bar.has_class("visible")
        assert bar.has_focus

        await pilot.press(*"grocer")
        await pilot.pause()
        table = app.query_one(TransactionTable)
        assert table.row_count == 1
        assert table.shown[0].payee == "Green Grocer"

        # Escape drops the filter and hides the bar.
        await pilot.press("escape")
        await pilot.pause()
        assert table.row_count == 6
        assert not bar.has_class("visible")


async def test_filter_combines_with_account_selection(ledger_path):
    app = BeancountTUI(ledger_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.selected_account = "Expenses:Food"
        await pilot.press("/")
        await pilot.press(*"dinner")
        await pilot.pause()
        table = app.query_one(TransactionTable)
        assert table.row_count == 1
        assert table.shown[0].payee == "Nice Restaurant"


async def test_account_completion_in_postings(ledger_path):
    app = BeancountTUI(ledger_path)
    async with app.run_test() as pilot:
        await pilot.press("n")
        await pilot.pause()
        area = app.screen.query_one("#postings", PostingsArea)
        area.focus()

        # Ambiguous prefix extends to the longest common prefix.
        area.text = "Exp"
        area.cursor_location = (0, 3)
        await pilot.press("tab")
        assert area.text == "Expenses:"

        # A unique match completes fully, ready for the amount.
        area.text = "Expenses:R"
        area.cursor_location = (0, 10)
        await pilot.press("tab")
        assert area.text == "Expenses:Rent  "

        # Completion also works past the first line.
        area.text = "Expenses:Rent  10 USD\nAssets:S"
        area.cursor_location = (1, 8)
        await pilot.press("tab")
        assert area.text.splitlines()[1] == "Assets:Savings  "

        # Outside the account position, the text is left alone.
        area.text = "Expenses:Rent  14"
        area.cursor_location = (0, 17)
        await pilot.press("tab")
        assert area.text == "Expenses:Rent  14"


async def test_duplicate_transaction(ledger_path):
    app = BeancountTUI(ledger_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one(TransactionTable)
        rent_row = next(i for i, e in enumerate(table.shown) if e.payee == "Landlord")
        table.move_cursor(row=rent_row)
        await pilot.press("c")
        await pilot.pause()
        form = app.screen
        assert isinstance(form, TransactionForm)
        assert form.query_one("#date").value == datetime.date.today().isoformat()
        assert form.query_one("#payee").value == "Landlord"
        assert "Expenses:Rent" in form.query_one("#postings").text

        form._save()
        await pilot.pause()
        assert table.row_count == 7

    ledger = Ledger.load(ledger_path)
    assert not ledger.errors
    copy = ledger.transactions[-1]
    assert copy.payee == "Landlord"
    assert copy.date == datetime.date.today()
    assert str(copy.postings[0].units.number) == "1450.00"


async def test_duplicate_requires_transaction(ledger_path):
    app = BeancountTUI(ledger_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("t")
        await pilot.pause()
        table = app.query_one(TransactionTable)
        note_row = next(
            i for i, e in enumerate(table.shown) if isinstance(e, data.Note)
        )
        table.move_cursor(row=note_row)
        await pilot.press("c")
        await pilot.pause()
        assert not isinstance(app.screen, TransactionForm)


async def test_toggle_directives(ledger_path):
    app = BeancountTUI(ledger_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one(TransactionTable)
        assert table.row_count == 6
        await pilot.press("t")
        await pilot.pause()
        # 6 transactions + 7 opens + 1 balance + 1 note
        assert table.row_count == 15
        await pilot.press("t")
        await pilot.pause()
        assert table.row_count == 6


async def test_edit_note_directive(ledger_path):
    app = BeancountTUI(ledger_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("t")
        await pilot.pause()
        table = app.query_one(TransactionTable)
        note_row = next(
            i for i, e in enumerate(table.shown) if isinstance(e, data.Note)
        )
        table.move_cursor(row=note_row)
        await pilot.press("e")
        await pilot.pause()
        form = app.screen
        assert isinstance(form, DirectiveForm)
        assert "note" in form.query_one("#text").text

        form.query_one("#text").text = (
            '2026-01-16 note Assets:Checking "Reconciled (edited)"'
        )
        form._save()
        await pilot.pause()

    assert "Reconciled (edited)" in ledger_path.read_text()
    assert not Ledger.load(ledger_path).errors


async def test_delete_directive_with_confirmation(ledger_path):
    app = BeancountTUI(ledger_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("t")
        await pilot.pause()
        table = app.query_one(TransactionTable)
        note_row = next(
            i for i, e in enumerate(table.shown) if isinstance(e, data.Note)
        )
        table.move_cursor(row=note_row)
        await pilot.press("d")
        await pilot.pause()
        dialog = app.screen
        assert isinstance(dialog, ConfirmDialog)
        dialog.query_one("#confirm").press()
        await pilot.pause()

    assert "Reconciled" not in ledger_path.read_text()
    assert not Ledger.load(ledger_path).errors


EXTERNAL_TXN = (
    '2026-01-21 * "External Editor" "Written outside the app"\n'
    "  Expenses:Food:Groceries  5.00 USD\n"
    "  Assets:Checking\n"
)


async def test_auto_reload_on_external_change(ledger_path):
    app = BeancountTUI(ledger_path, watch_interval=0.05)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.query_one(TransactionTable).row_count == 6

        append_transaction(ledger_path, EXTERNAL_TXN)
        await pilot.pause(0.5)

        table = app.query_one(TransactionTable)
        assert table.row_count == 7
        assert table.shown[-1].payee == "External Editor"


async def test_no_auto_reload_while_modal_open(ledger_path):
    app = BeancountTUI(ledger_path, watch_interval=0.05)
    async with app.run_test() as pilot:
        await pilot.press("n")
        await pilot.pause()
        assert isinstance(app.screen, TransactionForm)

        append_transaction(ledger_path, EXTERNAL_TXN)
        await pilot.pause(0.5)
        # The open form blocks the reload...
        assert app.query_one(TransactionTable).row_count == 6

        await pilot.press("escape")
        await pilot.pause(0.5)
        # ...and it happens once the form closes.
        assert app.query_one(TransactionTable).row_count == 7


async def test_account_tree_rolls_up_child_balances(ledger_path):
    app = BeancountTUI(ledger_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        tree = app.query_one(AccountTree)
        food = _find_node(tree.root, "Expenses:Food")
        assert food is not None
        # 87.35 groceries + 64.20 restaurant, none posted to Expenses:Food itself.
        assert "151.55 USD" in str(food.label)


def _find_node(node, account):
    if node.data == account:
        return node
    for child in node.children:
        found = _find_node(child, account)
        if found is not None:
            return found
    return None
