"""Unit tests for the pure beangulp importer integration (IMP-04), no
Textual pilot: loading a config module and running its matching importer
against a source file."""

from decimal import Decimal
from pathlib import Path

import pytest

from beancount_tui.beangulp_importer import (
    BeangulpImportError,
    extract_candidates,
    load_importer_module,
)

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE_MODULE = FIXTURES / "sample_beangulp_importer.py"
SAMPLE_SOURCE = FIXTURES / "sample_bank_export.txt"
BROKEN_MODULE = FIXTURES / "broken_beangulp_importer.py"
NO_CONFIG_MODULE = FIXTURES / "no_config_beangulp_importer.py"
CSV_FIXTURE = FIXTURES / "sample_import.csv"


def test_extract_candidates_end_to_end():
    module = load_importer_module(SAMPLE_MODULE)
    candidates = extract_candidates(module, SAMPLE_SOURCE)
    assert len(candidates) == 2

    first = candidates[0]
    assert first.payee == "Coffee Shop"
    assert first.narration == "Latte"
    assert first.account == "Assets:Checking"
    assert first.amount == Decimal("-4.50")
    assert first.row_number == 1
    assert first.error is None
    # The full beangulp-extracted transaction is preserved, postings intact,
    # not squashed into the CSV path's single-posting-plus-placeholder shape.
    assert first.transaction is not None
    assert len(first.transaction.postings) == 2
    assert first.transaction.postings[1].account == "Expenses:Food:Restaurant"

    second = candidates[1]
    assert second.payee == "Employer"
    assert second.narration == "Paycheck"
    assert second.amount == Decimal("1500.00")
    assert second.row_number == 2


def test_extract_candidates_honors_explicit_account_override():
    module = load_importer_module(SAMPLE_MODULE)
    candidates = extract_candidates(module, SAMPLE_SOURCE, account="Assets:Checking")
    assert all(c.account == "Assets:Checking" for c in candidates)


def test_extract_candidates_no_matching_importer():
    module = load_importer_module(SAMPLE_MODULE)
    with pytest.raises(BeangulpImportError, match="No importer"):
        extract_candidates(module, CSV_FIXTURE)


def test_extract_candidates_missing_source_file():
    module = load_importer_module(SAMPLE_MODULE)
    with pytest.raises(BeangulpImportError, match="No such file"):
        extract_candidates(module, FIXTURES / "does_not_exist.txt")


def test_load_importer_module_missing_file():
    with pytest.raises(BeangulpImportError, match="No such file"):
        load_importer_module(FIXTURES / "does_not_exist.py")


def test_load_importer_module_syntax_error():
    with pytest.raises(BeangulpImportError, match="Failed to load"):
        load_importer_module(BROKEN_MODULE)


def test_extract_candidates_module_with_no_importers():
    module = load_importer_module(NO_CONFIG_MODULE)
    with pytest.raises(BeangulpImportError, match="No beangulp Importer"):
        extract_candidates(module, SAMPLE_SOURCE)
