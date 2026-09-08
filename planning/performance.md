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

- **Status:** done
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
- [x] The UI remains responsive (e.g. cursor movement, scrolling) while a
      large ledger reloads in the background.
- [x] A visible indicator shows a reload is in progress.
- [x] A reload triggered while one is already running doesn't stack/race
      — it's coalesced or ignored.
- [x] Test covering: reload completes and updates the UI correctly, and
      that a rapid second trigger during an in-flight reload doesn't
      corrupt state.
- [x] `PERF-01`'s benchmark demonstrates the UI thread is no longer
      blocked for the load duration.

**Implementation notes:**

`Ledger.reload()` (`src/beancount_tui/ledger.py`) is split into two
pieces: `reload_data()` — a pure, read-only-w.r.t.-`self` call to
`Ledger._load_file(self.path)` that does the actual CPU-bound
`loader.load_file` reparse and returns `(entries, errors, options)`
without touching `self` at all — and `apply_reload(data)`, which takes
that result and does the (cheap) in-place mutation `reload()` used to do
directly: assigning `self.entries`/`self.errors`/`self.options`,
invalidating `_price_map`, and re-parsing budgets/recurring templates.
`reload()` itself is kept as `apply_reload(reload_data())` in one call,
so any caller that doesn't care about threading (direct `Ledger` use in
tests/scripts) is unaffected.

`BeancountTUI` (`src/beancount_tui/app.py`) never calls `Ledger.reload()`
directly any more. All four reload call sites —
`action_reload`, `action_undo`, `action_redo`, and
`_check_external_changes` — now go through one shared entry point,
`_start_reload(notify_message=...)`:

- `run_worker(self._reload_worker, thread=True, exclusive=False)` — real
  **thread-mode** (not asyncio mode), since `beancount.loader` is
  synchronous CPU-bound code with no `await` points; an asyncio worker
  would still block the event loop exactly like the old inline call did.
- `_reload_worker` (runs on the worker thread) calls only
  `self.ledger.reload_data()` — it never mutates `self.ledger` or touches
  any widget, since that's only safe from the main thread. It hands the
  result back to the main thread via `self.call_from_thread(self._finish_reload, loaded)`
  (Textual's documented safe way for a thread worker to call back into
  UI-mutating code) — or, if `reload_data()` unexpectedly raises,
  `call_from_thread(self._reload_failed, exc)` so a background-thread
  exception degrades into an error toast instead of vanishing silently or
  crashing the app.
- `_finish_reload` (runs on the main thread) calls
  `self.ledger.apply_reload(loaded)`, refreshes `_watched_mtimes`, calls
  `refresh_views()`, clears the in-flight indicator, and fires the
  caller's `notify_message` (e.g. "Ledger reloaded.", "Undid last change
  to ...", "Ledger changed on disk; reloaded.") — deferred until the
  reload actually completes, since it's no longer synchronous with the
  keypress/timer tick that requested it.

**Indicator:** rather than adding a new widget/CSS, `_start_reload`
appends a small "⏳ reloading…" suffix to `self.sub_title` (already used
to show the ledger path, in the always-visible `Header`), restoring the
bare path in `_finish_reload`/`_reload_failed`. This matches the "reuse
an existing status area" option from the task over adding a new widget,
since `Header`'s title bar is the one thing already visible across every
screen state.

**Reentrancy:** a single boolean, `self._reload_in_progress`, set the
instant `_start_reload` decides to actually launch a worker and cleared
only in `_finish_reload`/`_reload_failed`. Every one of the four call
sites either checks it directly (`_check_external_changes`) or goes
through `_start_reload`, which checks it first and returns immediately
(no-op) if a reload is already running — so a second `r` keypress, or
the watch-interval timer firing again mid-reload, is dropped rather than
queued or stacked against the same `Ledger` instance. All reads/writes of
the flag happen on the main/UI thread only (both the four call sites and
the `call_from_thread`-scheduled completion callbacks run there), so
there's no race on the flag itself. This is deliberately the "simple
in-flight boolean flag guard" the task calls sufficient, not a queue that
replays dropped requests — a dropped trigger from `_check_external_changes`
is harmless since the next timer tick re-checks mtimes against disk once
the in-flight reload finishes.

**Tests** (`tests/test_app.py`):
- `test_reload_completes_and_updates_ui_without_blocking` — monkeypatches
  `Ledger.reload_data` to `time.sleep(0.4)` before doing the real reparse
  (a deterministic window, not real-timing-dependent), triggers a reload
  via the `r` key, and asserts the reload is still `_reload_in_progress`
  immediately after — then, **while it's still running**, presses `down`
  and asserts the transaction table's cursor actually moved. This is the
  direct proof for the "UI thread is no longer blocked" acceptance
  criterion: an unrelated keypress is processed and changes visible state
  while a reload is mid-flight, which is only possible because the parse
  itself is off the UI thread. After `await app.workers.wait_for_complete()`,
  asserts the reload did complete and the table reflects the externally
  appended transaction.
- `test_second_reload_trigger_while_in_flight_is_coalesced` — same slow
  `reload_data` mock, but with a call counter. Presses `r` once, confirms
  `_reload_in_progress`, then presses `r` three more times while still in
  flight. After the worker completes, asserts `reload_data` was only
  actually called once (the extra triggers were dropped, not stacked) and
  that the resulting table state is exactly what one clean reload
  produces (no corruption from a hypothetical second concurrent reload).

**Benchmark / "UI thread no longer blocked" evidence:** `PERF-01`'s
`benchmarks/bench_perf01.py` measures `Ledger.load`/`update_entries`/
`update_accounts` in isolation and deliberately isn't a UI-thread-blocking
benchmark — it wasn't extended for this task, per the process notes
above, since `Ledger.load`/`reload_data`'s own duration is unchanged by
this change (moving *where* the same work runs doesn't make the parse
itself faster). Instead, the "no longer blocked" criterion is
demonstrated the way the task allows: by the worker mechanism itself
(`run_worker(..., thread=True)` genuinely hands the blocking call to a
different OS thread, which is why `time.sleep()` in the mocked
`reload_data` above doesn't stop `pilot.press("down")` from being
processed) plus the passing
`test_reload_completes_and_updates_ui_without_blocking` test above, which
asserts exactly that behavior against a reload slow enough (0.4s, in the
same ballpark as `PERF-01`'s real 20k-transaction baseline of ~0.4s) to
make the point unambiguously rather than relying on incidental scheduling
luck.

**Deviations from spec:** none of substance. The task suggested either
`@work(thread=True)` or `run_worker(..., thread=True)`; `run_worker` was
used directly (rather than the `@work` decorator) since the worker needs
to be started conditionally from inside `_start_reload`'s in-flight check
rather than unconditionally every time an action method is called, which
is more naturally expressed as an explicit `run_worker` call than via the
decorator's automatic-worker-per-call-site pattern.

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
