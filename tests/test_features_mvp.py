"""Tests for new MVP features: onboarding, rich media, pagination, read-only channels."""

import pytest

from telegram_tui.app import TelegramTUI
from telegram_tui.auth import WelcomeScreen
from telegram_tui.engine import MockEngine
from telegram_tui.models import Chat, ChatType, Message, utcnow
from telegram_tui.widgets.chat_view import ChatView
from telegram_tui.widgets.composer import Composer
from textual.widgets import Static

SIZE = (120, 36)


@pytest.mark.asyncio
async def test_welcome_screen_modal():
    app = TelegramTUI(engine=MockEngine(), live_traffic=False, show_welcome=True)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        assert isinstance(app.screen, WelcomeScreen)
        # Choosing demo mode dismisses modal and lands in app
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, WelcomeScreen)
        assert app.query_one(ChatView)


@pytest.mark.asyncio
async def test_channel_read_only_hides_composer():
    engine = MockEngine()
    # Add a read-only channel
    channel = Chat(
        id=9999,
        title="Breaking News Channel",
        chat_type=ChatType.CHANNEL,
        is_read_only=True,
        last_activity=utcnow(),
    )
    engine.chats[channel.id] = channel
    engine.messages[channel.id] = [
        Message(id=1, chat_id=channel.id, sender_id=9999, text="Official statement.")
    ]

    app = TelegramTUI(engine=engine, live_traffic=False)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        app.open_chat(channel.id, force=True)
        await pilot.pause()

        banner = app.query_one("#channel-banner", Static)
        composer = app.query_one("#composer", Composer)
        assert banner.display is True
        assert composer.display is False


@pytest.mark.asyncio
async def test_rich_media_rendering_in_chat_view():
    engine = MockEngine()
    chat_id = 8888
    engine.chats[chat_id] = Chat(
        id=chat_id,
        title="Media Test",
        chat_type=ChatType.PRIVATE,
        last_activity=utcnow(),
    )
    engine.messages[chat_id] = [
        Message(
            id=1,
            chat_id=chat_id,
            sender_id=10,
            text="Here is a sticker",
            media_type="sticker",
            sticker_emoji="🔥",
        ),
        Message(
            id=2,
            chat_id=chat_id,
            sender_id=10,
            text="",
            media_type="video_note",
            duration=12,
        ),
        Message(
            id=3,
            chat_id=chat_id,
            sender_id=10,
            text="",
            media_type="voice",
            has_voice=True,
            duration=35,
        ),
        Message(
            id=4,
            chat_id=chat_id,
            sender_id=10,
            text="React to this!",
            reactions=[("👍", 5), ("🚀", 2)],
        ),
    ]

    app = TelegramTUI(engine=engine, live_traffic=False)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        app.open_chat(chat_id, force=True)
        await pilot.pause()

        view = app.query_one(ChatView)
        # Older history can load itself in, so find each message by its id.
        by_id = {w.message.id: w for w in view._widgets()}

        assert by_id[1].query(".msg-sticker")
        assert by_id[2].query(".msg-video")
        assert by_id[3].query(".msg-voice")
        assert by_id[4].query(".msg-reactions")


@pytest.mark.asyncio
async def test_load_older_history_pagination():
    engine = MockEngine()
    first_chat = engine.sorted_chats()[0]
    app = TelegramTUI(engine=engine, live_traffic=False)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        app.open_chat(first_chat.id, force=True)
        await pilot.pause()

        view = app.query_one(ChatView)
        count_before = len(view._widgets())

        # Press Ctrl+O to trigger load older
        await pilot.press("ctrl+o")
        await pilot.pause()

        count_after = len(view._widgets())
        assert count_after > count_before


@pytest.mark.asyncio
async def test_api_credentials_screen():
    from telegram_tui.auth import ApiCredentialsScreen
    from textual.widgets import Input

    class DummyApp(TelegramTUI):
        def on_mount(self):
            self.run_worker(self._ask_creds())

        async def _ask_creds(self):
            creds = await self.push_screen_wait(ApiCredentialsScreen())
            self.entered_creds = creds

    app = DummyApp(engine=MockEngine(), live_traffic=False)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        assert isinstance(app.screen, ApiCredentialsScreen)

        # Type api_id and api_hash
        id_inp = app.screen.query_one("#input-api-id", Input)
        id_inp.value = "123456"
        hash_inp = app.screen.query_one("#input-api-hash", Input)
        hash_inp.value = "abcdef0123456789abcdef0123456789"

        await pilot.click("#btn-save-api")
        await pilot.pause()

        assert app.entered_creds == (123456, "abcdef0123456789abcdef0123456789")


def test_config_save_credentials(tmp_path):
    from telegram_tui.config import Config

    target = tmp_path / "config.toml"
    saved = Config.save_credentials(
        api_id=98765,
        api_hash="test_hash_123",
        path=target,
    )
    assert saved.exists()
    loaded = Config.load(path=target)
    assert loaded.api_id == 98765
    assert loaded.api_hash == "test_hash_123"
    assert loaded.mode == "live"


def test_waveform_formatting():
    from telegram_tui.media import format_waveform, decode_telegram_waveform

    # Default wave
    wave_str = format_waveform(None, width=16)
    assert len(wave_str) == 16
    assert any(c in " ▂▃▄▅▆▇█" for c in wave_str)

    # Decode raw 5-bit telegram bytes
    raw = bytes([0x1F, 0x00, 0xFF, 0xAA])
    samples = decode_telegram_waveform(raw, target_len=4)
    assert len(samples) == 4
    formatted = format_waveform(samples, width=4)
    assert len(formatted) == 4


@pytest.mark.asyncio
async def test_open_selected_media(monkeypatch):
    engine = MockEngine()
    opened_paths = []

    def fake_open(path, loop=False):
        opened_paths.append(path)
        return None

    monkeypatch.setattr("telegram_tui.media.open_external_media", fake_open)

    chat_id = next(c.id for c in engine.chats.values() if c.title == "Alice")
    app = TelegramTUI(engine=engine, live_traffic=False)

    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        app.open_chat(chat_id, force=True)
        await pilot.pause()

        # Alice has a photo message in fixture. Select first message
        view = app.query_one(ChatView)
        photo_idx = next(i for i, w in enumerate(view._widgets()) if w.message.has_photo)
        view.select(photo_idx)
        await pilot.pause()

        # Press 'o' to open
        await pilot.press("o")
        await pilot.pause()

        assert len(opened_paths) == 1
        assert opened_paths[0].suffix == ".png"
