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

- **Status:** done
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
- [x] `a` binding opens a directive-type picker listing at least Open, Close,
      Balance, Pad, Note.
- [x] Choosing a type opens `DirectiveForm` pre-filled with a valid template
      for that type, targeting the correct file when the ledger has includes.
- [x] Saving appends the entry, reloads the ledger, and the new entry appears
      in the table (behind the `t` toggle).
- [x] `editor.append_transaction` renamed to `append_entry` (or a thin
      generic wrapper added) with call sites updated.
- [x] Tests: creating one of each of the five types via the new flow round-
      trips through a real ledger file and appears in `Ledger.entries` after
      reload.

---

### LANG-02: Price directives

- **Status:** done
- **Depends on:** LANG-01
- **Effort:** 1h

**Description:** Add `data.Price` to `DISPLAYED_DIRECTIVES`, give it a row
renderer in `transaction_table._entry_row` (date, `"price"`, commodity, `N
CCY`), and add it to the LANG-01 type picker with a template like
`2026-09-06 price HOOL  100.00 USD`.

**Acceptance criteria:**
- [x] `Price` entries appear in the table when directives are toggled on.
- [x] Row shows date, keyword, commodity, and quoted price.
- [x] Creatable via the LANG-01 picker; editable/deletable like existing
      types (already generic, just needs the `DISPLAYED_DIRECTIVES` entry).
- [x] Test covering display and round-trip creation.

---

### LANG-03: Commodity directives

- **Status:** done
- **Depends on:** LANG-01
- **Effort:** 1h

**Description:** Same shape as `LANG-02` for `data.Commodity`. Row shows
date, `"commodity"`, the commodity symbol, and (if present) a `name`
metadata value in the summary column.

**Acceptance criteria:**
- [x] `Commodity` entries display with symbol and any `name` metadata.
- [x] Creatable via the LANG-01 picker with a template
      (`2026-09-06 commodity HOOL`).
- [x] Test covering display and round-trip creation.

---

### LANG-04: Event directives

- **Status:** done
- **Depends on:** LANG-01
- **Effort:** 1h

**Description:** Same shape for `data.Event`. Row shows date, `"event"`,
event type, and description (e.g. `"location": "Paris"`).

**Acceptance criteria:**
- [x] `Event` entries display with type and description.
- [x] Creatable via the LANG-01 picker with a template
      (`2026-09-06 event "location" "Paris"`).
- [x] Test covering display and round-trip creation.

---

### LANG-05: Document directives

- **Status:** done
- **Depends on:** LANG-01
- **Effort:** 1.5h

