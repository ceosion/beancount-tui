# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
once a first version is published.

## [Unreleased]

### Added

- Core TUI: account tree sidebar with balances, transaction table filtered by
  the selected account, and a modal form for adding/editing transactions
  with real Beancount-parser validation before anything is written to disk.
- Full read/write editing: new entries are appended and existing entries are
  replaced in place, located via the source `filename`/`lineno` metadata
  Beancount attaches to parsed entries.
- Support for creating, displaying, and editing the full range of Beancount
  directive types: `open`/`close`/`balance`/`pad`/`note` (LANG-01), `price`
  (LANG-02), `commodity` (LANG-03), `event` (LANG-04), `document` (LANG-05,
  including a missing-file flag), `custom` (LANG-06), and `query` (LANG-07).
- Transaction metadata, tags, and links surfaced in the filter bar and
  transaction table (LANG-08/LANG-09), and cost/price-annotated postings
  shown as resolved currency amounts (LANG-10).
- A ledger info screen summarizing the loaded file(s) (LANG-11).
- An income statement report (Income/Expenses per account with totals and
  net), scoped to an optional date range, behind the `i` binding.
- Transaction search/filter (`/`), duplication of the selected transaction
  (`c`), single-level undo of the last write (`u`), Tab-completion of
  account names in the postings editor, and support for multi-file ledgers
  including a target-file picker for new entries.
- Auto-reload of the ledger when its underlying file(s) change on disk.
- Non-transaction directives are viewable and editable through a dedicated
  raw-text form, sharing the same parser-backed validation path as the
  transaction form.
- CI running `pytest` and `ruff check`; `mypy` type checking added to the
  dev dependency group and CI.

### Notes

- PyPI packaging metadata (classifiers, project URLs) added; actual
  publishing to PyPI is not yet done (see `planning/tooling.md`, TOOL-04).
