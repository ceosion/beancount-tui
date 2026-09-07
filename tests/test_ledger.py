import datetime
from decimal import Decimal
from pathlib import Path

import beanquery
import pytest
from beancount.core import data, realization

from beancount_tui.editor import append_entry
from beancount_tui.ledger import (
    BudgetEntry,
    BudgetReportRow,
    ForecastedActivity,
    ForecastReportRow,
    Ledger,
    ProjectedTransaction,
    RecurringTemplate,
    filter_transactions,
    format_inventory,
    format_query_value,
    parse_date_range,
    parse_periods,
    resolve_date_preset,
    transaction_amount,
)


FIXTURES = Path(__file__).parent / "fixtures"


def test_load_example(ledger_path):
    ledger = Ledger.load(ledger_path)
    assert not ledger.errors
    assert len(ledger.transactions) == 6
    assert "Expenses:Food:Groceries" in ledger.accounts


def test_load_plugin_system_exit_surfaces_as_error_not_crash(tmp_path, monkeypatch):
    """LANG-13: a plugin calling sys.exit() during load must not crash the
    app -- it should degrade into a normal, #errors-panel-renderable load
    error that names the offending plugin, the same as an ordinary plugin
    exception already does."""
    monkeypatch.syspath_prepend(str(FIXTURES))
    ledger_file = tmp_path / "ledger.beancount"
    ledger_file.write_text(
        'plugin "plugin_raises_system_exit"\n'
        'option "operating_currency" "USD"\n'
        "\n"
        "2026-01-01 open Assets:Checking USD\n",
        encoding="utf-8",
    )
    ledger = Ledger.load(ledger_file)
    assert len(ledger.errors) == 1
    assert "plugin_raises_system_exit" in ledger.errors[0].message
    assert "simulated fatal plugin failure" in ledger.errors[0].message
    # The load bailed out cleanly rather than crashing mid-way.
    assert ledger.entries == []


def test_reload_plugin_system_exit_surfaces_as_error_not_crash(tmp_path, monkeypatch):
    """Same as above, but via reload() on an already-loaded ledger, since
    LANG-13 covers both entry points."""
    monkeypatch.syspath_prepend(str(FIXTURES))
    ledger_file = tmp_path / "ledger.beancount"
    ledger_file.write_text(
        'option "operating_currency" "USD"\n\n2026-01-01 open Assets:Checking USD\n',
        encoding="utf-8",
    )
    ledger = Ledger.load(ledger_file)
    assert not ledger.errors

    ledger_file.write_text(
        'plugin "plugin_raises_system_exit"\n'
        'option "operating_currency" "USD"\n\n'
        "2026-01-01 open Assets:Checking USD\n",
        encoding="utf-8",
    )
    ledger.reload()
    assert len(ledger.errors) == 1
    assert "plugin_raises_system_exit" in ledger.errors[0].message


def test_plugins_empty_when_none_declared(ledger_path):
    """LANG-12: `examples/example.beancount` has no `plugin` line."""
    ledger = Ledger.load(ledger_path)
    assert ledger.plugins == []


def test_plugins_returns_declared_plugin_names_and_configs(tmp_path):
    """LANG-12: `Ledger.plugins` mirrors how `operating_currency` is read
    from `self.options` -- a `plugin "module" "config"` line never becomes a
    `data.*` entry (it's parsed into `options_map["plugin"]`), but the
    real loader still runs it, so plugin-generated entries (here,
    `auto_accounts`'s synthesized `Open` directives) still show up in
    `ledger.entries` with zero special handling."""
    ledger_file = tmp_path / "ledger.beancount"
    ledger_file.write_text(
        'plugin "beancount.plugins.auto_accounts"\n'
        'option "operating_currency" "USD"\n'
        "\n"
        '2026-01-01 * "Employer" "Salary"\n'
        "  Assets:Checking  10.00 USD\n"
        "  Income:Salary\n",
        encoding="utf-8",
    )
    ledger = Ledger.load(ledger_file)
    assert not ledger.errors
    assert ledger.plugins == [("beancount.plugins.auto_accounts", None)]
    # The plugin actually ran: auto_accounts synthesized Open entries for
    # the two accounts posted to above, with no special handling needed.
    opens = {e.account for e in ledger.entries if isinstance(e, data.Open)}
    assert opens == {"Assets:Checking", "Income:Salary"}


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


def test_parse_periods_preset_tokens(fixed_today):
    assert parse_periods("month,last-month", today=fixed_today) == [
        ("month", datetime.date(2026, 3, 1), fixed_today),
        ("last-month", datetime.date(2026, 2, 1), datetime.date(2026, 2, 28)),
    ]


def test_parse_periods_explicit_ranges(fixed_today):
    assert parse_periods(
        "2026-01-01..2026-01-31,2026-02-01..2026-02-28", today=fixed_today
    ) == [
        ("2026-01-01..2026-01-31", datetime.date(2026, 1, 1), datetime.date(2026, 1, 31)),
        ("2026-02-01..2026-02-28", datetime.date(2026, 2, 1), datetime.date(2026, 2, 28)),
    ]


def test_parse_periods_mixed_tokens_and_ranges(fixed_today):
    assert parse_periods("year,2026-01-01..2026-01-10", today=fixed_today) == [
        ("year", datetime.date(2026, 1, 1), fixed_today),
        ("2026-01-01..2026-01-10", datetime.date(2026, 1, 1), datetime.date(2026, 1, 10)),
    ]


def test_parse_periods_ignores_blank_segments(fixed_today):
    assert parse_periods("month, ,last-month,", today=fixed_today) == parse_periods(
        "month,last-month", today=fixed_today
    )


def test_parse_periods_rejects_fewer_than_two_periods(fixed_today):
    assert parse_periods("month", today=fixed_today) is None
    assert parse_periods("", today=fixed_today) is None


def test_parse_periods_rejects_any_invalid_segment(fixed_today):
    # The whole list is rejected if any one segment fails to parse, rather
    # than silently dropping just the bad one.
    assert parse_periods("month,not-a-period", today=fixed_today) is None


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


def test_income_statement_comparison_requires_at_least_two_periods(ledger_path):
    """RPT-09: comparison mode is additive, not a replacement -- a single
    period should just call ``income_statement`` directly, and this method
    says so via ``ValueError`` rather than silently degrading."""
    ledger = Ledger.load(ledger_path)
    with pytest.raises(ValueError, match="at least 2 periods"):
        ledger.income_statement_comparison([(None, None)])


def test_income_statement_comparison_labels_length_mismatch(ledger_path):
    ledger = Ledger.load(ledger_path)
    with pytest.raises(ValueError, match="labels"):
        ledger.income_statement_comparison(
            [(None, None), (None, None)], labels=["only-one"]
        )


