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
from beancount_tui.config import load_config


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


class _RecordingApp:
    """Stand-in for `BeancountTUI` that records its constructor args instead
    of actually launching a Textual app -- what `main()` needs verifying
    here is argument-resolution/precedence, not the TUI itself."""

    instances: list["_RecordingApp"] = []

    def __init__(self, ledger_path: str | Path, watch_interval: float = app.DEFAULT_WATCH_INTERVAL):
        self.ledger_path = ledger_path
        self.watch_interval = watch_interval
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
