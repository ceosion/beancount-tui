# Language coverage (`LANG`)

Beancount has more directive types and transaction-level features than the
TUI currently surfaces. `ledger.py`'s `DISPLAYED_DIRECTIVES` only shows
`Transaction`, `Open`, `Close`, `Balance`, `Pad`, `Note` — and even those can
only be *edited or deleted*, not *created*, through the UI today (creation
only exists for transactions). `editor.py`'s `parse_directive_text` /
`replace_entry` / `delete_entry` and `directive_form.py`'s `DirectiveForm` are
already directive-agnostic, which is why most tasks below are small.

Goal: every directive type Beancount supports can be viewed, created, and
edited from the TUI, and transaction-level features (tags, links, metadata,
cost basis) are first-class instead of only reachable by hand-typing into a
free-text box.

---

### LANG-01: Add-directive infrastructure + templates for existing types

- **Status:** todo
- **Depends on:** none
- **Effort:** 2h

**Description:** There's currently no way to *create* an `open`, `close`,
`balance`, `pad`, or `note` directive from the UI — only edit/delete ones
that already exist in the ledger. Add a new binding (e.g. `a` for "add
directive") that opens a directive-type picker (a `Select`/list modal), then
pushes `DirectiveForm` pre-filled with a minimal valid template for the
chosen type (e.g. `2026-09-06 open Assets:  \n` for open), targeting the
appropriate ledger file (reuse the existing file picker from
`TransactionForm` for multi-file ledgers). On save, append the text with
`append_transaction` (rename to `append_entry` in `editor.py` since it's
already directive-agnostic — it just appends text).

This task only wires up `Open`, `Close`, `Balance`, `Pad`, `Note` (the types
already in `DISPLAYED_DIRECTIVES`). `LANG-02` through `LANG-07` reuse this
same infrastructure to add new directive types.

**Acceptance criteria:**
- [ ] `a` binding opens a directive-type picker listing at least Open, Close,
      Balance, Pad, Note.
- [ ] Choosing a type opens `DirectiveForm` pre-filled with a valid template
      for that type, targeting the correct file when the ledger has includes.
- [ ] Saving appends the entry, reloads the ledger, and the new entry appears
      in the table (behind the `t` toggle).
- [ ] `editor.append_transaction` renamed to `append_entry` (or a thin
      generic wrapper added) with call sites updated.
- [ ] Tests: creating one of each of the five types via the new flow round-
      trips through a real ledger file and appears in `Ledger.entries` after
      reload.

---

### LANG-02: Price directives

- **Status:** todo
- **Depends on:** LANG-01
- **Effort:** 1h

**Description:** Add `data.Price` to `DISPLAYED_DIRECTIVES`, give it a row
renderer in `transaction_table._entry_row` (date, `"price"`, commodity, `N
CCY`), and add it to the LANG-01 type picker with a template like
`2026-09-06 price HOOL  100.00 USD`.

**Acceptance criteria:**
- [ ] `Price` entries appear in the table when directives are toggled on.
- [ ] Row shows date, keyword, commodity, and quoted price.
- [ ] Creatable via the LANG-01 picker; editable/deletable like existing
      types (already generic, just needs the `DISPLAYED_DIRECTIVES` entry).
- [ ] Test covering display and round-trip creation.

---

### LANG-03: Commodity directives

- **Status:** todo
- **Depends on:** LANG-01
- **Effort:** 1h

**Description:** Same shape as `LANG-02` for `data.Commodity`. Row shows
date, `"commodity"`, the commodity symbol, and (if present) a `name`
metadata value in the summary column.

**Acceptance criteria:**
- [ ] `Commodity` entries display with symbol and any `name` metadata.
- [ ] Creatable via the LANG-01 picker with a template
      (`2026-09-06 commodity HOOL`).
- [ ] Test covering display and round-trip creation.

---

### LANG-04: Event directives

- **Status:** todo
- **Depends on:** LANG-01
- **Effort:** 1h

**Description:** Same shape for `data.Event`. Row shows date, `"event"`,
event type, and description (e.g. `"location": "Paris"`).

**Acceptance criteria:**
- [ ] `Event` entries display with type and description.
- [ ] Creatable via the LANG-01 picker with a template
      (`2026-09-06 event "location" "Paris"`).
- [ ] Test covering display and round-trip creation.

---

### LANG-05: Document directives

- **Status:** todo
- **Depends on:** LANG-01
- **Effort:** 1.5h

**Description:** Same shape for `data.Document`, plus one extra: check
whether the referenced file exists (relative to the ledger's directory) and
flag it visually (e.g. a `!` marker or muted color) if it's missing, since a
dangling `document` directive is a common ledger-hygiene issue.

**Acceptance criteria:**
- [ ] `Document` entries display with account and filename.
- [ ] Missing referenced files are visually flagged in the row.
- [ ] Creatable via the LANG-01 picker.
- [ ] Test covering display, the missing-file flag, and round-trip creation.

---

### LANG-06: Custom directives

- **Status:** todo
- **Depends on:** LANG-01
- **Effort:** 1h

**Description:** Same shape for `data.Custom`. Values are heterogeneous
(`entry.values` is a list of typed value objects), so render generically:
date, `"custom"`, `entry.type`, and a joined string of `v.value for v in
entry.values`.

**Acceptance criteria:**
- [ ] `Custom` entries display with their type and joined values.
- [ ] Creatable via the LANG-01 picker with a generic template
      (`2026-09-06 custom "budget" ...`).
- [ ] Test covering display and round-trip creation.

---

### LANG-07: Query directives

- **Status:** todo
- **Depends on:** LANG-01
- **Effort:** 1h

**Description:** Same shape for `data.Query` (named BQL queries stored in
the ledger, e.g. `2026-09-06 query "cash" "SELECT ..."`). Display only here
— actually *running* a query (named or ad hoc) is `RPT-06`.

**Acceptance criteria:**
- [ ] `Query` entries display with name and a truncated view of the query
      text.
- [ ] Creatable via the LANG-01 picker.
- [ ] Test covering display and round-trip creation.

---

### LANG-08: Tags and links

- **Status:** todo
- **Depends on:** none
- **Effort:** 2h

**Description:** `TransactionForm._assemble_text` builds the header as
`{date} {flag}{payee} "{narration}"` with no room for `#tag`/`^link`
tokens, and `_entry_row`/`_entry_search_text` don't surface them. Add a
"Tags / links" input field to the form (space-separated, e.g.
`#vacation ^receipt-123`), append it to the assembled header, parse existing
tags/links back into that field when editing (`entry.tags`, `entry.links`),
show them in the table (append to the narration cell or add a column), and
make `filter_transactions` match against them.

**Acceptance criteria:**
- [ ] Form has a tags/links field; round-trips correctly on create and edit
      (pre-filled from `entry.tags`/`entry.links` when editing).
- [ ] Table shows tags/links for transactions that have them.
- [ ] Text filter matches on tag/link content.
- [ ] Tests: create with tags+links, edit to change them, filter by tag.

---

### LANG-09: Metadata surfacing

- **Status:** todo
- **Depends on:** none
- **Effort:** 1h

**Description:** Transaction/posting metadata (`key: "value"` lines) can
already be typed into the postings `TextArea` as an indented line and will
parse correctly — but nothing displays or filters on it. Make
`_entry_search_text` include metadata values so the filter bar can match on
them, and show a lightweight indicator (e.g. a `+` marker or a count) in the
table when an entry has metadata, since full metadata display belongs to the
detail panel (`UX-03`).

**Acceptance criteria:**
- [ ] Filter matches substrings found in transaction or posting metadata
      values.
- [ ] Table row indicates when an entry has metadata beyond the standard
      fields.
- [ ] Test covering filter-by-metadata-value.

---

### LANG-10: Cost basis and price annotations in the table

- **Status:** todo
- **Depends on:** none
- **Effort:** 1.5h

**Description:** Postings with cost basis (`10 HOOL {500.00 USD}`) or a
price annotation (`@ 55.00 USD`) already parse and save correctly (it's
free text handled by the real parser), but `transaction_amount` sums raw
posting units per currency, which reads oddly for a lot-costed posting (e.g.
showing `10 HOOL` instead of a currency amount). Detect postings with `cost`
or `price` set and represent them using the cost/price total in the amount
summary instead of the bare commodity count.

**Acceptance criteria:**
- [ ] A transaction with a `{cost}`-annotated posting shows a sensible
      currency amount in the table, not a raw commodity quantity.
- [ ] A transaction with a `@ price` annotation is represented similarly.
- [ ] Existing behavior for plain-currency postings is unchanged.
- [ ] Test covering both cost-basis and price-annotation formatting.

---

### LANG-11: Ledger info screen

- **Status:** todo
- **Depends on:** none
- **Effort:** 1.5h

**Description:** A read-only modal/screen (e.g. bound to a new key, or
folded into an existing "info" area) showing effective Beancount options
that currently aren't visible anywhere in the UI: `title`, operating
currencies (`operating_currency`), default booking method
(`booking_method`), `name_assets`/`name_liabilities`/etc. if overridden, and
the list of source files (`Ledger.files`, already computed). Pull all of
this from `Ledger.options`.

**Acceptance criteria:**
- [ ] New screen/binding shows title, operating currencies, default booking
      method, and account-name overrides when present.
- [ ] Shows the full list of source files (top-level + includes).
- [ ] Gracefully handles ledgers that don't set any of these (defaults only).
- [ ] Test covering the screen against the example ledger's options.