def test_income_statement_comparison_explicit_ranges(ledger_path):
    """RPT-09: two explicit ``(start, end)`` ranges carved out of the same
    example ledger, manually computed:

    - 2026-01-01..2026-01-10: opening balance (not income/expense), the
      4,200.00 USD salary (01-05), 87.35 USD groceries (01-06), and
      1,450.00 USD rent (01-10). Net = 4,200.00 - 87.35 - 1,450.00 =
      2,662.65 USD.
    - 2026-01-11..2026-01-16: only the 64.20 USD restaurant dinner
      (01-14) falls in range (the savings transfer and balance
      assertion aren't income/expense postings). Net = -64.20 USD.

    The accounts touched don't fully overlap (Groceries/Rent only in the
    first period, Restaurant only in the second), which is exactly what
    exercises the alignment behavior: an account missing from one
    period's underlying ``income_statement`` still gets a row with an
    empty ``Inventory`` in that period's slot, not a missing column.
    """
    ledger = Ledger.load(ledger_path)
    comparison = ledger.income_statement_comparison(
        [
            (datetime.date(2026, 1, 1), datetime.date(2026, 1, 10)),
            (datetime.date(2026, 1, 11), datetime.date(2026, 1, 16)),
        ],
        labels=["first-half", "second-half"],
    )
    assert comparison.periods == ["first-half", "second-half"]

    income_by_account = dict(comparison.income)
    assert set(income_by_account) == {"Income:Salary"}
    assert [format_inventory(b) for b in income_by_account["Income:Salary"]] == [
        "4,200.00 USD",
        "",
    ]

    expenses_by_account = dict(comparison.expenses)
    assert set(expenses_by_account) == {
        "Expenses:Food:Groceries",
        "Expenses:Food:Restaurant",
        "Expenses:Rent",
    }
    assert [format_inventory(b) for b in expenses_by_account["Expenses:Food:Groceries"]] == [
        "87.35 USD",
        "",
    ]
    assert [format_inventory(b) for b in expenses_by_account["Expenses:Rent"]] == [
        "1,450.00 USD",
        "",
    ]
    assert [format_inventory(b) for b in expenses_by_account["Expenses:Food:Restaurant"]] == [
        "",
        "64.20 USD",
    ]

    assert [format_inventory(t) for t in comparison.income_total] == ["4,200.00 USD", ""]
    assert [format_inventory(t) for t in comparison.expenses_total] == [
        "1,537.35 USD",
        "64.20 USD",
    ]
    assert [format_inventory(t) for t in comparison.net] == ["2,662.65 USD", "-64.20 USD"]

    # Single-period behavior is untouched by the comparison mode existing.
    single = ledger.income_statement(
        start=datetime.date(2026, 1, 1), end=datetime.date(2026, 1, 10)
    )
    assert format_inventory(single.net) == "2,662.65 USD"


def test_income_statement_comparison_auto_labels(ledger_path):
    """Without explicit ``labels``, each period gets a ``START..END`` label
    that round-trips through ``parse_date_range``."""
    ledger = Ledger.load(ledger_path)
    comparison = ledger.income_statement_comparison(
        [
            (datetime.date(2026, 1, 1), datetime.date(2026, 1, 10)),
            (datetime.date(2026, 1, 11), None),
        ]
    )
    assert comparison.periods == ["2026-01-01..2026-01-10", "2026-01-11.."]


def test_income_statement_comparison_month_over_month(tmp_path):
    """RPT-09's headline acceptance criterion: a month-over-month
    comparison built from RPT-03's preset tokens (``month``/``last-month``),
    checked against manually computed per-period totals.

    With ``today`` fixed at 2026-03-15, ``last-month`` resolves to all of
    February and ``month`` resolves to March 1st through the 15th (see
    ``resolve_date_preset``). The fixture ledger below has:

    - February: a 3,000.00 USD salary (02-05), 150.00 USD groceries
      (02-10), and 1,200.00 USD rent (02-15).
      Net = 3,000.00 - 150.00 - 1,200.00 = 1,650.00 USD.
    - March (through the 15th): a 3,200.00 USD salary (03-05) and
      200.00 USD groceries (03-12); no rent transaction this month, which
      is exactly what exercises "missing account -> empty column" for
      Expenses:Rent in the March slot.
      Net = 3,200.00 - 200.00 = 3,000.00 USD.
    """
    today = datetime.date(2026, 3, 15)
    ledger_file = tmp_path / "ledger.beancount"
    ledger_file.write_text(
        'option "operating_currency" "USD"\n'
        "\n"
        "2026-01-01 open Assets:Checking          USD\n"
        "2026-01-01 open Income:Salary            USD\n"
        "2026-01-01 open Expenses:Food:Groceries  USD\n"
        "2026-01-01 open Expenses:Rent            USD\n"
        "\n"
        '2026-02-05 * "Employer" "Salary"\n'
        "  Assets:Checking  3000.00 USD\n"
        "  Income:Salary\n"
        "\n"
        '2026-02-10 * "Store" "Groceries"\n'
        "  Expenses:Food:Groceries  150.00 USD\n"
        "  Assets:Checking\n"
        "\n"
        '2026-02-15 * "Landlord" "Rent"\n'
        "  Expenses:Rent  1200.00 USD\n"
        "  Assets:Checking\n"
        "\n"
        '2026-03-05 * "Employer" "Salary"\n'
        "  Assets:Checking  3200.00 USD\n"
        "  Income:Salary\n"
        "\n"
        '2026-03-12 * "Store" "Groceries"\n'
        "  Expenses:Food:Groceries  200.00 USD\n"
        "  Assets:Checking\n",
        encoding="utf-8",
    )
    ledger = Ledger.load(ledger_file)
    assert not ledger.errors

    periods = parse_periods("month,last-month", today=today)
    assert periods is not None
    comparison = ledger.income_statement_comparison(
        periods=[(start, end) for _, start, end in periods],
        labels=[label for label, _, _ in periods],
    )
    assert comparison.periods == ["month", "last-month"]

    income_by_account = dict(comparison.income)
    assert [format_inventory(b) for b in income_by_account["Income:Salary"]] == [
        "3,200.00 USD",
        "3,000.00 USD",
    ]

    expenses_by_account = dict(comparison.expenses)
    assert [format_inventory(b) for b in expenses_by_account["Expenses:Food:Groceries"]] == [
        "200.00 USD",
        "150.00 USD",
    ]
    # No March rent transaction in the fixture -- the "month" column must
    # be an empty (not zero-valued-but-present, not missing) slot.
    assert [format_inventory(b) for b in expenses_by_account["Expenses:Rent"]] == [
        "",
        "1,200.00 USD",
    ]

    assert [format_inventory(t) for t in comparison.income_total] == [
        "3,200.00 USD",
        "3,000.00 USD",
    ]
    assert [format_inventory(t) for t in comparison.expenses_total] == [
        "200.00 USD",
        "1,350.00 USD",
    ]
    assert [format_inventory(t) for t in comparison.net] == ["3,000.00 USD", "1,650.00 USD"]


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


def test_price_history_returns_entries_in_date_order(priced_ledger_path):
    ledger = Ledger.load(priced_ledger_path)
    assert not ledger.errors
    assert ledger.price_history("AAPL") == [
        (datetime.date(2026, 1, 2), Decimal("150.00"), "USD"),
        (datetime.date(2026, 1, 3), Decimal("175.32"), "USD"),
    ]


def test_price_history_unknown_commodity_is_empty(priced_ledger_path):
    ledger = Ledger.load(priced_ledger_path)
    # XYZ is held (in the "Buy crypto" transaction) but never priced.
    assert ledger.price_history("XYZ") == []


