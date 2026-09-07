"""Tests for CONFIG-01: the optional TOML user config file.

Covers `beancount_tui.config.load_config` directly, plus `app.main()`'s
precedence rules (CLI args > config file > hardcoded defaults). All config
files here live under `tmp_path` -- `default_config_path` is monkeypatched
in every `main()`-level test so nothing ever touches the real
`~/.config/beancount-tui/` on this machine.
"""

from pathlib import Path

import pytest

from beancount_tui import app
from beancount_tui.config import load_config, resolve_bindings


def test_load_config_missing_file_returns_empty(tmp_path: Path) -> None:
    """A missing config file is not an error -- callers get `{}` back and
    fall through to their own hardcoded defaults."""
    assert load_config(tmp_path / "does-not-exist.toml") == {}


def test_load_config_present_file_is_read(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        'watch_interval = 5.0\ndefault_ledger = "/tmp/ledger.beancount"\n',
        encoding="utf-8",
    )
    config = load_config(config_path)
    assert config["watch_interval"] == 5.0
    assert config["default_ledger"] == "/tmp/ledger.beancount"


def test_load_config_malformed_file_exits_with_clear_message(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text("this is not valid toml [[[", encoding="utf-8")
    with pytest.raises(SystemExit, match="invalid config file"):
        load_config(config_path)


_SAMPLE_BINDINGS = [
    ("n", "new_transaction", "New"),
    ("e", "edit_transaction", "Edit"),
    ("q", "quit", "Quit"),
]


def test_resolve_bindings_remaps_action_to_new_key() -> None:
    """A key binding can be remapped via the config file (`CONFIG-02`)."""
    resolved = resolve_bindings(_SAMPLE_BINDINGS, {"new_transaction": "ctrl+n"})
    assert ("ctrl+n", "new_transaction", "New") in resolved
    assert not any(action == "new_transaction" and key == "n" for key, action, _ in resolved)


def test_resolve_bindings_keeps_unmapped_actions_at_default_key() -> None:
    resolved = resolve_bindings(_SAMPLE_BINDINGS, {"new_transaction": "ctrl+n"})
    assert ("e", "edit_transaction", "Edit") in resolved
    assert ("q", "quit", "Quit") in resolved


def test_resolve_bindings_no_overrides_returns_defaults_unchanged() -> None:
    assert resolve_bindings(_SAMPLE_BINDINGS, {}) == _SAMPLE_BINDINGS


def test_resolve_bindings_conflicting_keys_rejected() -> None:
    """Two actions ending up on the same key is a clear startup error, not
    silent shadowing."""
    with pytest.raises(SystemExit, match="conflicting"):
        resolve_bindings(_SAMPLE_BINDINGS, {"new_transaction": "q"})


def test_resolve_bindings_unknown_action_rejected() -> None:
    with pytest.raises(SystemExit, match="unknown action"):
        resolve_bindings(_SAMPLE_BINDINGS, {"not_a_real_action": "ctrl+n"})


def test_resolve_bindings_non_dict_overrides_rejected() -> None:
    with pytest.raises(SystemExit, match="must be a table"):
        resolve_bindings(_SAMPLE_BINDINGS, "not-a-table")  # type: ignore[arg-type]


def test_resolve_bindings_non_string_key_rejected() -> None:
    with pytest.raises(SystemExit, match="must be a string key"):
        resolve_bindings(_SAMPLE_BINDINGS, {"new_transaction": 123})  # type: ignore[dict-item]


class _RecordingApp:
    """Stand-in for `BeancountTUI` that records its constructor args instead
    of actually launching a Textual app -- what `main()` needs verifying
    here is argument-resolution/precedence, not the TUI itself."""

    instances: list["_RecordingApp"] = []

    def __init__(
        self,
        ledger_path: str | Path,
        watch_interval: float = app.DEFAULT_WATCH_INTERVAL,
        theme: str | None = None,
        config_path: Path | None = None,
    ):
        self.ledger_path = ledger_path
        self.watch_interval = watch_interval
        self.theme = theme
        self.config_path = config_path
        _RecordingApp.instances.append(self)

    def run(self) -> None:
        pass


@pytest.fixture
def recording_app(monkeypatch: pytest.MonkeyPatch) -> type[_RecordingApp]:
    _RecordingApp.instances = []
    monkeypatch.setattr(app, "BeancountTUI", _RecordingApp)
    return _RecordingApp


def test_main_with_no_config_file_falls_back_to_hardcoded_defaults(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    recording_app: type[_RecordingApp],
    ledger_path: Path,
) -> None:
    missing_config = tmp_path / "no-such-config.toml"
    monkeypatch.setattr(app, "default_config_path", lambda: missing_config)
    monkeypatch.setattr("sys.argv", ["beancount-tui", str(ledger_path)])

    app.main()

    assert len(recording_app.instances) == 1
    instance = recording_app.instances[0]
    assert instance.ledger_path == str(ledger_path)
    assert instance.watch_interval == app.DEFAULT_WATCH_INTERVAL


def test_main_reads_default_ledger_and_watch_interval_from_config_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    recording_app: type[_RecordingApp],
    ledger_path: Path,
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f'default_ledger = "{ledger_path}"\nwatch_interval = 3.5\n', encoding="utf-8"
    )
    monkeypatch.setattr(app, "default_config_path", lambda: config_path)
    monkeypatch.setattr("sys.argv", ["beancount-tui"])

    app.main()

    assert len(recording_app.instances) == 1
    instance = recording_app.instances[0]
    assert instance.ledger_path == str(ledger_path)
    assert instance.watch_interval == 3.5


