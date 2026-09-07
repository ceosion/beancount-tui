# Export & interop (`EXPORT`)

Every report/query result in beancount-tui is view-only today — rendered
into an on-screen `DataTable` with no save/export path. Checked all of
`income_statement`, `balance_sheet`, `trial_balance`, `holdings`,
`budget_screen`, `forecast_screen`, and `query_runner`: none define an
export action, all are dismissed via `escape`/`action_close` with no other
side effect. Fava and `bean-query`'s own CLI both let results leave the
tool as CSV/JSON; that's the gap here. No new dependency is needed — the
stdlib's `csv`/`json` cover it (`csv` is already imported in
`importer.py`; `json` isn't used anywhere yet). The file-path pattern to
reuse is the plain-`Input`-plus-validate one already used by
`import_form.py`/`beangulp_import_form.py` (type a path, validate on
submit, inline error `Static`) rather than inventing a directory browser —
there's no `DirectoryTree`/file-chooser widget anywhere in this codebase
today.

---

### EXPORT-01: Export infrastructure + CSV/JSON export for the query runner

- **Status:** done
- **Depends on:** RPT-06
- **Effort:** 2h

**Description:** Add a shared export helper (e.g. a new `export.py`:
`write_csv(columns, rows, path)` / `write_json(columns, rows, path)`)
operating on `QueryResult`'s raw `columns`/`rows` — not the
display-formatted strings from `Ledger.format_query_value`, which are
lossy for this purpose (it collapses `Decimal`/`Inventory`/`Amount` into
comma-grouped display text meant for on-screen reading). For CSV, per-cell
stringification is fine either way since CSV is text-only; for JSON,
prefer values that stay closer to their real types where straightforward
(e.g. `Decimal` as a JSON string to avoid float rounding, rather than
`format_query_value`'s human-formatted string). Add an export
binding/action to `QueryRunnerScreen`, using the same "type-a-path `Input`
+ validate on submit + inline error `Static`" pattern already used by
`import_form.py`/`beangulp_import_form.py`: check the parent directory
exists, and warn rather than silently overwrite if the target path already
exists.

**Acceptance criteria:**
- [x] Query runner has an export action producing a valid CSV file
      matching the on-screen columns/rows.
- [x] The same action (or a format toggle) can also produce a valid JSON
      file (array of row objects keyed by column name).
- [x] Invalid export paths (non-existent parent directory) show an inline
      error rather than crashing.
- [x] An existing target path prompts for confirmation rather than
      silently overwriting.
- [x] Test covering CSV and JSON output content against a known query
      result.

**Implementation notes:** Landed as `src/beancount_tui/export.py`
(`write_csv`/`write_json`, working from `QueryResult.columns`/`.rows`) plus
an export row (`Input` + CSV/JSON `Select` toggle + `Export` button) added
to `QueryRunnerScreen`, wired to the last-run query's raw result (not the
`format_query_value`-rendered `DataTable` contents). Overwrite confirmation
reuses the existing app-wide `ConfirmDialog` widget (the same one used for
e.g. deleting a transaction) rather than a bespoke yes/no prompt, since
that's the established pattern for "are you sure" moments in this
codebase and the task's inline-error `Static` pattern is reserved for
validation problems, not confirmations. JSON rendering of Beancount value
types goes a bit further than the task's specific `Decimal`-as-string
callout: `Amount`/`Position` become `{"number": "<str>", "currency": ...}`
objects and `Inventory` becomes a list of such objects (one per currency
lot), rather than falling back to a flattened string — this seemed like
the natural extension of "stay closer to real types" once `Decimal` was
being special-cased anyway. Covered by `tests/test_export.py` (helper
unit tests, including a real-ledger query) and four new
`tests/test_app.py::test_query_runner_export_*` tests exercising the full
widget flow (CSV, JSON, missing-parent-dir error, overwrite confirmation
cancel/confirm).

---

### EXPORT-02: Roll export out to the remaining report screens

- **Status:** done
- **Depends on:** EXPORT-01
- **Effort:** 1.5h

**Description:** Apply `EXPORT-01`'s shared export helper and path-input
pattern to `income_statement`, `balance_sheet`, `trial_balance`,
`holdings`, `budget_screen`, and `forecast_screen` — each already renders
its result into a `DataTable`, so this is a repetitive rollout of the same
action rather than new design work per screen.