def test_price_commodities_excludes_unpriced_commodities(priced_ledger_path):
    ledger = Ledger.load(priced_ledger_path)
    # AAPL has Price directives; USD (the operating currency) and XYZ
    # (held but never priced) don't and are excluded.
    assert ledger.price_commodities == ["AAPL"]


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


def test_running_balances_matches_register(ledger_path):
    # Ledger.running_balances (RPT-07) is a thin reshaping of the same
    # chronological walk register() uses -- id(transaction)-keyed running
    # balances should agree exactly, transaction for transaction.
    ledger = Ledger.load(ledger_path)
    rows = ledger.register("Assets:Checking")
    balances = ledger.running_balances("Assets:Checking")
    txns = ledger.transactions_for_account("Assets:Checking", ledger._actual_transactions)
    txns = sorted(txns, key=lambda txn: txn.date)
    assert [format_inventory(balances[id(txn)]) for txn in txns] == [
        format_inventory(r.running_balance) for r in rows
    ]


def test_running_balances_none_account_returns_empty(ledger_path):
    ledger = Ledger.load(ledger_path)
    assert ledger.running_balances("Assets:Nonexistent") == {}


def test_running_balances_multiple_currencies_kept_separate(tmp_path):
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
    txns = sorted(ledger.transactions_for_account("Assets:Wallet"), key=lambda t: t.date)
    balances = ledger.running_balances("Assets:Wallet")
    assert [format_inventory(balances[id(txn)]) for txn in txns] == [
        "100.00 USD",
        "50.00 EUR, 100.00 USD",
        "50.00 EUR, 120.00 USD",
    ]


def test_running_balances_only_cleared_filters_non_cleared_flags(tmp_path):
    # Cleared Balance (RPT-07) only accumulates "*"-flagged transactions --
    # a "!" (or any other non-"*") flag contributes to the flag-agnostic
    # running_balances() but is skipped entirely by only_cleared=True, and
    # every later cleared balance carries forward as if the "!" row weren't
    # there.
    path = tmp_path / "mixed-flags.beancount"
    path.write_text(
        'option "title" "Mixed Flags Ledger"\n'
        "\n"
        "2026-01-01 open Assets:Checking\n"
        "2026-01-01 open Income:Salary\n"
        "\n"
        '2026-01-01 * "Opening"\n'
        "  Assets:Checking    100.00 USD\n"
        "  Income:Salary\n"
        "\n"
        '2026-01-02 ! "Pending deposit"\n'
        "  Assets:Checking     50.00 USD\n"
        "  Income:Salary\n"
        "\n"
        '2026-01-03 * "Cleared deposit"\n'
        "  Assets:Checking     25.00 USD\n"
        "  Income:Salary\n",
        encoding="utf-8",
    )
    ledger = Ledger.load(path)
    assert not ledger.errors
    txns = sorted(ledger.transactions_for_account("Assets:Checking"), key=lambda t: t.date)
    running = ledger.running_balances("Assets:Checking")
    cleared = ledger.running_balances("Assets:Checking", only_cleared=True)
    assert [format_inventory(running[id(txn)]) for txn in txns] == [
        "100.00 USD",
        "150.00 USD",
        "175.00 USD",
    ]
    # The "!" transaction (index 1) never contributes to Cleared Balance, and
    # isn't present in the dict at all.
    assert id(txns[1]) not in cleared
    assert [format_inventory(cleared[id(txn)]) for txn in (txns[0], txns[2])] == [
        "100.00 USD",
        "125.00 USD",
    ]


def test_running_balances_excludes_recurring_template(ledger_path):
    append_entry(ledger_path, _RECURRING_RENT)
    ledger = Ledger.load(ledger_path)
    assert not ledger.errors
    balances = ledger.running_balances("Assets:Checking")
    # The recurring "Rent" template contributes no entry to the dict at all
    # (its own id() is simply absent, matching register()'s exclusion).
    recurring_txn = next(
        t for t in ledger.transactions if "recurring" in (t.tags or set())
    )
    assert id(recurring_txn) not in balances


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


def test_budget_report_excludes_recurring_template_from_actual(ledger_path):
    # Regression test for _account_currency_activity, which previously
    # iterated self.transactions instead of self._actual_transactions: a
    # #recurring template transaction is projection data (FORECAST-01), not
    # something that happened, and FORECAST-02 excludes it from every
    # actual-data view -- this report's "Actual" column is one of those
    # views too.
    append_entry(
        ledger_path,
        '2026-01-01 custom "budget" Expenses:Rent "monthly" 310.00 USD\n'
        '2026-01-20 * "Landlord" "Extra rent" #recurring\n'
        '  recurring-freq: "monthly"\n'
        "  Expenses:Rent      50000.00 USD\n"
        "  Assets:Checking\n",
    )
    ledger = Ledger.load(ledger_path)
    assert not ledger.errors
    rows = ledger.budget_report(datetime.date(2026, 1, 1), datetime.date(2026, 1, 31))
    row = next(r for r in rows if r.account == "Expenses:Rent")
    # example.beancount's real 2026-01-10 rent posting is 1450.00 USD; if the
    # 50,000.00 template posting were wrongly counted, actual would instead
    # be 51,450.00.
    assert row.actual == Decimal("1450.00")


def test_budget_report_rolled_up_sums_siblings_into_shared_parent(ledger_path):
    # example.beancount's 3-level hierarchy: Expenses:Food:Groceries and
    # Expenses:Food:Restaurant are sibling leaves under Expenses:Food, which
    # itself has no budget directive of its own. Groceries has an 87.35
    # actual posting (2026-01-06), Restaurant a 64.20 one (2026-01-14); both
    # amounts are multiples of 31 so the January (31-day) monthly proration
    # is exact, like the existing budget_report tests' 310.00 fixture.
    append_entry(
        ledger_path,
        '2026-01-01 custom "budget" Expenses:Food:Groceries "monthly" 310.00 USD\n'
        '2026-01-01 custom "budget" Expenses:Food:Restaurant "monthly" 155.00 USD\n',
    )
    ledger = Ledger.load(ledger_path)
    start, end = datetime.date(2026, 1, 1), datetime.date(2026, 1, 31)

    flat_rows = ledger.budget_report(start, end)
    flat_accounts = {row.account for row in flat_rows}
    assert flat_accounts == {"Expenses:Food:Groceries", "Expenses:Food:Restaurant"}

    rolled_up = ledger.budget_report_rolled_up(start, end)
    by_account = {row.account: row for row in rolled_up}

    # The flat leaf rows are unchanged.
    assert by_account["Expenses:Food:Groceries"].budgeted == Decimal("310.00")
    assert by_account["Expenses:Food:Groceries"].actual == Decimal("87.35")
    assert by_account["Expenses:Food:Restaurant"].budgeted == Decimal("155.00")
    assert by_account["Expenses:Food:Restaurant"].actual == Decimal("64.20")

    # Expenses:Food has no direct budget, so it's synthesized by summing its
    # two budgeted children.
    assert "Expenses:Food" in by_account
    food = by_account["Expenses:Food"]
    assert food.currency == "USD"
    assert food.budgeted == Decimal("465.00")
    assert food.actual == Decimal("151.55")
    assert food.remaining == Decimal("313.45")

    # Expenses (grandparent) is also synthesized, from the same two
    # budgeted descendants — not from Expenses:Food's already-synthesized
    # row, so the total isn't inflated by summing through an intermediate.
    assert "Expenses" in by_account
    assert by_account["Expenses"].budgeted == Decimal("465.00")
    assert by_account["Expenses"].actual == Decimal("151.55")

    # Expenses:Rent has postings but no budget in this test, and shouldn't
    # be pulled into any rollup.
    assert "Expenses:Rent" not in by_account


