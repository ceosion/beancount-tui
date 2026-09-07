# Config & theming (`CONFIG`)

Everything today is either a CLI arg or a hardcoded default in `app.py`.
The CLI entry point (`beancount-tui = "beancount_tui.app:main"` in
`pyproject.toml`, `main()` at the bottom of `app.py`) accepts exactly one
positional argument, the ledger path — `watch_interval` is a
`BeancountTUI.__init__` parameter but isn't CLI-reachable at all today,
only settable via direct Python instantiation (as tests do). There's no
config-file mechanism anywhere (no `tomllib`/`yaml`/`configparser`/
`appdirs` usage). `BeancountTUI.BINDINGS` is a flat hardcoded list of
`(key, action, description)` tuples with no indirection — a user can't
remap a key without editing source. Textual's built-in command palette
(`ctrl+p`, enabled by default and unmodified here) includes its own theme
picker in current Textual versions, but beancount-tui doesn't persist a
chosen theme or apply one at startup — theming is entirely whatever
Textual ships out of the box.

---

### CONFIG-01: User config file

- **Status:** done
- **Depends on:** none
- **Effort:** 1.5h

**Description:** Add support for an optional TOML config file (stdlib
`tomllib` for reading — no new dependency) at a conventional location
(e.g. `~/.config/beancount-tui/config.toml`, following XDG convention),
plus a `--config PATH` CLI override. Cover the settings that already
exist as constructor params but aren't CLI-reachable today —
`watch_interval` — plus a `default_ledger` path so `beancount-tui` can be
run with no positional argument when one is configured. Precedence:
explicit CLI args override config-file values, which override built-in
defaults.

**Acceptance criteria:**
- [x] A config file at the default location is read if present; a missing
      config file is not an error (falls back to current hardcoded
      defaults).
- [x] `watch_interval` is configurable via the file, closing the current
      gap where it's only reachable from Python.
- [x] `default_ledger` allows running with no positional argument.
- [x] Explicit CLI args override config-file values.
- [x] Test covering: config file present and absent, and a CLI override of
      a config-file value.

**Implementation note:** delivered as a new `src/beancount_tui/config.py`
module — `default_config_path()` (the XDG location, as a function so
tests can monkeypatch it rather than a value frozen in at import time) and
`load_config(path=None)`, which returns `{}` for a missing file and calls
`sys.exit` with a clear message for a *present but malformed* one (not
just an opaque `TOMLDecodeError` traceback — not explicitly required by
the acceptance criteria, but a one-line addition given `tomllib` already
raises a structured error). `app.main()` gained `--config PATH` and
`--watch-interval SECONDS` flags, and its `ledger` positional became
optional (`nargs="?"`); precedence is resolved inline in `main()`
(explicit CLI arg, else `config.get(...)`, else the hardcoded default) and
`main()` errors via `arg_parser.error(...)` if there's neither a `ledger`
arg nor a `default_ledger` in the config. Tests (`tests/test_config.py`)
cover `load_config` directly (present/absent/malformed file) plus
`app.main()`'s precedence by monkeypatching `app.default_config_path` to a
`tmp_path` location and substituting a recording stand-in for
`BeancountTUI` so no test launches a real Textual app or touches the
user's actual `~/.config/beancount-tui/`.

---

### CONFIG-02: Configurable key bindings

- **Status:** done
- **Depends on:** CONFIG-01
- **Effort:** 2h

**Description:** `BeancountTUI.BINDINGS` is a flat hardcoded list with no
indirection. Let `CONFIG-01`'s config file override individual bindings by
action name (e.g. `[bindings]` / `new_transaction = "ctrl+n"`), applied at
startup by rebuilding the effective `BINDINGS` list before the `App` is
constructed (Textual reads `BINDINGS` as a class/instance attribute at
mount time). Validate for conflicts — two actions mapped to the same key —
and refuse to start with a clear error message rather than silently
letting one binding shadow another.

**Acceptance criteria:**
- [x] A key binding can be remapped via the config file and takes effect
      on startup.
