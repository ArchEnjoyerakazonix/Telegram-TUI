"""Tests for the command line entry point: config errors and mode overrides."""

from __future__ import annotations

import pytest

from telegram_tui.__main__ import main
from telegram_tui.engine import MockEngine


@pytest.fixture
def config_file(isolate_user_state):
    return isolate_user_state / ".config" / "telegram-tui" / "config.toml"


@pytest.fixture
def captured_launch(monkeypatch):
    """Stop short of actually running the TUI, recording what it was built with."""
    launched: dict = {}

    def fake_run(self):
        launched["mode"] = self.config.mode
        launched["engine"] = type(self.engine)

    monkeypatch.setattr("telegram_tui.app.TelegramTUI.run", fake_run)
    return launched


def test_incomplete_live_config_reports_an_error_not_a_traceback(config_file, capsys):
    config_file.write_text('mode = "live"\n', encoding="utf-8")

    assert main([]) == 2

    err = capsys.readouterr().err
    assert "invalid configuration" in err
    assert "api_id" in err
    assert "Traceback" not in err
    assert "pydantic" not in err


def test_corrupt_toml_reports_the_parse_error(config_file, capsys):
    config_file.write_text("this is not = = toml\n", encoding="utf-8")

    assert main([]) == 2
    assert "invalid configuration" in capsys.readouterr().err


def test_missing_explicit_config_file_is_reported(tmp_path, capsys):
    assert main(["--config", str(tmp_path / "absent.toml")]) == 2
    assert "not found" in capsys.readouterr().err


def test_mode_mock_rescues_an_incomplete_live_config(config_file, captured_launch):
    """The offline demo must stay reachable when live settings are broken."""
    config_file.write_text('mode = "live"\n', encoding="utf-8")

    assert main(["--mode", "mock"]) == 0
    assert captured_launch == {"mode": "mock", "engine": MockEngine}


def test_mode_live_without_credentials_is_refused(config_file, capsys):
    config_file.write_text('mode = "mock"\n', encoding="utf-8")

    assert main(["--mode", "live"]) == 2
    assert "api_id" in capsys.readouterr().err


def test_print_config_succeeds(capsys):
    assert main(["--print-config"]) == 0
    assert 'mode = "mock"' in capsys.readouterr().out


def test_reset_clears_only_this_clients_sessions(isolate_user_state, tmp_path, monkeypatch):
    """--reset must not sweep away other Telethon apps' sessions from $HOME."""
    config_dir = isolate_user_state / ".config" / "telegram-tui"
    ours = config_dir / "telegram-tui.session"
    ours.write_text("ours", encoding="utf-8")
    someone_elses = isolate_user_state / "other-app.session"
    someone_elses.write_text("theirs", encoding="utf-8")

    cwd = tmp_path / "cwd"
    cwd.mkdir()
    legacy = cwd / "telegram-tui.session"
    legacy.write_text("legacy", encoding="utf-8")
    monkeypatch.chdir(cwd)

    assert main(["--reset"]) == 0

    assert not ours.exists()
    assert not legacy.exists()
    assert someone_elses.exists(), "an unrelated session file was deleted"
