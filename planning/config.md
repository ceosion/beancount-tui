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

- **Status:** todo
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
- [ ] A config file at the default location is read if present; a missing
      config file is not an error (falls back to current hardcoded
      defaults).
- [ ] `watch_interval` is configurable via the file, closing the current
      gap where it's only reachable from Python.
- [ ] `default_ledger` allows running with no positional argument.
- [ ] Explicit CLI args override config-file values.
- [ ] Test covering: config file present and absent, and a CLI override of
      a config-file value.

---

### CONFIG-02: Configurable key bindings

- **Status:** todo
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
- [ ] A key binding can be remapped via the config file and takes effect
      on startup.
- [ ] Unmapped actions keep their current default key.
- [ ] Two actions mapped to the same key produce a clear startup error
      rather than silent shadowing.
- [ ] Test covering a remapped binding actually triggers the correct
      action, and that a conflicting config is rejected.

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