def test_budget_report_rolled_up_direct_parent_budget_not_double_counted(ledger_path):
    # Expenses:Food gets its own direct budget on top of its two budgeted
    # children (BUDGET-04's "not double-counted" acceptance criterion).
    append_entry(
        ledger_path,
        '2026-01-01 custom "budget" Expenses:Food:Groceries "monthly" 310.00 USD\n'
        '2026-01-01 custom "budget" Expenses:Food:Restaurant "monthly" 155.00 USD\n'
        '2026-01-01 custom "budget" Expenses:Food "monthly" 930.00 USD\n',
    )
    ledger = Ledger.load(ledger_path)
    start, end = datetime.date(2026, 1, 1), datetime.date(2026, 1, 31)

    rolled_up = ledger.budget_report_rolled_up(start, end)
    by_account = {row.account: row for row in rolled_up}

    # Expenses:Food has a direct row, so no synthesized "sum of children"
    # row is added for it — it keeps only its own figures.
    food_rows = [row for row in rolled_up if row.account == "Expenses:Food"]
    assert len(food_rows) == 1
    assert food_rows[0].budgeted == Decimal("930.00")
    assert food_rows[0].actual == Decimal("0")

    # Expenses (grandparent) still has no direct budget, so it's
    # synthesized by summing every budgeted descendant exactly once: its
    # own Food entry plus Groceries plus Restaurant.
    assert by_account["Expenses"].budgeted == Decimal("930.00") + Decimal("310.00") + Decimal(
        "155.00"
    )
    assert by_account["Expenses"].actual == Decimal("87.35") + Decimal("64.20")


def test_budget_report_rolled_up_toggles_back_to_flat(ledger_path):
    # No parent-level assertions here beyond confirming the flat and
    # rolled-up views agree on the leaf rows they share, i.e. the rollup is
    # additive rather than replacing the flat view (BudgetScreen's "r"
    # toggle switches between calling one or the other).
    append_entry(
        ledger_path,
        '2026-01-01 custom "budget" Expenses:Food:Groceries "monthly" 310.00 USD\n',
    )
    ledger = Ledger.load(ledger_path)
    start, end = datetime.date(2026, 1, 1), datetime.date(2026, 1, 31)
    flat_rows = ledger.budget_report(start, end)
    rolled_up_rows = ledger.budget_report_rolled_up(start, end)
    flat_by_account = {row.account: row for row in flat_rows}
    rolled_up_by_account = {row.account: row for row in rolled_up_rows}
    assert flat_by_account["Expenses:Food:Groceries"] == rolled_up_by_account[
        "Expenses:Food:Groceries"
    ]


def test_recurring_templates_empty_when_no_recurring_tagged_transactions(ledger_path):
    ledger = Ledger.load(ledger_path)
    assert ledger.recurring_templates == []


def test_recurring_templates_parses_across_intervals_long_and_short_form(ledger_path):
    append_entry(
        ledger_path,
        '2026-02-01 * "Landlord" "Rent" #recurring\n'
        '  recurring-freq: "monthly"\n'
        "  Expenses:Rent      1450.00 USD\n"
        "  Assets:Checking\n"
        "\n"
        '2026-02-02 * "Gym" "Membership" #recurring\n'
        '  recurring-freq: "week"\n'
        "  Expenses:Rent      20.00 USD\n"
        "  Assets:Checking\n"
        "\n"
        '2026-02-03 * "Insurer" "Premium" #recurring\n'
        '  recurring-freq: "QUARTER"\n'
        "  Expenses:Rent      300.00 USD\n"
        "  Assets:Checking\n"
        "\n"
        '2026-02-04 * "Domain Registrar" "Renewal" #recurring\n'
        '  recurring-freq: "yearly"\n'
        "  Expenses:Rent      15.00 USD\n"
        "  Assets:Checking\n",
    )
    ledger = Ledger.load(ledger_path)
    assert not ledger.errors
    assert len(ledger.recurring_templates) == 4
    assert all(isinstance(t, RecurringTemplate) for t in ledger.recurring_templates)

    by_first_date = {t.first_date: t for t in ledger.recurring_templates}
    assert by_first_date[datetime.date(2026, 2, 1)].interval == "monthly"
    assert by_first_date[datetime.date(2026, 2, 2)].interval == "weekly"
    assert by_first_date[datetime.date(2026, 2, 3)].interval == "quarterly"
    assert by_first_date[datetime.date(2026, 2, 4)].interval == "yearly"
    # Every one of these templates has no end date.
    assert all(t.until is None for t in ledger.recurring_templates)


def test_recurring_templates_keeps_reference_to_original_transaction(ledger_path):
    append_entry(
        ledger_path,
        '2026-02-01 * "Landlord" "Rent" #recurring\n'
        '  recurring-freq: "monthly"\n'
        "  Expenses:Rent      1450.00 USD\n"
        "  Assets:Checking\n",
    )
    ledger = Ledger.load(ledger_path)
    template = ledger.recurring_templates[0]
    assert template.transaction.payee == "Landlord"
    assert template.transaction.narration == "Rent"
    assert template.transaction.date == template.first_date == datetime.date(2026, 2, 1)
    accounts = {p.account for p in template.transaction.postings}
    assert accounts == {"Expenses:Rent", "Assets:Checking"}


def test_recurring_templates_recurring_until_sets_end_date(ledger_path):
    append_entry(
        ledger_path,
        '2026-02-01 * "Landlord" "Rent" #recurring\n'
        '  recurring-freq: "monthly"\n'
        '  recurring-until: "2026-12-31"\n'
        "  Expenses:Rent      1450.00 USD\n"
        "  Assets:Checking\n",
    )
    ledger = Ledger.load(ledger_path)
    assert not ledger.errors
    assert len(ledger.recurring_templates) == 1
    assert ledger.recurring_templates[0].until == datetime.date(2026, 12, 31)


def test_recurring_templates_missing_freq_surfaces_as_error_not_crash(ledger_path):
    append_entry(
        ledger_path,
        '2026-02-01 * "Landlord" "Rent" #recurring\n'
        "  Expenses:Rent      1450.00 USD\n"
        "  Assets:Checking\n",
    )
    ledger = Ledger.load(ledger_path)
    assert ledger.recurring_templates == []
    assert len(ledger.errors) == 1
    assert "recurring-freq" in ledger.errors[0].message


def test_recurring_templates_invalid_freq_surfaces_as_error_not_crash(ledger_path):
    append_entry(
        ledger_path,
        '2026-02-01 * "Landlord" "Rent" #recurring\n'
        '  recurring-freq: "fortnightly"\n'
        "  Expenses:Rent      1450.00 USD\n"
        "  Assets:Checking\n",
    )
    ledger = Ledger.load(ledger_path)
    assert ledger.recurring_templates == []
    assert len(ledger.errors) == 1
    assert "fortnightly" in ledger.errors[0].message


