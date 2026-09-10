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
        widgets = view._widgets()
        assert len(widgets) == 4

        # Sticker message has .msg-sticker
        assert widgets[0].query(".msg-sticker")
        # Video note has .msg-video
        assert widgets[1].query(".msg-video")
        # Voice message has .msg-voice
        assert widgets[2].query(".msg-voice")
        # Reactions has .msg-reactions
        assert widgets[3].query(".msg-reactions")


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
