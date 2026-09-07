# Execution phases

Groups every currently `todo` task (21 across `RPT`, `LANG`, `EDIT`, `UX`,
`EXPORT`, `CONFIG`, `PERF`) into 5 phases. Each phase is a self-contained,
demoable slice — nothing in it depends on a task from a *later* phase, and
finishing it leaves the TUI in a coherent, testable state rather than a
half-wired feature. `TOOL-04` (package and publish) is excluded — it's
blocked on PyPI credentials, not a code task, and isn't something to UAT
in the running TUI.

Work proceeds phase by phase; each phase ends with you manually running
the TUI against a real or example ledger before the next phase starts.
Within a phase, tasks are independent of each other (per their own
`Depends on`, already satisfied by already-`done` work) and can be built
in parallel via the usual worktree-per-task pattern.

---

## Phase 1 — Register & editing polish

**Tasks:** `RPT-07`, `UX-05`, `EDIT-05`, `LANG-13` (~5.5h)

The smallest, highest-frequency-use changes, all touching the primary
daily-use surface: the main transaction table and the save/edit path.
Good first phase because it's fast to build and fast to verify — no new
screens, just sharper behavior on the one screen you already look at
constantly.

**What's delivered:**
- Inline Balance + Cleared Balance columns in the transaction table for a
  single selected leaf account, date-sorted (`RPT-07`).
- Single-key flag cycling (`*`/`!`) on the highlighted transaction
  (`UX-05`).
- A save-time prompt to create missing accounts, rejecting the save if
  declined (`EDIT-05`).
- A plugin that crashes via `sys.exit(...)` during load degrades to a
  readable error instead of taking down the app (`LANG-13`).

**UAT checklist:**
- [ ] Select a single leaf account; confirm Balance/Cleared Balance appear
      correctly in default and both date-sort states, and disappear for a
      parent account or a payee/amount sort.
- [ ] Highlight a transaction row and cycle its flag; confirm the file and
      undo/redo both reflect it.
- [ ] Start a new transaction referencing an account that doesn't exist
      yet; confirm you're prompted, and that declining does *not* save.
- [ ] (If you have or can fake a `plugin` line that raises `SystemExit`)
      confirm reload shows an error instead of crashing.

---

## Phase 2 — Fava-parity reporting & plugin visibility

**Tasks:** `RPT-08`, `RPT-09`, `RPT-10`, `RPT-11`, `LANG-12` (~8h)

Everything that adds or upgrades a report/sidebar screen. Grouped
together because the natural way to review it is a single pass through
every report screen back to back, rather than piecemeal.

**What's delivered:**
- Sidebar account tree remembers collapsed/expanded state across reloads
  (`RPT-08`).
- Income statement supports a multi-period (e.g. month-over-month)
  comparison view (`RPT-09`).
- A commodity price-history table (`RPT-10`).
- A preview modal for `Document`-referenced files (`RPT-11`).
- Declared `plugin` directives are listed in the ledger info screen, and
  can be added (creation-only) via the add-directive picker (`LANG-12`).

**UAT checklist:**
- [ ] Collapse a couple of sidebar nodes, reload/filter, confirm they
      stay collapsed; confirm a fresh ledger still opens fully expanded.
- [ ] Run an income-statement comparison across at least 3 periods
      (e.g. last 3 months) and sanity-check the totals per column.
- [ ] Open price history for a commodity with several `Price` entries;
      confirm date order and that commodities with no price data are
      excluded from the picker.
- [ ] Preview a `Document` row pointing at a real text file, a binary
      file, and a missing file — confirm each gets the right treatment.
- [ ] Confirm any `plugin` lines in your ledger show up in the ledger
      info screen, and that adding a new one via the picker appends
      correctly.

---

## Phase 3 — Form UX overhaul

**Tasks:** `UX-06`, `UX-07`, `UX-08` (~7h)

