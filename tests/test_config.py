"""Tests for configuration loading (mock/live switch)."""

import re

import pytest
from pydantic import ValidationError

from telegram_tui.config import DEFAULT_CONFIG_PATHS, EXAMPLE_CONFIG, Config


def test_defaults_are_mock(monkeypatch, tmp_path):
    monkeypatch.setattr("telegram_tui.config.DEFAULT_CONFIG_PATHS", (tmp_path / "absent.toml",))
    cfg = Config.load(environ={})
    assert cfg.mode == "mock"
    assert cfg.api_id is None
    assert cfg.media_player == "mpv"
    assert cfg.photo_renderer == "chafa"


def test_load_from_file(tmp_path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        'mode = "live"\napi_id = 12345\napi_hash = "abcdef"\nsession = "mysess"\n',
        encoding="utf-8",
    )
    cfg = Config.load(path=cfg_file, environ={})
    assert cfg.mode == "live"
    assert cfg.api_id == 12345
    assert cfg.api_hash == "abcdef"
    assert cfg.session == "mysess"


def test_env_overrides_file(tmp_path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('mode = "mock"\napi_id = 1\napi_hash = "x"\n', encoding="utf-8")
    cfg = Config.load(
        path=cfg_file,
        environ={
            "TG_TUI_MODE": "live",
            "TG_TUI_API_ID": "999",
            "TG_TUI_API_HASH": "from-env",
        },
    )
    assert cfg.mode == "live"
    assert cfg.api_id == 999
    assert cfg.api_hash == "from-env"


def test_missing_config_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        Config.load(path=tmp_path / "nope.toml", environ={})


def test_bad_mode_rejected(tmp_path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('mode = "hyperdrive"\n', encoding="utf-8")
    with pytest.raises(ValidationError):
        Config.load(path=cfg_file, environ={})


def test_live_mode_requires_credentials():
    with pytest.raises(ValueError, match="api_id"):
        Config(mode="live", api_id=None, api_hash=None)
    ok = Config(mode="live", api_id=1, api_hash="h")
    assert ok.mode == "live"


def test_default_paths_and_example_config():
    assert all(isinstance(p, object) for p in DEFAULT_CONFIG_PATHS)
    assert 'mode = "mock"' in EXAMPLE_CONFIG
    assert "my.telegram.org" in EXAMPLE_CONFIG


def test_user_facing_config_text_is_english():
    """The UI was translated once and these strings were left behind in Russian."""
    cyrillic = re.compile("[а-яА-Я]")
    assert not cyrillic.search(EXAMPLE_CONFIG)
    with pytest.raises(ValueError) as exc_info:
        Config(mode="live")
    assert not cyrillic.search(str(exc_info.value))
