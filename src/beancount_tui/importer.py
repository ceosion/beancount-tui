"""CSV import: pure parsing logic, no Textual dependency.

Reads a CSV file, maps its columns to date/amount/payee/narration, and
produces a list of :class:`ImportCandidate` rows for a target account.
Malformed rows (a date or amount that fails to parse) still produce a
candidate — with ``error`` set — rather than aborting the whole import, so
one bad row in a bank export doesn't block the rest.

This module only builds the in-memory candidate list; nothing here writes
to the ledger (that's a later stage). It also exposes
:func:`find_duplicate_reason`, a pure date+amount(+account) check against a
list of already-loaded transactions, used by the review screen to flag
candidates that look like they're already in the ledger.
"""

from __future__ import annotations

import csv
import datetime
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

from beancount.core import data


@dataclass
class CsvColumnMapping:
    """Which CSV column headers supply which transaction fields.

    ``payee``/``narration`` are optional: a CSV without a payee column, for
    instance, can leave that field unmapped and every candidate gets an
    empty payee.
    """

    date: str
    amount: str
    payee: str | None = None
    narration: str | None = None


@dataclass
class ImportCandidate:
    """A single parsed CSV row, not yet a real Beancount transaction.

    ``date``/``amount`` are ``None`` when the source cell failed to parse;
    the row is still returned, with ``error`` describing what went wrong,
    so the caller can show it to the user instead of silently dropping it.
    """

    date: datetime.date | None
    amount: Decimal | None
    payee: str
    narration: str
    account: str
    row_number: int
    error: str | None = None


def preview_csv(path: Path, max_rows: int = 5) -> tuple[list[str], list[dict[str, str]]]:
    """Return ``(headers, rows)`` for the first ``max_rows`` data rows of ``path``.

    Used to show the user a preview before they commit to a column mapping.
    """
    with Path(path).open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        headers = list(reader.fieldnames or [])
        rows: list[dict[str, str]] = []
        for row in reader:
            if len(rows) >= max_rows:
                break
            rows.append(dict(row))
    return headers, rows


def parse_csv(path: Path, mapping: CsvColumnMapping, account: str) -> list[ImportCandidate]:
    """Parse every row of ``path`` into a list of :class:`ImportCandidate`.

    A row with an unparseable date or amount is still included, with
    ``error`` set describing the problem, rather than raising or being
    dropped — so a single malformed row never fails the whole import.
    """
    candidates: list[ImportCandidate] = []
    with Path(path).open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row_number, row in enumerate(reader, start=1):
            candidates.append(_parse_row(row, row_number, mapping, account))
    return candidates


def _parse_row(
    row: dict[str, str | None],
    row_number: int,
    mapping: CsvColumnMapping,
    account: str,
) -> ImportCandidate:
    problems: list[str] = []

    date_text = (row.get(mapping.date) or "").strip()
    date: datetime.date | None
    try:
        date = datetime.date.fromisoformat(date_text)
    except ValueError:
        date = None
        problems.append(f"invalid date {date_text!r}")

    amount_text = (row.get(mapping.amount) or "").strip()
    amount: Decimal | None
    try:
        amount = Decimal(amount_text)
    except InvalidOperation:
        amount = None
        problems.append(f"invalid amount {amount_text!r}")

    payee = (row.get(mapping.payee) or "").strip() if mapping.payee else ""
    narration = (row.get(mapping.narration) or "").strip() if mapping.narration else ""

    return ImportCandidate(
        date=date,
        amount=amount,
        payee=payee,
        narration=narration,
        account=account,
        row_number=row_number,
        error="; ".join(problems) or None,
    )


def find_duplicate_reason(
    candidate: ImportCandidate, existing: list[data.Transaction]
) -> str | None:
    """Human-readable reason if ``candidate`` looks like it's already in the ledger.

    Matches by date + amount posted to the candidate's target account: if any
    transaction in ``existing`` has a posting on ``candidate.account`` dated
    exactly ``candidate.date`` with a numerically identical amount to
    ``candidate.amount``, that's almost certainly the same real-world
    transaction (e.g. importing the same bank statement twice), so a reason
    string is returned describing which existing entry it matches. Matching is
    exact (no fuzzing of date or amount) — keeping it simple and predictable.

    Returns ``None`` if the candidate has no parsed date/amount (already
    flagged separately via ``error``) or no match is found.
    """
    if candidate.date is None or candidate.amount is None:
        return None
    for txn in existing:
        if txn.date != candidate.date:
            continue
        for posting in txn.postings:
            if posting.account != candidate.account:
                continue
            if posting.units is None or posting.units.number is None:
                continue
            if posting.units.number == candidate.amount:
                label = txn.narration or txn.payee or "entry"
                return f"possible duplicate of {txn.date.isoformat()} {label}"
    return None
