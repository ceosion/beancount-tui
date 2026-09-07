"""Optional user config file support (`CONFIG-01`).

Everything here used to be either a CLI arg or a hardcoded default baked
into `app.py`. This module adds a small, read-only layer underneath that:
an optional TOML file, read with the stdlib `tomllib` (no new dependency —
note `tomllib` is read-only, so writing a config file back out, e.g. for a
future "persist the chosen theme" feature, is a different module's job).

Precedence (enforced by the caller, `app.main`, not by anything here):
explicit CLI args > config-file values > the hardcoded defaults below.
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path
from typing import Any

#: Default `watch_interval`, matching `BeancountTUI.__init__`'s own default
#: -- kept here too so callers have a single source of truth to fall back
#: on when neither a CLI arg nor a config file supplies one.
DEFAULT_WATCH_INTERVAL = 1.0

#: XDG-convention location: `~/.config/beancount-tui/config.toml`.
DEFAULT_CONFIG_PATH = Path.home() / ".config" / "beancount-tui" / "config.toml"


def default_config_path() -> Path:
    """The conventional config-file location, as a function (rather than
    just the `DEFAULT_CONFIG_PATH` module constant) so it's evaluated at
    call time -- tests can patch this instead of a value that was already
    frozen in at import time."""
    return DEFAULT_CONFIG_PATH


def load_config(path: Path | None = None) -> dict[str, Any]:
    """Read the config file at `path` (defaulting to
    `default_config_path()`) and return its contents as a dict.

    A missing config file is not an error -- it just means "no overrides",
    so this returns `{}` rather than raising. A *present but malformed*
    file is a user-facing error worth failing loudly on, so that's reported
    via `sys.exit` with a clear message instead of an opaque traceback.
    """
    if path is None:
        path = default_config_path()
    if not path.is_file():
        return {}
    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except tomllib.TOMLDecodeError as exc:
        sys.exit(f"error: invalid config file {path}: {exc}")
