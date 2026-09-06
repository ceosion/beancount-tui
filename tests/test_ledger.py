import datetime
from decimal import Decimal

from beancount_tui.editor import append_entry
from beancount_tui.ledger import (
    Ledger,
    filter_transactions,
    format_inventory,
    parse_date_range,
    resolve_date_preset,
    transaction_amount,
)


def test_load_example(ledger_path):
    ledger = Ledger.load(ledger_path)
    assert not ledger.errors
    assert len(ledger.transactions) == 6
    assert "Expenses:Food:Groceries" in ledger.accounts


def test_transactions_for_account_includes_subaccounts(ledger_path):
    ledger = Ledger.load(ledger_path)
    food = ledger.transactions_for_account("Expenses:Food")
    assert len(food) == 2
    assert {t.payee for t in food} == {"Green Grocer", "Nice Restaurant"}


def test_transactions_for_account_none_returns_all(ledger_path):
    ledger = Ledger.load(ledger_path)
    assert ledger.transactions_for_account(None) == ledger.transactions


def test_trial_balance_all_accounts(ledger_path):
    ledger = Ledger.load(ledger_path)
    balances = {a: format_inventory(b) for a, b in ledger.trial_balance()}
    assert balances == {
        "Assets:Checking": "4,098.45 USD",
        "Assets:Savings": "1,000.00 USD",
        "Equity:Opening-Balances": "-2,500.00 USD",
        "Expenses:Food:Groceries": "87.35 USD",
        "Expenses:Food:Restaurant": "64.20 USD",
        "Expenses:Rent": "1,450.00 USD",
        "Income:Salary": "-4,200.00 USD",
    }
    # Sorted by account name.
    assert [a for a, _ in ledger.trial_balance()] == sorted(balances)


def test_trial_balance_as_of_excludes_later_postings(ledger_path):
    ledger = Ledger.load(ledger_path)
    balances = {
        a: format_inventory(b)
        for a, b in ledger.trial_balance(as_of=datetime.date(2026, 1, 5))
    }
    # Only the opening balance and the salary deposit have posted by then.
    assert balances == {
        "Assets:Checking": "6,700.00 USD",
        "Equity:Opening-Balances": "-2,500.00 USD",
        "Income:Salary": "-4,200.00 USD",
    }


def test_transaction_amount(ledger_path):
    ledger = Ledger.load(ledger_path)
    rent = ledger.transactions_for_account("Expenses:Rent")[0]
    assert transaction_amount(rent) == "1,450.00 USD"


def test_transaction_amount_with_cost_basis(ledger_path):
    append_entry(
        ledger_path,
        "2026-01-01 open Assets:Investments  HOOL\n\n"
        '2026-01-20 * "Buy stock"\n'
        "  Assets:Investments  10 HOOL {500.00 USD}\n"
        "  Assets:Checking\n",
    )
    ledger = Ledger.load(ledger_path)
    assert not ledger.errors
    txn = ledger.transactions[-1]
    assert transaction_amount(txn) == "5,000.00 USD"


def test_transaction_amount_with_price_annotation(ledger_path):
    append_entry(
        ledger_path,
        "2026-01-01 open Assets:Investments  HOOL\n\n"
        '2026-01-21 * "Buy at price"\n'
        "  Assets:Investments  10 HOOL @ 55.00 USD\n"
        "  Assets:Checking\n",
    )
    ledger = Ledger.load(ledger_path)
    assert not ledger.errors
    txn = ledger.transactions[-1]
    assert transaction_amount(txn) == "550.00 USD"


def test_entries_for_account_includes_directives(ledger_path):
    ledger = Ledger.load(ledger_path)
    checking = ledger.entries_for_account("Assets:Checking")
    assert {"Open", "Note", "Transaction"} <= {type(e).__name__ for e in checking}
    salary = ledger.entries_for_account("Income:Salary")
    assert "Balance" in {type(e).__name__ for e in salary}


def test_directives_includes_all_displayed_types(ledger_path):
    ledger = Ledger.load(ledger_path)
    # 7 opens + 6 transactions + 1 balance + 1 note
    assert len(ledger.directives) == 15


def test_files_single_file(ledger_path):
    ledger = Ledger.load(ledger_path)
    assert ledger.files == [ledger_path.resolve()]


def test_files_lists_includes_after_top_level(multi_ledger_path):
    ledger = Ledger.load(multi_ledger_path)
    assert not ledger.errors
    assert ledger.files == [
        multi_ledger_path.resolve(),
        (multi_ledger_path.parent / "food.beancount").resolve(),
    ]


def test_filter_transactions_by_text(ledger_path):
    ledger = Ledger.load(ledger_path)
    txns = ledger.transactions
    assert [t.payee for t in filter_transactions(txns, "grocer")] == ["Green Grocer"]
    assert [t.narration for t in filter_transactions(txns, "RENT")] == ["January rent"]
    assert filter_transactions(txns, "") == txns
    assert filter_transactions(txns, "no such thing") == []