- [x] Unmapped actions keep their current default key.
- [x] Two actions mapped to the same key produce a clear startup error
      rather than silent shadowing.
- [x] Test covering a remapped binding actually triggers the correct
      action, and that a conflicting config is rejected.

**Implementation note:** `beancount_tui.config.resolve_bindings(default_bindings,
overrides)` takes the hardcoded `(key, action, description)` list plus the
config file's `[bindings]` table (`{action_name: key}`) and returns the
rebuilt list, replacing the key for each named action while leaving its
description and every unmapped action's key untouched. It calls `sys.exit`
with a clear message for three misconfigurations, not just the
one-key-two-actions case the acceptance criteria names: `[bindings]` not
being a table, an override naming an action that doesn't exist (almost
certainly a typo), and an override value that isn't a string — all
deliberate extensions beyond the letter of the spec, since a silent typo in
`[bindings]` would otherwise fail exactly as unhelpfully as the shadowing
case the criteria call out.

`app.py` now keeps the hardcoded defaults in a module-level
`_DEFAULT_BINDINGS` constant (rather than only on
`BeancountTUI.BINDINGS`), and `main()` calls a new `_rebuild_bindings(BeancountTUI,
config.get("bindings", {}))` before constructing the app. This turned out
to need more than just `BeancountTUI.BINDINGS = resolve_bindings(...)`:
Textual resolves `BINDINGS` into a cached `cls._merged_bindings` exactly
once, in `DOMNode.__init_subclass__` at class-definition (i.e.
module-import) time, and builds each instance's actual key-dispatch table
from that cache in `__init__` — reassigning `BINDINGS` afterwards silently
has *no effect* on which key triggers what unless that cache is also
recomputed. `_rebuild_bindings` therefore also reassigns
`BeancountTUI._merged_bindings = BeancountTUI._merge_bindings()` (the
private classmethod Textual itself uses to build that cache), which was
confirmed by direct experimentation against the installed Textual version
(8.2.8) to pick up a reassigned `BINDINGS` correctly. Using
`_DEFAULT_BINDINGS` (rather than reading `BeancountTUI.BINDINGS` at
rebuild time) as the base for every rebuild also means repeated calls
(e.g. across tests in the same process) always start from the true
defaults rather than compounding a previous run's overrides.

Tests: `tests/test_config.py` covers `resolve_bindings` directly (remap
applied, unmapped actions preserved, no-overrides no-op, and all four
rejection cases above) plus two `app.main()`-level tests (bindings config
reaching `BeancountTUI.BINDINGS` via the `_RecordingApp` stand-in already
used for `CONFIG-01`'s tests, and a conflicting config raising
`SystemExit` before the app is constructed). `tests/test_app.py` adds one
full Textual-`Pilot` end-to-end test
(`test_config_binding_override_triggers_remapped_action`) that remaps
`help` to `ctrl+h`, confirms the *old* key (`?`) no longer opens
`HelpScreen` and the *new* key does — proving the override reaches actual
key dispatch, not just the `BINDINGS` data — and restores
`BeancountTUI.BINDINGS`/`_merged_bindings` afterwards since both are
mutated class-level state shared across the test module.

---

### CONFIG-03: Theme selection

- **Status:** todo
- **Depends on:** CONFIG-01
- **Effort:** 1h

**Description:** Textual's built-in command palette already includes a
theme picker in current Textual versions, but beancount-tui doesn't
persist the chosen theme across restarts. Read a `theme` value from
`CONFIG-01`'s config file and apply it via `self.theme = ...` at startup
(Textual's `App.theme` reactive), and write the currently active theme
back to the config file when changed via the command palette, so a user's
choice sticks between sessions instead of resetting to Textual's default
every launch.

**Acceptance criteria:**
- [ ] A `theme` value in the config file is applied on startup.
- [ ] Changing the theme via Textual's built-in command palette persists
      it to the config file for the next launch.
- [ ] An invalid/unknown theme name falls back to Textual's default with
      no crash.
- [ ] Test covering: a config-specified theme applied on startup, and a
      theme change persisting to the file.