**Acceptance criteria:**
- [x] Each of the six report screens has a working CSV/JSON export action
      using the shared helper.
- [x] Exported content matches what's on screen for each report type.
- [x] Test covering export from at least two structurally different
      reports (e.g. a flat list like trial balance, and a sectioned report
      like the balance sheet) to confirm the shared helper handles both
      shapes.

**Implementation notes:** Rather than re-paste `QueryRunnerScreen`'s export
row (path `Input` + CSV/JSON `Select` + `Export` button + inline error
`Static`, overwrite confirmation via `ConfirmDialog`) six more times nearly
verbatim, that plumbing was factored into a new `ExportMixin`
(`src/beancount_tui/widgets/export_mixin.py`): `compose_export_row()`
yields the row's widgets, `_do_export()`/`_write_export()` own path
validation/overwrite-confirmation/writing, and each host screen only
implements `_export_columns_rows()` returning its current raw
`(columns, rows)`. Every one of the six screens now mixes this in
(`class FooScreen(ExportMixin, ModalScreen[None])`), pastes the same four
`#export-row`/`#export-error` CSS rules scoped to its own class name
(this codebase always prefixes screen CSS with the class name rather than
relying on implicit scoping, so there's no way to share the CSS itself),
and caches `self._export_columns`/`self._export_rows` at the end of its
existing `_render_report` (built alongside the on-screen `DataTable`, from
the same raw `Decimal`/`Inventory`/`Amount` values, not
`format_inventory`'s comma-grouped display strings) so export always
matches the currently-displayed report. Each report's own `Input.Changed`
handler for its date/period field had to gain an `event.input.id` guard,
since adding the export-path `Input` means `Input.Changed` now bubbles from
two different fields on the same screen.

Column/row shape per screen:
- **Flat reports** (`trial_balance`, `holdings`, `budget_screen`,
  `forecast_screen`): one export row per on-screen row, same columns,
  raw values instead of display text. `holdings` appends its on-screen net-
  worth row as a trailing summary row (dropping only the purely-visual
  blank separator row, which carries no data). `budget_screen` and
  `forecast_screen` each add a dedicated "Currency" column instead of the
  on-screen convention of folding the currency into each formatted amount
  string (e.g. "12.34 USD") — a machine-readable export benefits from a
  separated numeric value more than from a string a consumer would have to
  re-parse. `forecast_screen` additionally adds a "Status" column
  (explicit/assumed/mixed/actual): on screen that provenance is conveyed
  purely by the Projected cell's color, which has no CSV/JSON equivalent,
  so it becomes its own explicit column rather than being silently
  dropped.
- **Sectioned reports** (`balance_sheet`, `income_statement`): flattened to
  one row per line item — including subtotal rows — with a leading
  "Section" column (e.g. "Assets"/"Liabilities"/"Equity", or
  "Income"/"Expenses") repeated on every row belonging to that section,
  rather than the on-screen bold section-header/blank-separator rows
  (which don't survive a flatten to begin with). This was chosen over
  reproducing the header/separator rows verbatim as extra data rows
  because a spreadsheet or JSON consumer can filter/group on a real
  "Section" value far more usefully than on a visual-only separator, and
  because repeating the section per line item is more faithful to "this
  line belongs to this section" than a one-off header row would be. The
  one row that spans both sides of the sheet (`balance_sheet`'s "Total
  liabilities + equity") gets its own "Summary" section rather than being
  forced into either side. `income_statement`'s comparison mode (RPT-09,
  comma-separated periods) exports correctly too: `_export_columns`
  becomes `["Section", "Account", *periods]` (one amount column per
  period) instead of the single-period `["Section", "Account", "Amount"]`,
  matching whichever mode was last rendered.

Covered by ten new tests in `tests/test_app.py`
(`test_trial_balance_export_csv`, `test_balance_sheet_export_json`,
`test_income_statement_export_csv`, `test_holdings_export_json`,
`test_budget_screen_export_csv`, `test_forecast_screen_export_csv`, plus
the four `test_query_runner_export_*` tests already landed by
`EXPORT-01`) — one per report screen, covering both the flat and sectioned
shapes plus one of each output format (CSV/JSON).
