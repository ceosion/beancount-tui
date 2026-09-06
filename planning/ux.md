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

- **Status:** todo
- **Depends on:** none
- **Effort:** 1h

**Description:** Let the user cycle the transaction table's sort order by
date, payee, or amount — via clicking a column header (Textual's
`DataTable` supports header clicks) or a key that cycles sort field,
toggling ascending/descending on repeat.

**Acceptance criteria:**
- [ ] Table can be sorted by date, payee, and amount, each toggling
      ascending/descending on repeated selection.
- [ ] Sort persists across filter changes and account selection until
      explicitly changed.
- [ ] Test covering sort order for each field.

---

### UX-03: Transaction/directive detail panel

- **Status:** todo
- **Depends on:** none
- **Effort:** 1.5h

**Description:** The table elides metadata, cost basis, and tags/links for
space. Add a detail panel (side or bottom pane, or a modal on demand) that
shows the full source text of the currently selected entry via the existing
`editor.format_entry`, updating as the cursor moves.

**Acceptance criteria:**
- [ ] Selecting a row updates the detail panel with that entry's full
      formatted source text.
- [ ] Panel is togglable (doesn't have to always be visible, to preserve
      table space on small terminals).
- [ ] Test covering the panel content matches `format_entry` output for a
      selected entry.

---

### UX-04: Row polish for new directive types

- **Status:** todo
- **Depends on:** LANG-02, LANG-03, LANG-04, LANG-05, LANG-06, LANG-07
- **Effort:** 1h

**Description:** Once `Price`/`Commodity`/`Event`/`Document`/`Custom`/`Query`
rows exist (`LANG-02`..`LANG-07`), do a pass for visual consistency: distinct
color or short-tag styling per directive type in the flag/keyword column, so
a mixed-directive table (with `t` toggled on) stays scannable rather than
reading as a wall of similar rows.

**Acceptance criteria:**
- [ ] Each directive type has a visually distinct keyword marker (color or
      style) in the table.
- [ ] Verified visually by running the app against a ledger containing every
      directive type at once.
