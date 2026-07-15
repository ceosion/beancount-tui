from decimal import Decimal

from beancount_tui.ledger import Ledger, transaction_amount


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


def test_root_account_has_balances(ledger_path):
    ledger = Ledger.load(ledger_path)
    root = ledger.root_account()
    checking = root["Assets"]["Checking"]
    balance = checking.balance.reduce(lambda pos: pos.units)
    amounts = {(pos.units.number, pos.units.currency) for pos in balance}
    # 2500 + 4200 - 87.35 - 1450 - 64.20 - 1000
    assert amounts == {(Decimal("4098.45"), "USD")}
