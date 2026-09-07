"""Mutating operations on the ledger source files.

Beancount's library is read-only, so all edits happen at the text level:
new entries are appended to the ledger file, and edited entries replace
the original source lines located via the ``filename``/``lineno`` metadata
that Beancount attaches to every entry it parses.
"""

from __future__ import annotations

import re
from pathlib import Path

from beancount.core import data
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
