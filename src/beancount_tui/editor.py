"""Mutating operations on the ledger source files.

Beancount's library is read-only, so all edits happen at the text level:
new entries are appended to the ledger file, and edited entries replace
the original source lines located via the ``filename``/``lineno`` metadata
that Beancount attaches to every entry it parses.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from beancount.core import data
from beancount.core.number import MISSING
from beancount.parser import parser, printer


class TransactionParseError(Exception):
    """The text entered by the user is not a single valid transaction."""


def parse_directives_text(text: str) -> list[data.Directive]:
    """Parse user-entered text into however many directives it contains.

    Raises :class:`TransactionParseError` with a readable message if the text
    has syntax errors. Unlike :func:`parse_directive_text`, this does not
    require exactly one directive — it's used where a form intentionally
    holds more than one (e.g. a `pad` directive immediately followed by its
    `balance` assertion), so each can still be validated with the real
    Beancount parser rather than skipped.
    """
    entries, errors, _ = parser.parse_string(text)
    if errors:
        messages = "; ".join(error.message for error in errors)
        raise TransactionParseError(messages)
    return entries


def parse_directive_text(text: str) -> data.Directive:
    """Parse user-entered text into exactly one directive of any type.

    Raises :class:`TransactionParseError` with a readable message if the text
    has syntax errors or does not contain exactly one directive.
    """
    entries = parse_directives_text(text)
    if len(entries) != 1:
        raise TransactionParseError("Expected exactly one directive.")
    return entries[0]


def parse_transaction_text(text: str) -> data.Transaction:
    """Parse user-entered text into exactly one transaction.

    Raises :class:`TransactionParseError` with a readable message if the text
    has syntax errors or does not contain exactly one transaction.
    """
    entry = parse_directive_text(text)
    if not isinstance(entry, data.Transaction):
        raise TransactionParseError("Expected exactly one transaction.")
    return entry


@dataclass
class SimplePosting:
    """A posting representable in the structured postings UX (UX-08):
    just an account and an optional amount/currency -- no cost basis, price
    annotation, posting flag, or metadata.
    """

    account: str
    amount: str = ""
    currency: str = ""

    def to_line(self) -> str:
        """This posting as one ``PostingsArea`` source line, formatted
        ``ACCOUNT  AMOUNT CURRENCY`` (matching the raw view's convention: a
        double space separating the account from the amount, a single space
        between the amount and its currency)."""
        line = self.account
        if self.amount:
            line += f"  {self.amount}"
            if self.currency:
                line += f" {self.currency}"
        return line


def decompose_postings_text(postings_text: str) -> list[SimplePosting] | None:
    """Try to decompose raw posting-lines text into `SimplePosting`s.

    Used by the structured postings UX (UX-08) to load rows from the
    raw-text ``PostingsArea``'s content when the user toggles views. Parses
    ``postings_text`` with the real Beancount parser (wrapped in a throwaway
    transaction header) rather than a bespoke line-format regex, so this
    stays in exact agreement with what :func:`parse_transaction_text` will
    later accept at save time -- one source of truth for what's valid,
    shared by both the raw and structured views.

    Returns ``None`` if any posting can't be represented structurally --
    it has a cost basis (``{...}``), a price annotation (``@``), a posting
    flag, or metadata -- so the caller can keep the raw-text view active
    instead of losing or corrupting that posting's syntax.
    """
    body = "\n".join(
        "  " + line.strip() for line in postings_text.splitlines() if line.strip()
    )
    if not body:
        return []
    placeholder = f'1970-01-01 * ""\n{body}\n'
    try:
        entry = parse_transaction_text(placeholder)
    except TransactionParseError:
        return None
    result = []
    for posting in entry.postings:
        if posting.cost is not None or posting.price is not None or posting.flag is not None:
            return None
        extra_meta = {k for k in (posting.meta or {}) if k not in ("filename", "lineno")}
        if extra_meta:
            return None
        if posting.units is MISSING:
            result.append(SimplePosting(posting.account))
        else:
            result.append(
                SimplePosting(
                    posting.account, str(posting.units.number), posting.units.currency
                )
            )
    return result


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


def append_entry(path: str | Path, text: str) -> None:
    """Append entry ``text`` (any directive type) to the end of the ledger file."""
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


# Matches a transaction header's leading ``date  flag`` (the flag is always
# exactly one non-whitespace character per Beancount's grammar).
_TXN_HEADER_FLAG_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}\s+)(\S)(?=\s|$)")


def replace_flag(entry: data.Transaction, new_flag: str) -> None:
    """Swap `entry`'s flag character in place, touching only that one
    character in its source file.

    Unlike `replace_entry`, this doesn't re-serialize the whole entry via
    `format_entry`/`printer.format_entry` -- which fills in Beancount's
    interpolated amounts for any posting whose amount was elided in the
    source, changing more than just the flag. Locating and replacing the
    single character in place keeps the rest of the entry's source text
    byte-for-byte unchanged.
    """
    filename = entry.meta["filename"]
    lineno = entry.meta["lineno"]
    path = Path(filename)
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    index = lineno - 1
    line = lines[index]
    match = _TXN_HEADER_FLAG_RE.match(line)
    if not match:
        raise TransactionParseError(
            f"Could not locate a flag character on line {lineno} of {filename}"
        )
    start, end = match.start(2), match.end(2)
    lines[index] = line[:start] + new_flag + line[end:]
    path.write_text("".join(lines), encoding="utf-8")


def delete_entry(entry: data.Directive) -> None:
    """Remove ``entry``'s source lines from its source file."""
    filename = entry.meta["filename"]
    lineno = entry.meta["lineno"]
    path = Path(filename)
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    start = lineno - 1
    end = start + entry_line_span(lines, start)
    if end < len(lines) and not lines[end].strip():
        end += 1  # take the separating blank line with the entry
    del lines[start:end]
    path.write_text("".join(lines), encoding="utf-8")
