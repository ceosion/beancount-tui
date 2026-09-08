# Performance at scale (`PERF`)

Untested on large ledgers today. Every reload (`Ledger.load`/`reload`) is
a fully synchronous `loader.load_file` call on the UI thread — no
async/threading anywhere near it (`action_reload`, `action_undo`/
`action_redo`, and the polling `_check_external_changes` all call it
inline). `AccountTree`/`TransactionTable` both fully rebuild on every
refresh (`self.clear()` + re-add everything), and `Ledger.root_account()`
re-runs `realization.realize()` from scratch on every call — up to 3
times per user action (`refresh_views`, `action_balance_directive`,
`action_pad_and_verify`) — with no caching, unlike `_price_map_cached`'s
existing cache-until-reload pattern for price lookups. There is no
benchmark/perf test anywhere in the suite, so nothing currently proves any
of this is actually slow or measures whether a fix helps — that's why
`PERF-01` comes first, and why `PERF-02`-`PERF-04` all depend on it: their
acceptance criteria should cite actual before/after numbers, not "should
be faster."

---

### PERF-01: Large-ledger benchmark fixture

- **Status:** done
- **Depends on:** none
- **Effort:** 1.5h

**Description:** Add a synthetic large-ledger generator (tens of
thousands of transactions across a realistic account tree) as a test
fixture, plus timing coverage — either timing-asserting tests with
generous thresholds, or a standalone benchmark script (e.g. under a
`benchmarks/` directory, run manually rather than in CI if wall-clock
timing is too flaky for the regular suite) — covering: full `Ledger.load`,
`TransactionTable.update_entries` for the full entry set, and
`AccountTree.update_accounts`. This establishes a measurable baseline
before any of `PERF-02`-`PERF-04` land.

**Acceptance criteria:**
- [x] A generator produces a synthetic ledger of a configurable size (e.g.
      20,000+ transactions) that loads cleanly through the real Beancount
      parser.
- [x] Load, table-render, and tree-render timings are captured against
      the generated ledger.
- [x] Baseline numbers are documented (in the task/PR, not necessarily
      committed as a file) for `PERF-02`-`PERF-04` to compare against.
- [x] Test/benchmark infrastructure runs without disproportionately
      slowing the default test run (keep large-ledger timing out of the
      fast/default suite if needed).

**Implementation notes:** Went with the standalone-script option, not
timing-asserting `pytest` tests — wall-clock thresholds for a 20k+-entry
parse are exactly the kind of flaky-under-CI-load assertion the task
description warns about, and a script keeps this fully out of the
default `pytest -q` run (verified: default suite wall-clock is
unchanged — see below — vs. adding a skip-by-default marker that could
still be accidentally included).

