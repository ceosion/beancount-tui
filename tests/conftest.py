import shutil
from pathlib import Path

import pytest

EXAMPLE = Path(__file__).parent.parent / "examples" / "example.beancount"


@pytest.fixture
def ledger_path(tmp_path: Path) -> Path:
    """A throwaway copy of the example ledger, safe to mutate."""
    path = tmp_path / "ledger.beancount"
    shutil.copy(EXAMPLE, path)
    return path


@pytest.fixture
def multi_ledger_path(tmp_path: Path) -> Path:
    """A throwaway two-file ledger: main.beancount includes food.beancount."""
    main = tmp_path / "main.beancount"
    food = tmp_path / "food.beancount"
    main.write_text(
        'option "title" "Multi-file Ledger"\n'
        'option "operating_currency" "USD"\n'
        "\n"
        'include "food.beancount"\n'
        "\n"
        "2026-01-01 open Assets:Checking          USD\n"
        "2026-01-01 open Income:Salary            USD\n"
        "2026-01-01 open Expenses:Food:Groceries  USD\n"
        "\n"
        '2026-01-05 * "Acme Corp" "Salary"\n'
        "  Assets:Checking  4200.00 USD\n"
        "  Income:Salary\n",
        encoding="utf-8",
    )
    food.write_text(
        '2026-01-06 * "Green Grocer" "Weekly groceries"\n'
        "  Expenses:Food:Groceries  87.35 USD\n"
        "  Assets:Checking\n",
        encoding="utf-8",
    )
    return main
