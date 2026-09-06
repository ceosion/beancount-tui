# Reports (`RPT`)

Beyond the income statement that already ships, Beancount's other standard
reports (`bean-report`/`bean-query` equivalents) aren't available in the TUI
yet. `Ledger.income_statement` is the existing model to follow: filter
entries by date, realize/aggregate, hand a small dataclass to a screen
widget.

---

### RPT-01: Balance sheet view

- **Status:** todo
- **Depends on:** none
- **Effort:** 2h

**Description:** A screen (e.g. behind a `b` binding) summarizing Assets,
Liabilities, and Equity account balances as of a chosen date, following the
same pattern as `IncomeStatementScreen`/`Ledger.income_statement`. Include
the implicit net-income line (current period's income minus expenses,
computed the same way `Ledger.income_statement` does) so the sheet balances
even mid-year, before a bean-close would fold it into Equity.

**Acceptance criteria:**
- [ ] New screen shows Assets, Liabilities, Equity with per-account and
      section totals as of a selectable date (default: today).
- [ ] Includes a synthetic net-income line so total Assets = total
      Liabilities + Equity (+ net income).
- [ ] Test covering totals against a known example ledger state.

---

### RPT-02: Register view with running balance

- **Status:** todo
- **Depends on:** none
- **Effort:** 1.5h

**Description:** For the currently selected account, a view showing each
transaction's posting amount to that account plus the cumulative running
balance after it — what `bean-report register ACCOUNT` gives on the CLI.
Can reuse `Ledger.transactions_for_account` and iterate summing posting
units per currency.

**Acceptance criteria:**
- [ ] New screen/mode shows date, narration, posting amount, and running
      balance for the selected account's transactions, in date order.
- [ ] Handles accounts with postings in more than one currency without
      mixing running totals across currencies.
- [ ] Test covering running-balance correctness across a short known
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

- **Status:** todo
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
- [ ] New screen lists holdings by commodity/account with quantity, cost
      basis, and market value (when a price is available).
- [ ] Shows a net-worth total in the operating currency, falling back
      gracefully (e.g. "no price available") for commodities with no price
      history.
- [ ] Test covering a ledger with at least one costed lot and a matching
      `price` directive.

---

### RPT-06: Ad hoc BQL query runner

- **Status:** todo
- **Depends on:** none
- **Effort:** 2h

**Description:** A screen with a text input for a BQL query, run against the
loaded ledger via `beancount.query.query.run_query` (same engine as
`bean-query`), rendering the result as a table. If `LANG-07` (Query
directives) has landed, also let the user pick a saved named query from the
ledger to run instead of typing one.

**Acceptance criteria:**
- [ ] User can type a BQL query and see a result table.
- [ ] Query errors (bad syntax, unknown column) are shown inline rather than
      crashing the app.
- [ ] Test covering a simple known query against the example ledger.
- [ ] If `LANG-07` is done: named queries from the ledger are selectable and
      run the same way.
