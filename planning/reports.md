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

- **Status:** done
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
- [x] Balance column is present and correct for a single leaf account with
      the table in its default (untouched) state or either explicit date
      sort, matching `Ledger.register()`'s figures for the same account.
- [x] Cleared Balance column, alongside it, reflects only `*`-flagged
      transactions' cumulative total, under the same visibility rules.
- [x] Both columns are absent when no account is selected, when a
      non-leaf/parent account is selected, or when the table is sorted by
      payee or amount.
- [x] Reversing a date sort (asc → desc) keeps each row's balance values
      correct in both columns (i.e. earliest-to-latest cumulative, not
      recomputed against the reversed order) while flipping row order.
- [x] `#recurring`-tagged rows and non-`Transaction` directive rows show
      blank cells in both columns rather than a stale or incorrect figure.
- [x] A non-cleared transaction shows a normal (flag-agnostic) Balance cell
      but a blank Cleared Balance cell.
- [x] Test covering: leaf-account visibility in default/asc/desc date
      sorts, hidden for parent/no-account/payee/amount-sorted states,
      multi-currency non-mixing, Cleared Balance correctness against a mix
      of `*`/`!`-flagged transactions, and balance correctness under a
      reversed sort.

---

### RPT-08: Collapsible account tree

- **Status:** done
- **Depends on:** none
- **Effort:** 1h

**Description:** `AccountTree.update_accounts` force-expands every node on
every rebuild (`_add_account_nodes` adds each child with `expand=True`,
plus `update_accounts` itself calls `self.root.expand()`), and a rebuild
happens on every reload/filter change/account selection via
`refresh_views`. Textual's base `Tree` already ships per-node
collapse/expand (`action_toggle_node`, bound to `space`) and
collapse/expand-all-siblings (`action_toggle_expand_all`, `shift+space`)
for free — nothing new needs to be built there. The actual bug is that any
manual collapse a user makes is immediately wiped out the next time
`update_accounts` runs, since it unconditionally re-expands everything.
Fix by snapshotting which account paths are currently collapsed before
`self.clear()`, and re-applying that state after rebuilding, rather than
adding new collapse machinery.

**Acceptance criteria:**
- [x] Collapsing a node in the sidebar survives a ledger reload, filter
      change, or account selection (previously-collapsed accounts stay
      collapsed).
- [x] A freshly loaded ledger still starts fully expanded (first-load
      default is unchanged).
- [x] Existing `space`/`shift+space` collapse/expand bindings continue to
      work.
- [x] Test covering: collapse an account, trigger `update_accounts` again
      (simulating a reload), assert it's still collapsed.

---

### RPT-09: Multi-period comparison reports

- **Status:** done
- **Depends on:** RPT-03
- **Effort:** 2.5h

**Description:** `Ledger.income_statement`/`trial_balance`/`balance_sheet`/
`holdings` each take a single date/date-range, and their screens render
exactly one period at a time via one `_render_report` call into one
`DataTable` — no side-by-side month-over-month or this-year-vs-last-year
view like Fava's period comparison exists anywhere. Add a comparison mode
to `income_statement` first (the report where this matters most): accept
a list of periods and render one column per period per account, building
each period's `(start, end)` from `RPT-03`'s existing preset tokens
(`month`, `last-month`, `year`, `last-year`) as well as explicit ranges.
Keep the existing single-period call signature/behavior intact — this is
an additional mode, not a replacement.

**Acceptance criteria:**
- [x] A comparison mode accepts 2+ periods and renders a multi-column
      table (one column per period) for the income statement.
- [x] Existing single-period `income_statement`/screen behavior is
      unchanged when only one period is requested.
- [x] Period columns can be built from `RPT-03`'s preset tokens as well as
      explicit ranges.
- [x] Test covering a known ledger's month-over-month comparison against
      manually computed per-period totals.

---

### RPT-10: Commodity price history view

- **Status:** todo
- **Depends on:** LANG-02
- **Effort:** 1.5h

**Description:** `Ledger` only ever consumes `Price` directives via
`build_price_map` for a single latest-rate lookup (`_price_map_cached`,
used by `holdings()`/`converted_total()`) — there's no way to see a
commodity's price over time, unlike Fava's price chart. Add a
`Ledger.price_history(commodity) -> list[tuple[date, Decimal, str]]`
method returning every `Price` entry for that commodity in date order
(rate, quote currency), and a screen/binding showing it as a simple
date-ordered table — a chart is out of scope, since Textual has no native
charting widget and pulling in a plotting dependency is disproportionate
for a TUI; a table is the pragmatic equivalent here. Let the user pick a
commodity from those that actually have price history.

**Acceptance criteria:**
- [ ] New method returns a commodity's price entries in date order.
- [ ] New screen/binding lists commodities with price history and shows
      the selected one's full history as a table.
- [ ] Commodities with no `Price` directives are excluded from the picker.
- [ ] Test covering price-history output against a known ledger with
      multiple `Price` entries for one commodity.

---

### RPT-11: Document preview modal

- **Status:** done
- **Depends on:** none
- **Effort:** 1.5h

**Description:** `data.Document` rows already show account/filename and
flag missing files (`_entry_row`'s Document handling, from `LANG-05`), but
there's no way to view the referenced file's actual contents without
leaving the TUI. Add an action that, when a `Document` row is selected,
opens a modal previewing the file: render as plain text for text-like
files (by extension or a quick content sniff), and for binary/unsupported
files show a graceful fallback message with basic file metadata (size,
modified time) rather than attempting to dump raw bytes. A row whose file
is missing (already flagged with `!`) shows a "file not found" message
instead of attempting to read it.

**Acceptance criteria:**
- [x] Selecting a `Document` row and triggering the preview action opens a
      modal showing the file's text contents (for text-like files).
- [x] Binary/unsupported files show a graceful fallback message with basic
      file metadata instead of raw bytes or a crash.
- [x] A `Document` row whose file is missing shows a "file not found"
      message instead of attempting to read it.
- [x] Test covering: text file preview content, binary fallback message,
      and missing-file message, using fixture files under a temp ledger
      directory.