def test_filter_transactions_by_date_range(ledger_path):
    ledger = Ledger.load(ledger_path)
    txns = ledger.transactions
    ranged = filter_transactions(txns, "2026-01-05..2026-01-10")
    assert [str(t.date) for t in ranged] == ["2026-01-05", "2026-01-06", "2026-01-10"]
    assert len(filter_transactions(txns, "2026-01-14..")) == 2
    assert len(filter_transactions(txns, "..2026-01-01")) == 1


def test_filter_transactions_invalid_range_falls_back_to_text(ledger_path):
    ledger = Ledger.load(ledger_path)
    assert filter_transactions(ledger.transactions, "not..a-date") == []


def test_resolve_date_preset_month(fixed_today):
    assert resolve_date_preset("month", today=fixed_today) == (
        datetime.date(2026, 3, 1),
        fixed_today,
    )


def test_resolve_date_preset_last_month(fixed_today):
    assert resolve_date_preset("last-month", today=fixed_today) == (
        datetime.date(2026, 2, 1),
        datetime.date(2026, 2, 28),
    )


def test_resolve_date_preset_last_month_across_year_boundary():
    today = datetime.date(2026, 1, 15)
    assert resolve_date_preset("last-month", today=today) == (
        datetime.date(2025, 12, 1),
        datetime.date(2025, 12, 31),
    )


def test_resolve_date_preset_year(fixed_today):
    assert resolve_date_preset("year", today=fixed_today) == (
        datetime.date(2026, 1, 1),
        fixed_today,
    )


def test_resolve_date_preset_last_year(fixed_today):
    assert resolve_date_preset("last-year", today=fixed_today) == (
        datetime.date(2025, 1, 1),
        datetime.date(2025, 12, 31),
    )


def test_resolve_date_preset_case_insensitive_and_trimmed(fixed_today):
    assert resolve_date_preset("  MONTH  ", today=fixed_today) == (
        datetime.date(2026, 3, 1),
        fixed_today,
    )


def test_resolve_date_preset_unknown_token_returns_none(fixed_today):
    assert resolve_date_preset("fortnight", today=fixed_today) is None


def test_parse_date_range_recognizes_presets(fixed_today):
    assert parse_date_range("year", today=fixed_today) == (
        datetime.date(2026, 1, 1),
        fixed_today,
    )


def test_parse_date_range_explicit_range_unaffected_by_today(fixed_today):
    assert parse_date_range("2026-01-05..2026-01-10", today=fixed_today) == (
        datetime.date(2026, 1, 5),
        datetime.date(2026, 1, 10),
    )


def test_filter_transactions_with_month_preset(ledger_path):
    ledger = Ledger.load(ledger_path)
    txns = ledger.transactions
    # All example transactions fall in January 2026; treat "today" as being
    # partway through that month so the "month" preset covers them all.
    today = datetime.date(2026, 1, 20)
    assert filter_transactions(txns, "month", today=today) == filter_transactions(
        txns, "2026-01-01..2026-01-20"
    )


def test_filter_transactions_with_last_year_preset(ledger_path):
    ledger = Ledger.load(ledger_path)
    txns = ledger.transactions
    today = datetime.date(2027, 3, 1)
    assert filter_transactions(txns, "last-year", today=today) == txns
    assert filter_transactions(txns, "LAST-YEAR", today=today) == txns


def test_income_statement_all_dates(ledger_path):
    ledger = Ledger.load(ledger_path)
    stmt = ledger.income_statement()
    assert {a: format_inventory(b) for a, b in stmt.income} == {
        "Income:Salary": "4,200.00 USD",
    }
    assert {a: format_inventory(b) for a, b in stmt.expenses} == {
        "Expenses:Food:Groceries": "87.35 USD",
        "Expenses:Food:Restaurant": "64.20 USD",
        "Expenses:Rent": "1,450.00 USD",
    }
    assert format_inventory(stmt.income_total) == "4,200.00 USD"
    assert format_inventory(stmt.expenses_total) == "1,601.55 USD"
    assert format_inventory(stmt.net) == "2,598.45 USD"


def test_income_statement_date_range(ledger_path):
    ledger = Ledger.load(ledger_path)
    stmt = ledger.income_statement(
        start=datetime.date(2026, 1, 6), end=datetime.date(2026, 1, 10)
    )
    assert not stmt.income
    assert {a for a, _ in stmt.expenses} == {
        "Expenses:Food:Groceries",
        "Expenses:Rent",
    }
    assert format_inventory(stmt.net) == "-1,537.35 USD"


