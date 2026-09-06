# Core editing features (`EDIT`)

Enhancements to the write side beyond what v0.1 shipped (add/edit/duplicate/
delete/single-slot undo).

---

### EDIT-01: Multi-level undo/redo

- **Status:** done
- **Depends on:** none
- **Effort:** 1.5h

**Description:** `app.py` currently keeps one `(path, content)` snapshot in
`self._undo`, overwritten on every write. Replace it with a bounded stack
(e.g. last 20 changes) per file, and add a redo stack that's pushed to on
undo and cleared on any new write. Add a `U` (shift) or similar binding for
redo alongside the existing `u` for undo.

**Acceptance criteria:**
- [x] At least the last 20 writes to a file can be undone in sequence.
- [x] Redo restores an undone change; a new write clears the redo stack.
- [x] Undo/redo across writes touching *different* files in a multi-file
      ledger works independently per file.
- [x] Test covering undo-undo-redo-redo across 3+ sequential edits.

---

### EDIT-02: Balance-assertion helper

- **Status:** todo
- **Depends on:** LANG-01
- **Effort:** 1h

**Description:** A binding (e.g. `B`) that, for the currently selected
account, computes its current balance (already available via
`Ledger.root_account()`/realization) and opens the `LANG-01` add-directive
flow pre-filled with a `balance` directive for that account and amount,
dated today. This is the fastest way to checkpoint an account right after
reconciling it against a statement.

**Acceptance criteria:**
- [ ] Binding available when an account is selected in the sidebar.
- [ ] Pre-filled directive shows the account's current computed balance for
      each currency it holds (one directive per currency if it holds more
      than one).
- [ ] Saving appends and the ledger still validates (no self-inflicted
      assertion failure from a stale computed value).
- [ ] Test covering the pre-filled amount matches the account's realized
      balance.

---

### EDIT-03: Multi-currency valuation display

- **Status:** todo
- **Depends on:** none
- **Effort:** 1.5h

**Description:** Account balances in the sidebar/reports currently show
each currency's native amount side by side (`format_inventory`). Add an
optional converted total in the ledger's operating currency (from
`Ledger.options["operating_currency"]`), using
`beancount.core.prices.build_price_map` over the ledger's `Price` directives
to convert. Show "no price available" rather than silently omitting a
currency that can't be converted.

**Acceptance criteria:**
- [ ] Sidebar/account balances show a converted total in the operating
      currency alongside native amounts, when at least one operating
      currency is configured and prices are available.
- [ ] Currencies with no known price are called out rather than silently
      dropped from the total.
- [ ] No operating currency configured → unchanged current behavior.
- [ ] Test covering conversion math against a small ledger with known
      prices.

---

### EDIT-04: Pad-and-verify reconciliation helper

- **Status:** todo
- **Depends on:** EDIT-02
- **Effort:** 1h

**Description:** A companion to `EDIT-02`: a binding that inserts a `pad`
directive (from the selected account's usual pad-source account, or
prompted if none is inferable) immediately followed by the `balance`
assertion from `EDIT-02`, so reconciling an account against a statement is a
single action instead of two manual directive entries.

**Acceptance criteria:**
- [ ] Binding inserts both a `pad` and the matching `balance` directive in
      one action, correctly ordered (pad before balance, same date).
- [ ] If no prior pad-source account can be inferred for the selected
      account, the user is prompted to pick one.
- [ ] Test covering the generated pad+balance pair against a reconciliation
      scenario.
