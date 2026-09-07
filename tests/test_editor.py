import pytest
from beancount.core import data

from beancount_tui.editor import (
    SimplePosting,
    TransactionParseError,
    append_entry,
    decompose_postings_text,
    delete_entry,
    entry_line_span,
    parse_directive_text,
    parse_directives_text,
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


def test_parse_directive_text_valid():
    directive = parse_directive_text("2026-01-20 open Assets:Cash USD\n")
    assert directive.account == "Assets:Cash"


def test_parse_directive_text_rejects_multiple():
    with pytest.raises(TransactionParseError, match="exactly one"):
        parse_directive_text("2026-01-20 open Assets:Cash\n2026-01-21 open Assets:Bank\n")


def test_parse_directives_text_returns_each_directive():
    # Used for combined text blocks (e.g. a `pad` immediately followed by
    # its `balance` assertion) that `parse_directive_text` would otherwise
    # reject for holding more than one directive. Beancount's parser sorts
    # its output (by its own SORT_ORDER, not source order), so check by
    # type rather than by position.
    entries = parse_directives_text(
        "2026-01-20 pad Assets:Checking Equity:Opening-Balances\n"
        "2026-01-20 balance Assets:Checking  100.00 USD\n"
    )
    assert len(entries) == 2
    assert {type(entry) for entry in entries} == {data.Pad, data.Balance}


def test_parse_directives_text_syntax_error():
    with pytest.raises(TransactionParseError):
        parse_directives_text("2026-01-20 pad Assets:Checking\n")


def test_parse_transaction_text_rejects_non_transaction():
    with pytest.raises(TransactionParseError, match="transaction"):
        parse_transaction_text("2026-01-20 open Assets:Cash USD\n")


def test_replace_non_transaction_entry(ledger_path):
    ledger = Ledger.load(ledger_path)
    note = next(e for e in ledger.directives if isinstance(e, data.Note))
    replace_entry(note, '2026-01-16 note Assets:Checking "Updated note"\n')
    ledger.reload()
    assert not ledger.errors
    note = next(e for e in ledger.directives if isinstance(e, data.Note))
    assert note.comment == "Updated note"


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


def test_append_entry(ledger_path):
    append_entry(ledger_path, NEW_TXN)
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


def test_delete_entry(ledger_path):
    ledger = Ledger.load(ledger_path)
    rent = ledger.transactions_for_account("Expenses:Rent")[0]
    delete_entry(rent)
    ledger.reload()
    assert not ledger.errors
    assert len(ledger.transactions) == 5
    assert not ledger.transactions_for_account("Expenses:Rent")
    # The entry's separating blank line goes with it — no doubled blanks left.
    assert "\n\n\n" not in ledger_path.read_text()


def test_delete_last_entry_in_file(ledger_path):
    ledger = Ledger.load(ledger_path)
    delete_entry(ledger.transactions[-1])
    ledger.reload()
    assert not ledger.errors
    assert len(ledger.transactions) == 5


# UX-08: `decompose_postings_text` is the shared source of truth the
# structured postings UX uses to decide whether raw posting text can be
# represented as rows, and to load it if so.


def test_decompose_postings_text_simple():
    postings = decompose_postings_text(
        "Expenses:Food:Restaurant  4.50 USD\nAssets:Checking"
    )
    assert postings == [
        SimplePosting("Expenses:Food:Restaurant", "4.50", "USD"),
        SimplePosting("Assets:Checking"),
    ]


def test_decompose_postings_text_empty():
    assert decompose_postings_text("") == []
    assert decompose_postings_text("   \n  \n") == []


def test_decompose_postings_text_rejects_cost_basis():
    assert (
        decompose_postings_text(
            "Assets:Brokerage  10 HOOL {500.00 USD}\nAssets:Cash"
        )
        is None
    )


def test_decompose_postings_text_rejects_price_annotation():
    assert (
        decompose_postings_text("Assets:Cash  -25.00 USD @ 1.10 EUR\nAssets:Foreign")
        is None
    )


def test_decompose_postings_text_rejects_flag():
    assert (
        decompose_postings_text("! Assets:Pending  5.00 USD\nAssets:Checking") is None
    )


def test_decompose_postings_text_rejects_metadata():
    assert (
        decompose_postings_text(
            'Assets:Cash  5.00 USD\n  key: "value"\nAssets:Checking'
        )
        is None
    )


def test_decompose_postings_text_syntax_error():
    assert decompose_postings_text("not an account or amount") is None


def test_simple_posting_to_line():
    assert SimplePosting("Assets:Checking").to_line() == "Assets:Checking"
    assert (
        SimplePosting("Expenses:Food", "4.50", "USD").to_line()
        == "Expenses:Food  4.50 USD"
    )
