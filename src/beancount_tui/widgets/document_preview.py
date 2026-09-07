"""Modal document preview: view a ``document`` directive's referenced file
without leaving the TUI (RPT-11).

Beancount resolves a ``Document`` directive's ``filename`` to an absolute
path before it ever reaches the TUI (see ``transaction_table._entry_row``),
so this module works purely in terms of that already-resolved ``Path``.
"""

from __future__ import annotations

import datetime
from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Label, Static

# Extensions treated as text without needing to sniff content -- the common
# cases an accounting ledger's `document` directives point at.
_TEXT_EXTENSIONS = {".txt", ".md", ".csv", ".json", ".log", ".yaml", ".yml", ".tsv"}

# How much of a text file to decode/show. A preview doesn't need the whole
# file, and reading an arbitrarily large one in full would make the TUI
# sluggish (or exhaust memory) for a huge attachment.
_MAX_PREVIEW_BYTES = 200_000

# How many leading bytes to sniff when an extension isn't on the allowlist.
_SNIFF_BYTES = 8192


def _looks_like_text(sample: bytes) -> bool:
    """A quick binary sniff: no NUL bytes, and decodes cleanly as UTF-8.

    Good enough to separate "plain text we can show" from "binary/unknown
    format we shouldn't try to dump" without pulling in a dedicated
    file-type-detection dependency.
    """
    if b"\x00" in sample:
        return False
    try:
        sample.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def _format_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{int(value)} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def _format_metadata(path: Path) -> str:
    stat = path.stat()
    modified = datetime.datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    return f"Size: {_format_size(stat.st_size)}\nModified: {modified}"


def render_document_preview(path: Path) -> str:
    """Render the plain-text preview body for a `document` directive's file.

    - A missing file is reported without attempting to read it.
    - Text-like files (by extension allowlist, or a decode-attempt sniff
      for everything else) show their contents, truncated if huge.
    - Anything else (binary/unsupported) shows basic file metadata (size,
      modified time) instead of attempting to dump raw bytes.

    The result is plain text, never Rich markup -- file contents may
    contain ``[``/``]`` that would otherwise be misread as markup tags.
    """
    if not path.exists():
        return f"File not found: {path}"

    metadata = _format_metadata(path)

    try:
        raw = path.read_bytes()
    except OSError as exc:
        return f"{metadata}\n\nCould not read file: {exc}"

    is_text_extension = path.suffix.lower() in _TEXT_EXTENSIONS
    if is_text_extension or _looks_like_text(raw[:_SNIFF_BYTES]):
        try:
            text = raw[:_MAX_PREVIEW_BYTES].decode("utf-8")
        except UnicodeDecodeError:
            # Extension said text, content sniff disagrees (e.g. a
            # mislabeled binary file) -- fall back to metadata rather than
            # risk a garbled/undecodable dump.
            return f"{metadata}\n\n(binary or unsupported file -- preview unavailable)"
        if len(raw) > _MAX_PREVIEW_BYTES:
            text += "\n\n... (truncated)"
        return text if text else "(empty file)"

    return f"{metadata}\n\n(binary or unsupported file -- preview unavailable)"


class DocumentPreviewScreen(ModalScreen[None]):
    """Preview a `document` directive's referenced file; Escape closes it."""

    BINDINGS = [("escape", "cancel", "Close")]

    DEFAULT_CSS = """
    DocumentPreviewScreen {
        align: center middle;
    }
    DocumentPreviewScreen > Vertical {
        width: 96;
        height: auto;
        max-height: 90%;
        border: round $primary;
        padding: 1 2;
        background: $surface;
    }
    DocumentPreviewScreen #body {
        height: auto;
        max-height: 30;
        margin-top: 1;
    }
    """

    def __init__(self, path: Path) -> None:
        super().__init__()
        self._path = path

    def compose(self) -> ComposeResult:
        with Vertical():
            # markup=False here too: a file path could (rarely) contain
            # `[`/`]` and shouldn't be misread as Rich markup either.
            yield Label(f"Document: {self._path}", markup=False)
            with VerticalScroll(id="body"):
                # markup=False: file contents are shown verbatim, not parsed
                # as Rich markup (a document could legitimately contain
                # `[`/`]`).
                yield Static(render_document_preview(self._path), id="preview", markup=False)

    def action_cancel(self) -> None:
        self.dismiss(None)
