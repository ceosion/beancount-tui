# TODO

Follow-up tasks, roughly in priority order. Items in **Known scaffold
limitations** are gaps in the current implementation; the rest are new
features.

## Known scaffold limitations

- [x] **Preserve/choose the transaction flag in the form.** The form always
  saves with flag `*`, so editing a `!` (pending) transaction silently
  normalizes it to `*`. Add a flag field (or toggle) to `TransactionForm`
  and prefill it on edit.
- [x] **Delete transactions.** There is no way to remove a transaction from
  the UI. Add a `d` binding with a confirmation prompt; the write side can
  reuse `entry_line_span` to splice out the entry's source lines.
- [x] **Cumulative balances in the account tree.** The sidebar shows each
  account's own balance, not the roll-up of its children (e.g.
  `Expenses:Food` shows nothing even when its sub-accounts have activity).
  Use `realization.compute_balance` for parent nodes.

## Features

- [x] **Search / filter.** Filter the transaction table by payee, narration,
  or date range (e.g. a `/` binding opening a filter input).
- [x] **Multi-file ledgers.** `replace_entry` already writes to the correct
  file via the entry's `filename` metadata, but new transactions are always
  appended to the top-level file. Let the user pick the target file when the
  ledger uses `include` directives.
- [x] **Edit non-transaction directives.** `open`, `close`, `balance`, `pad`,
  and `note` directives are invisible in the UI. At minimum show them;
  ideally make them editable through the same text-validation path.
- [x] **Duplicate transaction.** A binding to copy the selected transaction
  into the new-transaction form with today's date — the fastest way to enter
  recurring transactions.
- [x] **Account name completion in the form.** The postings `TextArea` is
  free-text; offer completion from `Ledger.accounts`.
- [ ] **Auto-reload on external changes.** Watch the ledger file(s) and
  reload when another editor writes to them, instead of relying on `r`.
- [ ] **Undo.** At minimum, an in-app undo for the last write (keep the
  pre-write file content in memory).

## Tooling

- [x] **CI.** Add a GitHub Actions workflow running `uv run pytest` and
  `uv run ruff check .` — the repo currently has no CI.
- [ ] **Type checking.** Add mypy or pyright to the dev group and CI.