The three heaviest, most subjective UX changes, all landing in the same
forms (`TransactionForm` and friends). Grouped as one phase because
they're best judged together as "the new entry experience" rather than
in isolation — a date picker, completion suggestions, and a structured
postings editor all show up on the same screen at once.

**What's delivered:**
- A calendar-style date picker on every date field, with direct
  ISO-date typing still working (`UX-06`).
- Payee/Tags completion and Narration suggestions, extending the
  existing account-completion pattern (`UX-07`).
- A structured, row-based Postings editor as an alternative to the raw
  text editor, with a toggle between the two (`UX-08`).

**UAT checklist:**
- [ ] Open the date picker from a date field, navigate by day/month, and
      confirm it sets the field; confirm typing a date directly still
      works.
- [ ] Type a partial payee/tag that already exists in the ledger and
      confirm suggestion/completion behavior; check narration suggestions
      too.
- [ ] Toggle to the structured Postings editor, add/remove rows, and
      confirm switching back to raw text preserves what you entered;
      author a cost-basis posting in raw text and confirm it round-trips
      correctly when viewed in the structured view (or falls back
      gracefully if it can't be represented there).
- [ ] Create a full transaction end-to-end using only the new UX (date
      picker + completions + structured postings) and confirm it saves
      correctly.

---

## Phase 4 — Interop & configurability

**Tasks:** `EXPORT-01`, `EXPORT-02`, `CONFIG-01`, `CONFIG-02`, `CONFIG-03`
(~8h)

Power-user infrastructure: getting data out of the TUI, and making the
TUI's own behavior configurable. Grouped together as the "beyond a single
session" phase — export and config both matter most once you're using
beancount-tui repeatedly rather than just trying it out.

**What's delivered:**
- CSV/JSON export from the query runner, then every other report screen
  (`EXPORT-01`, `EXPORT-02`).
- A TOML config file for settings that today are hardcoded or
  CLI-unreachable (`CONFIG-01`).
- Configurable key bindings via that config file (`CONFIG-02`).
- A theme selection that persists across restarts (`CONFIG-03`).

**UAT checklist:**
- [ ] Export a query result to CSV and to JSON; open both and confirm
      the data matches what was on screen.
- [ ] Export at least one other report (e.g. balance sheet) and confirm
      it too.
- [ ] Write a config file setting `watch_interval` and/or `default_ledger`
      and confirm both take effect; confirm a missing config file doesn't
      break anything.
- [ ] Remap one key binding via config and confirm it works; try a
      conflicting remap and confirm it's rejected with a clear message.
- [ ] Pick a theme via the command palette, restart the app, and confirm
      it's still applied.

---

## Phase 5 — Performance at scale

**Tasks:** `PERF-01`, `PERF-02`, `PERF-03`, `PERF-04` (~6.5h)

Deliberately last: this is the one phase whose UAT isn't "click through
features" but "load a large ledger and see how it feels" — best done once
everything else is in its final shape, since a fully-featured build is
what you'll actually be running day to day.

**What's delivered:**
- A synthetic large-ledger benchmark fixture, establishing baseline
  timings (`PERF-01`).
- Cached account realization instead of re-computing on every action
  (`PERF-02`).
- Ledger load/reload moved off the UI thread, with a progress indicator
  (`PERF-03`).
- Incremental (rather than full-rebuild) transaction table updates on
  sort toggles (`PERF-04`).

**UAT checklist:**
- [ ] Generate (or ask for) a large synthetic ledger via `PERF-01`'s
      fixture/script and load it in the TUI.
- [ ] Confirm the sidebar and table remain responsive while a reload is
      in flight, and that a visible indicator shows the reload happening.
- [ ] Toggle table sort repeatedly on the large ledger and confirm it
      feels noticeably snappier than a full rebuild.
- [ ] Trigger back-to-back reloads quickly (e.g. two saves in fast
      succession) and confirm nothing races or corrupts state.
