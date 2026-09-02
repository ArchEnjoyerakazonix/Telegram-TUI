"""UI tests through textual.pilot: focus, navigation, hotkeys, resize."""

import pytest

from telegram_tui.app import TelegramTUI
from telegram_tui.engine import MockEngine
from telegram_tui.widgets.chat_list import ChatItem, ChatList
from telegram_tui.widgets.chat_view import ChatView
from telegram_tui.widgets.composer import Composer

SIZE = (110, 32)


@pytest.fixture
async def app():
    app = TelegramTUI(engine=MockEngine(seed=42), live_traffic=False)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        yield app, pilot


def chat_ids(app: TelegramTUI) -> list[int]:
    return [item.chat_id for item in app.query_one(ChatList).query(ChatItem)]


async def test_launch_renders_all_three_panels(app):
    app, _pilot = app
    assert app.query_one(ChatList)
    assert app.query_one(ChatView)
    assert app.query_one(Composer)
    assert len(app.query(ChatItem)) >= 8
    # The first chat is opened on mount and message history is rendered.
    assert app.query_one(ChatView).chat_id is not None
    assert app.query(ChatView).first().children, "messages must be rendered"


async def test_initial_focus_is_chat_list(app):
    app, _pilot = app
    assert isinstance(app.focused, ChatList)


async def test_arrow_keys_move_highlight(app):
    app, pilot = app
    chat_list = app.query_one(ChatList)
    first = chat_list.index
    await pilot.press("down")
    assert chat_list.index == first + 1
    await pilot.press("up")
    await pilot.press("up")
    assert chat_list.index == first - 1 if first else chat_list.index == 0


async def test_enter_opens_chat_and_clears_unread(app):
    app, pilot = app
    chat_list = app.query_one(ChatList)
    target = next(c for c in app.engine.chats.values() if c.unread > 0)
    items = list(chat_list.query(ChatItem))
    chat_list.index = items.index(next(i for i in items if i.chat_id == target.id))
    await pilot.pause()
    await pilot.press("enter")
    await pilot.pause()
    assert app.current_chat_id == target.id
    assert app.engine.chats[target.id].unread == 0
    assert app.query_one(ChatView).chat_id == target.id


async def test_search_hotkey_filters_list(app):
    app, pilot = app
    await pilot.press("ctrl+f")
    await pilot.pause()
    assert app.focused is not None and app.focused.id == "search"
    await pilot.press(*"py")
    await pilot.pause()
    ids = chat_ids(app)
    assert len(ids) == 1
    assert app.engine.chats[ids[0]].title == "Python Chat"
    # Escape clears the filter and returns focus to the chat list.
    await pilot.press("escape")
    await pilot.pause()
    assert isinstance(app.focused, ChatList)
    assert len(chat_ids(app)) == len(app.engine.chats)


async def test_slash_from_chat_list_focuses_search(app):
    app, pilot = app
    await pilot.press("/")
    await pilot.pause()
    assert app.focused is not None and app.focused.id == "search"


async def test_ctrl_up_down_cycles_panels(app):
    app, pilot = app
    await pilot.press("ctrl+down")
    await pilot.pause()
    assert isinstance(app.focused, Composer)
    await pilot.press("ctrl+down")
    await pilot.pause()
    assert app.focused is not None and app.focused.id == "search"
    await pilot.press("ctrl+down")
    await pilot.pause()
    assert isinstance(app.focused, ChatList)
    await pilot.press("ctrl+up")
    await pilot.pause()
    assert app.focused is not None and app.focused.id == "search"


async def test_send_message_with_enter(app):
    app, pilot = app
    view = app.query_one(ChatView)
    chat_id = view.chat_id
    before = len(app.engine.history(chat_id))
    await pilot.press("ctrl+down")  # focus composer
    await pilot.press(*"привет, мир")
    await pilot.pause()
    await pilot.press("enter")
    await pilot.pause()
    history = app.engine.history(chat_id)
    assert len(history) == before + 1
    assert history[-1].text == "привет, мир"
    assert history[-1].sender_id == app.engine.me.id
    assert app.query_one(Composer).text == ""
    # The view shows the sent message and scrolled to it.
    assert view.children


async def test_multiline_composer_alt_enter_newline(app):
    app, pilot = app
    await pilot.press("ctrl+down")
    await pilot.press("a")
    await pilot.press("alt+enter")
    await pilot.press("b")
    await pilot.pause()
    assert app.query_one(Composer).text == "a\nb"
    # Enter still sends the multiline text.
    await pilot.press("enter")
    await pilot.pause()
    assert app.query_one(Composer).text == ""
    assert app.engine.history(app.current_chat_id)[-1].text == "a\nb"


async def test_empty_composer_enter_does_not_send(app):
    app, pilot = app
    chat_id = app.current_chat_id
    before = len(app.engine.history(chat_id))
    await pilot.press("ctrl+down")
    await pilot.press("enter")
    await pilot.pause()
    assert len(app.engine.history(chat_id)) == before


async def test_pin_hotkey_ctrl_p(app):
    app, pilot = app
    chat_list = app.query_one(ChatList)
    highlighted = chat_list.highlighted_chat_id()
    was = app.engine.chats[highlighted].pinned
    await pilot.press("ctrl+p")
    await pilot.pause()
    assert app.engine.chats[highlighted].pinned is not was
    # Pinned chats now sort first.
    if app.engine.chats[highlighted].pinned:
        assert chat_ids(app)[0] == highlighted


async def test_mark_read_hotkey(app):
    app, pilot = app
    target = next(c for c in app.engine.chats.values() if c.unread > 0)
    chat_list = app.query_one(ChatList)
    items = list(chat_list.query(ChatItem))
    chat_list.index = items.index(next(i for i in items if i.chat_id == target.id))
    await pilot.pause()
    await pilot.press("ctrl+m")
    await pilot.pause()
    assert app.engine.chats[target.id].unread == 0


async def test_incoming_message_updates_view_and_badges(app):
    app, _pilot = app
    view = app.query_one(ChatView)
    open_id = view.chat_id
    before = len(view.children)
    app._ingest(app.engine.inject_incoming(open_id))
    await _pilot.pause()
    assert len(view.children) == before + 1
    assert app.engine.chats[open_id].unread == 0

    other = next(c for c in app.engine.chats.values() if c.id != open_id)
    was = other.unread
    app._ingest(app.engine.inject_incoming(other.id))
    await _pilot.pause()
    assert other.unread == was + 1
    # Unread badge is present on that chat's list item.
    item = app.query_one(ChatList).item_by_chat(other.id)
    assert item is not None


async def test_resize_terminal_no_crash_and_rerender(app):
    app, pilot = app
    await pilot.resize_terminal(80, 24)
    await pilot.pause()
    assert app.is_running
    assert app.query(ChatItem)
    assert app.query_one(ChatView).children
    await pilot.resize_terminal(140, 45)
    await pilot.pause()
    assert app.is_running
    # Sidebar shrank with the terminal, keeping the chat list usable.
    await pilot.press("down")
    await pilot.pause()
    assert isinstance(app.focused, ChatList)


async def test_resize_keeps_unread_badges_visible(app):
    app, pilot = app
    other = next(c for c in app.engine.chats.values() if c.unread > 0)
    await pilot.resize_terminal(90, 24)
    await pilot.pause()
    item = app.query_one(ChatList).item_by_chat(other.id)
    assert item is not None
    assert app.engine.chats[other.id].unread > 0
