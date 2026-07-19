# TODO

Roadmap for the next round of work, roughly in priority order within each
section. The v0.1 scope — full editing workflow (add/edit/duplicate/delete/
undo), filtering, multi-file ledgers, directive display/editing, auto-reload,
CI with lint + mypy + tests — is done; see the git history for details.

## Reports & views

- [ ] **Income statement view.** A screen (e.g. behind an `i` binding)
  summarizing Income and Expenses accounts over a selectable period, with
  per-account and net totals. `realization.realize` already provides the
  tree; filter entries by date range before realizing.
- [ ] **Balance sheet view.** Same idea for Assets/Liabilities/Equity at a
  chosen date, including the implicit net-income line so it balances.
- [ ] **Register view with running balance.** For the selected account, show
  each transaction's posting amount and the cumulative balance after it —
  what `bean-report register` gives on the CLI.
- [ ] **Date-range presets for the filter.** Quick keys or tokens for
  common ranges (this month, last month, this year) on top of the existing
  `START..END` syntax.

## Ledger features

- [ ] **Tags and links.** Show `#tag` / `^link` on transactions (a table
  column or detail row) and let the text filter match them.
- [ ] **Commodities and prices.** Display `commodity` and `price` directives
  (extend `DISPLAYED_DIRECTIVES`), and optionally show market-value
  balances in the sidebar via `beancount.core.prices`.
- [ ] **Balance-assertion helper.** A binding that inserts a `balance`
  directive for the selected account pre-filled with the currently computed
  amount — the fastest way to checkpoint an account after reconciling.
- [ ] **Multi-level undo/redo.** Grow the single-slot undo into a bounded
  history stack, with redo.

## Import

- [ ] **CSV import wizard.** Load a bank CSV, let the user map columns
  (date/amount/payee/narration) and pick the target account, preview the
  generated transactions, and append the ones they confirm. Deduplicate
  against existing entries by date+amount.
- [ ] **beangulp integration.** Once the built-in CSV path works, support
  running the user's existing beangulp importers and reviewing their output
  in the same preview flow.

## UX polish

- [ ] **Help screen.** A `?` binding listing all key bindings, since the
  footer is getting crowded.
- [ ] **Sortable columns.** Click or key-cycle the transaction table's sort
  (date, payee, amount).
- [ ] **Transaction detail panel.** Show the full source text (metadata,
  cost basis, tags) of the selected entry, since the table row elides it.

## Tooling

- [ ] **Textual snapshot tests.** Add `pytest-textual-snapshot` to catch
  visual regressions in the main screen and modals.
- [ ] **Python version matrix in CI.** Test against 3.11, 3.12, and 3.13
  instead of only the runner default.
- [ ] **Coverage reporting.** Run pytest with `--cov` in CI and fail below a
  threshold once the baseline is known.
- [ ] **Package and publish.** Fill out project metadata (classifiers,
  URLs), add a changelog, and publish to PyPI so `uvx beancount-tui` works.
