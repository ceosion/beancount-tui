# Reports (`RPT`)

Beyond the income statement that already ships, Beancount's other standard
reports (`bean-report`/`bean-query` equivalents) aren't available in the TUI
yet. `Ledger.income_statement` is the existing model to follow: filter
entries by date, realize/aggregate, hand a small dataclass to a screen
widget.

---

### RPT-01: Balance sheet view

- **Status:** done
- **Depends on:** none
- **Effort:** 2h

**Description:** A screen (e.g. behind a `b` binding) summarizing Assets,
Liabilities, and Equity account balances as of a chosen date, following the
same pattern as `IncomeStatementScreen`/`Ledger.income_statement`. Include
the implicit net-income line (current period's income minus expenses,
computed the same way `Ledger.income_statement` does) so the sheet balances
even mid-year, before a bean-close would fold it into Equity.

**Acceptance criteria:**
- [x] New screen shows Assets, Liabilities, Equity with per-account and
      section totals as of a selectable date (default: today).
- [x] Includes a synthetic net-income line so total Assets = total
      Liabilities + Equity (+ net income).
- [x] Test covering totals against a known example ledger state.

---

### RPT-02: Register view with running balance

- **Status:** done
- **Depends on:** none
- **Effort:** 1.5h

**Description:** For the currently selected account, a view showing each
transaction's posting amount to that account plus the cumulative running
balance after it — what `bean-report register ACCOUNT` gives on the CLI.
Can reuse `Ledger.transactions_for_account` and iterate summing posting
units per currency.

**Acceptance criteria:**
- [x] New screen/mode shows date, narration, posting amount, and running
      balance for the selected account's transactions, in date order.
- [x] Handles accounts with postings in more than one currency without
      mixing running totals across currencies.
- [x] Test covering running-balance correctness across a short known
      sequence of transactions.

---

### RPT-03: Date-range presets for the filter

- **Status:** done
- **Depends on:** none
- **Effort:** 1h

**Description:** The filter bar already supports `START..END` date ranges
via `parse_date_range`. Add quick tokens/keys for common ranges — e.g.
typing `month`, `last-month`, `year`, `last-year` (or dedicated keybindings)
expands to the equivalent `START..END` computed from today's date.

**Acceptance criteria:**
- [x] At least `month`, `last-month`, `year`, `last-year` tokens are
      recognized by the filter bar and produce the correct date range.
- [x] Existing explicit `START..END` and text-search behavior is unchanged.
- [x] Tests covering each preset token resolves to the expected range for a
      fixed "today".

---

### RPT-04: Trial balance view

- **Status:** done
- **Depends on:** none
- **Effort:** 1h

**Description:** A screen listing every account with a nonzero balance as
of a chosen date, across all five account types — `bean-report balances`
equivalent. Simpler than the balance sheet (no implicit net-income line,
no section grouping beyond a flat sorted list), useful as a quick
sanity-check view.

**Acceptance criteria:**
- [x] New screen lists all accounts with nonzero balances at a selectable
      date, sorted by account name.
- [x] Test covering output against a known example ledger state.

---

### RPT-05: Holdings / net worth report

- **Status:** done
- **Depends on:** LANG-02, LANG-10
- **Effort:** 2h

**Description:** Aggregate cost-basis lots across Assets/Liabilities
accounts into per-commodity holdings (quantity, cost basis, and market value
using the latest known price from `beancount.core.prices.build_price_map`
over `Price` directives), plus a net-worth total converted to the operating
currency where prices allow. This is the one report that needs price data,
hence the dependency on `Price` directives being modeled (`LANG-02`) and
cost-basis postings being handled correctly elsewhere (`LANG-10`).

**Acceptance criteria:**
- [x] New screen lists holdings by commodity/account with quantity, cost
      basis, and market value (when a price is available).
- [x] Shows a net-worth total in the operating currency, falling back
      gracefully (e.g. "no price available") for commodities with no price
      history.
- [x] Test covering a ledger with at least one costed lot and a matching
      `price` directive.

---

### RPT-06: Ad hoc BQL query runner

- **Status:** done
- **Depends on:** none
- **Effort:** 2h

**Description:** A screen with a text input for a BQL query, run against the
loaded ledger via the Beancount query engine (same engine as `bean-query`),
rendering the result as a table. Note: on `beancount>=3.0.0`, the query
engine no longer lives at `beancount.query.query` — that module was split
out into the separate `beanquery` package (added as a dependency here);
`Ledger.run_query` in `ledger.py` wraps it (`beanquery.connect("beancount:",
entries=..., errors=..., options=...)` then `connection.execute(...)`). If
`LANG-07` (Query directives) has landed, also let the user pick a saved
named query from the ledger to run instead of typing one — it has, so this
is implemented: `data.Query` entries are listed in a `Select`.

**Acceptance criteria:**
- [x] User can type a BQL query and see a result table.
- [x] Query errors (bad syntax, unknown column) are shown inline rather than
      crashing the app.
