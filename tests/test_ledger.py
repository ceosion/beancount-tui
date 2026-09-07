import datetime
from decimal import Decimal
from pathlib import Path

import beanquery
import pytest
from beancount.core import realization

from beancount_tui.editor import append_entry
from beancount_tui.ledger import (
    BudgetEntry,
    BudgetReportRow,
    Ledger,
    filter_transactions,
    format_inventory,
    format_query_value,
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


def test_holdings_aggregates_costed_lot_with_market_value(ledger_path):
    append_entry(
        ledger_path,
        "2026-01-01 open Assets:Investments  HOOL\n\n"
        '2026-01-20 * "Buy stock"\n'
        "  Assets:Investments  10 HOOL {500.00 USD}\n"
        "  Assets:Checking\n\n"
        "2026-02-01 price HOOL  550.00 USD\n",
    )
    ledger = Ledger.load(ledger_path)
    assert not ledger.errors
    report = ledger.holdings(as_of=datetime.date(2026, 2, 15))

    assert len(report.holdings) == 1
    holding = report.holdings[0]
    assert holding.account == "Assets:Investments"
    assert holding.commodity == "HOOL"
    assert holding.quantity == Decimal("10")
    assert format_inventory(holding.cost_basis) == "5,000.00 USD"
    assert holding.priced_in_operating_currency is True
    assert holding.market_value.number == Decimal("5500.00")
    assert holding.market_value.currency == "USD"

    assert report.operating_currency == "USD"
    assert format_inventory(report.net_worth) == "5,500.00 USD"


def test_holdings_before_price_directive_has_no_market_value(ledger_path):
    append_entry(
        ledger_path,
        "2026-01-01 open Assets:Investments  HOOL\n\n"
        '2026-01-20 * "Buy stock"\n'
        "  Assets:Investments  10 HOOL {500.00 USD}\n"
        "  Assets:Checking\n\n"
        "2026-02-01 price HOOL  550.00 USD\n",
    )
    ledger = Ledger.load(ledger_path)
    assert not ledger.errors
    # As of the purchase date, no price directive has posted yet.
    report = ledger.holdings(as_of=datetime.date(2026, 1, 20))

    assert len(report.holdings) == 1
    holding = report.holdings[0]
    assert holding.market_value is None
    assert holding.priced_in_operating_currency is False
    assert format_inventory(report.net_worth) == ""


def test_holdings_excludes_uncosted_postings(ledger_path):
    ledger = Ledger.load(ledger_path)
    report = ledger.holdings()
    # The example ledger's Checking/Savings balances aren't held at cost.
    assert report.holdings == []
    assert format_inventory(report.net_worth) == ""


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


@pytest.fixture
def priced_ledger_path(tmp_path: Path) -> Path:
    """A throwaway ledger with an operating currency and known prices.

    ``Assets:Brokerage`` holds USD plus AAPL (priced), ``Assets:Crypto``
    holds an unpriced currency (XYZ), and ``Assets:Cash`` holds only USD
    (the operating currency itself, nothing to convert).
    """
    path = tmp_path / "priced.beancount"
    path.write_text(
        'option "title" "Priced Ledger"\n'
        'option "operating_currency" "USD"\n'
        "\n"
        "2026-01-01 open Assets:Brokerage\n"
        "2026-01-01 open Assets:Crypto\n"
        "2026-01-01 open Assets:Cash\n"
        "2026-01-01 open Equity:Opening-Balances\n"
        "\n"
        "2026-01-02 price AAPL 150.00 USD\n"
        "2026-01-03 price AAPL 175.32 USD\n"
        "\n"
        '2026-01-01 * "Opening cash"\n'
        "  Assets:Cash            1000.00 USD\n"
        "  Equity:Opening-Balances\n"
        "\n"
        '2026-01-04 * "Buy stock, keep some cash"\n'
        "  Assets:Brokerage       100.00 USD\n"
        "  Assets:Brokerage       50 AAPL\n"
        "  Equity:Opening-Balances  -100.00 USD\n"
        "  Equity:Opening-Balances  -50 AAPL\n"
        "\n"
        '2026-01-05 * "Buy crypto"\n'
        "  Assets:Crypto          10 XYZ\n"
        "  Equity:Opening-Balances  -10 XYZ\n",
        encoding="utf-8",
    )
    return path


def test_converted_total_mixed_currencies_with_known_price(priced_ledger_path):
    ledger = Ledger.load(priced_ledger_path)
    assert not ledger.errors
    root = ledger.root_account()
    brokerage_balance = realization.compute_balance(root["Assets"]["Brokerage"]).reduce(
        lambda pos: pos.units
    )
    total, unpriced = ledger.converted_total(brokerage_balance)
    # 100.00 USD + 50 * 175.32 USD (the latest AAPL price) == 8,866.00 USD.
    assert total == Decimal("8866.00")
    assert unpriced == []


def test_converted_total_reports_no_price_available(priced_ledger_path):
    ledger = Ledger.load(priced_ledger_path)
    root = ledger.root_account()
    crypto_balance = realization.compute_balance(root["Assets"]["Crypto"]).reduce(
        lambda pos: pos.units
    )
    total, unpriced = ledger.converted_total(crypto_balance)
    assert total is None
    assert unpriced == ["XYZ"]


def test_converted_total_no_operating_currency_configured(ledger_path):
    # examples/example.beancount configures "USD" as the operating currency;
    # temporarily clear it to exercise the "not configured" branch.
    ledger = Ledger.load(ledger_path)
    ledger.options["operating_currency"] = []
    root = ledger.root_account()
    checking_balance = realization.compute_balance(root["Assets"]["Checking"]).reduce(
        lambda pos: pos.units
    )
    total, unpriced = ledger.converted_total(checking_balance)
    assert total is None
    assert unpriced == []


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


def test_run_query_returns_columns_and_rows(ledger_path):
    ledger = Ledger.load(ledger_path)
    result = ledger.run_query("SELECT account, sum(position) AS total GROUP BY account")
    assert result.columns == ["account", "total"]
    rendered = {row[0]: format_query_value(row[1]) for row in result.rows}
    assert rendered["Assets:Checking"] == "4,098.45 USD"


def test_run_query_bad_syntax_raises_beanquery_error(ledger_path):
    ledger = Ledger.load(ledger_path)
    with pytest.raises(beanquery.Error):
        ledger.run_query("SELEKT accountz")


def test_run_query_unknown_column_raises_beanquery_error(ledger_path):
    ledger = Ledger.load(ledger_path)
    with pytest.raises(beanquery.Error):
        ledger.run_query("SELECT no_such_column FROM postings")


def test_format_query_value_renders_none_as_empty_string():
    assert format_query_value(None) == ""
    assert format_query_value("Assets:Checking") == "Assets:Checking"


def test_ledger_queries_lists_query_directives(ledger_path):
    append_entry(
        ledger_path,
        '2026-03-01 query "cash" "SELECT account, sum(position) GROUP BY account"\n',
    )
    ledger = Ledger.load(ledger_path)
    assert not ledger.errors
    assert len(ledger.queries) == 1
    assert ledger.queries[0].name == "cash"
    assert ledger.queries[0].query_string == "SELECT account, sum(position) GROUP BY account"


def test_budgets_empty_when_no_budget_directives(ledger_path):
    ledger = Ledger.load(ledger_path)
    assert ledger.budgets == []


def test_budgets_parses_all_five_intervals_long_and_short_form(ledger_path):
    append_entry(
        ledger_path,
        '2026-02-01 custom "budget" Assets:Checking "daily" 10.00 USD\n'
        '2026-02-01 custom "budget" Assets:Checking "day" 11.00 USD\n'
        '2026-02-01 custom "budget" Assets:Savings "weekly" 70.00 USD\n'
        '2026-02-01 custom "budget" Assets:Savings "week" 71.00 USD\n'
        '2026-02-01 custom "budget" Expenses:Rent "monthly" 300.00 USD\n'
        '2026-02-01 custom "budget" Expenses:Rent "month" 301.00 USD\n'
        '2026-02-01 custom "budget" Expenses:Food:Groceries "quarterly" 900.00 USD\n'
        '2026-02-01 custom "budget" Expenses:Food:Groceries "quarter" 901.00 USD\n'
        '2026-02-01 custom "budget" Expenses:Food:Restaurant "YEARLY" 1200.00 USD\n'
        '2026-02-01 custom "budget" Expenses:Food:Restaurant "Year" 1201.00 USD\n',
    )
    ledger = Ledger.load(ledger_path)
    assert not ledger.errors
    assert len(ledger.budgets) == 10
    assert all(isinstance(b, BudgetEntry) for b in ledger.budgets)
    assert all(b.date == datetime.date(2026, 2, 1) for b in ledger.budgets)

    seen = {(b.account, b.interval, b.amount.number, b.amount.currency) for b in ledger.budgets}
    # Long and short forms of the same interval canonicalize identically.
    assert seen == {
        ("Assets:Checking", "daily", Decimal("10.00"), "USD"),
        ("Assets:Checking", "daily", Decimal("11.00"), "USD"),
        ("Assets:Savings", "weekly", Decimal("70.00"), "USD"),
        ("Assets:Savings", "weekly", Decimal("71.00"), "USD"),
        ("Expenses:Rent", "monthly", Decimal("300.00"), "USD"),
        ("Expenses:Rent", "monthly", Decimal("301.00"), "USD"),
        ("Expenses:Food:Groceries", "quarterly", Decimal("900.00"), "USD"),
        ("Expenses:Food:Groceries", "quarterly", Decimal("901.00"), "USD"),
        ("Expenses:Food:Restaurant", "yearly", Decimal("1200.00"), "USD"),
        ("Expenses:Food:Restaurant", "yearly", Decimal("1201.00"), "USD"),
    }


def test_budgets_invalid_interval_surfaces_as_error_not_crash(ledger_path):
    append_entry(
        ledger_path,
        '2026-02-01 custom "budget" Expenses:Rent "fortnightly" 100.00 USD\n',
    )
    ledger = Ledger.load(ledger_path)
    assert ledger.budgets == []
    assert len(ledger.errors) == 1
    assert "fortnightly" in ledger.errors[0].message
    assert ledger.errors[0].entry.type == "budget"


def test_budgets_invalid_interval_does_not_block_valid_ones(ledger_path):
    append_entry(
        ledger_path,
        '2026-02-01 custom "budget" Expenses:Rent "monthly" 300.00 USD\n'
        '2026-02-01 custom "budget" Expenses:Food:Groceries "fortnightly" 50.00 USD\n',
    )
    ledger = Ledger.load(ledger_path)
    assert len(ledger.budgets) == 1
    assert ledger.budgets[0].account == "Expenses:Rent"
    assert ledger.budgets[0].interval == "monthly"
    assert len(ledger.errors) == 1
    assert "fortnightly" in ledger.errors[0].message


def test_budget_target_no_matching_budget_is_zero(ledger_path):
    ledger = Ledger.load(ledger_path)
    assert ledger.budget_target(
        "Expenses:Rent", "USD", datetime.date(2026, 1, 1), datetime.date(2026, 1, 31)
    ) == Decimal(0)


def test_budget_target_days_before_earliest_entry_contribute_nothing(ledger_path):
    append_entry(
        ledger_path,
        '2026-02-01 custom "budget" Expenses:Rent "daily" 10.00 USD\n',
    )
    ledger = Ledger.load(ledger_path)
    # Only Feb 1 is on/after the entry's date; Jan 30-31 predate it and
    # contribute nothing (clean absence, not a zero-with-a-flag per day).
    assert ledger.budget_target(
        "Expenses:Rent", "USD", datetime.date(2026, 1, 30), datetime.date(2026, 2, 1)
    ) == Decimal("10.00")


def test_budget_target_daily(ledger_path):
    append_entry(
        ledger_path,
        '2026-01-01 custom "budget" Assets:Checking "daily" 10.00 USD\n',
    )
    ledger = Ledger.load(ledger_path)
    # 5 days (Jan 1-5 inclusive) at a flat 10.00/day.
    total = ledger.budget_target(
        "Assets:Checking", "USD", datetime.date(2026, 1, 1), datetime.date(2026, 1, 5)
    )
    assert total == Decimal("50.00")


def test_budget_target_weekly(ledger_path):
    append_entry(
        ledger_path,
        '2026-01-01 custom "budget" Assets:Savings "weekly" 70.00 USD\n',
    )
    ledger = Ledger.load(ledger_path)
    # 70.00/week = 10.00/day (flat 7-day bucket), over 10 days.
    total = ledger.budget_target(
        "Assets:Savings", "USD", datetime.date(2026, 1, 1), datetime.date(2026, 1, 10)
    )
    assert total == Decimal("100.00")


def test_budget_target_monthly(ledger_path):
    append_entry(
        ledger_path,
        '2026-04-01 custom "budget" Expenses:Rent "monthly" 300.00 USD\n',
    )
    ledger = Ledger.load(ledger_path)
    # April has 30 days, so 300.00/30 = 10.00/day, over the first 10 days.
    total = ledger.budget_target(
        "Expenses:Rent", "USD", datetime.date(2026, 4, 1), datetime.date(2026, 4, 10)
    )
    assert total == Decimal("100.00")


def test_budget_target_quarterly(ledger_path):
    append_entry(
        ledger_path,
        '2026-04-01 custom "budget" Expenses:Food:Groceries "quarterly" 910.00 USD\n',
    )
    ledger = Ledger.load(ledger_path)
    # Q2 2026 (Apr/May/Jun) is 30+31+30 = 91 days, so 910.00/91 = 10.00/day,
    # over the first 10 days.
    total = ledger.budget_target(
        "Expenses:Food:Groceries", "USD", datetime.date(2026, 4, 1), datetime.date(2026, 4, 10)
    )
    assert total == Decimal("100.00")


def test_budget_target_yearly(ledger_path):
    append_entry(
        ledger_path,
        '2026-01-01 custom "budget" Expenses:Food:Restaurant "yearly" 3650.00 USD\n',
    )
    ledger = Ledger.load(ledger_path)
    # 2026 is not a leap year (365 days), so 3650.00/365 = 10.00/day, over
    # the first 10 days.
    total = ledger.budget_target(
        "Expenses:Food:Restaurant", "USD", datetime.date(2026, 1, 1), datetime.date(2026, 1, 10)
    )
    assert total == Decimal("100.00")


def test_budget_target_leap_year_february(ledger_path):
    append_entry(
        ledger_path,
        '2024-02-01 custom "budget" Expenses:Rent "monthly" 290.00 USD\n',
    )
    ledger = Ledger.load(ledger_path)
    # 2024 is a leap year, so February has 29 (not 28) days: 290.00/29 =
    # 10.00/day, over the entire month.
    total = ledger.budget_target(
        "Expenses:Rent", "USD", datetime.date(2024, 2, 1), datetime.date(2024, 2, 29)
    )
    assert total == Decimal("290.00")


def test_budget_target_quarter_boundary_uses_each_days_own_bucket(ledger_path):
    append_entry(
        ledger_path,
        '2026-01-01 custom "budget" Expenses:Food:Groceries "quarterly" 8190.00 USD\n',
    )
    ledger = Ledger.load(ledger_path)
    # A single quarterly entry spanning the Q1/Q2 boundary: Q1 2026
    # (Jan/Feb/Mar) is 31+28+31 = 90 days (8190.00/90 = 91.00/day); Q2 2026
    # (Apr/May/Jun) is 30+31+30 = 91 days (8190.00/91 = 90.00/day). Each
    # day's own calendar-quarter bucket is used, not a flat average across
    # the range: Mar 30-31 (2 days at 91.00) + Apr 1-2 (2 days at 90.00).
    total = ledger.budget_target(
        "Expenses:Food:Groceries", "USD", datetime.date(2026, 3, 30), datetime.date(2026, 4, 2)
    )
    assert total == Decimal("362.00")


def test_budget_target_later_entry_supersedes_from_its_own_date(ledger_path):
    append_entry(
        ledger_path,
        '2026-01-01 custom "budget" Expenses:Rent "monthly" 310.00 USD\n'
        '2026-01-20 custom "budget" Expenses:Rent "monthly" 620.00 USD\n',
    )
    ledger = Ledger.load(ledger_path)
    # January has 31 days: the first entry is 310.00/31 = 10.00/day, the
    # second (superseding from Jan 20 onward) is 620.00/31 = 20.00/day.
    # Jan 15-19 (5 days, pre-replacement) + Jan 20-25 (6 days, replaced).
    total = ledger.budget_target(
        "Expenses:Rent", "USD", datetime.date(2026, 1, 15), datetime.date(2026, 1, 25)
    )
    assert total == Decimal("170.00")

    # The earlier entry still applies to days before the replacement date.
    only_before = ledger.budget_target(
        "Expenses:Rent", "USD", datetime.date(2026, 1, 15), datetime.date(2026, 1, 19)
    )
    assert only_before == Decimal("50.00")


def test_budget_target_tracks_currencies_independently(ledger_path):
    append_entry(
        ledger_path,
        '2026-01-01 custom "budget" Expenses:Food:Groceries "monthly" 310.00 USD\n'
        '2026-01-01 custom "budget" Expenses:Food:Groceries "monthly" 620.00 EUR\n',
    )
    ledger = Ledger.load(ledger_path)
    usd_before = ledger.budget_target(
        "Expenses:Food:Groceries", "USD", datetime.date(2026, 1, 1), datetime.date(2026, 1, 5)
    )
    assert usd_before == Decimal("50.00")

    # Add a second, later EUR entry that supersedes the first EUR one.
    append_entry(
        ledger_path,
        '2026-01-15 custom "budget" Expenses:Food:Groceries "monthly" 930.00 EUR\n',
    )
    ledger = Ledger.load(ledger_path)

    # The USD series is untouched by the EUR replacement.
    usd_after = ledger.budget_target(
        "Expenses:Food:Groceries", "USD", datetime.date(2026, 1, 1), datetime.date(2026, 1, 5)
    )
    assert usd_after == usd_before == Decimal("50.00")

    # EUR itself resolved its own most-recent entry per day: 620.00/31 =
    # 20.00/day before Jan 15, then 930.00/31 = 30.00/day from Jan 15 on.
    eur_before_replacement = ledger.budget_target(
        "Expenses:Food:Groceries", "EUR", datetime.date(2026, 1, 1), datetime.date(2026, 1, 10)
    )
    assert eur_before_replacement == Decimal("200.00")
    eur_after_replacement = ledger.budget_target(
        "Expenses:Food:Groceries", "EUR", datetime.date(2026, 1, 15), datetime.date(2026, 1, 20)
    )
    assert eur_after_replacement == Decimal("180.00")


def test_budget_report_known_budget_and_actual_produces_expected_remaining(ledger_path):
    # example.beancount already has a 87.35 USD posting to
    # Expenses:Food:Groceries on 2026-01-06; a 310.00/month budget (January
    # has 31 days, so 310.00/31 = 10.00/day, exact over the whole month)
    # gives a round expected Remaining.
    append_entry(
        ledger_path,
        '2026-01-01 custom "budget" Expenses:Food:Groceries "monthly" 310.00 USD\n',
    )
    ledger = Ledger.load(ledger_path)
    rows = ledger.budget_report(datetime.date(2026, 1, 1), datetime.date(2026, 1, 31))
    assert len(rows) == 1
    row = rows[0]
    assert isinstance(row, BudgetReportRow)
    assert row.account == "Expenses:Food:Groceries"
    assert row.currency == "USD"
    assert row.budgeted == Decimal("310.00")
    assert row.actual == Decimal("87.35")
    assert row.remaining == Decimal("222.65")


def test_budget_report_excludes_accounts_with_no_budget(ledger_path):
    append_entry(
        ledger_path,
        '2026-01-01 custom "budget" Expenses:Food:Groceries "monthly" 310.00 USD\n',
    )
    ledger = Ledger.load(ledger_path)
    rows = ledger.budget_report(datetime.date(2026, 1, 1), datetime.date(2026, 1, 31))
    accounts = {row.account for row in rows}
    # Expenses:Rent has postings in this range but no budget directive.
    assert accounts == {"Expenses:Food:Groceries"}


def test_budget_report_excludes_budgets_starting_after_the_range(ledger_path):
    append_entry(
        ledger_path,
        '2026-03-01 custom "budget" Expenses:Rent "monthly" 300.00 USD\n',
    )
    ledger = Ledger.load(ledger_path)
    rows = ledger.budget_report(datetime.date(2026, 1, 1), datetime.date(2026, 1, 31))
    assert rows == []


def test_budget_report_tracks_currencies_as_separate_rows(ledger_path):
    append_entry(
        ledger_path,
        '2026-01-01 custom "budget" Expenses:Food:Groceries "monthly" 310.00 USD\n'
        '2026-01-01 custom "budget" Expenses:Food:Groceries "monthly" 620.00 EUR\n',
    )
    ledger = Ledger.load(ledger_path)
    rows = ledger.budget_report(datetime.date(2026, 1, 1), datetime.date(2026, 1, 31))
    by_currency = {row.currency: row for row in rows}
    assert set(by_currency) == {"USD", "EUR"}
    assert by_currency["USD"].actual == Decimal("87.35")
    assert by_currency["EUR"].actual == Decimal("0")
