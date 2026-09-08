"""Synthetic large-ledger generator for PERF-01's benchmark fixture.

Produces a plain-text Beancount ledger with a configurable number of
transactions spread across a small, realistic personal-finance account
tree (a handful of Asset/Liability/Income/Expense leaf accounts) and a
wide date range. The output is ordinary Beancount syntax written to a
file and parsed by the *real* ``beancount.loader`` -- there is no
synthetic shortcut that bypasses parsing.

Run directly to write a ledger to disk for manual inspection::

    uv run python benchmarks/generate_large_ledger.py /tmp/large.beancount -n 20000

See ``benchmarks/bench_perf01.py`` for the timing harness that consumes
this generator.
"""

from __future__ import annotations

import argparse
import random
from datetime import date, timedelta
from pathlib import Path

# A handful of leaf accounts per top-level account type -- enough to
# form a realistic-looking personal-finance account tree without
# needing hundreds of accounts for `AccountTree`/`realization.realize`
# to have a meaningfully-sized hierarchy to walk.
ASSET_ACCOUNTS = [
    "Assets:Checking",
    "Assets:Savings",
    "Assets:Brokerage",
]
LIABILITY_ACCOUNTS = [
    "Liabilities:CreditCard",
]
INCOME_ACCOUNTS = [
    "Income:Salary",
    "Income:Freelance",
    "Income:Interest",
]
EXPENSE_ACCOUNTS = [
    "Expenses:Food:Groceries",
    "Expenses:Food:Restaurant",
    "Expenses:Rent",
    "Expenses:Utilities",
    "Expenses:Transport",
    "Expenses:Entertainment",
    "Expenses:Health",
    "Expenses:Shopping",
    "Expenses:Travel",
    "Expenses:Insurance",
]

ALL_ACCOUNTS = [
    *ASSET_ACCOUNTS,
    *LIABILITY_ACCOUNTS,
    *INCOME_ACCOUNTS,
    *EXPENSE_ACCOUNTS,
]

PAYEES = [
    "Acme Corp", "Green Grocer", "City Power & Light", "MetroTransit",
    "Lively Bistro", "Cornerstone Realty", "Streamflix", "Wellness Clinic",
    "Style Outlet", "Skyline Airlines", "SafeGuard Insurance", "QuickMart",
    "Java House", "Fresh Fields Market", "TechHub",
]

# (kind, relative weight) -- "expense" dominates like a real ledger's mix
# of many small purchases against a few large recurring items.
_KINDS = ["salary", "freelance", "interest", "rent", "transfer", "expense"]
_WEIGHTS = [8, 4, 3, 12, 8, 65]


def _random_transaction(rng: random.Random, day: date) -> str:
    """Render one balanced two-posting transaction dated ``day``.

    Only one posting's amount is given; the other is elided so
    Beancount auto-balances it -- the same convention this project's
    own test fixtures (``tests/conftest.py``) use, rather than
    hand-computing both legs.
    """
    kind = rng.choices(_KINDS, weights=_WEIGHTS)[0]
    payee = rng.choice(PAYEES)

    if kind == "salary":
        amount = rng.uniform(2800, 5200)
        narration = "Salary"
        lines = f"  Assets:Checking  {amount:.2f} USD\n  Income:Salary\n"
    elif kind == "freelance":
        amount = rng.uniform(200, 1800)
        narration = "Freelance payment"
        lines = f"  Assets:Checking  {amount:.2f} USD\n  Income:Freelance\n"
    elif kind == "interest":
        amount = rng.uniform(1, 40)
        narration = "Interest"
        lines = f"  Assets:Savings  {amount:.2f} USD\n  Income:Interest\n"
    elif kind == "rent":
        amount = rng.uniform(1100, 1900)
        narration = "Monthly rent"
        lines = f"  Expenses:Rent  {amount:.2f} USD\n  Assets:Checking\n"
    elif kind == "transfer":
        amount = rng.uniform(100, 1500)
        destination = rng.choice(["Assets:Savings", "Assets:Brokerage"])
        narration = "Transfer"
        lines = f"  {destination}  {amount:.2f} USD\n  Assets:Checking\n"
    else:  # expense
        account = rng.choice(EXPENSE_ACCOUNTS)
        source = rng.choice(["Assets:Checking", "Liabilities:CreditCard"])
        amount = rng.uniform(4, 220)
        narration = "Purchase"
        lines = f"  {account}  {amount:.2f} USD\n  {source}\n"

    return f'{day.isoformat()} * "{payee}" "{narration}"\n{lines}'


def generate_large_ledger(
    path: str | Path,
    num_transactions: int = 20_000,
    start_date: date = date(2011, 1, 1),
    span_days: int = 15 * 365,
    seed: int = 20260101,
) -> Path:
    """Write a synthetic Beancount ledger of ``num_transactions`` entries to ``path``.

    Deterministic given ``seed`` (fixed default) so repeated benchmark
    runs are comparable to each other. Every account's ``open`` directive
    is dated ``start_date`` and listed before any transaction; transaction
    dates are then spread evenly across ``[start_date, start_date +
    span_days]`` -- at the default 20,000-transactions-over-15-years
    scale that's a handful of transactions per day, reading like ordinary
    day-to-day personal-finance activity rather than one entry a year.

    Returns ``path`` (as a ``Path``) for convenient chaining.
    """
    path = Path(path)
    rng = random.Random(seed)

    lines: list[str] = [
        'option "title" "Synthetic Large Ledger"\n',
        'option "operating_currency" "USD"\n',
        "\n",
    ]
    for account in ALL_ACCOUNTS:
        lines.append(f"{start_date.isoformat()} open {account}  USD\n")
    lines.append("\n")

    for i in range(num_transactions):
        day_offset = (i * span_days) // max(num_transactions, 1)
        day = start_date + timedelta(days=day_offset)
        lines.append(_random_transaction(rng, day))
        lines.append("\n")

    path.write_text("".join(lines), encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="Path to write the generated ledger to")
    parser.add_argument(
        "-n", "--num-transactions", type=int, default=20_000,
        help="Number of transactions to generate (default: 20000)",
    )
    args = parser.parse_args()
    generate_large_ledger(args.output, num_transactions=args.num_transactions)
    print(f"Wrote {args.num_transactions} transactions to {args.output}")


if __name__ == "__main__":
    main()
