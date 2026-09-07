# UX polish (`UX`)

Usability improvements that aren't tied to a specific Beancount feature.

---

### UX-01: Help screen

- **Status:** done
- **Depends on:** none
- **Effort:** 1h

**Description:** A `?` binding that opens a modal listing every key binding
currently registered in `BeancountTUI.BINDINGS` (plus any modal-specific
bindings worth surfacing), since the footer is getting crowded and new
bindings keep landing across the `LANG`/`RPT`/`EDIT` tasks.

**Acceptance criteria:**
- [x] `?` opens a modal listing key → action → description for all
      top-level app bindings.
- [x] Modal is dismissible (`escape` or a close button).
- [x] Test covering the modal opens and lists the expected bindings.

---

### UX-02: Sortable columns

- **Status:** done
- **Depends on:** none
- **Effort:** 1h

**Description:** Let the user cycle the transaction table's sort order by
date, payee, or amount — via clicking a column header (Textual's
`DataTable` supports header clicks) or a key that cycles sort field,
toggling ascending/descending on repeat.

**Acceptance criteria:**
- [x] Table can be sorted by date, payee, and amount, each toggling
      ascending/descending on repeated selection.
- [x] Sort persists across filter changes and account selection until
      explicitly changed.
- [x] Test covering sort order for each field.

---

### UX-03: Transaction/directive detail panel

- **Status:** done
- **Depends on:** none
- **Effort:** 1.5h

**Description:** The table elides metadata, cost basis, and tags/links for
space. Add a detail panel (side or bottom pane, or a modal on demand) that
shows the full source text of the currently selected entry via the existing
`editor.format_entry`, updating as the cursor moves.

**Acceptance criteria:**
- [x] Selecting a row updates the detail panel with that entry's full
      formatted source text.
- [x] Panel is togglable (doesn't have to always be visible, to preserve
      table space on small terminals).
- [x] Test covering the panel content matches `format_entry` output for a
      selected entry.

---

### UX-04: Row polish for new directive types

- **Status:** done
- **Depends on:** LANG-02, LANG-03, LANG-04, LANG-05, LANG-06, LANG-07
- **Effort:** 1h

**Description:** Once `Price`/`Commodity`/`Event`/`Document`/`Custom`/`Query`
rows exist (`LANG-02`..`LANG-07`), do a pass for visual consistency: distinct
color or short-tag styling per directive type in the flag/keyword column, so
a mixed-directive table (with `t` toggled on) stays scannable rather than
reading as a wall of similar rows.

**Acceptance criteria:**
- [x] Each directive type has a visually distinct keyword marker (color or
      style) in the table.
- [x] Verified visually by running the app against a ledger containing every
      directive type at once. (No interactive terminal was available in this
      environment, so this was verified programmatically instead: an
      automated test loads a ledger containing one of every directive type
      through the real Beancount parser, runs each entry through the same
      `_entry_row` function `TransactionTable` uses, and asserts every
      directive keyword renders as a `rich.text.Text` cell with a style
      unique to its directive type, distinct from a Transaction's plain,
      unstyled flag cell.)

---

### UX-05: Single-key flag cycling on the highlighted transaction

- **Status:** done
- **Depends on:** none
- **Effort:** 1h

**Description:** A binding (`f` is currently free in `BeancountTUI.BINDINGS`)
that, when `TransactionTable.selected_entry` is a `data.Transaction` (a
no-op for directive rows when the `t` toggle is on), cycles its flag
between the two states this codebase already documents — `*` (cleared) and
`!` (pending), per `TransactionForm`'s own "Flag (* = cleared, ! = pending)"
label — without opening the full edit form. Reuse `entry._replace(flag=...)`
(Beancount directives are `NamedTuple`s) plus the existing
`editor.format_entry`/`editor.replace_entry` pair already used by the
edit/duplicate flows, followed by the same `_snapshot_for_undo` +
`action_reload` sequence `action_new_transaction` and friends use, so the
change is undoable like any other edit.

**Acceptance criteria:**
- [x] Pressing the binding on a highlighted `Transaction` row toggles its
      flag between `*` and `!` and persists the change to the source file.
- [x] Pressing it on a highlighted directive row (or with no row selected)
      is a no-op.