**Description:** Same shape for `data.Document`, plus one extra: check
whether the referenced file exists (relative to the ledger's directory) and
flag it visually (e.g. a `!` marker or muted color) if it's missing, since a
dangling `document` directive is a common ledger-hygiene issue.

**Acceptance criteria:**
- [x] `Document` entries display with account and filename.
- [x] Missing referenced files are visually flagged in the row.
- [x] Creatable via the LANG-01 picker.
- [x] Test covering display, the missing-file flag, and round-trip creation.

---

### LANG-06: Custom directives

- **Status:** done
- **Depends on:** LANG-01
- **Effort:** 1h

**Description:** Same shape for `data.Custom`. Values are heterogeneous
(`entry.values` is a list of typed value objects), so render generically:
date, `"custom"`, `entry.type`, and a joined string of `v.value for v in
entry.values`.

**Acceptance criteria:**
- [x] `Custom` entries display with their type and joined values.
- [x] Creatable via the LANG-01 picker with a generic template
      (`2026-09-06 custom "budget" ...`).
- [x] Test covering display and round-trip creation.

---

### LANG-07: Query directives

- **Status:** done
- **Depends on:** LANG-01
- **Effort:** 1h

**Description:** Same shape for `data.Query` (named BQL queries stored in
the ledger, e.g. `2026-09-06 query "cash" "SELECT ..."`). Display only here
— actually *running* a query (named or ad hoc) is `RPT-06`.

**Acceptance criteria:**
- [x] `Query` entries display with name and a truncated view of the query
      text.
- [x] Creatable via the LANG-01 picker.
- [x] Test covering display and round-trip creation.

---

### LANG-08: Tags and links

- **Status:** done
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
- [x] Form has a tags/links field; round-trips correctly on create and edit
      (pre-filled from `entry.tags`/`entry.links` when editing).
- [x] Table shows tags/links for transactions that have them.
- [x] Text filter matches on tag/link content.
- [x] Tests: create with tags+links, edit to change them, filter by tag.

---

### LANG-09: Metadata surfacing

- **Status:** done
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
- [x] Filter matches substrings found in transaction or posting metadata
      values.
- [x] Table row indicates when an entry has metadata beyond the standard
      fields.
- [x] Test covering filter-by-metadata-value.

---

### LANG-10: Cost basis and price annotations in the table

- **Status:** done
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
- [x] A transaction with a `{cost}`-annotated posting shows a sensible
      currency amount in the table, not a raw commodity quantity.
- [x] A transaction with a `@ price` annotation is represented similarly.
- [x] Existing behavior for plain-currency postings is unchanged.
- [x] Test covering both cost-basis and price-annotation formatting.

---

### LANG-11: Ledger info screen

- **Status:** done
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
- [x] New screen/binding shows title, operating currencies, default booking
      method, and account-name overrides when present.
- [x] Shows the full list of source files (top-level + includes).
- [x] Gracefully handles ledgers that don't set any of these (defaults only).
- [x] Test covering the screen against the example ledger's options.

---

### LANG-12: Surface and create `plugin` directives

- **Status:** done
- **Depends on:** LANG-01, LANG-11
- **Effort:** 1.5h

**Description:** Beancount's real loader (`loader.load_file`) already
executes `plugin "module"` directives during parsing — plugin-generated
entries (`auto_accounts`, `unrealized`, `sellgains`, etc.) come back fully
baked into `entries` with zero special handling needed from
beancount-tui, so nothing is silently dropped at the data level. The
actual gap is narrower: `plugin` directives aren't `data.*` entries at all
(there's no `data.Plugin` namedtuple — they're parsed into
`options_map["plugin"]`, a list of `(name, config)` tuples, the same place
`operating_currency` already lives), so (1) there's no UI showing which
plugins are declared for the loaded ledger, and (2) `"plugin"` isn't one
of the keywords in `_directive_template`/`DIRECTIVE_TYPES`
(`directive_type_picker.py`), so a user can't add one without leaving the
TUI. Add a `Ledger.plugins` accessor (`self.options.get("plugin", [])`,
mirroring how `operating_currency` is read) and surface it in `LANG-11`'s
`LedgerInfoScreen`; add `"plugin"` to the type picker with a template like
`2026-09-06 plugin "beancount.plugins.auto_accounts"`, appended via the
existing generic `append_entry` (plugin lines are plain text as far as
appending goes). Editing/deleting an *existing* plugin line is explicitly
out of scope here: `DirectiveForm`'s edit/delete flow locates entries via
`.meta['filename']`/`.meta['lineno']` on a `data.Directive`, which plugin
directives don't have — making that work would need new line-locating
logic against raw file text rather than reusing the entry-object model
every other directive type shares.

**Acceptance criteria:**
- [x] `Ledger.plugins` returns the ledger's declared plugin names/configs.
- [x] `LedgerInfoScreen` lists declared plugins alongside existing options.
- [x] The add-directive picker can create a new `plugin` line (appended to
      the target file) via the same file-picker/template mechanism as
      other types.
- [x] Editing/deleting an existing `plugin` line is not attempted by this
      task (documented as a follow-up, not a silent gap).
- [x] Test covering `Ledger.plugins` against a ledger with a `plugin`
      directive, the info screen showing it, and a new plugin line
      appending correctly via the add-directive flow.

---

### LANG-13: Harden plugin-load failure handling

- **Status:** done
- **Depends on:** none
- **Effort:** 1h

**Description:** `beancount.loader.load_file`'s `run_transformations`
already catches an ordinary exception from a failing plugin and turns it
into a normal `BeancountError`, which surfaces fine through
beancount-tui's existing `#errors` panel (`refresh_views` in `app.py`).
But a plugin that calls `sys.exit(...)` raises `SystemExit`, which
propagates out of `loader.load_file` uncaught — crashing `Ledger.load`/
`reload` and the whole app instead of surfacing as a readable load error.
Catch `SystemExit` around the `loader.load_file` call in `Ledger.load`/
`reload` and convert it into the same kind of load-error entry the
`#errors` panel already renders, so a misbehaving plugin degrades
gracefully instead of taking down the TUI.

**Acceptance criteria:**
- [x] A plugin calling `sys.exit(...)` during load no longer crashes the
      app.
- [x] The failure surfaces in the existing `#errors` panel with a readable
      message identifying the plugin.
- [x] Normal (non-plugin-related) load errors are unaffected.
- [x] Test covering load against a fixture ledger declaring a plugin that
      raises `SystemExit`.
