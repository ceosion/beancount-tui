"""End-to-end smoke tests driving the Textual app."""

import datetime
from pathlib import Path

from beancount.core import data
from textual.widgets import Checkbox, DataTable, OptionList, Select

from beancount_tui.app import BeancountTUI, UndoManager
from beancount_tui.editor import append_entry
from beancount_tui.ledger import Ledger
from beancount_tui.widgets.account_tree import AccountTree
from beancount_tui.widgets.balance_sheet import BalanceSheetScreen
from beancount_tui.widgets.confirm_dialog import ConfirmDialog
from beancount_tui.widgets.directive_form import DirectiveForm
from beancount_tui.widgets.directive_type_picker import DirectiveTypePicker
from beancount_tui.widgets.import_form import ImportForm
from beancount_tui.widgets.import_review import ImportReviewScreen
from beancount_tui.widgets.postings_area import PostingsArea
from beancount_tui.widgets.filter_bar import FilterBar
from beancount_tui.widgets.help_screen import HelpScreen
from beancount_tui.widgets.holdings import HoldingsScreen
from beancount_tui.widgets.income_statement import IncomeStatementScreen
from beancount_tui.widgets.ledger_info import LedgerInfoScreen
from beancount_tui.widgets.query_runner import QueryRunnerScreen
from beancount_tui.widgets.register import RegisterScreen
from beancount_tui.widgets.transaction_form import TransactionForm
from beancount_tui.widgets.transaction_table import TransactionTable, _entry_row
from beancount_tui.widgets.trial_balance import TrialBalanceScreen

FIXTURE_CSV = Path(__file__).parent / "fixtures" / "sample_import.csv"


