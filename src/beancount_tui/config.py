"""Optional user config file support (`CONFIG-01`, `CONFIG-02`).

Everything here used to be either a CLI arg or a hardcoded default baked
into `app.py`. This module adds a small, read-only layer underneath that:
an optional TOML file, read with the stdlib `tomllib` (no new dependency —
note `tomllib` is read-only, so writing a config file back out, e.g. for a
future "persist the chosen theme" feature, is a different module's job).

Precedence (enforced by the caller, `app.main`, not by anything here):
explicit CLI args > config-file values > the hardcoded defaults below.

`resolve_bindings` (`CONFIG-02`) additionally lets the config file's
`[bindings]` table override `BeancountTUI.BINDINGS` by action name; see its
docstring, and `app._rebuild_bindings`/`app.main` for how the result gets
applied to the app class before it's instantiated.
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


def resolve_bindings(
    default_bindings: list[tuple[str, str, str]], overrides: dict[str, Any]
) -> list[tuple[str, str, str]]:
    """Rebuild an ``App``'s ``BINDINGS`` list (`CONFIG-02`) with config-file
    overrides applied by action name.

    ``default_bindings`` is the hardcoded ``(key, action, description)``
    list; ``overrides`` is the config file's ``[bindings]`` table, e.g.
    ``{"new_transaction": "ctrl+n"}``. For each default binding whose action
    appears in ``overrides``, its key is replaced (description kept as-is,
    so the help screen still shows something meaningful); actions not
    mentioned in ``overrides`` keep their default key unchanged.

    Fails loudly via `sys.exit` -- rather than silently misbehaving -- in
    three cases: ``overrides`` isn't a table at all (a malformed config
    file), it names an action that doesn't exist in ``default_bindings``
    (almost certainly a typo), or applying it makes two different actions
    share the same key (Textual would otherwise let one silently shadow the
    other with no warning).
    """
    if not isinstance(overrides, dict):
        sys.exit(
            "error: config file's [bindings] section must be a table of "
            f'action = "key" entries, got {type(overrides).__name__}'
        )

    known_actions = {action for _key, action, _description in default_bindings}
    unknown_actions = sorted(set(overrides) - known_actions)
    if unknown_actions:
        sys.exit(
            "error: config file [bindings] section references unknown action(s): "
            + ", ".join(unknown_actions)
        )

    for action, key in overrides.items():
        if not isinstance(key, str):
            sys.exit(
                f"error: config file [bindings].{action} must be a string key, "
                f"got {key!r}"
            )

    resolved = [
        (overrides.get(action, key), action, description)
        for key, action, description in default_bindings
    ]

    actions_by_key: dict[str, list[str]] = {}
    for key, action, _description in resolved:
        actions_by_key.setdefault(key, []).append(action)
    conflicts = {key: actions for key, actions in actions_by_key.items() if len(actions) > 1}
    if conflicts:
        details = "; ".join(
            f"{key!r} -> {', '.join(actions)}" for key, actions in sorted(conflicts.items())
        )
        sys.exit(f"error: conflicting key bindings in config file: {details}")

    return resolved


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
