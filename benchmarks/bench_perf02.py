"""PERF-02 benchmark: measures the saving from caching ``Ledger.root_account()``.

Before PERF-02, ``root_account()`` re-ran ``realization.realize()`` from
scratch on every call, and today's app calls it up to 3x per user action
(``app.refresh_views``, ``action_balance_directive``,
``action_pad_and_verify`` -- see ``planning/performance.md``). This script
measures both sides directly against the same synthetic large ledger
PERF-01 introduced (``generate_large_ledger.py``):

- "before" -- 3 independent, uncached ``realization.realize(entries)``
  calls (what ``root_account()`` used to do every time it was called).
- "after"  -- 3 calls to ``Ledger.root_account()`` on the same ``Ledger``
  instance (what the app actually does today): the first call populates
  the cache, the second and third are cache hits.

Standalone script, not part of the default ``pytest -q`` suite -- same
reasoning as ``bench_perf01.py`` (wall-clock timing at 20,000+
transactions is slow and would disproportionately slow the everyday test
loop). Run it manually::

    uv run python benchmarks/bench_perf02.py
    uv run python benchmarks/bench_perf02.py --num-transactions 50000
"""

from __future__ import annotations

import argparse
import tempfile
import time
from pathlib import Path

from beancount.core import realization

from generate_large_ledger import generate_large_ledger

from beancount_tui.ledger import Ledger


def run(num_transactions: int) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        # Throwaway ledger file under a tempdir -- never touches
        # examples/example.beancount or any tracked fixture.
        ledger_path = Path(tmp) / "large.beancount"
        generate_large_ledger(ledger_path, num_transactions=num_transactions)

        ledger = Ledger.load(ledger_path)
        assert not ledger.errors
        assert len(ledger.transactions) == num_transactions

        # "Before": 3 independent, uncached realize() passes -- what
        # root_account() used to do on every one of its (up to 3) calls
        # per user action.
        entries = ledger._actual_entries
        start = time.perf_counter()
        for _ in range(3):
            realization.realize(entries)
        before_elapsed = time.perf_counter() - start

        # "After": 3 calls to the real, now-cached root_account() on the
        # same Ledger instance -- exactly what refresh_views +
        # action_balance_directive + action_pad_and_verify do today.
        start = time.perf_counter()
        for _ in range(3):
            ledger.root_account()
        after_elapsed = time.perf_counter() - start

        print(f"num_transactions:                       {num_transactions}")
        print(f"3x uncached realize() (before PERF-02):  {before_elapsed:.4f}s")
        print(f"3x root_account() calls (after PERF-02): {after_elapsed:.4f}s")
        saving = before_elapsed - after_elapsed
        pct = (saving / before_elapsed * 100) if before_elapsed else 0.0
        print(f"saving:                                  {saving:.4f}s ({pct:.1f}%)")


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
