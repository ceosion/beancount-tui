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

- **Status:** todo
- **Depends on:** EXPORT-01
- **Effort:** 1.5h

**Description:** Apply `EXPORT-01`'s shared export helper and path-input
pattern to `income_statement`, `balance_sheet`, `trial_balance`,
`holdings`, `budget_screen`, and `forecast_screen` — each already renders
its result into a `DataTable`, so this is a repetitive rollout of the same
action rather than new design work per screen.

**Acceptance criteria:**
- [ ] Each of the six report screens has a working CSV/JSON export action
      using the shared helper.
- [ ] Exported content matches what's on screen for each report type.
- [ ] Test covering export from at least two structurally different
      reports (e.g. a flat list like trial balance, and a sectioned report
      like the balance sheet) to confirm the shared helper handles both
      shapes.
