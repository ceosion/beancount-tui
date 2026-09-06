"""beangulp importer integration: pure loading/extraction logic, no Textual dependency.

Lets the user point at a plain Python module that defines one or more
`beangulp <https://github.com/beancount/beangulp>`_ ``Importer`` subclasses
(the same kind of "config module" beangulp's own CLI takes, e.g. a
module-level list named ``CONFIG`` or ``importers`` — see beangulp's
``examples/import.py``) plus a source file to run through it. The matching
importer's ``extract()`` produces real Beancount ``data.Transaction``
entries (already fully-formed, with real postings, payee, narration, tags
and links) which are converted here into the same
:class:`~beancount_tui.importer.ImportCandidate` shape the CSV import path
(``importer.py``) produces, so both flow through the same preview, dedup,
and append screens.

Nothing here writes to the ledger or touches Textual; it only builds an
in-memory candidate list (mirroring ``importer.py``'s CSV parsing) or raises
:class:`BeangulpImportError` with a message fit to show directly in the UI.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import beangulp
from beancount.core import data
from beangulp import extract as beangulp_extract

from beancount_tui.importer import ImportCandidate

# Module-level attribute names beangulp config modules conventionally use for
# their list of importer instances. beangulp's own examples/import.py uses
# `importers`; the older beancount.ingest convention (still common in
# existing user configs) uses `CONFIG`.
_CONFIG_ATTR_NAMES = ("CONFIG", "importers", "IMPORTERS")


class BeangulpImportError(Exception):
    """A module/importer problem with a message fit to show in the UI directly.

    Covers every place this integration can fail short of a crash: the
    module path doesn't exist, the module has a syntax/import error, no
    importer (or more than one) matches the source file, or the matched
    importer's own ``identify()``/``extract()`` raises.
    """


def load_importer_module(module_path: Path) -> ModuleType:
    """Load an arbitrary ``.py`` file as a module and return it.

    Raises :class:`BeangulpImportError` (never lets the underlying
    exception propagate) if the path doesn't exist or the module fails to
    import for any reason (syntax error, missing dependency, exception at
    import time, ...).
    """
    module_path = Path(module_path)
    if not module_path.is_file():
        raise BeangulpImportError(f"No such file: {module_path}")

    spec = importlib.util.spec_from_file_location(module_path.stem, module_path)
    if spec is None or spec.loader is None:
        raise BeangulpImportError(f"Could not load {module_path} as a Python module.")

    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001 - any import-time failure is reported, not raised
        raise BeangulpImportError(f"Failed to load importer module {module_path}: {exc}") from exc
    return module


def _find_importers(module: ModuleType) -> list[beangulp.Importer]:
    """Find the module's list of beangulp ``Importer`` instances.

    Looks first for a module-level ``CONFIG``/``importers``/``IMPORTERS``
    attribute (a list, or a single importer), matching beangulp's own
    config-module convention; failing that, scans every module-level
    attribute for ``Importer`` instances (or lists of them), so a
    differently-named config still works.
    """
    for name in _CONFIG_ATTR_NAMES:
        value = getattr(module, name, None)
        if value is None:
            continue
        candidates = value if isinstance(value, (list, tuple)) else [value]
        found = [c for c in candidates if isinstance(c, beangulp.Importer)]
        if found:
            return found

    found = []
    for value in vars(module).values():
        if isinstance(value, beangulp.Importer):
            found.append(value)
        elif isinstance(value, (list, tuple)):
            found.extend(v for v in value if isinstance(v, beangulp.Importer))
    if found:
        return found

    raise BeangulpImportError(
        f"No beangulp Importer instances found in {module.__name__!r} "
        "(expected a module-level list of importers, e.g. `CONFIG = [MyImporter(...)]`)."
    )


def _candidate_from_transaction(
    txn: data.Transaction, row_number: int, account: str
) -> ImportCandidate:
    """Convert a beangulp-extracted transaction into an ``ImportCandidate``.

    ``account``/``amount`` are derived from the posting matching the
    target account (for IMP-03 dedup, which matches on date+amount+account),
    falling back to the transaction's first posting if none matches. The
    full transaction is preserved on ``ImportCandidate.transaction`` so the
    review screen can render it with its real postings intact instead of
    the CSV path's single-posting-plus-placeholder shape.
    """
    amount = None
    matched_account = account
    for posting in txn.postings:
        if posting.account == account and posting.units is not None:
            amount = posting.units.number
            break
    if amount is None and txn.postings:
        first = txn.postings[0]
        if not matched_account:
            matched_account = first.account
        if first.units is not None:
            amount = first.units.number

    return ImportCandidate(
        date=txn.date,
        amount=amount,
        payee=txn.payee or "",
        narration=txn.narration or "",
        account=matched_account or "",
        row_number=row_number,
        transaction=txn,
    )


def extract_candidates(
    module: ModuleType,
    source_file: Path,
    account: str | None = None,
    existing: list[data.Transaction] | None = None,
) -> list[ImportCandidate]:
    """Run the module's matching importer against ``source_file``.

    Finds the single importer (from :func:`_find_importers`) whose
    ``identify()`` returns ``True`` for ``source_file``, calls its
    ``extract()``, and converts every resulting ``data.Transaction`` into
    an :class:`ImportCandidate`. Non-transaction directives (e.g. balance
    assertions some importers also emit) are skipped, since the existing
    review/append flow only handles transactions.

    ``account`` overrides the importer's own declared account (used for
    dedup matching and as a fallback target); if omitted, the importer's
    ``account(filepath)`` is used.

    Raises :class:`BeangulpImportError` — never an uncaught exception from
    the loaded module — if no importer matches, more than one matches, or
    the matched importer raises during ``identify()``/``account()``/
    ``extract()``.
    """
    source_file = Path(source_file)
    if not source_file.is_file():
        raise BeangulpImportError(f"No such file: {source_file}")

    importers = _find_importers(module)
    filepath = str(source_file)

    matches: list[beangulp.Importer] = []
    for imp in importers:
        try:
            if imp.identify(filepath):
                matches.append(imp)
        except Exception as exc:  # noqa: BLE001 - importer bugs must not crash the app
            name = getattr(imp, "name", type(imp).__name__)
            raise BeangulpImportError(
                f"Importer {name} raised an error identifying {source_file}: {exc}"
            ) from exc

    if not matches:
        raise BeangulpImportError(f"No importer in the module matches {source_file}.")
    if len(matches) > 1:
        names = ", ".join(getattr(imp, "name", type(imp).__name__) for imp in matches)
        raise BeangulpImportError(
            f"More than one importer matches {source_file}: {names}."
        )

    importer = matches[0]
    try:
        entries = beangulp_extract.extract_from_file(importer, filepath, list(existing or []))
    except Exception as exc:  # noqa: BLE001 - importer bugs must not crash the app
        name = getattr(importer, "name", type(importer).__name__)
        raise BeangulpImportError(
            f"Importer {name} failed to extract entries from {source_file}: {exc}"
        ) from exc

    target_account = account
    if not target_account:
        try:
            target_account = importer.account(filepath)
        except Exception:  # noqa: BLE001 - account() is best-effort here
            target_account = ""

    candidates: list[ImportCandidate] = []
    row_number = 0
    for entry in entries:
        if not isinstance(entry, data.Transaction):
            continue
        row_number += 1
        candidates.append(_candidate_from_transaction(entry, row_number, target_account or ""))
    return candidates
