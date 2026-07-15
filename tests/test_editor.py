import pytest

from beancount_tui.editor import (
    TransactionParseError,
    append_transaction,
    entry_line_span,
    parse_transaction_text,
    replace_entry,
)
from beancount_tui.ledger import Ledger

NEW_TXN = """\
2026-01-20 * "Corner Cafe" "Coffee"
  Expenses:Food:Restaurant  4.50 USD
  Assets:Checking
"""


def test_parse_transaction_text_valid():
    txn = parse_transaction_text(NEW_TXN)
    assert txn.payee == "Corner Cafe"
    assert len(txn.postings) == 2


def test_parse_transaction_text_syntax_error():
    with pytest.raises(TransactionParseError):
        parse_transaction_text('2026-01-20 * "broken\n  Assets:Checking  1 USD\n')


def test_parse_transaction_text_rejects_multiple_entries():
    with pytest.raises(TransactionParseError, match="exactly one"):
        parse_transaction_text(NEW_TXN + "\n" + NEW_TXN)


def test_entry_line_span():
    lines = [
        '2026-01-01 * "One"\n',
        "  Assets:A  1 USD\n",
        "  Assets:B\n",
        "\n",
        '2026-01-02 * "Two"\n',
    ]
    assert entry_line_span(lines, 0) == 3
    assert entry_line_span(lines, 4) == 1


def test_append_transaction(ledger_path):
    append_transaction(ledger_path, NEW_TXN)
    ledger = Ledger.load(ledger_path)
    assert not ledger.errors
    assert len(ledger.transactions) == 7
    assert ledger.transactions[-1].payee == "Corner Cafe"


def test_replace_entry(ledger_path):
    ledger = Ledger.load(ledger_path)
    rent = ledger.transactions_for_account("Expenses:Rent")[0]
    replace_entry(
        rent,
        '2026-01-10 * "Landlord" "January rent (corrected)"\n'
        "  Expenses:Rent  1500.00 USD\n"
        "  Assets:Checking\n",
    )
    ledger.reload()
    assert not ledger.errors
    assert len(ledger.transactions) == 6
    rent = ledger.transactions_for_account("Expenses:Rent")[0]
    assert rent.narration == "January rent (corrected)"
    assert str(rent.postings[0].units.number) == "1500.00"
