# beancount-tui

A terminal user interface for [Beancount](https://beancount.github.io/), the
plain-text double-entry accounting system. Browse your ledger, inspect
accounts, and add or edit transactions — all without leaving the terminal.

Built with [Textual](https://textual.textualize.io/) and the `beancount`
library.

## Features

- **Account tree** — browse the full account hierarchy with balances.
- **Transaction table** — scroll through transactions, filtered by the
  selected account.
- **Full editing** — add new transactions and edit existing ones through a
  form; changes are written back to your ledger file.
- **Error panel** — Beancount validation errors are surfaced in the UI.

## Installation

Requires Python 3.11+.

```sh
uv sync            # install dependencies (or: pip install -e .)
```

## Usage

```sh
uv run beancount-tui path/to/ledger.beancount
```

Try it with the bundled example ledger:

```sh
uv run beancount-tui examples/example.beancount
```

### Key bindings

| Key      | Action                          |
| -------- | ------------------------------- |
| `n`      | New transaction                 |
| `e`      | Edit selected transaction       |
| `r`      | Reload ledger from disk         |
| `q`      | Quit                            |

## Development

```sh
uv sync                # install deps including dev group
uv run pytest          # run tests
uv run ruff check .    # lint
```

## How editing works

Beancount itself is read-only: the library parses and validates ledgers but
has no API for modifying them. This project edits the ledger as text:

- **New transactions** are formatted with `beancount.parser.printer` and
  appended to the ledger file.
- **Edits** replace the original entry's source lines in place, located via
  the `filename`/`lineno` metadata Beancount attaches to every entry.

After every write the ledger is re-loaded and re-validated, so mistakes show
up immediately in the error panel.
