# Forecasting (`FORECAST`)

Recurring/scheduled transaction templates and a forward-looking cash-flow
projection, following the budgeting milestone (`planning/budgeting.md`).
Unlike budgeting, there's no established cross-tool convention to adopt here
— Beancount has no native periodic-transaction directive, and the closest
prior art (`beanahead`) is a low-adoption tool that materializes generated
transactions into separate ledger files with its own CLI (`addrx`/`recon`).
That approach is a poor fit for an interactive TUI, so this milestone
defines its own lightweight scheme instead:

- **Virtual/projection-only** — recurring templates and forecast output are
  never written to the ledger (matches `hledger --forecast`'s model, not
  `beanahead`'s). Nothing here calls `append_entry` with synthesized data;
  the projection exists only in memory for the report screen.
- **Templates are ordinary transactions, not a new directive type** — a
  recurring template is a normal `Transaction`, dated at its first
  occurrence, carrying the tag `#recurring` plus metadata `recurring-freq`
  (same five interval values as `BUDGET-01`, reusing its validation) and
  optional `recurring-until`. This leans entirely on already-shipped
  infrastructure (`LANG-08` tags, `LANG-09` metadata, the full
  `TransactionForm` postings/payee/narration editor) instead of building a
  parallel editing UI.
- **Budget fallback** — for an account/day in the forecast horizon with no
  generated template instance, the projection falls back to that account's
  `BUDGET-02` prorated target as assumed spend, so the forecast isn't
  limited to only the transactions the user thought to template. An account
  with a template instance on a given day does not also draw a budget
  fallback for that same day (avoids double-counting explicit vs. assumed
  spend).

---

### FORECAST-01: Recurring template data model & parsing

- **Status:** done
- **Depends on:** LANG-08, LANG-09, BUDGET-01
- **Effort:** 1.5h

**Description:** Define the `#recurring` tag + `recurring-freq`/
`recurring-until` metadata convention and parse matching transactions into a
`RecurringTemplate` dataclass (first-occurrence date, interval, optional end
date, and the template's full posting/payee/narration data reused as-is from
the existing `Transaction` entry). Validate `recurring-freq` against the
same five interval values as `BUDGET-01` (reuse its validation function
rather than duplicating it) and surface an invalid value the same way other
malformed data does — via the existing error panel, not a crash.

**Acceptance criteria:**
- [x] `Ledger.recurring_templates` (or equivalent) returns parsed
      `RecurringTemplate` objects for every transaction tagged `#recurring`
      with a valid `recurring-freq`.
- [x] An invalid `recurring-freq` value surfaces as a validation error
      rather than being silently dropped or crashing.
- [x] `recurring-until` is optional; when absent, the template has no end
      date (projects indefinitely, bounded only by the report's own window).
- [x] Test covering parsing a handful of `#recurring` transactions across
      intervals, including one with `recurring-until` and one with an
      invalid interval.

---

### FORECAST-02: Exclude recurring templates from actual-data views

- **Status:** done
- **Depends on:** FORECAST-01
- **Effort:** 1h

**Description:** Every existing report (`income_statement`, `balance_sheet`,
`trial_balance`, `register`, `holdings`) and the main transaction table
currently iterate `self.transactions` unconditionally. A `#recurring`
template transaction is real Beancount data (it has to be, to be editable
via the normal transaction infrastructure) but must **not** be counted as
actual activity — it's a template, not something that happened. Filter
`#recurring`-tagged transactions out of every actual-data view, while still
showing them (clearly labeled, e.g. a "Recurring" indicator) in the main
transaction table so they remain visible/editable/deletable like any other
transaction.

**Acceptance criteria:**
- [x] `#recurring`-tagged transactions are excluded from income statement,
      balance sheet, trial balance, register, and holdings computations.
- [x] They remain visible (with a distinguishing marker) and editable in the
      main transaction table.
- [x] A ledger with only a `#recurring` template and no real postings shows
      zero actual activity in every report.
- [x] Test covering a template transaction that would visibly skew a
      report's totals if it were incorrectly included.

---

### FORECAST-03: Recurring template creation/editing

- **Status:** done
- **Depends on:** FORECAST-01
- **Effort:** 1.5h

**Description:** Extend `TransactionForm` with an optional "recurring"
toggle that, when enabled, reveals an interval `Select` (the same five
values as `BUDGET-05`'s interval field) and an optional end-date input.
Saving assembles the `#recurring` tag and `recurring-freq`/
`recurring-until` metadata onto the transaction text alongside the normal
payee/narration/postings fields already handled by the existing assembly
logic — no separate form or duplicated postings editor.

**Acceptance criteria:**
- [x] Toggling "recurring" on a new or existing transaction adds the
      interval select and optional end-date field.
- [x] Saving produces a transaction with the `#recurring` tag and correct
      metadata, parseable by `FORECAST-01`.
- [x] Toggling recurring off before saving produces a normal transaction
      with no tag/metadata added.
- [x] Test covering creating a recurring template through the form and
      confirming it round-trips into a `RecurringTemplate`.

---

### FORECAST-04: Projection engine (virtual instance generation)

- **Status:** done
- **Depends on:** FORECAST-01
- **Effort:** 2h

**Description:** Given a future date range, generate virtual transaction
instances from each `RecurringTemplate` by advancing its first-occurrence
date by its interval (reusing `BUDGET-02`'s calendar-bucket day-counting
logic for month/quarter/year-length correctness) until the range's end or
the template's `recurring-until`, whichever is earlier. These instances are
plain in-memory dataclasses (same posting/amount shape as a real
transaction) — never constructed as parseable Beancount text, never
appended anywhere.

**Acceptance criteria:**
- [x] A monthly template generates one instance per calendar month in the
      requested range, correctly handling month-length variation (e.g. a
      template dated the 31st doesn't skip or crash in February).
- [x] A template with `recurring-until` stops generating instances after
      that date, even if the requested range extends further.
- [x] Templates starting after the requested range's start only generate
      instances from their own first occurrence onward.
- [x] Test covering monthly/quarterly/yearly generation across a
      multi-month range, plus the `recurring-until` cutoff.

---

### FORECAST-05: Budget fallback for untemplated accounts

- **Status:** done
- **Depends on:** FORECAST-04, BUDGET-02
- **Effort:** 1.5h

**Description:** For each account and day in the forecast horizon, if no
generated template instance (`FORECAST-04`) touches that account on that
day, layer in the account's `BUDGET-02` prorated target for that day as
assumed spend. An account/day covered by an explicit template instance does
not additionally draw a budget-fallback amount (explicit beats assumed,
never both). Accounts with neither a template nor a budget contribute
nothing to the projection, same as today's clean-absence behavior.

**Acceptance criteria:**
- [x] An account with a budget but no template gets its prorated target as
      projected spend for days with no explicit instance.
- [x] An account with a template covering a given day does not also draw a
      budget-fallback amount for that same day.
- [x] An account with neither a template nor a budget projects zero
      additional activity.
- [x] Test covering all three cases (template-only, budget-only, neither)
      over the same forecast window.

---

### FORECAST-06: Cash-flow forecast report screen

- **Status:** done
- **Depends on:** FORECAST-05
- **Effort:** 2h

**Description:** New `ForecastScreen` modal, structurally cloned from
`income_statement.py`'s pattern (period `Input` reusing `parse_date_range`,
`DataTable`, inline error `Static`), defaulting to a forward-looking window
(e.g. today through the next 3 months) rather than requiring the user to
type a future range by hand. Shows projected per-account (or running
total/net) figures combining real actuals up to today with projected
activity beyond it, with projected rows visually distinguished (e.g. a
distinct style or column marker) from real historical data so speculative
figures are never mistaken for actual transactions.

**Acceptance criteria:**
- [x] Default view projects roughly 3 months forward from today without
      requiring manual date entry.
- [x] Projected figures are visually distinguished from actual historical
      figures.
- [x] Bad period input shows an inline error without crashing, matching
      other report screens' existing behavior.
- [x] Test covering a fixture with one recurring template and one budget
      producing the expected blended projection.

---

### FORECAST-07: Discoverability — binding + help screen entry

- **Status:** todo
- **Depends on:** FORECAST-06
- **Effort:** 0.5h

**Description:** Add a top-level binding to open `ForecastScreen` (confirm
against the current binding table, including `BUDGET-06`'s new binding,
before picking a key) and add the corresponding entry to the `UX-01` help
screen.

**Acceptance criteria:**
- [ ] New binding opens `ForecastScreen` from the main screen.
- [ ] Help screen lists the new binding alongside the other report
      bindings.
- [ ] Test covering the binding opens the screen (extending the existing
      `test_app.py` binding-coverage pattern).
