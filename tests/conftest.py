"""Shared fixtures.

Two things must never happen while the suite runs, because both destroy real
user state on the developer's machine:

  * touching ``~/.config/telegram-tui`` — the live Telethon session lives
    there, and ``TelethonBackend`` deletes session files it considers stale;
  * opening a real MTProto connection, which is slow and writes a fresh
    auth key over whatever was there.

Rather than trusting every test to remember, both are neutralised for the
whole suite here.
"""

from __future__ import annotations

import pathlib
import tempfile
from unittest.mock import AsyncMock

import pytest


@pytest.fixture(autouse=True)
def isolate_user_state(tmp_path, monkeypatch):
    """Point ``Path.home()`` and the config lookup at a throwaway directory."""
    home = tmp_path / "home"
    (home / ".config" / "telegram-tui").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(pathlib.Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(
        "telegram_tui.config.DEFAULT_CONFIG_PATHS",
        (home / ".config" / "telegram-tui" / "config.toml",),
    )
    # Downloaded media is cached under the temp dir by a stable name, so give
    # each test its own or they would read each other's files.
    scratch = tmp_path / "tmp"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))
    return home


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Stub out the MTProto socket so no test can reach Telegram."""
    from telethon import TelegramClient

    monkeypatch.setattr(TelegramClient, "connect", AsyncMock())
    monkeypatch.setattr(TelegramClient, "disconnect", AsyncMock())


@pytest.fixture
def make_backend(tmp_path):
    """Build a TelethonBackend whose session file lives under tmp_path."""
    from telegram_tui.telethon_backend import TelethonBackend

    def factory(
        api_id: int = 12345,
        api_hash: str = "0123456789abcdef0123456789abcdef",
        session: str | None = None,
    ) -> TelethonBackend:
        return TelethonBackend(
            api_id, api_hash, session=session or str(tmp_path / "test-session")
        )

    return factory
