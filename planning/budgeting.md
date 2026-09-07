# Budgeting (`BUDGET`)

Per-account budget targets and a budget-vs-actual report, using Fava's
established `custom "budget"` directive convention so ledgers stay
interoperable with fava and other Beancount tools. Scope for this milestone
is budgeting only — recurring/scheduled transactions and forecasting are a
separate, later milestone.

Budget directives already display, edit, and delete correctly today as
generic `Custom` entries (`LANG-06`); what's missing is interpreting them
(account/interval/amount extraction, day-based proration, a time-series
"latest wins" model per currency), a dedicated report, and a guided creation
form.

---

### BUDGET-01: Budget directive parsing

- **Status:** done
- **Depends on:** LANG-06
- **Effort:** 1.5h

**Description:** Add a typed accessor for budget entries on top of the
existing generic `Custom` handling. Filter `self.entries` for
`isinstance(e, data.Custom) and e.type == "budget"` and parse each into a
`BudgetEntry` dataclass (`date`, `account`, `interval`, `Amount`). Validate
the interval string against Fava's five accepted values (`daily`/`weekly`/
`monthly`/`quarterly`/`yearly`, plus the short forms `day`/`week`/`month`/
`quarter`/`year`, case-insensitive) and surface an invalid interval the same
way other malformed directives are surfaced (existing error panel), rather
than crashing. This is pure parsing — no proration math yet.

**Acceptance criteria:**
- [x] `Ledger.budgets` (or equivalent) returns parsed `BudgetEntry` objects
      for every `custom "budget"` entry in the ledger.
- [x] Both long-form and short-form interval strings parse to the same
      canonical interval.
- [x] An unrecognized interval string surfaces as a validation error rather
      than crashing or being silently dropped.
- [x] Test covering parsing a handful of budget directives across all five
      intervals plus one invalid-interval case.

---

### BUDGET-02: Budget target calculation (day-prorated, time-series)

- **Status:** done
- **Depends on:** BUDGET-01
- **Effort:** 2h

**Description:** Implement Fava's day-by-day proration: for a given account,
currency, and date range, sum each day's share of the applicable budget
(`amount / days_in_that_day's_calendar_bucket`), where the calendar bucket's
day count is computed exactly (real month/quarter/year lengths, handling
leap years), not a flat average. Budget entries are a **time series of
targets per currency**, not additive — when multiple entries exist for the
same account, the most recent entry whose date is on or before the day
being evaluated wins, tracked independently per currency (a EUR budget and a
USD budget for the same account each have their own "most recent" pointer).
An account with no matching budget for a given day/currency contributes
nothing (clean absence, not a zero-with-a-flag).

**Acceptance criteria:**
- [x] Prorated target over an arbitrary date range matches hand-computed
      expected values for daily, weekly, monthly, quarterly, and yearly
      budgets, including a range spanning a leap-year February and a
      calendar-quarter boundary.
- [x] A later budget entry for the same account/currency supersedes the
      earlier one from its start date onward; the earlier entry still
      applies to days before that.
- [x] Two budget entries for the same account in different currencies are
      tracked independently (replacing one doesn't affect the other).
- [x] Test covering the time-series replacement and the leap-year/quarter
      proration edge cases explicitly.

---

### BUDGET-03: Budget-vs-actual report screen

- **Status:** todo
- **Depends on:** BUDGET-02
- **Effort:** 2h

**Description:** New `BudgetScreen` modal, structurally cloned from
`income_statement.py`'s pattern (`ModalScreen[None]`, a period `Input`
reusing `parse_date_range`/`resolve_date_preset`, a `DataTable`, inline error
`Static` for bad period text). Rows are the leaf accounts that have at least
one budget entry active anywhere in the selected range, with columns for
Budgeted (from `BUDGET-02`), Actual (postings summed the same way
`income_statement`/`balance_sheet` already do), and Remaining (Budgeted −
Actual). Accounts with no budget defined are excluded from this view (parent
rollup is `BUDGET-04`).

**Acceptance criteria:**
- [ ] Report lists every leaf account with an active budget in the selected
      period, with Budgeted/Actual/Remaining columns.
- [ ] Default (no period entered) view uses a sensible default range (e.g.
      current month), not all-time.
- [ ] Bad period input shows an inline error without crashing, matching
      `IncomeStatementScreen`'s existing behavior.
- [ ] Test covering a known budget + matching actual postings fixture
      producing the expected Remaining value.

---

### BUDGET-04: Parent/child budget rollup

- **Status:** todo
- **Depends on:** BUDGET-03
- **Effort:** 1h

**Description:** Budgets are defined per leaf account with no automatic
inheritance. Add an opt-in rollup (mirroring Fava's
`calculate_budget_children`): for a parent account with no direct budget of
its own, sum the already-prorated Budgeted/Actual/Remaining of itself and
every descendant account (string-prefix match) into a synthesized parent
row. Toggle this behind a binding on `BudgetScreen` (e.g. `r` for
rolled-up), off by default so the flat per-leaf view from `BUDGET-03` stays
the default.

**Acceptance criteria:**
- [ ] Toggling rollup on shows parent-account rows summing their budgeted
      descendants' figures.
- [ ] A parent account with its own direct budget entry is not
      double-counted against its children's rolled-up total.
- [ ] Toggling rollup off returns to the flat `BUDGET-03` view.
- [ ] Test covering a 3-level account hierarchy with budgets on two
      siblings, rolled up into their shared parent.

---

### BUDGET-05: Structured budget creation form

- **Status:** done
- **Depends on:** LANG-06, BUDGET-01
- **Effort:** 2h

**Description:** `DirectiveTypePicker` + `DirectiveForm` already support
creating a `custom "budget"` entry as raw text (per `LANG-06`'s acceptance
criteria), but offer no guided fields. Add a dedicated `BudgetForm` widget
(account input with the same tab-completion as `postings_area.py`, an
interval `Select` constrained to the five valid values, numeric amount +
currency inputs) that assembles the structured input into
`YYYY-MM-DD custom "budget" Account "interval" NN.NN CCY` text and reuses
`DirectiveForm`'s validate/save path (`parse_directives_text`,
`DirectiveFormResult`) rather than duplicating it. Wire it in as an
alternative to the generic picker specifically for the `budget` custom-type
case.

**Acceptance criteria:**
- [x] Account field tab-completes against known ledger accounts the same
      way the postings editor does.
- [x] Interval select only offers the five valid values; amount/currency
      inputs reject non-numeric input before submission.
- [x] Assembled text round-trips through the real parser exactly like the
      existing generic raw-text flow (same validation guarantees).
- [x] Test covering filling the structured form and confirming the
      resulting directive parses as a valid `BudgetEntry` (`BUDGET-01`).

---

### BUDGET-06: Discoverability — binding + help screen entry

- **Status:** todo
- **Depends on:** BUDGET-03
- **Effort:** 0.5h

**Description:** Add a top-level binding to open `BudgetScreen` (e.g. `g`
for "budget", avoiding existing bindings — confirm against the current
binding table before picking a key) and add the corresponding entry to the
`UX-01` help screen so it's discoverable the same way other reports are.

**Acceptance criteria:**
- [ ] New binding opens `BudgetScreen` from the main screen.
- [ ] Help screen lists the new binding alongside the other report
      bindings.
- [ ] Test covering the binding opens the screen (extending the existing
      `test_app.py` binding-coverage pattern).