def test_recurring_templates_invalid_until_surfaces_as_error_not_crash(ledger_path):
    append_entry(
        ledger_path,
        '2026-02-01 * "Landlord" "Rent" #recurring\n'
        '  recurring-freq: "monthly"\n'
        '  recurring-until: "not-a-date"\n'
        "  Expenses:Rent      1450.00 USD\n"
        "  Assets:Checking\n",
    )
    ledger = Ledger.load(ledger_path)
    assert ledger.recurring_templates == []
    assert len(ledger.errors) == 1
    assert "recurring-until" in ledger.errors[0].message


def test_recurring_templates_invalid_one_does_not_block_valid_ones(ledger_path):
    append_entry(
        ledger_path,
        '2026-02-01 * "Landlord" "Rent" #recurring\n'
        '  recurring-freq: "monthly"\n'
        "  Expenses:Rent      1450.00 USD\n"
        "  Assets:Checking\n"
        "\n"
        '2026-02-05 * "Gym" "Membership" #recurring\n'
        '  recurring-freq: "fortnightly"\n'
        "  Expenses:Rent      20.00 USD\n"
        "  Assets:Checking\n",
    )
    ledger = Ledger.load(ledger_path)
    assert len(ledger.recurring_templates) == 1
    assert ledger.recurring_templates[0].interval == "monthly"
    assert len(ledger.errors) == 1


def test_recurring_templates_ignores_untagged_transactions(ledger_path):
    # A transaction with recurring-freq metadata but no #recurring tag isn't
    # a template at all — the tag is what marks intent, not the metadata's
    # mere presence.
    append_entry(
        ledger_path,
        '2026-02-01 * "Landlord" "Rent"\n'
        '  recurring-freq: "monthly"\n'
        "  Expenses:Rent      1450.00 USD\n"
        "  Assets:Checking\n",
    )
    ledger = Ledger.load(ledger_path)
    assert ledger.recurring_templates == []
    assert not ledger.errors


# --- FORECAST-02: #recurring templates excluded from actual-data reports ---
#
# A #recurring transaction is real Beancount data (see the parsing tests
# above), but it's a template, not something that happened — every report
# that summarizes actual activity must exclude it. Each test below adds a
# #recurring transaction large enough to obviously skew the report if it
# were wrongly included, then asserts the report matches the same baseline
# values the non-recurring tests above already pin down.

_RECURRING_RENT = (
    '2026-02-01 * "Landlord" "Rent" #recurring\n'
    '  recurring-freq: "monthly"\n'
    "  Expenses:Rent      50000.00 USD\n"
    "  Assets:Checking\n"
)


def test_income_statement_excludes_recurring_template(ledger_path):
    append_entry(ledger_path, _RECURRING_RENT)
    ledger = Ledger.load(ledger_path)
    assert not ledger.errors
    stmt = ledger.income_statement()
    # Same totals as test_income_statement_all_dates -- the 50,000.00 USD
    # recurring "Rent" posting must not show up in Expenses:Rent or net.
    assert {a: format_inventory(b) for a, b in stmt.expenses} == {
        "Expenses:Food:Groceries": "87.35 USD",
        "Expenses:Food:Restaurant": "64.20 USD",
        "Expenses:Rent": "1,450.00 USD",
    }
    assert format_inventory(stmt.expenses_total) == "1,601.55 USD"
    assert format_inventory(stmt.net) == "2,598.45 USD"


def test_trial_balance_excludes_recurring_template(ledger_path):
    append_entry(ledger_path, _RECURRING_RENT)
    ledger = Ledger.load(ledger_path)
    assert not ledger.errors
    balances = {
        a: format_inventory(b)
        for a, b in ledger.trial_balance(as_of=datetime.date(2026, 3, 1))
    }
    # Same as test_trial_balance_all_accounts -- Expenses:Rent and
    # Assets:Checking are untouched by the 50,000.00 USD recurring posting.
    assert balances == {
        "Assets:Checking": "4,098.45 USD",
        "Assets:Savings": "1,000.00 USD",
        "Equity:Opening-Balances": "-2,500.00 USD",
        "Expenses:Food:Groceries": "87.35 USD",
        "Expenses:Food:Restaurant": "64.20 USD",
        "Expenses:Rent": "1,450.00 USD",
        "Income:Salary": "-4,200.00 USD",
    }


def test_balance_sheet_excludes_recurring_template(ledger_path):
    append_entry(ledger_path, _RECURRING_RENT)
    ledger = Ledger.load(ledger_path)
    assert not ledger.errors
    sheet = ledger.balance_sheet(as_of=datetime.date(2026, 3, 1))
    # Same as test_balance_sheet_all_accounts -- Assets:Checking would be
    # 50,000.00 USD lower if the recurring posting were wrongly included.
    assert {a: format_inventory(b) for a, b in sheet.assets} == {
        "Assets:Checking": "4,098.45 USD",
        "Assets:Savings": "1,000.00 USD",
    }
    assert format_inventory(sheet.assets_total) == "5,098.45 USD"
    assert format_inventory(sheet.net_income) == "2,598.45 USD"
    assert sheet.assets_total == sheet.liabilities_total + sheet.equity_total + sheet.net_income


def test_register_excludes_recurring_template(ledger_path):
    append_entry(ledger_path, _RECURRING_RENT)
    ledger = Ledger.load(ledger_path)
    assert not ledger.errors
    rows = ledger.register("Assets:Checking")
    # Same sequence as test_register_running_balance -- no extra row for the
    # recurring "Rent" template, and the running balance never dips by
    # 50,000.00 USD.
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


def test_root_account_excludes_recurring_template(ledger_path):
    append_entry(ledger_path, _RECURRING_RENT)
    ledger = Ledger.load(ledger_path)
    assert not ledger.errors
    root = ledger.root_account()
    checking = root["Assets"]["Checking"]
    balance = checking.balance.reduce(lambda pos: pos.units)
    amounts = {(pos.units.number, pos.units.currency) for pos in balance}
    # Same as test_root_account_has_balances -- unaffected by the recurring
    # 50,000.00 USD posting.
    assert amounts == {(Decimal("4098.45"), "USD")}


def test_holdings_excludes_recurring_template(ledger_path):
    append_entry(
        ledger_path,
        "2026-01-01 open Assets:Investments  HOOL\n\n"
        '2026-02-01 * "Broker" "Recurring stock buy" #recurring\n'
        '  recurring-freq: "monthly"\n'
        "  Assets:Investments  10 HOOL {500.00 USD}\n"
        "  Assets:Checking\n",
    )
    ledger = Ledger.load(ledger_path)
    assert not ledger.errors
    report = ledger.holdings(as_of=datetime.date(2026, 3, 1))
    # The recurring costed-lot "buy" must not create a holding.
    assert report.holdings == []
    assert format_inventory(report.net_worth) == ""


