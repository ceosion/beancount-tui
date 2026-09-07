# Planning

Task-level breakdown of the work needed for beancount-tui to support all major
features and capabilities of the Beancount system, plus the reports/import/UX
backlog that had been tracked in `TODO.md`. This replaces `TODO.md`.

Each task is scoped to roughly **1-2 hours** of focused effort. Larger
features are deliberately split across several tasks with explicit
dependencies rather than left as one big item.

## Status tracking

Every task has a `Status` field. Update it in place as work progresses:

| Status        | Meaning                                              |
| ------------- | ----------------------------------------------------- |
| `todo`        | Not started.                                           |
| `in-progress` | Actively being worked on.                              |
| `blocked`     | Can't proceed — see the task's notes for why.          |
| `done`        | Merged and meets its acceptance criteria.              |

Within a task, tick off individual acceptance-criteria checkboxes as they're
satisfied; flip `Status` to `done` only once all of them are checked.

`Depends on` lists task IDs (or "none"). A task shouldn't be started until
everything it depends on is `done`, unless its notes say otherwise.

## Task areas

| File | Prefix | Covers |
| ---- | ------ | ------ |
| [language-coverage.md](language-coverage.md) | `LANG` | Beancount directive types, tags/links, metadata, cost basis, booking, options — making the TUI a complete editor for the language, not just transactions. |
| [reports.md](reports.md) | `RPT` | Balance sheet, register, trial balance, holdings/net worth, BQL queries, filter presets. |
| [editing-core.md](editing-core.md) | `EDIT` | Undo/redo, reconciliation helpers, multi-currency valuation. |
| [import.md](import.md) | `IMP` | CSV import wizard and beangulp integration. |
| [ux.md](ux.md) | `UX` | Help screen, sortable columns, entry detail panel. |
| [tooling.md](tooling.md) | `TOOL` | Snapshot tests, CI matrix, coverage, packaging/publishing. |
| [budgeting.md](budgeting.md) | `BUDGET` | Per-account budget targets via Fava's `custom "budget"` convention, proration, budget-vs-actual report. |
| [forecasting.md](forecasting.md) | `FORECAST` | Recurring/scheduled transaction templates and a virtual (never-persisted) forward-looking cash-flow projection, blending templates with budget targets. |

## Suggested order

Dependencies are authoritative; this is just a reasonable path through them:

1. **`LANG-01`** first — it's the add-directive infrastructure (type picker +
   template) that `LANG-02` through `LANG-07` and `EDIT-02` build on.
2. The rest of `LANG` can proceed in parallel once `LANG-01` lands.
3. `RPT-01` through `RPT-04` have no hard dependencies and can start anytime.
   `RPT-05` and `RPT-06` want `LANG-02`/`LANG-10` first for consistent data.
4. `EDIT`, `IMP`, `UX`, `TOOL` are largely independent of each other and of
   `LANG`/`RPT`, except where individual tasks note otherwise.
5. `BUDGET-01` through `BUDGET-04` are a strict chain (parsing → proration →
   report → rollup); `BUDGET-05` (creation form) and `BUDGET-06`
   (discoverability) can start as soon as their own dependencies land.
6. `FORECAST` follows `BUDGET` — `FORECAST-05` needs `BUDGET-02`'s proration.
   `FORECAST-01`/`FORECAST-02` (data model + excluding templates from actual
   views) come first since everything else depends on them; `FORECAST-03`
   (creation form) can proceed in parallel with `FORECAST-04`→`FORECAST-06`
   (projection engine → budget fallback → report screen), which is itself a
   strict chain.

## Baseline (already implemented, for context)

Not tracked as tasks — this is what v0.1 already shipped, per git history:

- Account tree sidebar with realized balances.
- Transaction table filtered by selected account, with a text/date-range
  filter bar.
- Full transaction editing: add, edit, duplicate, delete, single-slot undo.
- Multi-file ledgers (`include`), with a target-file picker on save when more
  than one file exists.
- Directive display/editing for `open`, `close`, `balance`, `pad`, `note`
  (view + edit + delete only — no create flow yet; see `LANG-01`).
- Auto-reload on external file changes; validation errors surfaced in an
  error panel after every load.
- Income statement report (`i` binding) over a selectable date range.
- CI with lint (ruff) + tests.

## Total scope

46 tasks across 8 areas: 11 `LANG`, 6 `RPT`, 4 `EDIT`, 4 `IMP`, 4 `UX`, 4
`TOOL`, 6 `BUDGET`, 7 `FORECAST`.
