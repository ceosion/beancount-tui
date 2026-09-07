"""Tests for the shared CSV/JSON export helpers (EXPORT-01)."""

from __future__ import annotations

import csv
import datetime
import json
from decimal import Decimal

from beancount.core import data
from beancount.core.inventory import Inventory

from beancount_tui.export import write_csv, write_json
from beancount_tui.ledger import Ledger


def _make_inventory(*amounts: tuple[str, str]) -> Inventory:
    inv = Inventory()
    for number, currency in amounts:
        inv.add_amount(data.Amount(Decimal(number), currency))
    return inv


def test_write_csv_basic_types(tmp_path):
    columns = ["account", "total", "opened", "note"]
    rows = [
        ("Assets:Checking", Decimal("1234.56"), datetime.date(2026, 1, 1), None),
    ]
    path = tmp_path / "out.csv"
    write_csv(columns, rows, path)

    with path.open(newline="", encoding="utf-8") as fh:
        rows_read = list(csv.reader(fh))

    assert rows_read[0] == columns
    # Decimal renders as a plain, non-comma-grouped number; None (SQL NULL)
    # renders as an empty cell, not the string "None"; dates are ISO.
    assert rows_read[1] == ["Assets:Checking", "1234.56", "2026-01-01", ""]


def test_write_csv_inventory_and_position(tmp_path):
    inv = _make_inventory(("10.00", "USD"), ("5.00", "EUR"))
    pos = next(iter(inv))
    columns = ["inventory", "position"]
    rows = [(inv, pos)]
    path = tmp_path / "out.csv"
    write_csv(columns, rows, path)

    with path.open(newline="", encoding="utf-8") as fh:
        rows_read = list(csv.reader(fh))

    assert rows_read[0] == columns
    inventory_cell, position_cell = rows_read[1]
    assert "USD" in inventory_cell and "EUR" in inventory_cell
    assert position_cell == str(pos)


def test_write_json_basic_types(tmp_path):
    columns = ["account", "total", "opened", "note"]
    rows = [
        ("Assets:Checking", Decimal("1234.56"), datetime.date(2026, 1, 1), None),
    ]
    path = tmp_path / "out.json"
    write_json(columns, rows, path)

    records = json.loads(path.read_text(encoding="utf-8"))
    assert records == [
        {
            "account": "Assets:Checking",
            "total": "1234.56",
            "opened": "2026-01-01",
            "note": None,
        }
    ]
    # Decimal must be a JSON string, not a (potentially rounding) float.
    assert isinstance(records[0]["total"], str)


def test_write_json_decimal_preserves_exact_value(tmp_path):
    """A Decimal that a JSON float would mangle round-trips exactly as a string."""
    columns = ["n"]
    rows = [(Decimal("9999999999999.99"),)]
    path = tmp_path / "out.json"
    write_json(columns, rows, path)

    raw = path.read_text(encoding="utf-8")
    assert '"9999999999999.99"' in raw
    records = json.loads(raw)
    assert records[0]["n"] == "9999999999999.99"


def test_write_json_amount_inventory_and_position(tmp_path):
    amount = data.Amount(Decimal("42.00"), "USD")
    inv = _make_inventory(("10.00", "USD"), ("5.00", "EUR"))
    pos = next(iter(inv))
    columns = ["amount", "inventory", "position"]
    rows = [(amount, inv, pos)]
    path = tmp_path / "out.json"
    write_json(columns, rows, path)

    records = json.loads(path.read_text(encoding="utf-8"))
    row = records[0]
    assert row["amount"] == {"number": "42.00", "currency": "USD"}
    currencies = {item["currency"] for item in row["inventory"]}
    assert currencies == {"USD", "EUR"}
    assert row["position"] == {"number": "10.00", "currency": "USD"}


def test_write_json_multiple_rows_preserve_order(tmp_path):
    columns = ["a", "b"]
    rows = [(1, "x"), (2, "y"), (3, "z")]
    path = tmp_path / "out.json"
    write_json(columns, rows, path)

    records = json.loads(path.read_text(encoding="utf-8"))
    assert records == [
        {"a": 1, "b": "x"},
        {"a": 2, "b": "y"},
        {"a": 3, "b": "z"},
    ]


def test_export_matches_known_query_result(ledger_path, tmp_path):
    """CSV and JSON export of a real query's raw columns/rows against the
    example ledger, matching the known Assets:Checking balance used
    elsewhere in the test suite (see test_app.py's query runner tests).
    """
    ledger = Ledger.load(ledger_path)
    result = ledger.run_query(
        "SELECT account, sum(position) AS total GROUP BY account"
    )

    csv_path = tmp_path / "out.csv"
    json_path = tmp_path / "out.json"
    write_csv(result.columns, result.rows, csv_path)
    write_json(result.columns, result.rows, json_path)

    with csv_path.open(newline="", encoding="utf-8") as fh:
        csv_rows = {row[0]: row[1] for row in csv.reader(fh) if row and row[0] != "account"}
    assert csv_rows["Assets:Checking"] == "(4098.45 USD)"

    records = json.loads(json_path.read_text(encoding="utf-8"))
    by_account = {rec["account"]: rec["total"] for rec in records}
    assert by_account["Assets:Checking"] == [{"number": "4098.45", "currency": "USD"}]