def test_ledger_with_only_recurring_template_shows_zero_activity(tmp_path):
    """A ledger with nothing but opens and a #recurring template has no
    actual activity at all -- every report should come back empty/zero,
    even though the template itself is real, parseable transaction data.
    """
    path = tmp_path / "only-template.beancount"
    path.write_text(
        'option "operating_currency" "USD"\n\n'
        "2026-01-01 open Assets:Checking  USD\n"
        "2026-01-01 open Expenses:Rent    USD\n\n"
        '2026-02-01 * "Landlord" "Rent" #recurring\n'
        '  recurring-freq: "monthly"\n'
        "  Expenses:Rent      1450.00 USD\n"
        "  Assets:Checking\n",
        encoding="utf-8",
    )
    ledger = Ledger.load(path)
    assert not ledger.errors
    # The template is real data -- it shows up in the raw transaction list
    # and as a parsed recurring template -- just not in any report below.
    assert len(ledger.transactions) == 1
    assert len(ledger.recurring_templates) == 1

    stmt = ledger.income_statement()
    assert stmt.income == []
    assert stmt.expenses == []
    assert format_inventory(stmt.net) == ""

    assert ledger.trial_balance(as_of=datetime.date(2026, 3, 1)) == []

    sheet = ledger.balance_sheet(as_of=datetime.date(2026, 3, 1))
    assert sheet.assets == []
    assert sheet.liabilities == []
    assert sheet.equity == []
    assert format_inventory(sheet.net_income) == ""

    assert ledger.register("Assets:Checking") == []
    assert ledger.register("Expenses:Rent") == []

    report = ledger.holdings(as_of=datetime.date(2026, 3, 1))
    assert report.holdings == []
    assert format_inventory(report.net_worth) == ""

    root = ledger.root_account()
    checking = root["Assets"]["Checking"]
    assert checking.balance.is_empty()


# --- FORECAST-04: projection engine (virtual instance generation) ---


def test_project_recurring_empty_when_no_templates(ledger_path):
    ledger = Ledger.load(ledger_path)
    projected = ledger.project_recurring(datetime.date(2026, 1, 1), datetime.date(2026, 12, 31))
    assert projected == []


def test_project_recurring_daily(ledger_path):
    append_entry(
        ledger_path,
        '2026-04-01 * "Coffee Shop" "Coffee" #recurring\n'
        '  recurring-freq: "daily"\n'
        "  Expenses:Food:Restaurant  5.00 USD\n"
        "  Assets:Checking\n",
    )
    ledger = Ledger.load(ledger_path)
    assert not ledger.errors
    projected = ledger.project_recurring(datetime.date(2026, 4, 1), datetime.date(2026, 4, 5))
    assert [p.date for p in projected] == [
        datetime.date(2026, 4, 1),
        datetime.date(2026, 4, 2),
        datetime.date(2026, 4, 3),
        datetime.date(2026, 4, 4),
        datetime.date(2026, 4, 5),
    ]


def test_project_recurring_weekly(ledger_path):
    append_entry(
        ledger_path,
        '2026-04-02 * "Gym" "Membership" #recurring\n'
        '  recurring-freq: "weekly"\n'
        "  Expenses:Food:Restaurant  20.00 USD\n"
        "  Assets:Checking\n",
    )
    ledger = Ledger.load(ledger_path)
    assert not ledger.errors
    projected = ledger.project_recurring(datetime.date(2026, 4, 1), datetime.date(2026, 4, 23))
    assert [p.date for p in projected] == [
        datetime.date(2026, 4, 2),
        datetime.date(2026, 4, 9),
        datetime.date(2026, 4, 16),
        datetime.date(2026, 4, 23),
    ]


def test_project_recurring_monthly_across_multi_month_range(ledger_path):
    append_entry(
        ledger_path,
        '2026-01-01 * "Landlord" "Rent" #recurring\n'
        '  recurring-freq: "monthly"\n'
        "  Expenses:Rent      1450.00 USD\n"
        "  Assets:Checking\n",
    )
    ledger = Ledger.load(ledger_path)
    assert not ledger.errors
    projected = ledger.project_recurring(datetime.date(2026, 1, 1), datetime.date(2026, 4, 30))
    assert [p.date for p in projected] == [
        datetime.date(2026, 1, 1),
        datetime.date(2026, 2, 1),
        datetime.date(2026, 3, 1),
        datetime.date(2026, 4, 1),
    ]
    # Payee/narration/postings are reused as-is from the source transaction.
    template = ledger.recurring_templates[0]
    first = projected[0]
    assert isinstance(first, ProjectedTransaction)
    assert first.payee == "Landlord"
    assert first.narration == "Rent"
    assert first.postings == template.transaction.postings
    assert first.template is template


def test_project_recurring_quarterly_across_multi_month_range(ledger_path):
    append_entry(
        ledger_path,
        '2026-01-15 * "Insurer" "Premium" #recurring\n'
        '  recurring-freq: "quarterly"\n'
        "  Expenses:Rent      300.00 USD\n"
        "  Assets:Checking\n",
    )
    ledger = Ledger.load(ledger_path)
    assert not ledger.errors
    projected = ledger.project_recurring(datetime.date(2026, 1, 1), datetime.date(2026, 12, 31))
    assert [p.date for p in projected] == [
        datetime.date(2026, 1, 15),
        datetime.date(2026, 4, 15),
        datetime.date(2026, 7, 15),
        datetime.date(2026, 10, 15),
    ]


def test_project_recurring_yearly_across_multi_year_range(ledger_path):
    append_entry(
        ledger_path,
        '2026-03-01 * "Domain Registrar" "Renewal" #recurring\n'
        '  recurring-freq: "yearly"\n'
        "  Expenses:Rent      15.00 USD\n"
        "  Assets:Checking\n",
    )
    ledger = Ledger.load(ledger_path)
    assert not ledger.errors
    projected = ledger.project_recurring(datetime.date(2026, 1, 1), datetime.date(2028, 12, 31))
    assert [p.date for p in projected] == [
        datetime.date(2026, 3, 1),
        datetime.date(2027, 3, 1),
        datetime.date(2028, 3, 1),
    ]


def test_project_recurring_day_31_clamps_into_february(ledger_path):
    # A monthly template dated the 31st must not skip or crash in February
    # (28 days in 2026, a non-leap year) -- and must snap back to the 31st
    # once a month is long enough again, rather than drifting down forever.
    append_entry(
        ledger_path,
        '2026-01-31 * "Landlord" "Rent" #recurring\n'
        '  recurring-freq: "monthly"\n'
        "  Expenses:Rent      1450.00 USD\n"
        "  Assets:Checking\n",
    )
    ledger = Ledger.load(ledger_path)
    assert not ledger.errors
    projected = ledger.project_recurring(datetime.date(2026, 1, 1), datetime.date(2026, 6, 30))
    assert [p.date for p in projected] == [
        datetime.date(2026, 1, 31),
        datetime.date(2026, 2, 28),
        datetime.date(2026, 3, 31),
        datetime.date(2026, 4, 30),
        datetime.date(2026, 5, 31),
        datetime.date(2026, 6, 30),
    ]