- [x] Test covering a simple known query against the example ledger.
- [x] If `LANG-07` is done: named queries from the ledger are selectable and
      run the same way. (LANG-07 is done; implemented via a `Select` of
      `data.Query` directives in `QueryRunnerScreen`.)

---

### RPT-07: Inline running & cleared balance columns in the main transaction table

- **Status:** todo
- **Depends on:** UX-02
- **Effort:** 2h

**Description:** `RPT-02`'s `RegisterScreen` (bound to `g`) already shows a
running balance for one account, but only in a separate modal. Add the same
figure directly to the main `TransactionTable` as a Balance column, so
reconciling doesn't require leaving the primary view. Alongside it, add a
second column, **Cleared Balance**, tracking the cumulative total of only
the `*`-flagged (cleared) transactions contributing to the account —
useful for confirming an account matches a bank statement independent of
any still-pending (`!`) activity also in the ledger. The two columns are
computed by the same walk with different filters and share every
visibility rule below; the existing Balance column remains flag-agnostic
(sums every contributing transaction regardless of `*`/`!`/other flag) —
that behavior must not change, only Cleared Balance is flag-filtered. A
running balance (of either kind) is only meaningful for one account's own
chronological history, so both columns are conditional rather than
always-present:

- **Only when a single leaf account is selected** — `self.selected_account`
  is set and has no descendant accounts (`not any(a.startswith(selected +
  ":") for a in ledger.accounts)`). Viewing "all accounts" or a parent
  account (whose rows span multiple distinct accounts via
  `transactions_for_account`'s prefix match) has no single balance to
  accumulate; that's a job for an ad hoc query/report, not this table.
- **Only when the table's sort is date-based** — either explicit `date`
  sort state from `UX-02`'s `_SORT_STEPS` (asc or desc), *or* the table's
  untouched default (`_sort_field is None`), since Beancount's loader
  already yields entries in date order and the default view visually reads
  as date-ascending even though no explicit sort has been chosen yet.
  Sorting by payee or amount hides the column — a running balance across a
  payee- or amount-ordered list doesn't visually make sense.

Both **balances must always be computed earliest-to-latest**, decoupled
from whatever order the table is currently displaying: for a descending date
sort, the same chronologically-correct post-transaction balances are shown
against reversed rows, not recomputed backwards. Extract the walk
`Ledger.register()` already does (chronological, sub-account-inclusive,
`#recurring`-exclusive per `_actual_transactions`) into a shared helper, and
expose it as a new method (e.g. `Ledger.running_balances(account) ->
dict[data.Transaction, Inventory]`) mapping each contributing transaction to
its cumulative balance immediately after, plus a flag-filtered variant (or
an optional filter parameter on the same helper) for Cleared Balance that
only accumulates transactions whose `flag == "*"` — `RegisterRow`'s existing
public shape is untouched, this is additive. A `#recurring`-tagged row
(visible in the main table per `FORECAST-02`, marked with "↻") gets blank
cells in both columns, consistent with every other actual-data view
excluding templates. Rows for non-`Transaction` directives (visible when
the `t` toggle is on) also get blank cells in both columns — they have no
posting amount to accumulate. A non-cleared (`!` or other flag) transaction
still gets a normal Balance cell (flag-agnostic) but a blank Cleared
Balance cell, since it doesn't contribute to that running total.

The columns themselves should be added/removed from the `DataTable`
(Textual's `add_column`/`remove_column`) rather than always present with
blank cells, so viewing "all accounts" or a non-leaf account doesn't carry
permanently empty columns. Visibility is re-evaluated inside
`TransactionTable.update_entries` (covering account/filter changes from
`app.py`) and inside its own `_set_sort`/`action_cycle_sort`/header-click
paths (covering in-table sort changes), all of which already funnel into
`update_entries`/a shared redraw, so no separate hook is needed — `app.py`
only needs to pass `running_balances=None`/`cleared_balances=None` (or the
computed dicts, when the single-leaf condition holds) at its existing
`update_entries` call sites.

**Acceptance criteria:**
- [ ] Balance column is present and correct for a single leaf account with
      the table in its default (untouched) state or either explicit date
      sort, matching `Ledger.register()`'s figures for the same account.
- [ ] Cleared Balance column, alongside it, reflects only `*`-flagged
      transactions' cumulative total, under the same visibility rules.
- [ ] Both columns are absent when no account is selected, when a
      non-leaf/parent account is selected, or when the table is sorted by
      payee or amount.
- [ ] Reversing a date sort (asc → desc) keeps each row's balance values
      correct in both columns (i.e. earliest-to-latest cumulative, not
      recomputed against the reversed order) while flipping row order.
- [ ] `#recurring`-tagged rows and non-`Transaction` directive rows show
      blank cells in both columns rather than a stale or incorrect figure.
- [ ] A non-cleared transaction shows a normal (flag-agnostic) Balance cell
      but a blank Cleared Balance cell.
- [ ] Test covering: leaf-account visibility in default/asc/desc date
      sorts, hidden for parent/no-account/payee/amount-sorted states,
      multi-currency non-mixing, Cleared Balance correctness against a mix
      of `*`/`!`-flagged transactions, and balance correctness under a
      reversed sort.