def test_balance_sheet_all_accounts(ledger_path):
    ledger = Ledger.load(ledger_path)
    sheet = ledger.balance_sheet()
    assert {a: format_inventory(b) for a, b in sheet.assets} == {
        "Assets:Checking": "4,098.45 USD",
        "Assets:Savings": "1,000.00 USD",
    }
    assert sheet.liabilities == []
    assert {a: format_inventory(b) for a, b in sheet.equity} == {
        "Equity:Opening-Balances": "2,500.00 USD",
    }
    assert format_inventory(sheet.assets_total) == "5,098.45 USD"
    assert format_inventory(sheet.liabilities_total) == ""
    assert format_inventory(sheet.equity_total) == "2,500.00 USD"
    assert format_inventory(sheet.net_income) == "2,598.45 USD"

    # The accounting equation holds once the implicit net-income line is
    # folded in, even though nothing has actually closed the books yet.
    assert sheet.assets_total == sheet.liabilities_total + sheet.equity_total + sheet.net_income


def test_balance_sheet_as_of_excludes_later_postings(ledger_path):
    ledger = Ledger.load(ledger_path)
    sheet = ledger.balance_sheet(as_of=datetime.date(2026, 1, 5))
    assert {a: format_inventory(b) for a, b in sheet.assets} == {
        "Assets:Checking": "6,700.00 USD",
    }
    assert sheet.liabilities == []
    assert {a: format_inventory(b) for a, b in sheet.equity} == {
        "Equity:Opening-Balances": "2,500.00 USD",
    }
    assert format_inventory(sheet.net_income) == "4,200.00 USD"
    assert sheet.assets_total == sheet.liabilities_total + sheet.equity_total + sheet.net_income


def test_root_account_has_balances(ledger_path):
    ledger = Ledger.load(ledger_path)
    root = ledger.root_account()
    checking = root["Assets"]["Checking"]
    balance = checking.balance.reduce(lambda pos: pos.units)
    amounts = {(pos.units.number, pos.units.currency) for pos in balance}
    # 2500 + 4200 - 87.35 - 1450 - 64.20 - 1000
    assert amounts == {(Decimal("4098.45"), "USD")}


def test_register_running_balance(ledger_path):
    ledger = Ledger.load(ledger_path)
    rows = ledger.register("Assets:Checking")
    # Known sequence for Assets:Checking in examples/example.beancount, in
    # date order, each posting amount and the running balance after it.
    assert [
        (
            r.date,
            r.narration,
            format_inventory(r.posting_amount),
            format_inventory(r.running_balance),
        )
        for r in rows
    ] == [
        (datetime.date(2026, 1, 1), "Opening balance", "2,500.00 USD", "2,500.00 USD"),
        (datetime.date(2026, 1, 5), "Salary", "4,200.00 USD", "6,700.00 USD"),
        (datetime.date(2026, 1, 6), "Weekly groceries", "-87.35 USD", "6,612.65 USD"),
        (datetime.date(2026, 1, 10), "January rent", "-1,450.00 USD", "5,162.65 USD"),
        (datetime.date(2026, 1, 14), "Dinner with friends", "-64.20 USD", "5,098.45 USD"),
        (datetime.date(2026, 1, 15), "Transfer to savings", "-1,000.00 USD", "4,098.45 USD"),
    ]
    # Rows are in date order.
    assert [r.date for r in rows] == sorted(r.date for r in rows)


def test_register_none_account_returns_empty(ledger_path):
    ledger = Ledger.load(ledger_path)
    assert ledger.register("Assets:Nonexistent") == []


def test_register_multiple_currencies_kept_separate(tmp_path):
    path = tmp_path / "multi-currency.beancount"
    path.write_text(
        'option "title" "Multi-currency Ledger"\n'
        "\n"
        "2026-01-01 open Assets:Wallet\n"
        "2026-01-01 open Income:Salary\n"
        "2026-01-01 open Income:Freelance\n"
        "\n"
        '2026-01-02 * "Employer" "USD salary"\n'
        "  Assets:Wallet    100.00 USD\n"
        "  Income:Salary\n"
        "\n"
        '2026-01-03 * "Client" "EUR invoice"\n'
        "  Assets:Wallet     50.00 EUR\n"
        "  Income:Freelance\n"
        "\n"
        '2026-01-04 * "Employer" "USD salary"\n'
        "  Assets:Wallet     20.00 USD\n"
        "  Income:Salary\n",
        encoding="utf-8",
    )
    ledger = Ledger.load(path)
    assert not ledger.errors
    rows = ledger.register("Assets:Wallet")
    balances = [format_inventory(r.running_balance) for r in rows]
    # Each currency accumulates independently; they never mix into one total.
    assert balances == [
        "100.00 USD",
        "50.00 EUR, 100.00 USD",
        "50.00 EUR, 120.00 USD",
    ]
    posting_amounts = [format_inventory(r.posting_amount) for r in rows]
    assert posting_amounts == ["100.00 USD", "50.00 EUR", "20.00 USD"]