def test_project_recurring_stops_at_recurring_until_even_if_range_extends_further(ledger_path):
    append_entry(
        ledger_path,
        '2026-01-01 * "Landlord" "Rent" #recurring\n'
        '  recurring-freq: "monthly"\n'
        '  recurring-until: "2026-03-31"\n'
        "  Expenses:Rent      1450.00 USD\n"
        "  Assets:Checking\n",
    )
    ledger = Ledger.load(ledger_path)
    assert not ledger.errors
    # Requested range runs through the end of the year, well past the
    # template's own cutoff.
    projected = ledger.project_recurring(datetime.date(2026, 1, 1), datetime.date(2026, 12, 31))
    assert [p.date for p in projected] == [
        datetime.date(2026, 1, 1),
        datetime.date(2026, 2, 1),
        datetime.date(2026, 3, 1),
    ]


def test_project_recurring_until_exactly_on_boundary_is_inclusive(ledger_path):
    append_entry(
        ledger_path,
        '2026-01-01 * "Landlord" "Rent" #recurring\n'
        '  recurring-freq: "monthly"\n'
        '  recurring-until: "2026-03-01"\n'
        "  Expenses:Rent      1450.00 USD\n"
        "  Assets:Checking\n",
    )
    ledger = Ledger.load(ledger_path)
    projected = ledger.project_recurring(datetime.date(2026, 1, 1), datetime.date(2026, 12, 31))
    # The occurrence that lands exactly on recurring-until is included, not
    # excluded.
    assert [p.date for p in projected] == [
        datetime.date(2026, 1, 1),
        datetime.date(2026, 2, 1),
        datetime.date(2026, 3, 1),
    ]


def test_project_recurring_template_starting_after_range_start_only_generates_from_its_own_first_occurrence(
    ledger_path,
):
    append_entry(
        ledger_path,
        '2026-03-01 * "Landlord" "Rent" #recurring\n'
        '  recurring-freq: "monthly"\n'
        "  Expenses:Rent      1450.00 USD\n"
        "  Assets:Checking\n",
    )
    ledger = Ledger.load(ledger_path)
    assert not ledger.errors
    # The requested range starts well before the template's own first_date.
    projected = ledger.project_recurring(datetime.date(2026, 1, 1), datetime.date(2026, 6, 30))
    assert [p.date for p in projected] == [
        datetime.date(2026, 3, 1),
        datetime.date(2026, 4, 1),
        datetime.date(2026, 5, 1),
        datetime.date(2026, 6, 1),
    ]


def test_project_recurring_template_starting_after_range_end_generates_nothing(ledger_path):
    append_entry(
        ledger_path,
        '2026-09-01 * "Landlord" "Rent" #recurring\n'
        '  recurring-freq: "monthly"\n'
        "  Expenses:Rent      1450.00 USD\n"
        "  Assets:Checking\n",
    )
    ledger = Ledger.load(ledger_path)
    assert not ledger.errors
    projected = ledger.project_recurring(datetime.date(2026, 1, 1), datetime.date(2026, 6, 30))
    assert projected == []


def test_project_recurring_covers_multiple_templates_independently(ledger_path):
    append_entry(
        ledger_path,
        '2026-01-01 * "Landlord" "Rent" #recurring\n'
        '  recurring-freq: "monthly"\n'
        "  Expenses:Rent      1450.00 USD\n"
        "  Assets:Checking\n"
        "\n"
        '2026-01-15 * "Insurer" "Premium" #recurring\n'
        '  recurring-freq: "quarterly"\n'
        "  Expenses:Rent      300.00 USD\n"
        "  Assets:Checking\n",
    )
    ledger = Ledger.load(ledger_path)
    assert not ledger.errors
    projected = ledger.project_recurring(datetime.date(2026, 1, 1), datetime.date(2026, 3, 31))
    rent_dates = [p.date for p in projected if p.narration == "Rent"]
    premium_dates = [p.date for p in projected if p.narration == "Premium"]
    assert rent_dates == [
        datetime.date(2026, 1, 1),
        datetime.date(2026, 2, 1),
        datetime.date(2026, 3, 1),
    ]
    assert premium_dates == [datetime.date(2026, 1, 15)]


# FORECAST-05: Ledger.forecast blends explicit template instances with
# budget-fallback figures for accounts a template doesn't cover on a given
# day. The window below (April, chosen to stay clear of example.beancount's
# January actuals) is reused across these tests so template-only,
# budget-only, and neither-only accounts can be checked side by side.


def test_forecast_empty_when_no_templates_or_budgets(ledger_path):
    ledger = Ledger.load(ledger_path)
    assert ledger.forecast(datetime.date(2026, 4, 1), datetime.date(2026, 4, 30)) == []


def test_forecast_template_only_produces_explicit_rows(ledger_path):
    append_entry(
        ledger_path,
        '2026-04-01 * "Landlord" "Rent" #recurring\n'
        '  recurring-freq: "monthly"\n'
        "  Expenses:Rent      1450.00 USD\n"
        "  Assets:Checking\n",
    )
    ledger = Ledger.load(ledger_path)
    assert not ledger.errors
    rows = ledger.forecast(datetime.date(2026, 4, 1), datetime.date(2026, 4, 30))

    rent_rows = [r for r in rows if r.account == "Expenses:Rent"]
    assert rent_rows == [
        ForecastedActivity(
            date=datetime.date(2026, 4, 1),
            account="Expenses:Rent",
            currency="USD",
            amount=Decimal("1450.00"),
            explicit=True,
        )
    ]

    # The auto-balancing Assets:Checking leg is interpolated to a concrete
    # amount by the loader, and shows up as its own explicit row too.
    checking_rows = [r for r in rows if r.account == "Assets:Checking"]
    assert checking_rows == [
        ForecastedActivity(
            date=datetime.date(2026, 4, 1),
            account="Assets:Checking",
            currency="USD",
            amount=Decimal("-1450.00"),
            explicit=True,
        )
    ]


def test_forecast_budget_only_produces_assumed_rows_for_every_day(ledger_path):
    append_entry(
        ledger_path,
        '2026-01-01 custom "budget" Expenses:Food:Groceries "daily" 10.00 USD\n',
    )
    ledger = Ledger.load(ledger_path)
    assert not ledger.errors
    rows = ledger.forecast(datetime.date(2026, 4, 1), datetime.date(2026, 4, 5))

    groceries_rows = [r for r in rows if r.account == "Expenses:Food:Groceries"]
    assert [r.date for r in groceries_rows] == [
        datetime.date(2026, 4, 1),
        datetime.date(2026, 4, 2),
        datetime.date(2026, 4, 3),
        datetime.date(2026, 4, 4),
        datetime.date(2026, 4, 5),
    ]
    assert all(r.amount == Decimal("10.00") for r in groceries_rows)
    assert all(r.explicit is False for r in groceries_rows)
    assert all(r.currency == "USD" for r in groceries_rows)


def test_forecast_account_with_neither_template_nor_budget_projects_nothing(ledger_path):
    # Expenses:Food:Restaurant has no budget or recurring template anywhere
    # in example.beancount.
    append_entry(
        ledger_path,
        '2026-04-01 * "Landlord" "Rent" #recurring\n'
        '  recurring-freq: "monthly"\n'
        "  Expenses:Rent      1450.00 USD\n"
        "  Assets:Checking\n"
        '2026-01-01 custom "budget" Expenses:Food:Groceries "daily" 10.00 USD\n',
    )
    ledger = Ledger.load(ledger_path)
    assert not ledger.errors
    rows = ledger.forecast(datetime.date(2026, 4, 1), datetime.date(2026, 4, 30))
    assert [r for r in rows if r.account == "Expenses:Food:Restaurant"] == []


