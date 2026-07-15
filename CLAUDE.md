# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

A terminal user interface (TUI) for [Beancount](https://beancount.github.io/), the plain-text double-entry accounting system. Scope is a **full editor**: browse the ledger and add/edit transactions, with changes written back to the ledger file. Built in Python with [Textual](https://textual.textualize.io/), using the `beancount` library (v3) directly for loading and validation.

## Commands

Uses [uv](https://docs.astral.sh/uv/) for dependency management (Python 3.11+).

```sh
uv sync                                        # install deps (incl. dev group)
uv run pytest                                  # run all tests
uv run pytest tests/test_editor.py::test_replace_entry  # run one test
uv run ruff check .                            # lint
uv run beancount-tui examples/example.beancount  # run the app
```

## Architecture

Source lives in `src/beancount_tui/`. The key boundary is **read vs. write**:

- `ledger.py` — read side. The `Ledger` dataclass wraps `beancount.loader.load_file` and exposes transactions, the realized account tree (`beancount.core.realization`) with balances, and validation errors. It never mutates files.
- `editor.py` — write side. Beancount's library is read-only, so all edits are text-level operations on the ledger source: new transactions are appended (`append_transaction`); edits replace the original entry's source lines in place (`replace_entry`), located via the `filename`/`lineno` metadata Beancount attaches to every parsed entry, with the entry's extent computed by `entry_line_span` (first line plus all following indented lines). User-entered transaction text is validated with the real Beancount parser (`parse_transaction_text`) before it ever touches a file.
- `app.py` — the Textual `App` (`BeancountTUI`) and CLI entry point (`main`). Holds the `Ledger` and the selected-account filter state; after every write it reloads the ledger from disk and refreshes all views, so validation errors surface immediately in the error panel.
- `widgets/` — one file per widget: `account_tree.py` (sidebar hierarchy with balances; posts `AccountSelected` messages), `transaction_table.py` (transactions for the selected account), `transaction_form.py` (modal add/edit form that assembles Beancount source text and rejects it if the parser does).

Data flows one way: widgets render from the `Ledger`, edits go through `editor.py` to disk, then everything re-renders from a fresh load. Widgets never mutate ledger state directly.

## Testing

Tests in `tests/` use a throwaway copy of `examples/example.beancount` (see the `ledger_path` fixture in `conftest.py`). `test_app.py` drives the real app end-to-end with Textual's `run_test()` pilot, including submitting the transaction form. `asyncio_mode = "auto"` is set, so async tests need no decorator.
