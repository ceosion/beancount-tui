# Import (`IMP`)

Bringing external transaction data into the ledger, rather than hand-typing
every entry. Split into small stages so each lands as an independently
useful, testable increment.

---

### IMP-01: CSV load and column mapping

- **Status:** done
- **Depends on:** none
- **Effort:** 2h

**Description:** A modal flow: pick a CSV file (path input), preview its
first few rows, let the user map columns to date/amount/payee/narration
(and pick which account the CSV represents, e.g. the bank account being
imported), then parse the full file into a list of candidate transactions
held in memory (not yet written anywhere — that's `IMP-02`).

**Acceptance criteria:**
- [x] User can point at a CSV file and see a preview of its rows.
- [x] User maps date/amount/payee/narration to columns and picks the target
      account.
- [x] Parsing produces an in-memory list of candidate `data.Transaction`-like
      structures (need not be full Beancount `Transaction` objects yet).
- [x] Malformed rows (bad date, non-numeric amount) are reported per-row,
      not a hard failure of the whole import.
- [x] Test covering column mapping and parsing against a small fixture CSV.

---

### IMP-02: Import preview and selective append

- **Status:** todo
- **Depends on:** IMP-01
- **Effort:** 2h

**Description:** A review screen listing the candidate transactions from
`IMP-01`, each with a checkbox (default checked), letting the user
deselect ones they don't want, edit one via the existing `TransactionForm`
before import, and then append every confirmed one via `append_transaction`
to the appropriate target file.

**Acceptance criteria:**
- [ ] Review screen lists all candidates with a per-row toggle.
- [ ] A candidate can be opened in `TransactionForm` for edits before import.
- [ ] Confirming appends only the checked candidates and reloads the ledger.
- [ ] Test covering partial selection (some appended, some skipped).

---

### IMP-03: Duplicate detection against existing entries

- **Status:** todo
- **Depends on:** IMP-01
- **Effort:** 1h

**Description:** Before showing the `IMP-02` preview, flag candidates that
likely already exist in the ledger — matching by date + amount (+ account)
against `Ledger.transactions_for_account` — and default those rows to
unchecked, with a visible reason (e.g. "possible duplicate of 2026-08-03
entry").

**Acceptance criteria:**
- [ ] Candidates matching an existing transaction by date+amount(+account)
      are flagged and default to unchecked in the `IMP-02` preview.
- [ ] The match reason/reference is visible to the user.
- [ ] Test covering a candidate that duplicates a fixture ledger entry.

---

### IMP-04: beangulp importer integration

- **Status:** todo
- **Depends on:** IMP-02
- **Effort:** 2h

**Description:** Let the user point at a Python module defining
[beangulp](https://github.com/beancount/beangulp) `Importer` subclasses and
a source file; run the matching importer's `extract()` to produce
candidate entries, then feed them into the same `IMP-02` preview/append
flow (and `IMP-03` dedup) used for the built-in CSV path.

**Acceptance criteria:**
- [ ] User can specify a beangulp importer config/module and a file to
      import.
- [ ] The importer's extracted entries flow through the same preview,
      dedup, and append path as CSV import.
- [ ] A config/module that fails to load or has no matching importer
      produces a clear error, not a crash.
- [ ] Test covering a minimal fixture beangulp importer end to end.
