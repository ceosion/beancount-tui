"""PERF-01 baseline benchmark: timing coverage for the three operations
named in `planning/performance.md` -- full `Ledger.load`,
`TransactionTable.update_entries`, and `AccountTree.update_accounts` --
against a synthetic large ledger (see `generate_large_ledger.py`).

This is a standalone script, deliberately NOT part of the default
`pytest -q` suite: wall-clock timing at 20,000+ transactions is slow
(multiple seconds) and would disproportionately slow down the everyday
test loop if it ran on every `pytest` invocation. Run it manually::

    uv run python benchmarks/bench_perf01.py
    uv run python benchmarks/bench_perf01.py --num-transactions 50000

The numbers this prints are what PERF-02/PERF-03/PERF-04 should cite as
their "before" baseline -- see `planning/performance.md`'s "Baseline (as
of PERF-01)" section for the run recorded there.
"""

from __future__ import annotations

import argparse
import asyncio
import tempfile
import time
from pathlib import Path

from textual.app import App, ComposeResult
from textual.widgets import DataTable

from generate_large_ledger import generate_large_ledger
from rich.text import Text

from beancount_tui.ledger import Ledger
from beancount_tui.widgets.account_tree import AccountTree
from beancount_tui.widgets.transaction_table import TransactionTable


class _BenchApp(App):
    """Minimal host app -- just enough for the two widgets under test to
    be mounted and running, mirroring how `BeancountTUI` itself hosts
    them (see `src/beancount_tui/app.py`)."""

    def compose(self) -> ComposeResult:
        yield AccountTree(id="sidebar")
        yield TransactionTable(id="transactions")


def _header_selected(table: TransactionTable, column_index: int) -> DataTable.HeaderSelected:
    """Build a real `HeaderSelected` message for `column_index`, the same
    way a header click would (mirrors `tests/test_app.py`'s helper of the
    same name)."""
    column_key = list(table.columns.keys())[column_index]
    return DataTable.HeaderSelected(table, column_key, column_index, Text("header"))


async def _time_widgets(ledger: Ledger) -> tuple[float, float, float, float]:
    """Time `TransactionTable.update_entries` and `AccountTree.update_accounts`
    against `ledger`, run inside a real (headless) Textual app -- both
    widgets rely on being mounted (e.g. `DataTable.add_row`, `Tree.add`
    both touch app-level state), so a bare unmounted widget instance
    isn't a faithful stand-in for how the real app drives them.

    Also times PERF-04's sort-toggle case two ways against the *same*
    already-shown entry set: once through the normal (optimized) code path
    -- a header click, which reorders existing rows in place -- and once
    by directly invoking the old-style full rebuild (`_rebuild_rows`) on
    the identical data, so the two numbers are directly comparable as a
    genuine before/after for the one thing PERF-04 targets."""
    app = _BenchApp()
    async with app.run_test() as pilot:
        table = app.query_one(TransactionTable)
        tree = app.query_one(AccountTree)

        start = time.perf_counter()
        table.update_entries(ledger.directives)
        table_elapsed = time.perf_counter() - start

        # PERF-04 "after": a sort toggle (date ascending -> date descending)
        # on the exact same entry set already shown -- takes the
        # reorder-in-place path (see `TransactionTable._can_reorder_in_place`).
        start = time.perf_counter()
        table.on_data_table_header_selected(_header_selected(table, 0))
        sort_reorder_elapsed = time.perf_counter() - start

        # PERF-04 "before": what the old clear()+rebuild path costs for the
        # *identical* reorder (same entries, same running-balance state) --
        # calling the full-rebuild helper directly, bypassing the new
        # fast path, for a genuine apples-to-apples comparison.
        start = time.perf_counter()
        table._rebuild_rows(table.shown, table._running_balances, table._cleared_balances)
        sort_rebuild_elapsed = time.perf_counter() - start

        root = ledger.root_account()
        start = time.perf_counter()
        tree.update_accounts(root, ledger)
        tree_elapsed = time.perf_counter() - start

        await pilot.pause()
    return table_elapsed, tree_elapsed, sort_reorder_elapsed, sort_rebuild_elapsed


def run(num_transactions: int) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        # Throwaway ledger file under a tempdir -- never touches
        # examples/example.beancount or any tracked fixture.
        ledger_path = Path(tmp) / "large.beancount"

        gen_start = time.perf_counter()
        generate_large_ledger(ledger_path, num_transactions=num_transactions)
        gen_elapsed = time.perf_counter() - gen_start
        print(f"generate_large_ledger(n={num_transactions}): {gen_elapsed:.3f}s")

        start = time.perf_counter()
        ledger = Ledger.load(ledger_path)
        load_elapsed = time.perf_counter() - start
        print(
            f"Ledger.load:                    {load_elapsed:.3f}s "
            f"({len(ledger.entries)} entries, {len(ledger.errors)} errors)"
        )
        # Proves the generator produces a ledger that loads cleanly
        # through the real parser -- not just that it runs without
        # raising.
        assert not ledger.errors, f"generated ledger had load errors: {ledger.errors}"
        assert len(ledger.transactions) == num_transactions

        table_elapsed, tree_elapsed, sort_reorder_elapsed, sort_rebuild_elapsed = (
            asyncio.run(_time_widgets(ledger))
        )
        print(
            f"TransactionTable.update_entries: {table_elapsed:.3f}s "
            f"({len(ledger.directives)} rows)"
        )
        print(f"AccountTree.update_accounts:      {tree_elapsed:.3f}s")
        print(
            f"PERF-04 sort-toggle (reorder-in-place, after):  "
            f"{sort_reorder_elapsed:.3f}s"
        )
        print(
            f"PERF-04 sort-toggle (clear()+rebuild, before):  "
            f"{sort_rebuild_elapsed:.3f}s"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-n", "--num-transactions", type=int, default=20_000,
        help="Number of transactions in the generated ledger (default: 20000)",
    )
    args = parser.parse_args()
    run(args.num_transactions)


if __name__ == "__main__":
    main()
