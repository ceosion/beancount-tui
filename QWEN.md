# beancount-tui

A terminal user interface (TUI) for browsing and editing [Beancount](https://beancount.github.io/) ledgers. This application allows users to interact with their double-entry accounting files directly from the terminal using a modern, interactive layout built with the [Textual](https://textual.textualize.io/) framework.

## Project Overview

The project provides a way to navigate account hierarchies, view transaction history, and perform CRUD operations on Beancount entries (transactions and directives). Because the `beancount` library is read-only, this TUI implements editing by performing text-level manipulations (appending for new transactions, in-place replacement for edits) on the source ledger files.

### Core Components
- **`BeancountTUI` (`src/beancount_tui/app.py`)**: The main Textual application that manages the layout, key bindings, and coordination between widgets.
- **`Ledger` (`src/beancount_tui/ledger.py`)**: Handles loading, reloading, and querying Beancount entries from files.
- **`Editor` (`src/beancount_tui/editor.py`)**: Provides the low-level logic for mutating ledger files by appending or replacing text blocks based on entry metadata (filename and line number).
- **Widgets**: A collection of Textual widgets located in `src/beancount_tui/widgets/` providing specific UI functionality:
    - `AccountTree`: Sidebar for account hierarchy navigation.
    - `TransactionTable`: Main view for listing entries.
    - `TransactionForm`/`DirectiveForm`: Modal forms for data entry and editing.
    - `FilterBar`: Search interface for transaction filtering.

## Building and Running

### Prerequisites
- Python 3.11+
- On macOS: `brew install flex bison` (required if building `beancount` from source)
- On Termux: `pkg install clang flex bison`

### Installation
The project uses `uv` for dependency management.

```sh
# Install dependencies and the project in editable mode
uv sync
```

### Running the Application
To launch the TUI with a specific ledger file:

```sh
uv run beancount-tui path/to/ledger.beancount
```

For testing with the bundled example:
```sh
uv run beancount-tui examples/example.beancount
```

## Development Conventions

### Tooling
- **Dependency Management**: `uv` is used for all package and environment management.
- **Linting & Formatting**: `ruff` is used for linting the codebase.
- **Type Checking**: `mypy` is used for static type analysis (configured in `pyproject.toml`).
- **Testing**: `pytest` is used for running the test suite, including asynchronous tests via `pytest-asyncio`.

### Common Commands
```sh
# Run the test suite
uv run pytest

# Run linter
uv run ruff check .

# Run type checker
uv run mypy src/
```

### Key Bindings in UI
| Key | Action |
| --- | --- |
| `n` | New transaction |
| `e` | Edit selected entry |
| `c` | Duplicate transaction |
| `d` | Delete transaction |
| `/` | Toggle filter bar |
| `r` | Reload ledger from disk |
| `q` | Quit |

### Coding Style
- **Typing**: Extensive use of type hints is expected.
- **Async**: Since it's a Textual app, much of the logic and widget interaction is asynchronous.
