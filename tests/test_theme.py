"""Tests for CONFIG-03: theme selection.

Covers applying a config-specified theme at startup, persisting a theme
change back to the config file, and falling back (without crashing) on an
unknown theme name. All config files here live under `tmp_path` -- nothing
touches the real `~/.config/beancount-tui/`.
"""

from pathlib import Path


from beancount_tui.app import BeancountTUI
from beancount_tui.config import set_theme


async def test_configured_theme_applied_on_startup(tmp_path: Path, ledger_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    app = BeancountTUI(ledger_path, theme="nord", config_path=config_path)
    async with app.run_test():
        assert app.theme == "nord"


async def test_theme_change_persists_to_config_file(tmp_path: Path, ledger_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    app = BeancountTUI(ledger_path, config_path=config_path)
    async with app.run_test():
        app.theme = "gruvbox"

    assert config_path.is_file()
    assert 'theme = "gruvbox"' in config_path.read_text(encoding="utf-8")


async def test_startup_theme_application_does_not_rewrite_config_file(
    tmp_path: Path, ledger_path: Path
) -> None:
    """Applying a theme that came *from* the config file at startup
    shouldn't turn around and rewrite that same file -- only a genuine
    change (e.g. via the command palette) should persist."""
    config_path = tmp_path / "config.toml"
    config_path.write_text('theme = "nord"\ndefault_ledger = "/tmp/x"\n', encoding="utf-8")
    original_text = config_path.read_text(encoding="utf-8")

    app = BeancountTUI(ledger_path, theme="nord", config_path=config_path)
    async with app.run_test():
        assert app.theme == "nord"

    assert config_path.read_text(encoding="utf-8") == original_text


async def test_theme_change_preserves_rest_of_config_file(
    tmp_path: Path, ledger_path: Path
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        'default_ledger = "/tmp/x.beancount"\nwatch_interval = 2.5\n',
        encoding="utf-8",
    )
    app = BeancountTUI(ledger_path, config_path=config_path)
    async with app.run_test():
        app.theme = "dracula"

    text = config_path.read_text(encoding="utf-8")
    assert 'default_ledger = "/tmp/x.beancount"' in text
    assert "watch_interval = 2.5" in text
    assert 'theme = "dracula"' in text


async def test_invalid_configured_theme_falls_back_to_default_without_crashing(
    tmp_path: Path, ledger_path: Path
) -> None:
    config_path = tmp_path / "config.toml"
    app = BeancountTUI(ledger_path, theme="not-a-real-theme", config_path=config_path)
    async with app.run_test():
        # Falls back to whatever Textual's own default already is, rather
        # than crashing or leaving `self.theme` unset.
        assert app.theme in app.available_themes
        assert app.theme != "not-a-real-theme"

    # An invalid theme was never actually assigned, so nothing was written.
    assert not config_path.is_file()


def test_set_theme_creates_file_and_parent_directory(tmp_path: Path) -> None:
    config_path = tmp_path / "nested" / "config.toml"
    set_theme(config_path, "nord")
    assert config_path.read_text(encoding="utf-8") == 'theme = "nord"\n'


def test_set_theme_replaces_existing_top_level_theme_line(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text('theme = "nord"\ndefault_ledger = "/tmp/x"\n', encoding="utf-8")
    set_theme(config_path, "dracula")
    text = config_path.read_text(encoding="utf-8")
    assert 'theme = "dracula"' in text
    assert "nord" not in text
    assert 'default_ledger = "/tmp/x"' in text


def test_set_theme_inserts_before_first_section_header(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text('default_ledger = "/tmp/x"\n\n[bindings]\nquit = "ctrl+q"\n', encoding="utf-8")
    set_theme(config_path, "nord")
    text = config_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    theme_index = next(i for i, line in enumerate(lines) if line.startswith("theme"))
    section_index = next(i for i, line in enumerate(lines) if line.startswith("["))
    assert theme_index < section_index
    assert 'quit = "ctrl+q"' in text
