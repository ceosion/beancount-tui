"""Optional user config file support (`CONFIG-01`).

Everything here used to be either a CLI arg or a hardcoded default baked
into `app.py`. This module adds a small, read-only layer underneath that:
an optional TOML file, read with the stdlib `tomllib` (no new dependency —
note `tomllib` is read-only, so writing a value back out needs its own
narrow helper; see `set_theme` below, added for `CONFIG-03`'s "persist the
chosen theme" need).

Precedence (enforced by the caller, `app.main`, not by anything here):
explicit CLI args > config-file values > the hardcoded defaults below.
"""

from __future__ import annotations

import json
import re
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


#: Matches a top-level `theme = ...` assignment -- i.e. one that isn't
#: indented and isn't inside a `[table]` (this regex alone can't tell those
#: apart; `set_theme` below only applies it to the slice of lines that
#: precede the file's first `[section]` header, which is where a top-level
#: key has to live in TOML).
_THEME_LINE_RE = re.compile(r"^theme\s*=")
_SECTION_HEADER_RE = re.compile(r"^\s*\[")


def set_theme(path: Path, theme_name: str) -> None:
    """Persist `theme_name` as the top-level `theme = "..."` key in the TOML
    config file at `path`, creating the file (and its parent directory) if
    neither already exists, and preserving everything else already in the
    file.

    `tomllib` (used by `load_config` above) is read-only, and pulling in a
    full TOML-writer dependency just to update one scalar key felt like
    overkill for `CONFIG-03` -- so this does a small targeted text edit
    instead of a real round-trip parse/serialize:

    1. Split the file's lines into a "top" part (everything before the
       first `[section]` header, i.e. where top-level keys live in TOML)
       and a "rest" part (that header onward, untouched).
    2. If "top" already has a `theme = ...` line, replace it in place.
       Otherwise append a new one to the end of "top" (i.e. immediately
       before the first section header, or at the end of the file if there
       are no section headers at all).
    3. Reassemble and write back.

    This is safe for the narrow case this feature needs -- a single
    top-level scalar key -- but it is *not* a general TOML writer: it does
    not understand multi-line arrays/tables, inline tables, or a `theme`
    key that's already part of one of those. Nothing in `beancount-tui`
    writes such a thing today, so this holds for any config file this
    module itself produces or that a user hand-writes for these documented
    top-level keys; a config file with a hand-crafted `theme` inside some
    exotic nested structure is out of scope.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []

    section_index = next((i for i, line in enumerate(lines) if _SECTION_HEADER_RE.match(line)), None)
    top = lines if section_index is None else lines[:section_index]
    rest = [] if section_index is None else lines[section_index:]

    new_line = f"theme = {json.dumps(theme_name)}"
    replaced = False
    for i, line in enumerate(top):
        if _THEME_LINE_RE.match(line):
            top[i] = new_line
            replaced = True
            break
    if not replaced:
        top.append(new_line)

    path.write_text("\n".join(top + rest) + "\n", encoding="utf-8")
