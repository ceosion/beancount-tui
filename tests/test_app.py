"""End-to-end smoke tests driving the Textual app."""

from beancount_tui.app import BeancountTUI
from beancount_tui.ledger import Ledger
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
