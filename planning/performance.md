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

- **Status:** done
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
- [x] `root_account()` returns a cached result across repeated calls
      within the same load, invalidated correctly on reload/write.
- [x] `action_balance_directive`/`action_pad_and_verify` no longer trigger
      extra `realize()` passes beyond what `refresh_views` already did.
- [x] Test covering: cache hit on repeated calls, cache invalidation after
      `reload()`.
- [x] `PERF-01`'s benchmark shows a measurable improvement for actions
      that previously triggered multiple realizations.

**Implementation notes:** Added a new `_root_account` dataclass field
(`realization.RealAccount | None`, `repr=False, compare=False`), mirroring
`_price_map`'s exact shape and cache-until-reload contract. `root_account()`
now returns `self._root_account` if already populated, otherwise computes
`realization.realize(self._actual_entries)` once and stores it before
returning. `reload()` resets `self._root_account = None` right alongside
its existing `self._price_map = None` reset -- the only place `_price_map`
is invalidated, so it's the only place that needed mirroring.

Audited every path that mutates `self.entries`/`self._actual_entries`
(grepped `src/beancount_tui/*.py` for direct entries mutation and for
every `self.ledger.reload()` call site in `app.py`): every write flow
(`action_balance_directive`, `action_pad_and_verify`, `action_undo`,
`action_redo`, `action_reload`, `_check_external_changes`) writes to disk
via `append_entry`/`Path.write_text` and then calls `self.ledger.reload()`
-- there is no code path that mutates `self.entries` directly without
going through `reload()`. So invalidating only in `reload()` is complete,
matching `_price_map`'s existing invalidation surface exactly (no
deviation from the `_price_map_cached` pattern was needed).

Verified `action_balance_directive`/`action_pad_and_verify`: both call
`realization.get(self.ledger.root_account(), account)` once each, and
`refresh_views()` (which runs immediately beforehand, driven by account
selection / the screen render loop) also calls `self.ledger.root_account()`
once. All three now share one cached tree per ledger state instead of each
triggering its own `realize()` pass.

Added `tests/test_ledger.py::test_root_account_caches_realize_across_calls`
(monkeypatches `beancount.core.realization.realize` with a call-counting
wrapper, asserts exactly 1 call across 3 `root_account()` calls, and that
all 3 results are the identical object) and
`::test_root_account_cache_invalidated_by_reload` (asserts a `reload()`
between calls forces a second `realize()` call and returns a distinct
object, then that the cache resumes hitting afterward).

**Measured improvement:** Added `benchmarks/bench_perf02.py` (same
throwaway-tempdir convention as `bench_perf01.py`), which times, on the
same synthetic ledger: 3 independent uncached `realization.realize()`
calls (the exact pre-PERF-02 behavior) vs. 3 calls to the real, now-cached
`Ledger.root_account()` on one `Ledger` instance (the exact post-PERF-02
behavior, matching `refresh_views` + `action_balance_directive` +
`action_pad_and_verify`'s combined call pattern). Run via
`uv run python benchmarks/bench_perf02.py [-n NUM_TRANSACTIONS]`.

Results on this machine (2026-09-07):

| num_transactions | before (3x uncached realize) | after (3x cached root_account) | saving |
|---|---|---|---|
| 20,000 | 0.1443s | 0.0326s | 0.1117s (77.4%) |
| 50,000 | 0.4169s | 0.1468s | 0.2701s (64.8%) |

Consistent with PERF-01's baseline estimate (~0.03-0.05s/call, ~0.1-0.15s
per multi-call action at 20k transactions): the "after" number is
dominated by the single first (real) `realize()` call, with the 2nd/3rd
calls now effectively free cache hits — confirmed directly rather than
left as a hand-waved estimate.

Full suite (`uv run pytest -q`, 361 tests -- 359 + 2 new for this task):
all passing, 91.63s wall-clock (no regression vs. PERF-01's 89.98s
baseline; the ~1.6s difference is normal run-to-run variance, not
attributable to this change since it only adds a `None` check + attribute
read on an existing hot path). `uv run ruff check .` passes clean.

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

- **Status:** todo
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
- [ ] Toggling sort order on an unchanged filtered/selected entry set does
      not perform a full `clear()`+rebuild (or, if Textual's `DataTable`
      genuinely has no cheaper path in the pinned version, this is
      documented as a hard constraint rather than silently left
      unaddressed).
- [ ] Existing sort/filter/account-selection behavior and tests are
      unaffected.
- [ ] `PERF-01`'s benchmark shows measurable improvement for the
      sort-toggle case on a large ledger.
- [ ] Test covering sort-toggle behavior still produces correct row
      order/content after the optimization.
