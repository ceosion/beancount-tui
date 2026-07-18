from decimal import Decimal

from beancount_tui.ledger import Ledger, filter_transactions, transaction_amount


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


def test_transaction_amount(ledger_path):
    ledger = Ledger.load(ledger_path)
    rent = ledger.transactions_for_account("Expenses:Rent")[0]
    assert transaction_amount(rent) == "1450.00 USD"


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


def test_root_account_has_balances(ledger_path):
    ledger = Ledger.load(ledger_path)
    root = ledger.root_account()
    checking = root["Assets"]["Checking"]
    balance = checking.balance.reduce(lambda pos: pos.units)
    amounts = {(pos.units.number, pos.units.currency) for pos in balance}
    # 2500 + 4200 - 87.35 - 1450 - 64.20 - 1000
    assert amounts == {(Decimal("4098.45"), "USD")}