def test_forecast_template_day_does_not_also_draw_budget_fallback(ledger_path):
    # Expenses:Rent has both a monthly template (firing on the 1st) and a
    # daily budget -- the template's day must not also carry a
    # budget-fallback row, but every other day in the window still should.
    append_entry(
        ledger_path,
        '2026-01-01 custom "budget" Expenses:Rent "daily" 5.00 USD\n'
        '2026-04-01 * "Landlord" "Rent" #recurring\n'
        '  recurring-freq: "monthly"\n'
        "  Expenses:Rent      1450.00 USD\n"
        "  Assets:Checking\n",
    )
    ledger = Ledger.load(ledger_path)
    assert not ledger.errors
    rows = ledger.forecast(datetime.date(2026, 4, 1), datetime.date(2026, 4, 5))
    rent_rows = sorted(
        (r for r in rows if r.account == "Expenses:Rent"), key=lambda r: r.date
    )
    assert [(r.date, r.amount, r.explicit) for r in rent_rows] == [
        (datetime.date(2026, 4, 1), Decimal("1450.00"), True),
        (datetime.date(2026, 4, 2), Decimal("5.00"), False),
        (datetime.date(2026, 4, 3), Decimal("5.00"), False),
        (datetime.date(2026, 4, 4), Decimal("5.00"), False),
        (datetime.date(2026, 4, 5), Decimal("5.00"), False),
    ]


def test_forecast_covers_template_only_budget_only_and_neither_over_same_window(
    ledger_path,
):
    # The three FORECAST-05 acceptance-criteria cases, all in one window:
    # Expenses:Rent has a template but no budget, Expenses:Food:Groceries
    # has a budget but no template, and Expenses:Food:Restaurant has
    # neither.
    append_entry(
        ledger_path,
        '2026-04-01 * "Landlord" "Rent" #recurring\n'
        '  recurring-freq: "monthly"\n'
        "  Expenses:Rent      1450.00 USD\n"
        "  Assets:Checking\n"
        '2026-01-01 custom "budget" Expenses:Food:Groceries "daily" 10.00 USD\n',
    )
    ledger = Ledger.load(ledger_path)
    assert not ledger.errors
    rows = ledger.forecast(datetime.date(2026, 4, 1), datetime.date(2026, 4, 3))
    by_account: dict[str, list[ForecastedActivity]] = {}
    for row in rows:
        by_account.setdefault(row.account, []).append(row)

    # Template-only: one explicit row, on the template's own date.
    assert by_account["Expenses:Rent"] == [
        ForecastedActivity(
            date=datetime.date(2026, 4, 1),
            account="Expenses:Rent",
            currency="USD",
            amount=Decimal("1450.00"),
            explicit=True,
        )
    ]

    # Budget-only: one assumed row per day in the window.
    groceries = sorted(by_account["Expenses:Food:Groceries"], key=lambda r: r.date)
    assert [(r.date, r.amount, r.explicit) for r in groceries] == [
        (datetime.date(2026, 4, 1), Decimal("10.00"), False),
        (datetime.date(2026, 4, 2), Decimal("10.00"), False),
        (datetime.date(2026, 4, 3), Decimal("10.00"), False),
    ]

    # Neither: no rows at all.
    assert "Expenses:Food:Restaurant" not in by_account


def test_forecast_report_blends_real_actual_with_projection(ledger_path):
    # FORECAST-06's fixture: one recurring template (Expenses:Rent, firing
    # 2026-04-20, after "today") plus one budget (Expenses:Food:Groceries,
    # 10.00 USD/day), split at a fixed "today" of 2026-04-15 so the
    # actual/projected boundary is deterministic. A real (non-template)
    # purchase before "today" proves the "actual" side is genuinely real
    # posted activity, not more projection.
    append_entry(
        ledger_path,
        '2026-04-20 * "Landlord" "Rent" #recurring\n'
        '  recurring-freq: "monthly"\n'
        "  Expenses:Rent      1450.00 USD\n"
        "  Assets:Checking\n"
        '2026-01-01 custom "budget" Expenses:Food:Groceries "daily" 10.00 USD\n'
        '2026-04-05 * "Green Grocer" "Early April groceries"\n'
        "  Expenses:Food:Groceries     87.35 USD\n"
        "  Assets:Checking\n",
    )
    ledger = Ledger.load(ledger_path)
    assert not ledger.errors
    today = datetime.date(2026, 4, 15)
    rows = ledger.forecast_report(
        datetime.date(2026, 4, 1), datetime.date(2026, 4, 30), today=today
    )
    by_account = {(r.account, r.currency): r for r in rows}

    # Budget-only: real 87.35 actual (before today) plus 16 days
    # (04-15..04-30 inclusive) of the 10.00/day budget fallback, all
    # "assumed" since no template ever touches this account.
    groceries = by_account["Expenses:Food:Groceries", "USD"]
    assert groceries == ForecastReportRow(
        account="Expenses:Food:Groceries",
        currency="USD",
        actual=Decimal("87.35"),
        projected=Decimal("160.00"),
        status="assumed",
        total=Decimal("247.35"),
    )

    # Template-only: no real Rent activity before today (the template
    # itself is excluded from actual data), and the template's own
    # 2026-04-20 instance is "explicit".
    rent = by_account["Expenses:Rent", "USD"]
    assert rent == ForecastReportRow(
        account="Expenses:Rent",
        currency="USD",
        actual=Decimal("0"),
        projected=Decimal("1450.00"),
        status="explicit",
        total=Decimal("1450.00"),
    )

    # The template's auto-balanced funding leg blends a real actual
    # (-87.35, from the grocery purchase) with an explicit projected
    # (-1450.00, from the rent instance).
    checking = by_account["Assets:Checking", "USD"]
    assert checking == ForecastReportRow(
        account="Assets:Checking",
        currency="USD",
        actual=Decimal("-87.35"),
        projected=Decimal("-1450.00"),
        status="explicit",
        total=Decimal("-1537.35"),
    )

    # Accounts with neither a template nor a budget don't appear at all.
    assert ("Expenses:Food:Restaurant", "USD") not in by_account


def test_forecast_report_entire_range_before_today_has_no_projected_component(
    ledger_path,
):
    # A range that falls entirely before "today" still resolves the same
    # account universe (budgets/templates, independent of the window) but
    # every row is purely "actual" -- there's nothing left to project.
    append_entry(
        ledger_path,
        '2026-01-01 custom "budget" Expenses:Food:Groceries "daily" 10.00 USD\n',
    )
    ledger = Ledger.load(ledger_path)
    assert not ledger.errors
    rows = ledger.forecast_report(
        datetime.date(2026, 1, 1),
        datetime.date(2026, 1, 31),
        today=datetime.date(2026, 4, 15),
    )
    groceries = next(r for r in rows if r.account == "Expenses:Food:Groceries")
    # example.beancount's real 87.35 posting on 2026-01-06 is the only
    # actual activity in this window; no forecast rows since the whole
    # range predates "today".
    assert groceries.actual == Decimal("87.35")
    assert groceries.projected == Decimal("0")
    assert groceries.status == "actual"
    assert groceries.total == Decimal("87.35")