def test_main_cli_args_override_config_file_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    recording_app: type[_RecordingApp],
    ledger_path: Path,
    multi_ledger_path: Path,
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f'default_ledger = "{ledger_path}"\nwatch_interval = 3.5\n', encoding="utf-8"
    )
    monkeypatch.setattr(app, "default_config_path", lambda: config_path)
    monkeypatch.setattr(
        "sys.argv",
        ["beancount-tui", str(multi_ledger_path), "--watch-interval", "9"],
    )

    app.main()

    assert len(recording_app.instances) == 1
    instance = recording_app.instances[0]
    assert instance.ledger_path == str(multi_ledger_path)
    assert instance.watch_interval == 9.0


def test_main_no_ledger_and_no_default_ledger_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recording_app: type[_RecordingApp]
) -> None:
    missing_config = tmp_path / "no-such-config.toml"
    monkeypatch.setattr(app, "default_config_path", lambda: missing_config)
    monkeypatch.setattr("sys.argv", ["beancount-tui"])

    with pytest.raises(SystemExit):
        app.main()

    assert recording_app.instances == []


def test_main_explicit_config_flag_overrides_default_location(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    recording_app: type[_RecordingApp],
    ledger_path: Path,
) -> None:
    real_config = tmp_path / "real.toml"
    real_config.write_text(f'default_ledger = "{ledger_path}"\n', encoding="utf-8")
    decoy_config = tmp_path / "decoy.toml"
    decoy_config.write_text('default_ledger = "/nonexistent/decoy.beancount"\n', encoding="utf-8")
    monkeypatch.setattr(app, "default_config_path", lambda: decoy_config)
    monkeypatch.setattr("sys.argv", ["beancount-tui", "--config", str(real_config)])

    app.main()

    assert len(recording_app.instances) == 1
    assert recording_app.instances[0].ledger_path == str(ledger_path)


def test_main_applies_bindings_override_from_config_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    recording_app: type[_RecordingApp],
    ledger_path: Path,
) -> None:
    """`CONFIG-02`: a `[bindings]` table in the config file is applied to
    the app class's `BINDINGS` before it's constructed, and actions not
    named in it keep their hardcoded default key."""
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f'default_ledger = "{ledger_path}"\n\n[bindings]\nnew_transaction = "ctrl+n"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(app, "default_config_path", lambda: config_path)
    monkeypatch.setattr("sys.argv", ["beancount-tui"])

    app.main()

    assert len(recording_app.instances) == 1
    resolved = {action: key for key, action, _desc in recording_app.BINDINGS}
    assert resolved["new_transaction"] == "ctrl+n"
    assert resolved["quit"] == "q"


def test_main_rejects_conflicting_bindings_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    recording_app: type[_RecordingApp],
    ledger_path: Path,
) -> None:
    """Remapping `new_transaction` onto `quit`'s default key `q` is a
    startup error, not silent shadowing -- and the app never gets
    constructed."""
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f'default_ledger = "{ledger_path}"\n\n[bindings]\nnew_transaction = "q"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(app, "default_config_path", lambda: config_path)
    monkeypatch.setattr("sys.argv", ["beancount-tui"])

    with pytest.raises(SystemExit, match="conflicting"):
        app.main()

    assert recording_app.instances == []


def test_main_passes_configured_theme_and_resolved_config_path_to_app(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    recording_app: type[_RecordingApp],
    ledger_path: Path,
) -> None:
    """`CONFIG-03`: `main()` reads a `theme` key from the config file and
    passes it through to `BeancountTUI`, along with the config path that was
    actually resolved for this run (the explicit `--config` value here) --
    that's the file a later theme change needs to be written back to."""
    config_path = tmp_path / "config.toml"
    config_path.write_text(f'default_ledger = "{ledger_path}"\ntheme = "nord"\n', encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["beancount-tui", "--config", str(config_path)])

    app.main()

    assert len(recording_app.instances) == 1
    instance = recording_app.instances[0]
    assert instance.theme == "nord"
    assert instance.config_path == config_path


def test_main_with_no_theme_in_config_passes_none(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    recording_app: type[_RecordingApp],
    ledger_path: Path,
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(f'default_ledger = "{ledger_path}"\n', encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["beancount-tui", "--config", str(config_path)])

    app.main()

    assert len(recording_app.instances) == 1
    assert recording_app.instances[0].theme is None