async def _pick_directive_type(pilot, keyword: str) -> None:
    picker = pilot.app.screen
    assert isinstance(picker, DirectiveTypePicker)
    option_list = picker.query_one(OptionList)
    option_list.highlighted = option_list.get_option_index(keyword)
    await pilot.press("enter")
    await pilot.pause()


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
    append_entry(
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


async def test_new_transaction_with_tags_links_via_form(ledger_path):
    app = BeancountTUI(ledger_path)
    async with app.run_test() as pilot:
        await pilot.press("n")
        await pilot.pause()
        form = app.screen
        assert isinstance(form, TransactionForm)

        form.query_one("#payee").value = "Corner Cafe"
        form.query_one("#narration").value = "Coffee"
        form.query_one("#tags_links").value = "#vacation ^receipt-123"
        form.query_one("#postings").text = (
            "Expenses:Food:Restaurant  4.50 USD\nAssets:Checking"
        )
        await pilot.pause()
        form._save()
        await pilot.pause()

    ledger = Ledger.load(ledger_path)
    assert not ledger.errors
    txn = ledger.transactions[-1]
    assert txn.narration == "Coffee"
    assert txn.tags == frozenset({"vacation"})
    assert txn.links == frozenset({"receipt-123"})


async def test_edit_transaction_tags_links_via_form(ledger_path):
    append_entry(
        ledger_path,
        '2026-01-16 * "Corner Cafe" "Coffee" #vacation ^receipt-123\n'
        "  Expenses:Food:Restaurant  4.50 USD\n"
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
        assert form.query_one("#tags_links").value == "#vacation ^receipt-123"

        form.query_one("#tags_links").value = "#work"
        form._save()
        await pilot.pause()

    ledger = Ledger.load(ledger_path)
    assert not ledger.errors
    txn = ledger.transactions[-1]
    assert txn.tags == frozenset({"work"})
    assert txn.links == frozenset()


async def test_filter_by_tag(ledger_path):
    append_entry(
        ledger_path,
        '2026-01-16 * "Corner Cafe" "Coffee" #vacation\n'
        "  Expenses:Food:Restaurant  4.50 USD\n"
        "  Assets:Checking\n",
    )
    app = BeancountTUI(ledger_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("/")
        await pilot.press(*"vacation")
        await pilot.pause()
        table = app.query_one(TransactionTable)
        assert table.row_count == 1
        assert table.shown[0].payee == "Corner Cafe"


def test_entry_row_shows_tags_and_links():
    txn = data.Transaction(
        meta={},
        date=datetime.date(2026, 1, 16),
        flag="*",
        payee="Corner Cafe",
        narration="Coffee",
        tags=frozenset({"vacation"}),
        links=frozenset({"receipt-123"}),
        postings=[],
    )
    row = _entry_row(txn)
    assert row[3] == "Coffee #vacation ^receipt-123"


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


async def test_filter_by_metadata_value(ledger_path):
    append_entry(
        ledger_path,
        '2026-02-01 * "Widget Co" "Gadget purchase"\n'
        '  invoice-ref: "zephyrinvoice"\n'
        "  Assets:Checking  -15.00 USD\n"
        "  Expenses:Food:Groceries  15.00 USD\n",
    )
    app = BeancountTUI(ledger_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("/")
        await pilot.pause()
        await pilot.press(*"zephyrinvoice")
        await pilot.pause()
        table = app.query_one(TransactionTable)
        assert table.row_count == 1
        assert table.shown[0].payee == "Widget Co"
        # The narration cell surfaces a marker for the extra metadata.
        row = _entry_row(table.shown[0])
        assert row[3].endswith("+")


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


async def test_add_directive_type_picker_lists_types(ledger_path):
    app = BeancountTUI(ledger_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()
        picker = app.screen
        assert isinstance(picker, DirectiveTypePicker)
        option_list = picker.query_one(OptionList)
        ids = {option_list.get_option_at_index(i).id for i in range(option_list.option_count)}
        assert ids == {
            "open", "close", "balance", "pad", "note", "price", "event", "custom", "query",
            "document", "commodity",
        }

        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, DirectiveTypePicker)


async def test_add_open_directive(ledger_path):
    app = BeancountTUI(ledger_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()
        await _pick_directive_type(pilot, "open")

        form = app.screen
        assert isinstance(form, DirectiveForm)
        assert "open Assets:FIXME" in form.query_one("#text").text

        form.query_one("#text").text = "2026-09-06 open Assets:NewAccount  USD"
        form._save()
        await pilot.pause()

    ledger = Ledger.load(ledger_path)
    assert not ledger.errors
    opens = [e for e in ledger.entries if isinstance(e, data.Open)]
    assert any(o.account == "Assets:NewAccount" for o in opens)


async def test_add_close_directive(ledger_path):
    app = BeancountTUI(ledger_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()
        await _pick_directive_type(pilot, "close")

        form = app.screen
        assert isinstance(form, DirectiveForm)
        form.query_one("#text").text = "2026-09-06 close Assets:Savings"
        form._save()
        await pilot.pause()

    ledger = Ledger.load(ledger_path)
    assert not ledger.errors
    closes = [e for e in ledger.entries if isinstance(e, data.Close)]
    assert any(c.account == "Assets:Savings" for c in closes)


async def test_add_balance_directive(ledger_path):
    app = BeancountTUI(ledger_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()
        await _pick_directive_type(pilot, "balance")

        form = app.screen
        assert isinstance(form, DirectiveForm)
        assert "balance Assets:FIXME" in form.query_one("#text").text

        # Assets:Checking's balance after the example ledger's transactions.
        form.query_one("#text").text = "2026-09-06 balance Assets:Checking  4098.45 USD"
        form._save()
        await pilot.pause()

    ledger = Ledger.load(ledger_path)
    assert not ledger.errors
    balances = [e for e in ledger.entries if isinstance(e, data.Balance)]
    assert any(
        b.account == "Assets:Checking" and str(b.amount.number) == "4098.45"
        for b in balances
    )


async def test_balance_directive_helper_requires_selected_account(ledger_path):
    app = BeancountTUI(ledger_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.selected_account is None
        await pilot.press("B")
        await pilot.pause()
        assert not isinstance(app.screen, DirectiveForm)


async def test_balance_directive_helper_skips_type_picker(ledger_path):
    app = BeancountTUI(ledger_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.selected_account = "Assets:Checking"
        await pilot.press("B")
        await pilot.pause()

        form = app.screen
        assert isinstance(form, DirectiveForm)
        today = datetime.date.today().isoformat()
        # Pre-filled with today's date and Assets:Checking's actual realized
        # balance (same figure asserted in test_add_balance_directive above),
        # not a stale/placeholder value.
        assert form.query_one("#text").text == (
            f"{today} balance Assets:Checking  4098.45 USD"
        )

        form._save()
        await pilot.pause()

    ledger = Ledger.load(ledger_path)
    assert not ledger.errors
    balances = [e for e in ledger.entries if isinstance(e, data.Balance)]
    assert any(
        b.account == "Assets:Checking" and str(b.amount.number) == "4098.45"
        for b in balances
    )


async def test_balance_directive_helper_multi_currency(ledger_path):
    # A wallet account (no currency restriction on its `open`) holding two
    # currencies: the helper should produce one balance directive per
    # currency, in sequence.
    append_entry(
        ledger_path,
        "2026-01-01 open Assets:Wallet\n"
        "2026-01-01 open Equity:Wallet-Seed\n",
    )
    append_entry(
        ledger_path,
        '2026-01-20 * "Wallet seed" "Euros"\n'
        "  Assets:Wallet  50.00 EUR\n"
        "  Equity:Wallet-Seed\n"
        "\n"
        '2026-01-20 * "Wallet seed" "Dollars"\n'
        "  Assets:Wallet  -50.00 USD\n"
        "  Equity:Wallet-Seed\n",
    )
    app = BeancountTUI(ledger_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.selected_account = "Assets:Wallet"
        await pilot.press("B")
        await pilot.pause()

        today = datetime.date.today().isoformat()
        first_form = app.screen
        assert isinstance(first_form, DirectiveForm)
        assert first_form.query_one("#text").text == (
            f"{today} balance Assets:Wallet  50.00 EUR"
        )
        first_form._save()
        await pilot.pause()

        # One directive per currency: a second form for the other currency
        # opens automatically after the first is saved.
        second_form = app.screen
        assert isinstance(second_form, DirectiveForm)
        assert second_form.query_one("#text").text == (
            f"{today} balance Assets:Wallet  -50.00 USD"
        )
        second_form._save()
        await pilot.pause()

        assert not isinstance(app.screen, DirectiveForm)

    ledger = Ledger.load(ledger_path)
    assert not ledger.errors
    balances = [
        e
        for e in ledger.entries
        if isinstance(e, data.Balance) and e.account == "Assets:Wallet"
    ]
    assert any(str(b.amount.number) == "50.00" and b.amount.currency == "EUR" for b in balances)
    assert any(str(b.amount.number) == "-50.00" and b.amount.currency == "USD" for b in balances)


async def test_add_pad_directive(ledger_path):
    app = BeancountTUI(ledger_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()
        await _pick_directive_type(pilot, "pad")

        form = app.screen
        assert isinstance(form, DirectiveForm)
        assert "pad Assets:FIXME Equity:Opening-Balances" in form.query_one("#text").text

        form.query_one("#text").text = (
            "2026-09-06 pad Assets:Savings Equity:Opening-Balances"
        )
        form._save()
        await pilot.pause()

    ledger = Ledger.load(ledger_path)
    pads = [e for e in ledger.entries if isinstance(e, data.Pad)]
    assert any(
        p.account == "Assets:Savings" and p.source_account == "Equity:Opening-Balances"
        for p in pads
    )


async def test_add_note_directive(ledger_path):
    app = BeancountTUI(ledger_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()
        await _pick_directive_type(pilot, "note")

        form = app.screen
        assert isinstance(form, DirectiveForm)
        form.query_one("#text").text = (
            '2026-09-06 note Assets:Checking "Reviewed year to date"'
        )
        form._save()
        await pilot.pause()

    ledger = Ledger.load(ledger_path)
    assert not ledger.errors
    notes = [e for e in ledger.entries if isinstance(e, data.Note)]
    assert any(n.comment == "Reviewed year to date" for n in notes)


async def test_add_price_directive(ledger_path):
    app = BeancountTUI(ledger_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()
        await _pick_directive_type(pilot, "price")

        form = app.screen
        assert isinstance(form, DirectiveForm)
        assert "price FIXME" in form.query_one("#text").text

        form.query_one("#text").text = "2026-09-06 price HOOL  100.00 USD"
        form._save()
        await pilot.pause()

    ledger = Ledger.load(ledger_path)
    assert not ledger.errors
    prices = [e for e in ledger.entries if isinstance(e, data.Price)]
    assert any(
        p.currency == "HOOL" and str(p.amount.number) == "100.00" and p.amount.currency == "USD"
        for p in prices
    )


async def test_price_directive_displayed_in_table(ledger_path):
    append_entry(ledger_path, "2026-09-06 price HOOL  100.00 USD")
    app = BeancountTUI(ledger_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("t")
        await pilot.pause()
        table = app.query_one(TransactionTable)
        row_index = next(
            i for i, e in enumerate(table.shown) if isinstance(e, data.Price)
        )
        row = table.get_row_at(row_index)
        assert tuple(row) == ("2026-09-06", "price", "", "HOOL", "100.00 USD")


async def test_add_event_directive(ledger_path):
    app = BeancountTUI(ledger_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()
        await _pick_directive_type(pilot, "event")

        form = app.screen
        assert isinstance(form, DirectiveForm)
        assert 'event "location" "FIXME"' in form.query_one("#text").text

        form.query_one("#text").text = '2026-09-06 event "location" "Paris"'
        form._save()
        await pilot.pause()

        await pilot.press("t")
        await pilot.pause()
        table = app.query_one(TransactionTable)
        event_row = next(i for i, e in enumerate(table.shown) if isinstance(e, data.Event))
        row = table.get_row_at(event_row)
        assert row[1] == "event"
        assert row[3] == '"location": "Paris"'

    ledger = Ledger.load(ledger_path)
    assert not ledger.errors
    events = [e for e in ledger.entries if isinstance(e, data.Event)]
    assert any(e.type == "location" and e.description == "Paris" for e in events)


async def test_add_custom_directive(ledger_path):
    app = BeancountTUI(ledger_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()
        await _pick_directive_type(pilot, "custom")

        form = app.screen
        assert isinstance(form, DirectiveForm)
        assert 'custom "budget" "FIXME"' in form.query_one("#text").text

        form.query_one("#text").text = (
            '2026-09-06 custom "budget" "Groceries" 500.00 USD'
        )
        form._save()
        await pilot.pause()

        await pilot.press("t")
        await pilot.pause()
        table = app.query_one(TransactionTable)
        row = next(e for e in table.shown if isinstance(e, data.Custom))
        assert _entry_row(row) == (
            "2026-09-06",
            "custom",
            "",
            'budget: Groceries, 500.00 USD',
            "",
        )

    ledger = Ledger.load(ledger_path)
    assert not ledger.errors
    customs = [e for e in ledger.entries if isinstance(e, data.Custom)]
    assert any(
        c.type == "budget"
        and c.values[0].value == "Groceries"
        and str(c.values[1].value) == "500.00 USD"
        for c in customs
    )


async def test_query_directive_display(ledger_path):
    long_query_text = "SELECT account, sum(position) GROUP BY account ORDER BY account"
    append_entry(ledger_path, f'2026-09-06 query "cash" "{long_query_text}"')

    app = BeancountTUI(ledger_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("t")
        await pilot.pause()
        table = app.query_one(TransactionTable)
        query_row = next(
            i for i, e in enumerate(table.shown) if isinstance(e, data.Query)
        )
        row = table.get_row_at(query_row)
        assert row[1] == "query"
        assert row[3] == f"cash: {long_query_text[:40]}..."


async def test_add_query_directive(ledger_path):
    app = BeancountTUI(ledger_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()
        await _pick_directive_type(pilot, "query")

        form = app.screen
        assert isinstance(form, DirectiveForm)
        assert 'query "FIXME"' in form.query_one("#text").text

        form.query_one("#text").text = (
            '2026-09-06 query "cash" "SELECT account, sum(position) GROUP BY account"'
        )
        form._save()
        await pilot.pause()

    ledger = Ledger.load(ledger_path)
    assert not ledger.errors
    queries = [e for e in ledger.entries if isinstance(e, data.Query)]
    assert any(
        q.name == "cash" and q.query_string == "SELECT account, sum(position) GROUP BY account"
        for q in queries
    )


async def test_add_directive_into_included_file(multi_ledger_path):
    food = (multi_ledger_path.parent / "food.beancount").resolve()
    app = BeancountTUI(multi_ledger_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()
        await _pick_directive_type(pilot, "note")

        form = app.screen
        assert isinstance(form, DirectiveForm)
        form.query_one("#text").text = (
            '2026-01-06 note Expenses:Food:Groceries "Filed receipt"'
        )
        form.query_one("#target-file", Select).value = str(food)
        await pilot.pause()
        form._save()
        await pilot.pause()

    assert "Filed receipt" in food.read_text()
    assert "Filed receipt" not in multi_ledger_path.read_text()
    assert not Ledger.load(multi_ledger_path).errors


def test_document_directive_row_flags_missing_file(tmp_path):
    from beancount_tui.widgets.transaction_table import _entry_row

    existing = tmp_path / "receipt.pdf"
    existing.write_text("dummy", encoding="utf-8")
    missing = tmp_path / "missing.pdf"
    meta = {"filename": str(tmp_path / "ledger.beancount"), "lineno": 1}

    present_entry = data.Document(
        meta=meta,
        date=datetime.date(2026, 1, 20),
        account="Assets:Checking",
        filename=str(existing),
        tags=frozenset(),
        links=frozenset(),
    )
    missing_entry = data.Document(
        meta=meta,
        date=datetime.date(2026, 1, 20),
        account="Assets:Checking",
        filename=str(missing),
        tags=frozenset(),
        links=frozenset(),
    )

    date, keyword, payee, summary, amount = _entry_row(present_entry)
    assert date == "2026-01-20"
    assert keyword == "document"
    assert payee == ""
    assert amount == ""
    assert summary == f"Assets:Checking: {existing}"

    _, _, _, missing_summary, _ = _entry_row(missing_entry)
    assert missing_summary == f"! Assets:Checking: {missing}"


async def test_add_document_directive(ledger_path):
    receipt = ledger_path.parent / "receipt.pdf"
    receipt.write_text("dummy", encoding="utf-8")
    app = BeancountTUI(ledger_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()
        await _pick_directive_type(pilot, "document")

        form = app.screen
        assert isinstance(form, DirectiveForm)
        assert 'document Assets:FIXME "path/to/file.pdf"' in form.query_one("#text").text

        form.query_one("#text").text = f'2026-09-06 document Assets:Checking "{receipt}"'
        form._save()
        await pilot.pause()

    ledger = Ledger.load(ledger_path)
    assert not ledger.errors
    documents = [e for e in ledger.entries if isinstance(e, data.Document)]
    assert any(d.account == "Assets:Checking" and d.filename == str(receipt) for d in documents)


async def test_add_commodity_directive(ledger_path):
    app = BeancountTUI(ledger_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()
        await _pick_directive_type(pilot, "commodity")

        form = app.screen
        assert isinstance(form, DirectiveForm)
        assert "commodity HOOL" in form.query_one("#text").text

        form.query_one("#text").text = (
            '2026-09-06 commodity HOOL\n  name: "Alphabet Inc"'
        )
        form._save()
        await pilot.pause()

    ledger = Ledger.load(ledger_path)
    assert not ledger.errors
    commodities = [e for e in ledger.entries if isinstance(e, data.Commodity)]
    assert any(
        c.currency == "HOOL" and c.meta.get("name") == "Alphabet Inc" for c in commodities
    )


async def test_commodity_directive_displayed_in_table(ledger_path):
    append_entry(ledger_path, "2026-09-06 commodity HOOL\n  name: \"Alphabet Inc\"")
    append_entry(ledger_path, "2026-09-06 commodity USD")
    app = BeancountTUI(ledger_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("t")
        await pilot.pause()
        table = app.query_one(TransactionTable)
        by_currency = {
            e.currency: i for i, e in enumerate(table.shown) if isinstance(e, data.Commodity)
        }

        hool_row = table.get_row_at(by_currency["HOOL"])
        assert tuple(hool_row) == ("2026-09-06", "commodity", "", "HOOL (Alphabet Inc)", "")

        usd_row = table.get_row_at(by_currency["USD"])
        assert tuple(usd_row) == ("2026-09-06", "commodity", "", "USD", "")


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


async def test_undo_restores_after_delete(ledger_path):
    original = ledger_path.read_text()
    app = BeancountTUI(ledger_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.query_one(TransactionTable).move_cursor(row=0)
        await pilot.press("d")
        await pilot.pause()
        app.screen.query_one("#confirm").press()
        await pilot.pause()
        assert app.query_one(TransactionTable).row_count == 5

        await pilot.press("u")
        await pilot.pause()
        assert app.query_one(TransactionTable).row_count == 6

    assert ledger_path.read_text() == original


async def test_undo_restores_after_add(ledger_path):
    original = ledger_path.read_text()
    app = BeancountTUI(ledger_path)
    async with app.run_test() as pilot:
        await pilot.press("n")
        await pilot.pause()
        form = app.screen
        form.query_one("#narration").value = "Soon undone"
        form.query_one("#postings").text = (
            "Expenses:Food:Groceries  1.00 USD\nAssets:Checking"
        )
        form._save()
        await pilot.pause()
        assert app.query_one(TransactionTable).row_count == 7

        await pilot.press("u")
        await pilot.pause()
        assert app.query_one(TransactionTable).row_count == 6

        # A second undo has nothing to restore.
        await pilot.press("u")
        await pilot.pause()
        assert app.query_one(TransactionTable).row_count == 6

    assert ledger_path.read_text() == original


def test_undo_manager_caps_history_length():
    """Only the most recent `limit` writes are kept; older ones fall off."""
    manager = UndoManager(limit=3)
    for i in range(5):
        manager.record(Path(f"file{i}.beancount"), f"content-{i}")

    popped = []
    while manager.can_undo():
        popped.append(manager.pop_undo())

    # Most-recent-first (LIFO), and only the last 3 records survived.
    assert [content for _, content in popped] == [
        "content-4",
        "content-3",
        "content-2",
    ]


def test_undo_manager_redo_stack_also_capped():
    manager = UndoManager(limit=2)
    for i in range(4):
        manager.push_redo(Path(f"file{i}.beancount"), f"content-{i}")

    redone = []
    while manager.can_redo():
        redone.append(manager.pop_redo())
    assert [content for _, content in redone] == ["content-3", "content-2"]


async def test_undo_redo_across_three_sequential_edits(ledger_path):
    """undo-undo-redo-redo across 3+ sequential edits to the same file."""
    original = ledger_path.read_text()
    app = BeancountTUI(ledger_path)
    async with app.run_test() as pilot:
        snapshots = [original]
        for narration in ("Edit one", "Edit two", "Edit three"):
            await pilot.press("n")
            await pilot.pause()
            form = app.screen
            assert isinstance(form, TransactionForm)
            form.query_one("#narration").value = narration
            form.query_one("#postings").text = (
                "Expenses:Food:Groceries  1.00 USD\nAssets:Checking"
            )
            form._save()
            await pilot.pause()
            snapshots.append(ledger_path.read_text())

        assert app.query_one(TransactionTable).row_count == 9

        # Undo twice: back to after edit one.
        await pilot.press("u")
        await pilot.pause()
        assert app.query_one(TransactionTable).row_count == 8
        assert ledger_path.read_text() == snapshots[2]

        await pilot.press("u")
        await pilot.pause()
        assert app.query_one(TransactionTable).row_count == 7
        assert ledger_path.read_text() == snapshots[1]

        # A third undo restores the pristine original.
        await pilot.press("u")
        await pilot.pause()
        assert app.query_one(TransactionTable).row_count == 6
        assert ledger_path.read_text() == snapshots[0]

        # Redo twice: forward through edit one, then edit two.
        await pilot.press("U")
        await pilot.pause()
        assert app.query_one(TransactionTable).row_count == 7
        assert ledger_path.read_text() == snapshots[1]

        await pilot.press("U")
        await pilot.pause()
        assert app.query_one(TransactionTable).row_count == 8
        assert ledger_path.read_text() == snapshots[2]

        # A new write clears the redo stack: no more redoing forward past
        # this new edit, even though one logical redo (edit three) remained.
        await pilot.press("n")
        await pilot.pause()
        form = app.screen
        form.query_one("#narration").value = "Fresh edit after redo"
        form.query_one("#postings").text = (
            "Expenses:Food:Groceries  1.00 USD\nAssets:Checking"
        )
        form._save()
        await pilot.pause()
        assert app.query_one(TransactionTable).row_count == 9

        await pilot.press("U")
        await pilot.pause()
        # Nothing to redo: row count unchanged.
        assert app.query_one(TransactionTable).row_count == 9


async def test_undo_redo_across_two_files_independent(multi_ledger_path):
    """Undo/redo across writes to different files in a multi-file ledger."""
    food = (multi_ledger_path.parent / "food.beancount").resolve()
    main_original = multi_ledger_path.read_text()
    food_original = food.read_text()

    app = BeancountTUI(multi_ledger_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.query_one(TransactionTable).row_count == 2

        # Write to the main file (default target).
        await pilot.press("n")
        await pilot.pause()
        form = app.screen
        assert isinstance(form, TransactionForm)
        form.query_one("#payee").value = "Main Payee"
        form.query_one("#narration").value = "Main edit"
        form.query_one("#postings").text = (
            "Expenses:Food:Groceries  1.00 USD\nAssets:Checking"
        )
        form._save()
        await pilot.pause()
        main_after_edit = multi_ledger_path.read_text()
        assert "Main edit" in main_after_edit
        assert app.query_one(TransactionTable).row_count == 3

        # Write to the included food file.
        await pilot.press("n")
        await pilot.pause()
        form = app.screen
        assert isinstance(form, TransactionForm)
        form.query_one("#payee").value = "Food Payee"
        form.query_one("#narration").value = "Food edit"
        form.query_one("#postings").text = (
            "Expenses:Food:Groceries  2.00 USD\nAssets:Checking"
        )
        form.query_one("#target-file", Select).value = str(food)
        await pilot.pause()
        form._save()
        await pilot.pause()
        food_after_edit = food.read_text()
        assert "Food edit" in food_after_edit
        assert app.query_one(TransactionTable).row_count == 4

        # Undo restores the food file (most recent change) without touching
        # the main file's edit.
        await pilot.press("u")
        await pilot.pause()
        assert food.read_text() == food_original
        assert multi_ledger_path.read_text() == main_after_edit
        assert app.query_one(TransactionTable).row_count == 3

        # A second undo restores the main file, independently.
        await pilot.press("u")
        await pilot.pause()
        assert multi_ledger_path.read_text() == main_original
        assert food.read_text() == food_original
        assert app.query_one(TransactionTable).row_count == 2

        # Redo replays main, then food, each touching only its own file.
        await pilot.press("U")
        await pilot.pause()
        assert multi_ledger_path.read_text() == main_after_edit
        assert food.read_text() == food_original
        assert app.query_one(TransactionTable).row_count == 3

        await pilot.press("U")
        await pilot.pause()
        assert multi_ledger_path.read_text() == main_after_edit
        assert food.read_text() == food_after_edit
        assert app.query_one(TransactionTable).row_count == 4


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

        append_entry(ledger_path, EXTERNAL_TXN)
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

        append_entry(ledger_path, EXTERNAL_TXN)
        await pilot.pause(0.5)
        # The open form blocks the reload...
        assert app.query_one(TransactionTable).row_count == 6

        await pilot.press("escape")
        await pilot.pause(0.5)
        # ...and it happens once the form closes.
        assert app.query_one(TransactionTable).row_count == 7


async def test_income_statement_screen(ledger_path):
    from textual.widgets import DataTable, Input

    app = BeancountTUI(ledger_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("i")
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, IncomeStatementScreen)

        def cells(column):
            table = screen.query_one("#report", DataTable)
            return [str(table.get_row_at(i)[column]) for i in range(table.row_count)]

        assert any("Income:Salary" in c for c in cells(0))
        assert any("Expenses:Rent" in c for c in cells(0))
        assert "2,598.45 USD" in cells(1)  # net over all dates

        # Narrowing the period recomputes the report.
        screen.query_one("#period", Input).value = "2026-01-06..2026-01-10"
        await pilot.pause()
        assert "-1,537.35 USD" in cells(1)
        assert not any("Income:Salary" in c for c in cells(0))

        # An invalid period shows an error and keeps the last report.
        screen.query_one("#period", Input).value = "not-a-range"
        await pilot.pause()
        assert "-1,537.35 USD" in cells(1)

        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, IncomeStatementScreen)


async def test_trial_balance_screen(ledger_path):
    from textual.widgets import DataTable, Input

    app = BeancountTUI(ledger_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("b")
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, TrialBalanceScreen)

        def cells(column):
            table = screen.query_one("#report", DataTable)
            return [str(table.get_row_at(i)[column]) for i in range(table.row_count)]

        # As-of defaults to today, so every account with a nonzero balance
        # over the whole (Jan-2026-dated) example ledger appears.
        assert any("Assets:Checking" in c for c in cells(0))
        assert any("Income:Salary" in c for c in cells(0))
        assert "4,098.45 USD" in cells(1)

        # Narrowing the as-of date recomputes the report: only the opening
        # balance and salary deposit have posted by 2026-01-05.
        screen.query_one("#as-of", Input).value = "2026-01-05"
        await pilot.pause()
        assert "6,700.00 USD" in cells(1)
        assert not any("Expenses:Rent" in c for c in cells(0))

        # An invalid date shows an error and keeps the last report.
        screen.query_one("#as-of", Input).value = "not-a-date"
        await pilot.pause()
        assert "6,700.00 USD" in cells(1)

        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, TrialBalanceScreen)


async def test_register_screen(ledger_path):
    app = BeancountTUI(ledger_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.selected_account = "Assets:Checking"
        await pilot.press("g")
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, RegisterScreen)

        table = screen.query_one("#report", DataTable)
        rows = [
            tuple(str(cell) for cell in table.get_row_at(i)) for i in range(table.row_count)
        ]
        assert rows[0] == ("2026-01-01", "Opening balance", "2,500.00 USD", "2,500.00 USD")
        assert rows[-1] == (
            "2026-01-15",
            "Transfer to savings",
            "-1,000.00 USD",
            "4,098.45 USD",
        )

        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, RegisterScreen)


async def test_register_requires_selected_account(ledger_path):
    app = BeancountTUI(ledger_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.selected_account is None
        await pilot.press("g")
        await pilot.pause()
        assert not isinstance(app.screen, RegisterScreen)


async def test_balance_sheet_screen(ledger_path):
    from textual.widgets import DataTable, Input

    app = BeancountTUI(ledger_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("s")
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, BalanceSheetScreen)

        def cells(column):
            table = screen.query_one("#report", DataTable)
            return [str(table.get_row_at(i)[column]) for i in range(table.row_count)]

        # As-of defaults to today, so the whole (Jan-2026-dated) example
        # ledger is in scope.
        assert any("Assets:Checking" in c for c in cells(0))
        assert any("Equity:Opening-Balances" in c for c in cells(0))
        assert "4,098.45 USD" in cells(1)
        assert "5,098.45 USD" in cells(1)  # total assets
        assert "2,598.45 USD" in cells(1)  # implicit net-income line
        # total liabilities + equity (incl. net income) balances total assets
        assert "5,098.45 USD" in cells(1)

        # Narrowing the as-of date recomputes the report: only the opening
        # balance and salary deposit have posted by 2026-01-05.
        screen.query_one("#as-of", Input).value = "2026-01-05"
        await pilot.pause()
        assert "6,700.00 USD" in cells(1)
        assert "4,200.00 USD" in cells(1)  # net income through 2026-01-05

        # An invalid date shows an error and keeps the last report.
        screen.query_one("#as-of", Input).value = "not-a-date"
        await pilot.pause()
        assert "6,700.00 USD" in cells(1)

        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, BalanceSheetScreen)


async def test_holdings_screen(ledger_path):
    from textual.widgets import DataTable, Input

    append_entry(
        ledger_path,
        "2026-01-01 open Assets:Investments  HOOL\n\n"
        '2026-01-20 * "Buy stock"\n'
        "  Assets:Investments  10 HOOL {500.00 USD}\n"
        "  Assets:Checking\n\n"
        "2026-02-01 price HOOL  550.00 USD\n",
    )
    app = BeancountTUI(ledger_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("w")
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, HoldingsScreen)

        def cells(column):
            table = screen.query_one("#report", DataTable)
            return [str(table.get_row_at(i)[column]) for i in range(table.row_count)]

        # As-of defaults to today, so the price directive is in scope.
        assert any("HOOL" in c for c in cells(0))
        assert any("Assets:Investments" in c for c in cells(1))
        assert "5,000.00 USD" in cells(3)  # cost basis
        assert "5,500.00 USD" in cells(4)  # market value
        assert any("Net worth" in c for c in cells(0))
        assert "5,500.00 USD" in cells(4)

        # Before the price directive posted, the lot has no known market value.
        screen.query_one("#as-of", Input).value = "2026-01-20"
        await pilot.pause()
        assert any("no price available" in c for c in cells(4))

        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, HoldingsScreen)


async def test_ledger_info_screen(ledger_path):
    from textual.widgets import Static

    app = BeancountTUI(ledger_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("L")
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, LedgerInfoScreen)

        text = str(screen.query_one("#info", Static).render())

        # From examples/example.beancount's `option` lines.
        assert "Example Ledger" in text
        assert "USD" in text
        # Booking method and account-name roots always render, even though
        # this ledger never overrides them (defaults only).
        assert "STRICT" in text
        assert "Assets" in text
        assert "Expenses" in text
        # The full source-file list, top-level file included.
        assert str(app.ledger.path.resolve()) in text
        for file in app.ledger.files:
            assert str(file) in text

        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, LedgerInfoScreen)


async def test_help_screen(ledger_path):
    from textual.widgets import DataTable

    app = BeancountTUI(ledger_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("?")
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, HelpScreen)

        table = screen.query_one("#bindings", DataTable)
        rows = [
            (str(table.get_row_at(i)[0]), str(table.get_row_at(i)[1]))
            for i in range(table.row_count)
        ]
        for key, _action, description in BeancountTUI.BINDINGS:
            assert (key, description) in rows

        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, HelpScreen)


async def test_account_tree_rolls_up_child_balances(ledger_path):
    app = BeancountTUI(ledger_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        tree = app.query_one(AccountTree)
        food = _find_node(tree.root, "Expenses:Food")
        assert food is not None
        # 87.35 groceries + 64.20 restaurant, none posted to Expenses:Food itself.
        assert "151.55 USD" in tree._amounts[food.id]


async def test_account_tree_shows_converted_total_and_missing_price(ledger_path):
    # examples/example.beancount already sets operating_currency to USD.
    append_entry(
        ledger_path,
        "2026-01-01 open Assets:Brokerage  AAPL,USD\n\n"
        "2026-01-02 price AAPL 175.32 USD\n\n"
        '2026-01-20 * "Buy stock"\n'
        "  Assets:Brokerage  50 AAPL\n"
        "  Assets:Brokerage  100.00 USD\n"
        "  Assets:Checking  -8866.00 USD\n",
    )
    app = BeancountTUI(ledger_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        tree = app.query_one(AccountTree)
        brokerage = _find_node(tree.root, "Assets:Brokerage")
        assert brokerage is not None
        amounts = tree._amounts[brokerage.id]
        assert "50 AAPL" in amounts
        assert "100.00 USD" in amounts
        # 100.00 USD + 50 * 175.32 USD == 8,866.00 USD.
        assert "≈ 8,866.00 USD" in amounts


async def test_account_tree_no_converted_total_when_single_operating_currency(ledger_path):
    # Assets:Checking only ever holds USD, the ledger's own operating
    # currency, so there's nothing to convert and no note should appear.
    app = BeancountTUI(ledger_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        tree = app.query_one(AccountTree)
        checking = _find_node(tree.root, "Assets:Checking")
        assert checking is not None
        assert "≈" not in tree._amounts[checking.id]


def _find_node(node, account):
    if node.data == account:
        return node
    for child in node.children:
        found = _find_node(child, account)
        if found is not None:
            return found
    return None


async def test_import_csv_via_form(ledger_path):
    app = BeancountTUI(ledger_path)
    results = []
    async with app.run_test() as pilot:
        await pilot.pause()
        app.push_screen(ImportForm(), lambda candidates: results.append(candidates))
        await pilot.pause()
        form = app.screen
        assert isinstance(form, ImportForm)

        form.query_one("#path").value = str(FIXTURE_CSV)
        form._load_preview()
        await pilot.pause()

        preview = form.query_one("#preview", DataTable)
        assert preview.row_count == 5

        form.query_one("#col-date", Select).value = "Date"
        form.query_one("#col-amount", Select).value = "Amount"
        form.query_one("#col-payee", Select).value = "Merchant"
        form.query_one("#col-narration", Select).value = "Description"
        form.query_one("#account").value = "Assets:Checking"
        await pilot.pause()

        form._do_import()
        await pilot.pause()

        assert not isinstance(app.screen, ImportForm)

    assert len(results) == 1
    candidates = results[0]
    assert candidates is not None
    assert len(candidates) == 5
    assert candidates[0].payee == "Corner Cafe"
    assert candidates[0].narration == "Coffee and pastry"
    assert candidates[0].account == "Assets:Checking"
    assert sum(1 for c in candidates if c.error is not None) == 2

    # The malformed rows are reported, not dropped or fatal.
    bad_date = next(c for c in candidates if c.row_number == 3)
    assert bad_date.date is None
    assert bad_date.error is not None
    bad_amount = next(c for c in candidates if c.row_number == 4)
    assert bad_amount.amount is None
    assert bad_amount.error is not None

    # Nothing gets written to the ledger at this stage.
    ledger = Ledger.load(ledger_path)
    assert not ledger.errors
    assert len(ledger.transactions) == 6


async def test_import_csv_binding_opens_review_screen(ledger_path):
    app = BeancountTUI(ledger_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("m")
        await pilot.pause()
        form = app.screen
        assert isinstance(form, ImportForm)

        form.query_one("#path").value = str(FIXTURE_CSV)
        form._load_preview()
        await pilot.pause()

        form.query_one("#col-date", Select).value = "Date"
        form.query_one("#col-amount", Select).value = "Amount"
        form.query_one("#account").value = "Assets:Checking"
        await pilot.pause()

        form._do_import()
        await pilot.pause()

        assert not isinstance(app.screen, ImportForm)
        review = app.screen
        assert isinstance(review, ImportReviewScreen)
        assert len(review._rows) == 5

        # Confirming with nothing changed still leaves the review screen and
        # notifies with a count, exercising the full "m" -> review -> import path.
        review._do_import()
        await pilot.pause()
        assert not isinstance(app.screen, ImportReviewScreen)


def _import_review_setup_and_parse(form) -> None:
    form.query_one("#path").value = str(FIXTURE_CSV)
    form._load_preview()
    form.query_one("#col-date", Select).value = "Date"
    form.query_one("#col-amount", Select).value = "Amount"
    form.query_one("#col-payee", Select).value = "Merchant"
    form.query_one("#col-narration", Select).value = "Description"
    form.query_one("#account").value = "Assets:Checking"


async def test_import_review_partial_selection(ledger_path):
    """Uncheck one candidate before confirming: it's skipped, the rest are appended."""
    app = BeancountTUI(ledger_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("m")
        await pilot.pause()
        form = app.screen
        assert isinstance(form, ImportForm)
        _import_review_setup_and_parse(form)
        await pilot.pause()

        form._do_import()
        await pilot.pause()

        review = app.screen
        assert isinstance(review, ImportReviewScreen)
        assert len(review._rows) == 5

        # Rows 3/4 (bad date / bad amount) carry a parse error and default unchecked.
        # Row 1 (Green Grocer, 2026-01-06 -87.35 -> Assets:Checking) matches the
        # ledger's existing "Weekly groceries" entry and defaults unchecked as a
        # possible duplicate (IMP-03), with the reason visible on the checkbox label.
        assert review._rows[0].checked is True  # Corner Cafe
        assert review._rows[1].checked is False  # Green Grocer - possible duplicate
        assert review._rows[1].duplicate_reason is not None
        assert "duplicate" in review._rows[1].duplicate_reason
        assert "duplicate" in str(review.query_one("#check-1", Checkbox).label)
        assert review._rows[2].checked is False  # bad date row
        assert review._rows[3].checked is False  # bad amount row
        assert review._rows[4].checked is True  # Acme Corp paycheck

        # Deselect the Corner Cafe row: it should be skipped, not appended.
        review.query_one("#check-0", Checkbox).value = False
        await pilot.pause()
        assert review._rows[0].checked is False

        # Re-check Green Grocer anyway: the duplicate flag is a warning, not a
        # hard block, and the user can decide to import it after all.
        review.query_one("#check-1", Checkbox).value = True
        await pilot.pause()
        assert review._rows[1].checked is True

        review._do_import()
        await pilot.pause()

        assert not isinstance(app.screen, ImportReviewScreen)

    ledger = Ledger.load(ledger_path)
    # Started with 6 transactions; Green Grocer + Acme Corp paycheck get appended,
    # Corner Cafe (unchecked) and the two errored rows (default unchecked) do not.
    assert len(ledger.transactions) == 8
    narrations = {t.narration for t in ledger.transactions}
    assert "Weekly groceries" in narrations
    assert "Paycheck" in narrations
    assert "Coffee and pastry" not in narrations
    assert "Bad date row" not in narrations
    assert "Bad amount row" not in narrations


async def test_import_review_edit_before_import(ledger_path):
    """A candidate can be opened in TransactionForm and edited before import."""
    app = BeancountTUI(ledger_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("m")
        await pilot.pause()
        form = app.screen
        assert isinstance(form, ImportForm)
        _import_review_setup_and_parse(form)
        await pilot.pause()

        form._do_import()
        await pilot.pause()

        review = app.screen
        assert isinstance(review, ImportReviewScreen)

        # Edit the Corner Cafe row: replace the placeholder balancing account.
        review._open_edit(0)
        await pilot.pause()
        edit_form = app.screen
        assert isinstance(edit_form, TransactionForm)
        postings = edit_form.query_one("#postings", PostingsArea)
        assert "Expenses:FIXME" in postings.text
        postings.text = postings.text.replace("Expenses:FIXME", "Expenses:Food:Restaurant")
        edit_form._save()
        await pilot.pause()

        assert not isinstance(app.screen, TransactionForm)
        assert review._rows[0].edited is True
        assert "Expenses:Food:Restaurant" in review._rows[0].text
        assert review._rows[0].checked is True

        review._do_import()
        await pilot.pause()

        assert not isinstance(app.screen, ImportReviewScreen)

    ledger = Ledger.load(ledger_path)
    edited_txn = next(t for t in ledger.transactions if t.payee == "Corner Cafe")
    accounts = {p.account for p in edited_txn.postings}
    assert "Expenses:Food:Restaurant" in accounts
    assert "Expenses:FIXME" not in accounts


async def test_query_runner_screen_runs_typed_query(ledger_path):
    from textual.widgets import DataTable, Input, Static

    app = BeancountTUI(ledger_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("Q")
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, QueryRunnerScreen)

        query_input = screen.query_one("#query", Input)
        query_input.value = "SELECT account, sum(position) AS total GROUP BY account"
        await pilot.pause()
        query_input.focus()
        await pilot.press("enter")
        await pilot.pause()

        table = screen.query_one("#results", DataTable)
        assert len(table.columns) == 2
        rows = {
            table.get_row_at(i)[0]: table.get_row_at(i)[1] for i in range(table.row_count)
        }
        assert rows["Assets:Checking"] == "4,098.45 USD"

        error = screen.query_one("#error", Static)
        assert str(error.render()) == ""

        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, QueryRunnerScreen)


async def test_query_runner_screen_shows_inline_error_for_bad_query(ledger_path):
    from textual.widgets import Input, Static

    app = BeancountTUI(ledger_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("Q")
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, QueryRunnerScreen)

        query_input = screen.query_one("#query", Input)
        query_input.value = "SELEKT accountz"
        await pilot.pause()
        query_input.focus()
        await pilot.press("enter")
        await pilot.pause()

        error = screen.query_one("#error", Static)
        assert str(error.render()) != ""
        # The app is still alive and the modal is still open, i.e. no crash.
        assert isinstance(app.screen, QueryRunnerScreen)


async def test_query_runner_screen_saved_query_picker(ledger_path):
    from textual.widgets import DataTable, Select

    append_entry(
        ledger_path,
        '2026-01-01 query "cash" '
        '"SELECT account, sum(position) AS total GROUP BY account"\n',
    )
    app = BeancountTUI(ledger_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("Q")
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, QueryRunnerScreen)

        select = screen.query_one("#saved-query", Select)
        select.value = "SELECT account, sum(position) AS total GROUP BY account"
        await pilot.pause()

        table = screen.query_one("#results", DataTable)
        rows = {
            table.get_row_at(i)[0]: table.get_row_at(i)[1] for i in range(table.row_count)
        }
        assert rows["Assets:Checking"] == "4,098.45 USD"
