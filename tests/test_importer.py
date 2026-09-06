"""Unit tests for the pure CSV-import parsing logic (no Textual pilot)."""

import datetime
from decimal import Decimal
from pathlib import Path

from beancount_tui.importer import (
    CsvColumnMapping,
    ImportCandidate,
    find_duplicate_reason,
    parse_csv,
    preview_csv,
)
from beancount_tui.ledger import Ledger

FIXTURE = Path(__file__).parent / "fixtures" / "sample_import.csv"

MAPPING = CsvColumnMapping(
    date="Date", amount="Amount", payee="Merchant", narration="Description"
)


def test_preview_csv_returns_headers_and_first_rows():
    headers, rows = preview_csv(FIXTURE, max_rows=2)
    assert headers == ["Date", "Amount", "Description", "Merchant"]
    assert len(rows) == 2
    assert rows[0]["Merchant"] == "Corner Cafe"


def test_parse_csv_parses_well_formed_rows():
    candidates = parse_csv(FIXTURE, MAPPING, account="Assets:Checking")
    assert len(candidates) == 5

    first = candidates[0]
    assert first.date == datetime.date(2026, 1, 5)
    assert first.amount == Decimal("-12.50")
    assert first.payee == "Corner Cafe"
    assert first.narration == "Coffee and pastry"
    assert first.account == "Assets:Checking"
    assert first.row_number == 1
    assert first.error is None


def test_parse_csv_reports_malformed_rows_without_failing():
    candidates = parse_csv(FIXTURE, MAPPING, account="Assets:Checking")

    bad_date = candidates[2]
    assert bad_date.row_number == 3
    assert bad_date.date is None
    assert bad_date.amount == Decimal("-20.00")
    assert bad_date.error is not None
    assert "date" in bad_date.error

    bad_amount = candidates[3]
    assert bad_amount.row_number == 4
    assert bad_amount.amount is None
    assert bad_amount.date == datetime.date(2026, 1, 8)
    assert bad_amount.error is not None
    assert "amount" in bad_amount.error

    # The rows around the malformed ones still parsed correctly: one bad
    # row doesn't take down the rest of the import.
    good_rows = [c for c in candidates if c.error is None]
    assert len(good_rows) == 3


def test_parse_csv_without_payee_or_narration_mapping():
    mapping = CsvColumnMapping(date="Date", amount="Amount")
    candidates = parse_csv(FIXTURE, mapping, account="Assets:Checking")
    assert all(c.payee == "" and c.narration == "" for c in candidates)


def test_find_duplicate_reason_matches_existing_fixture_entry(ledger_path):
    """The fixture CSV's Green Grocer row (2026-01-06, -87.35, Assets:Checking)
    matches an entry already present in the example ledger — same date, same
    amount posted to the same account — so it should be flagged as a likely
    duplicate, with a human-readable reason naming the existing entry."""
    ledger = Ledger.load(ledger_path)
    existing = ledger.transactions_for_account(None)

    candidates = parse_csv(FIXTURE, MAPPING, account="Assets:Checking")
    green_grocer = candidates[1]
    assert green_grocer.date == datetime.date(2026, 1, 6)
    assert green_grocer.amount == Decimal("-87.35")

    reason = find_duplicate_reason(green_grocer, existing)
    assert reason is not None
    assert "2026-01-06" in reason
    assert "Weekly groceries" in reason


def test_find_duplicate_reason_no_match_for_different_amount(ledger_path):
    ledger = Ledger.load(ledger_path)
    existing = ledger.transactions_for_account(None)

    candidate = ImportCandidate(
        date=datetime.date(2026, 1, 6),
        amount=Decimal("-99.99"),
        payee="Green Grocer",
        narration="Weekly groceries",
        account="Assets:Checking",
        row_number=1,
    )
    assert find_duplicate_reason(candidate, existing) is None


def test_find_duplicate_reason_no_match_for_different_account(ledger_path):
    ledger = Ledger.load(ledger_path)
    existing = ledger.transactions_for_account(None)

    candidate = ImportCandidate(
        date=datetime.date(2026, 1, 6),
        amount=Decimal("-87.35"),
        payee="Green Grocer",
        narration="Weekly groceries",
        account="Assets:Savings",
        row_number=1,
    )
    assert find_duplicate_reason(candidate, existing) is None


def test_find_duplicate_reason_none_without_parsed_date_or_amount():
    incomplete = ImportCandidate(
        date=None,
        amount=Decimal("-87.35"),
        payee="",
        narration="",
        account="Assets:Checking",
        row_number=1,
        error="invalid date",
    )
    assert find_duplicate_reason(incomplete, []) is None