- [x] The change is undoable via the existing `u` binding.
- [x] Test covering the cycle (`*` → `!` → `*`) against a known transaction
      and that the on-disk text reflects only the flag character changing.

---

### UX-06: Enhanced date picker UX

- **Status:** todo
- **Depends on:** none
- **Effort:** 2h

**Description:** Date fields across the app (`TransactionForm`,
`DirectiveForm`, `BudgetForm`, report date pickers, the filter bar's
`START..END` range) are currently plain text `Input`s requiring an exact
`YYYY-MM-DD` string. Add a calendar-style picker overlay (arrow keys to
move by day, `pageup`/`pagedown` or similar by month, `enter` to accept)
reachable from any date field, while keeping direct typed-ISO-date entry as
a fallback for users who prefer it — this should be additive, not a
replacement that forces every date through the picker.

**Acceptance criteria:**
- [ ] A calendar picker can be opened from any existing date `Input` and
      set that field's value on selection.
- [ ] Typing an ISO date directly still works without opening the picker.
- [ ] Picker defaults to the field's current value (or today, if empty) and
      supports day/month navigation via keys.
- [ ] Test covering picker-driven date selection produces the same
      `YYYY-MM-DD` string a direct type would have.

---

### UX-07: Intelligent completion suggestions for Payee, Narration, and Tags

- **Status:** done
- **Depends on:** none
- **Effort:** 2h

**Description:** `AccountInput`/`PostingsArea` already Tab-complete account
names against `ledger.accounts` (longest-common-prefix, full completion on
a unique match — see `account_input.py`/`postings_area.py`). Extend the
same pattern to the Payee and Narration `Input`s and the Tags field in
`TransactionForm` (and anywhere else they appear), suggesting from values
already seen in the ledger: distinct `entry.payee`/`entry.narration`
strings across `ledger.transactions`, and distinct tags across
`entry.tags`. Payee/tag matching can reuse the exact longest-common-prefix
logic; narration is free text so a looser "recently used, prefix-matched"
suggestion list (rather than forced full-line completion) fits better.

**Acceptance criteria:**
- [x] Payee field suggests/completes from payees already used in the
      ledger.
- [x] Tags field suggests/completes from tags already used in the ledger
      (including tags used only on non-transaction directives, if any).
- [x] Narration field offers prefix-matched suggestions from prior
      narrations without forcing a single completion.
- [x] Typing a value with no match is unaffected (falls through to normal
      input behavior, mirroring `AccountInput`'s no-match fallback).
- [x] Test covering suggestion/completion behavior for each of the three
      fields against a ledger with known prior values.

---

### UX-08: Structured Postings editor with raw-text toggle

- **Status:** todo
- **Depends on:** none
- **Effort:** 3h

**Description:** `PostingsArea` (`postings_area.py`) is a raw `TextArea`
with Tab-completion on the account token of the current line — powerful but
unguided (free-form Beancount syntax, no per-posting structure). Add an
alternate structured UX: one row per posting with a dedicated account field
(reusing `AccountInput`'s completion) and a dedicated amount/currency
field, plus add/remove-row controls. Provide a toggle (key or button) to
switch between this structured view and the existing raw-text
`PostingsArea` for the same in-progress entry, so postings needing syntax
the structured UX doesn't model yet (cost basis, price annotations,
per-posting metadata, `LANG-10`'s cost/price postings) always have an
escape hatch. Whichever view is active when the form is submitted is the
one whose content is used — both must serialize to/parse from the same
Beancount posting text so switching mid-edit doesn't lose entered data.

**Acceptance criteria:**
- [ ] A toggle switches between the structured row-based postings UX and
      the existing raw-text `PostingsArea`, preserving already-entered
      postings across the switch.
- [ ] Structured UX supports add/remove posting rows, account completion
      (via `AccountInput`), and amount/currency entry.
- [ ] Postings entered in either UX produce identical parsed
      `data.Posting` results for equivalent input.
- [ ] Postings using syntax the structured UX doesn't model (e.g. cost
      basis) round-trip correctly when authored/viewed via the raw-text
      fallback.
- [ ] Test covering structured-to-raw and raw-to-structured round-trips for
      a simple two-posting transaction.

