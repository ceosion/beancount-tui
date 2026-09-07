"""Shared CSV/JSON export helpers for BQL query results (``EXPORT-01``).

Every report/query result in beancount-tui was view-only before this
module: rendered into an on-screen ``DataTable`` via
:func:`beancount_tui.ledger.format_query_value`, with no way to get the
data back out. That formatting function is deliberately lossy for export
purposes -- it collapses ``Decimal``/``Inventory``/``Amount``/``Position``
cells into comma-grouped, human-readable strings meant for on-screen
reading (e.g. an ``Inventory`` becomes ``"1,234.56 USD"``, a bare
``Decimal`` becomes ``"1,234.56"`` with thousands separators baked in).

These helpers instead work from :class:`~beancount_tui.ledger.QueryResult`'s
*raw* ``columns``/``rows`` -- the actual typed values beanquery hands
back (``str``, ``Decimal``, ``datetime.date``, ``Inventory``, ``Position``,
``Amount``, ``None`` for SQL NULL, etc.) -- and render them for each
target format on its own terms:

* CSV is text-only anyway, so per-cell ``str()`` is fine there (see
  :func:`_csv_cell`) -- it happens to produce *non*-comma-grouped numbers
  (``str(Decimal("1234.56"))`` is ``"1234.56"``), which is actually a nicer
  property for a machine-readable export than what the on-screen
  formatter produces.
* JSON gets values closer to their real types where that's
  straightforward (see :func:`_json_cell`): a bare ``Decimal`` becomes a
  JSON *string* (not a float -- floats would silently round e.g.
  ``9999999999999.99``), a ``datetime.date`` becomes its ISO string, and
  ``Amount``/``Position``/``Inventory`` become small JSON objects/lists
  carrying ``number`` (as a string, same reasoning) and ``currency``
  rather than a flattened display string.
"""

from __future__ import annotations

import csv
import datetime
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from beancount.core import data, position
from beancount.core.inventory import Inventory


def _csv_cell(value: object) -> str:
    """Render one cell as plain text for a CSV file.

    ``None`` (SQL NULL) becomes an empty cell, matching
    ``format_query_value``'s convention; everything else is ``str()``'d,
    which for ``Decimal`` gives an exact, non-comma-grouped number and for
    Beancount's own value types (``Inventory``, ``Position``, ``Amount``)
    gives their own reasonably compact ``__str__``.
    """
    if value is None:
        return ""
    return str(value)


def _amount_to_json(amount: data.Amount) -> dict[str, str]:
    return {"number": str(amount.number), "currency": amount.currency}


def _position_to_json(pos: position.Position) -> dict[str, Any]:
    result: dict[str, Any] = _amount_to_json(pos.units)
    if pos.cost is not None:
        result["cost"] = {"number": str(pos.cost.number), "currency": pos.cost.currency}
    return result


def _json_cell(value: object) -> object:
    """Render one cell as a JSON-serializable value, staying close to its
    real type rather than collapsing it to a display string.

    - ``None`` (SQL NULL) stays ``None`` (JSON ``null``).
    - ``Decimal`` becomes a JSON *string* of its exact value, avoiding the
      float rounding that ``json.dumps`` would otherwise apply.
    - ``datetime.date``/``datetime.datetime`` becomes an ISO date string.
    - ``Inventory`` becomes a list of per-position objects (see below).
    - ``Position``/``Amount`` become ``{"number": "<str>", "currency": ...}``
      objects (``Position`` additionally nests a ``"cost"`` object if the
      position is held at cost).
    - Anything else (``str``, ``int``, ``bool``, ...) passes through
      unchanged -- already JSON-native.
    """
    if value is None:
        return None
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime.date):
        return value.isoformat()
    if isinstance(value, Inventory):
        return [_position_to_json(pos) for pos in value]
    if isinstance(value, position.Position):
        return _position_to_json(value)
    if isinstance(value, data.Amount):
        return _amount_to_json(value)
    return value


def write_csv(columns: list[str], rows: list[tuple], path: str | Path) -> None:
    """Write ``columns``/``rows`` (a :class:`~beancount_tui.ledger.QueryResult`'s
    raw fields) to ``path`` as CSV, with ``columns`` as the header row.

    Assumes the parent directory of ``path`` already exists and that any
    "would overwrite an existing file" confirmation has already happened
    -- both are the caller's responsibility (see
    ``QueryRunnerScreen._do_export``), so this simply opens ``path`` for
    writing and lets any ``OSError`` propagate.
    """
    path = Path(path)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(columns)
        for row in rows:
            writer.writerow([_csv_cell(cell) for cell in row])


def write_json(columns: list[str], rows: list[tuple], path: str | Path) -> None:
    """Write ``columns``/``rows`` to ``path`` as a JSON array of row objects,
    each keyed by column name, in column order.

    Same parent-directory/overwrite assumptions as :func:`write_csv`.
    """
    path = Path(path)
    records = [
        {col: _json_cell(cell) for col, cell in zip(columns, row, strict=True)}
        for row in rows
    ]
    with path.open("w", encoding="utf-8") as fh:
        json.dump(records, fh, indent=2)
        fh.write("\n")
