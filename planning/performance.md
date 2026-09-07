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

- **Status:** todo
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
- [ ] A generator produces a synthetic ledger of a configurable size (e.g.
      20,000+ transactions) that loads cleanly through the real Beancount
      parser.
- [ ] Load, table-render, and tree-render timings are captured against
      the generated ledger.
- [ ] Baseline numbers are documented (in the task/PR, not necessarily
      committed as a file) for `PERF-02`-`PERF-04` to compare against.
- [ ] Test/benchmark infrastructure runs without disproportionately
      slowing the default test run (keep large-ledger timing out of the
      fast/default suite if needed).

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
