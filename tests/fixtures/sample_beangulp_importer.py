"""Minimal beangulp importer fixture, used by tests/test_beangulp_importer.py
and the app-level IMP-04 test in tests/test_app.py.

Identifies exactly one hardcoded file path (a stand-in for a real bank
export) and extracts two fixed, fully-formed transactions with real
multi-posting shapes — exercising the full-fidelity path beangulp import
uses, as opposed to CSV import's single-posting-plus-placeholder shape.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

import beangulp
from beancount.core import data
from beancount.core.amount import Amount

ACCOUNT = "Assets:Checking"


class SampleImporter(beangulp.Importer):
    def identify(self, filepath: str) -> bool:
        return filepath.endswith("sample_bank_export.txt")

    def account(self, filepath: str) -> str:
        return ACCOUNT

    def extract(self, filepath: str, existing: data.Entries) -> data.Entries:
        txn1 = data.Transaction(
            meta=data.new_metadata(filepath, 1),
            date=datetime.date(2026, 2, 1),
            flag="*",
            payee="Coffee Shop",
            narration="Latte",
            tags=frozenset(),
            links=frozenset(),
            postings=[
                data.Posting(ACCOUNT, Amount(Decimal("-4.50"), "USD"), None, None, None, None),
                data.Posting(
                    "Expenses:Food:Restaurant",
                    Amount(Decimal("4.50"), "USD"),
                    None,
                    None,
                    None,
                    None,
                ),
            ],
        )
        txn2 = data.Transaction(
            meta=data.new_metadata(filepath, 2),
            date=datetime.date(2026, 2, 2),
            flag="*",
            payee="Employer",
            narration="Paycheck",
            tags=frozenset(),
            links=frozenset(),
            postings=[
                data.Posting(ACCOUNT, Amount(Decimal("1500.00"), "USD"), None, None, None, None),
                data.Posting(
                    "Income:Salary", Amount(Decimal("-1500.00"), "USD"), None, None, None, None
                ),
            ],
        )
        return [txn1, txn2]


CONFIG = [SampleImporter()]
