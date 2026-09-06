"""End-to-end smoke tests driving the Textual app."""

import datetime

from beancount.core import data
from textual.widgets import OptionList, Select

from beancount_tui.app import BeancountTUI
from beancount_tui.editor import append_entry
from beancount_tui.ledger import Ledger
from beancount_tui.widgets.account_tree import AccountTree
from beancount_tui.widgets.confirm_dialog import ConfirmDialog
from beancount_tui.widgets.directive_form import DirectiveForm
from beancount_tui.widgets.directive_type_picker import DirectiveTypePicker
from beancount_tui.widgets.postings_area import PostingsArea
from beancount_tui.widgets.filter_bar import FilterBar
from beancount_tui.widgets.income_statement import IncomeStatementScreen
from beancount_tui.widgets.ledger_info import LedgerInfoScreen
from beancount_tui.widgets.transaction_form import TransactionForm
from beancount_tui.widgets.transaction_table import TransactionTable, _entry_row
from beancount_tui.widgets.trial_balance import TrialBalanceScreen


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


async def test_account_tree_rolls_up_child_balances(ledger_path):
    app = BeancountTUI(ledger_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        tree = app.query_one(AccountTree)
        food = _find_node(tree.root, "Expenses:Food")
        assert food is not None
        # 87.35 groceries + 64.20 restaurant, none posted to Expenses:Food itself.
        assert "151.55 USD" in tree._amounts[food.id]


def _find_node(node, account):
    if node.data == account:
        return node
    for child in node.children:
        found = _find_node(child, account)
        if found is not None:
            return found
    return None
