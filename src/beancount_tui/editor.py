"""Mutating operations on the ledger source files.

Beancount's library is read-only, so all edits happen at the text level:
new entries are appended to the ledger file, and edited entries replace
the original source lines located via the ``filename``/``lineno`` metadata
that Beancount attaches to every entry it parses.
"""

from __future__ import annotations

from pathlib import Path

from beancount.core import data
from beancount.parser import parser, printer


class TransactionParseError(Exception):
    """The text entered by the user is not a single valid transaction."""


def parse_transaction_text(text: str) -> data.Transaction:
    """Parse user-entered text into exactly one transaction.

    Raises :class:`TransactionParseError` with a readable message if the text
    has syntax errors or does not contain exactly one transaction.
    """
    entries, errors, _ = parser.parse_string(text)
    if errors:
        messages = "; ".join(error.message for error in errors)
        raise TransactionParseError(messages)
    transactions = [e for e in entries if isinstance(e, data.Transaction)]
    if len(entries) != 1 or len(transactions) != 1:
        raise TransactionParseError("Expected exactly one transaction.")
    return transactions[0]


def format_entry(entry: data.Directive) -> str:
    """Canonically format a loaded entry back into Beancount source text."""
    return printer.format_entry(entry)


def entry_line_span(lines: list[str], start_index: int) -> int:
    """Number of source lines the entry starting at ``start_index`` occupies.

    An entry is its first line plus every following line that is indented
    (postings, metadata, indented comments). A blank or non-indented line
    ends the entry.
    """
    count = 1
    for line in lines[start_index + 1 :]:
        if line.strip() and line[0] in (" ", "\t"):
            count += 1
        else:
            break
    return count


def append_transaction(path: str | Path, text: str) -> None:
    """Append transaction ``text`` to the end of the ledger file."""
    path = Path(path)
    existing = path.read_text(encoding="utf-8")
    separator = "" if existing.endswith("\n\n") or not existing else "\n"
    if existing and not existing.endswith("\n"):
        separator = "\n\n"
    path.write_text(existing + separator + text.rstrip("\n") + "\n", encoding="utf-8")


def replace_entry(entry: data.Directive, new_text: str) -> None:
    """Replace ``entry``'s source lines with ``new_text`` in its source file."""
    filename = entry.meta["filename"]
    lineno = entry.meta["lineno"]
    path = Path(filename)
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    start = lineno - 1
    span = entry_line_span(lines, start)
    replacement = [line + "\n" for line in new_text.rstrip("\n").split("\n")]
    lines[start : start + span] = replacement
    path.write_text("".join(lines), encoding="utf-8")