- `benchmarks/generate_large_ledger.py` — `generate_large_ledger(path,
  num_transactions=20_000, ...)` writes a plain-text Beancount ledger:
  a small realistic account tree (3 Asset, 1 Liability, 3 Income, 10
  Expense leaf accounts), one `open` per account dated at the start of
  a configurable date span (default 15 years), then `num_transactions`
  balanced two-posting transactions (one leg's amount given, the other
  elided so Beancount auto-balances it — the same convention
  `tests/conftest.py`'s fixtures already use) with dates spread evenly
  across the span and a weighted mix of transaction kinds (salary,
  freelance, interest, rent, transfers, everyday expenses) so it reads
  like real activity rather than one repeated template. Deterministic
  via a fixed `seed` default, so repeated runs are comparable. No
  synthetic shortcut bypasses the parser — the file is real Beancount
  syntax loaded through `Ledger.load` -> `loader.load_file` like any
  other ledger.
- `benchmarks/bench_perf01.py` — generates a throwaway ledger under a
  `tempfile.TemporaryDirectory()` (never touches
  `examples/example.beancount` or any tracked fixture), then times, in
  order: `Ledger.load`, `TransactionTable.update_entries(ledger.directives)`,
  and `AccountTree.update_accounts(ledger.root_account(), ledger)`,
  inside a real (headless, `run_test()`) Textual app — both widgets
  touch app-level state (`DataTable.add_row`, `Tree.add`) and aren't
  faithfully exercised unmounted. Asserts the generated ledger loaded
  with zero errors and the expected transaction count, so a run also
  double-checks the generator's "loads cleanly" acceptance criterion
  every time it's invoked. Run via:
  `uv run python benchmarks/bench_perf01.py [-n NUM_TRANSACTIONS]`.

**Baseline (as of PERF-01, 2026-09-07, this machine):**

Default `uv run pytest -q` run (359 tests, unaffected by this task since
none of the above lives in `tests/`): **89.98s** before and after this
change — no measurable regression.

`uv run python benchmarks/bench_perf01.py -n 20000`:

| Operation | Time | Notes |
|---|---|---|
| `generate_large_ledger` | 0.023s | fixture generation itself, not part of the "app" baseline |
| `Ledger.load` | **0.408s** | 20,017 entries (20,000 txns + 17 opens), 0 errors |
| `TransactionTable.update_entries` | **0.171s** | all 20,017 rows, full `clear()` + rebuild |
| `AccountTree.update_accounts` | **~0.000s** | see note below |

`uv run python benchmarks/bench_perf01.py -n 50000` (larger scale, to see trend):

| Operation | Time |
|---|---|
| `Ledger.load` | **1.535s** (50,017 entries) |
| `TransactionTable.update_entries` | **0.443s** (50,017 rows) |
| `AccountTree.update_accounts` | **~0.000s** |

Both `Ledger.load` and `TransactionTable.update_entries` scale
roughly linearly with transaction count (as expected: a full re-parse
and a full `clear()`+`add_row` rebuild each touch every entry).
`AccountTree.update_accounts` stays flat regardless of transaction
count in this fixture — it walks the *realized account tree*, whose
node count is bounded by the number of distinct accounts (17 in this
fixture), not the number of postings, so it's cheap by construction
here. `PERF-04` targets `TransactionTable`'s rebuild cost, not
`AccountTree`'s, which matches this: the account tree isn't the
expensive rebuild path at this fixture's account-count scale, and a
future benchmark run with a much wider (not just deeper) account tree
would be a more meaningful stress test for `AccountTree` specifically
if that ever becomes a target.

Additional context for `PERF-02` (not one of the three named
operations, but directly relevant to its "cache `root_account()`"
scope): a single `ledger.root_account()` call (`realization.realize()`
under the hood) on the 20,000-transaction ledger took **~0.03-0.05s**
per call across 3 repeated calls with no caching — consistent with
`realize()` doing real work every time rather than being dominated by
one-time setup cost. At up to 3 calls per user action today (per this
file's intro), that's roughly 0.1-0.15s of avoidable repeated work per
action on a ledger this size — the concrete number `PERF-02` should
cite as its "before."

---

### PERF-02: Cache `Ledger.root_account()`/realization

- **Status:** todo
- **Depends on:** PERF-01
- **Effort:** 1h

**Description:** `Ledger.root_account()` re-runs
`realization.realize(self._actual_entries)` from scratch on every call,
with no caching — unlike `_price_map_cached`, which explicitly caches
until reload. It's called at least 3 times per user action across
`refresh_views`, `action_balance_directive`, and `action_pad_and_verify`.
Cache the realized tree the same way `_price_map_cached` already does
(invalidate on `reload`/any write), so repeated calls within the same
ledger state reuse one `realize()` pass instead of repeating it.

**Acceptance criteria:**
- [ ] `root_account()` returns a cached result across repeated calls
      within the same load, invalidated correctly on reload/write.
- [ ] `action_balance_directive`/`action_pad_and_verify` no longer trigger
      extra `realize()` passes beyond what `refresh_views` already did.
- [ ] Test covering: cache hit on repeated calls, cache invalidation after
      `reload()`.
- [ ] `PERF-01`'s benchmark shows a measurable improvement for actions
      that previously triggered multiple realizations.

---

### PERF-03: Move ledger load/reload off the UI thread

- **Status:** todo
- **Depends on:** PERF-01
- **Effort:** 2h

**Description:** Every reload path (`action_reload`, `action_undo`/
`action_redo`, the polling `_check_external_changes`) calls
`loader.load_file` inline on the UI thread, blocking the whole app for the
duration of a full re-parse with no progress indicator or cancellation.
Move the `loader.load_file` call to a Textual worker (`@work`/
`run_worker`, thread-mode since `beancount.loader` is synchronous
CPU-bound code, not asyncio-friendly), showing a lightweight
"reloading..." indicator while it runs, and applying the result back on
the main thread when done. Handle reentrancy — a reload triggered while
one is already in flight (e.g. the watch-interval timer firing again
before a slow prior reload finishes) should be coalesced/ignored rather
than stacking concurrent reloads against the same `Ledger` instance.

**Acceptance criteria:**
- [ ] The UI remains responsive (e.g. cursor movement, scrolling) while a
      large ledger reloads in the background.
- [ ] A visible indicator shows a reload is in progress.
- [ ] A reload triggered while one is already running doesn't stack/race
      — it's coalesced or ignored.
- [ ] Test covering: reload completes and updates the UI correctly, and
      that a rapid second trigger during an in-flight reload doesn't
      corrupt state.
- [ ] `PERF-01`'s benchmark demonstrates the UI thread is no longer
      blocked for the load duration.

---

### PERF-04: Incremental TransactionTable updates

- **Status:** done
- **Depends on:** PERF-01
- **Effort:** 2h

**Description:** `update_entries` always does `self.clear()` + `add_row`
for every entry, even when only a filter keystroke or sort toggle changed
the visible/ordered subset — cost scales with total row count on every
such change. Where the *set* of shown entries is unchanged and only order
changed (a sort toggle), reorder existing rows instead of clearing and
re-adding (check whichever reordering API the pinned Textual version
actually offers — a `move_row`-style API if available, or re-keying rows
in place as a fallback). Where the entry set itself changed (filter/
account selection), a full rebuild is unavoidable but should still be
measured against `PERF-01`'s baseline instead of assumed to cost the same
as before.

**Acceptance criteria:**
- [x] Toggling sort order on an unchanged filtered/selected entry set does
      not perform a full `clear()`+rebuild (or, if Textual's `DataTable`
      genuinely has no cheaper path in the pinned version, this is
      documented as a hard constraint rather than silently left
      unaddressed).
- [x] Existing sort/filter/account-selection behavior and tests are
      unaffected.
- [x] `PERF-01`'s benchmark shows measurable improvement for the
      sort-toggle case on a large ledger.
- [x] Test covering sort-toggle behavior still produces correct row
      order/content after the optimization.

**Implementation notes:**

Investigated Textual 8.2.8 (the version actually installed under the
`textual>=0.80.0` pin) for a `move_row`-style reordering API on
`DataTable`:

- No public `move_row` (or similarly-named) method exists.
- `DataTable.sort(*columns, key=None, reverse=False)` is the one public
  reordering method, and it *is* cheap — internally it just rebuilds the
  private `_row_locations` two-way map (row key <-> display index) and
  leaves `_data` (the actual rendered cell content, populated by
  `add_row`) untouched. But its `key` callable only ever receives
  *rendered cell values* for a row (see `key_wrapper` in
  `textual/widgets/_data_table.py`), never the row's backing domain
  object. That can't reproduce this table's three sort orders correctly:
  payee sort is case-insensitive but the Payee cell preserves case,
  amount sort compares numeric `Decimal` magnitude but the Amount cell is
  a formatted currency string (`"1,200.00 USD"` sorts before `"200.00
  USD"` lexicographically — wrong), and non-`Transaction` directives need
  a synthetic zero amount that isn't in any cell at all. Using
  `DataTable.sort()` as-is would have silently changed sort behavior for
  2 of the table's 3 sort fields — unacceptable per this task's own
  "existing behavior unaffected" criterion.
- Per-row `remove_row` + `add_row` (the task's suggested fallback) was
  also ruled out: `remove_row` does an O(n) rebuild of `_row_locations`
  on every call (shifting every row's index), so reordering all N rows
  that way is O(n²) — much worse than the existing `clear()`+rebuild for
  any ledger large enough to matter.

Given that, `TransactionTable._reorder_rows` (in
`src/beancount_tui/widgets/transaction_table.py`) reaches around the
public `sort()` wrapper and does exactly what `sort()` does internally —
replace `self._row_locations` with a freshly-built `TwoWayDict` mapping
each existing row key to its new display index — but keyed by this
table's own entry-aware sort functions (`_SORT_KEYS`) instead of
rendered-cell values. This needed importing the private
`textual._two_way_dict.TwoWayDict` (the same private module
`_data_table.py` itself imports it from), documented at the import site
in `transaction_table.py`. Row content (`_data`) is never touched, so
this skips the expensive part of a rebuild entirely: no `_entry_row()`
re-computation, no new `Row`/cell objects, no `add_row` bookkeeping per
row.

`update_entries` now dispatches on `TransactionTable._can_reorder_in_place`,
which takes the fast (`_reorder_rows`) path only when *all* of the
following hold, falling back to the original full `_rebuild_rows` path
(`clear()` + `add_row` per entry) otherwise:
- the incoming `entries` are exactly the same *set* of entry objects
  already backing the table's rows (compared by `id()`, via a
  `dict[id(entry) -> row_key]` populated at the last full rebuild) —
  this is what makes it safe for the sort-toggle call site
  (`_set_sort`/`action_cycle_sort`, which literally pass `self.shown`
  back in) while still falling back correctly for a filter keystroke or
  account-selection change (a genuinely different, freshly-computed
  entry list from `app._visible_entries()`);
- `running_balances`/`cleared_balances` are the identical objects already
  set (`is` comparison) — true only when the caller didn't recompute
  them, which in practice is only the sort-toggle call sites;
- and the sort change won't flip whether the Balance/Cleared Balance
  columns are shown (`_should_show_balance_columns()` unchanged) — since
  that changes the per-row column count, which a pure reorder can't
  express safely. This one rare edge case (crossing from a date-based
  sort to payee/amount or back, on a leaf account with running balances)
  still takes the full-rebuild path; `test_balance_columns_hidden_for_payee_and_amount_sort`
  already exercises exactly that transition and continues to pass.

New test: `test_sort_toggle_reorders_rows_in_place` in `tests/test_app.py`
monkeypatches `TransactionTable._rebuild_rows` to record calls, performs
two header-click sort toggles (date ascending, then date descending —
the latter genuinely reverses row order), and asserts both that the
resulting row order/content is correct (`table.shown` and every rendered
row via `get_row_at`) *and* that `_rebuild_rows` was never called and
each entry's row key is unchanged — i.e., the optimization actually fired
rather than silently falling back.

**Benchmark (this machine, `uv run python benchmarks/bench_perf01.py`,
added `PERF-04 sort-toggle` lines time a header-click sort toggle on the
already-shown entry set two ways: the real optimized path, and — for a
direct before/after — an explicit call to the old-style `_rebuild_rows`
on the identical data):**

At 20,000 transactions (20,017 rows):

| | Before (`clear()`+rebuild) | After (reorder-in-place) | Speedup |
|---|---|---|---|
| Sort toggle | 0.192s | 0.005s | ~38x |

At 50,000 transactions (50,017 rows):

| | Before (`clear()`+rebuild) | After (reorder-in-place) | Speedup |
|---|---|---|---|
| Sort toggle | 0.560s | 0.014s | ~40x |

The "after" numbers scale far more gently with row count than the
"before" ones (roughly O(n log n) dict-rebuild cost vs. `add_row`'s
per-row rendering work), so the improvement widens at larger ledger
sizes rather than narrowing.
