"""End-to-end smoke tests driving the Textual app."""

from beancount_tui.app import BeancountTUI
from beancount_tui.editor import append_transaction
from beancount_tui.ledger import Ledger
from beancount_tui.widgets.account_tree import AccountTree
from beancount_tui.widgets.confirm_dialog import ConfirmDialog
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
