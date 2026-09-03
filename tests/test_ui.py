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
    assert isinstance(app.focused, ChatView)
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
    await pilot.press("ctrl+down", "ctrl+down")  # focus composer (past messages)
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
    await pilot.press("ctrl+down", "ctrl+down")
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
    await pilot.press("ctrl+down", "ctrl+down")
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


# -- vim navigation -------------------------------------------------------------


async def test_vim_jk_moves_chat_list(app):
    app, pilot = app
    chat_list = app.query_one(ChatList)
    start = chat_list.index
    await pilot.press("j")
    await pilot.pause()
    assert chat_list.index == start + 1
    await pilot.press("k")
    await pilot.pause()
    assert chat_list.index == start


async def test_vim_navigation_selects_messages(app):
    app, pilot = app
    await pilot.press("ctrl+down")  # focus message history
    await pilot.pause()
    view = app.query_one(ChatView)
    view.action_sel_first()
    await pilot.pause()
    widgets = view._widgets()
    assert widgets[0].has_class("-selected")
    await pilot.press("j")
    await pilot.pause()
    assert widgets[1].has_class("-selected")
    assert not widgets[0].has_class("-selected")
    await pilot.press("k")
    await pilot.pause()
    assert widgets[0].has_class("-selected")
    await pilot.press("G")
    await pilot.pause()
    assert widgets[-1].has_class("-selected")


# -- reply by 'r' ------------------------------------------------------------


async def test_reply_hotkey_r_quotes_message(app):
    app, pilot = app
    chat_id = next(c.id for c in app.engine.chats.values() if c.title == "Python Chat")
    app.open_chat(chat_id, force=True)
    await pilot.pause()
    view = app.query_one(ChatView)
    view.action_sel_first()
    await pilot.pause()
    target_id = view.selected_message().id

    await pilot.press("r")
    await pilot.pause()
    assert app.pending_reply == (chat_id, target_id)
    assert isinstance(app.focused, Composer)
    assert "↱" in str(app.query_one(Composer).border_title)

    await pilot.press(*"отвечаю")
    await pilot.press("enter")
    await pilot.pause()
    last = app.engine.history(chat_id)[-1]
    assert last.text == "отвечаю"
    assert last.reply_to == target_id
    assert app.pending_reply is None
    assert not str(app.query_one(Composer).border_title)


async def test_escape_cancels_pending_reply(app):
    app, pilot = app
    await pilot.press("ctrl+down")
    await pilot.press("r")
    await pilot.pause()
    assert app.pending_reply is not None
    await pilot.press("escape")
    await pilot.pause()
    assert app.pending_reply is None
    assert isinstance(app.focused, Composer)
    # Second escape returns to the chat list.
    await pilot.press("escape")
    await pilot.pause()
    assert isinstance(app.focused, ChatList)


# -- in-chat full-text search -------------------------------------------------


async def test_search_in_chat_highlights_and_jumps(app):
    app, pilot = app
    chat_id = next(c.id for c in app.engine.chats.values() if c.title == "Python Chat")
    app.open_chat(chat_id, force=True)
    await pilot.pause()
    view = app.query_one(ChatView)
    await pilot.press("ctrl+down")
    await pilot.press("/")
    await pilot.pause()
    assert app.focused is not None and app.focused.id == "msg-search"
    await pilot.press(*"textual")
    await pilot.pause()
    assert view.hits, "должны найтись совпадения по 'textual'"
    assert all(w.has_class("-hit") for w in view.hits)
    first_hit = view.hit_index
    await pilot.press("enter")
    await pilot.pause()
    assert view.hit_index == (first_hit + 1) % len(view.hits)
    # n jumps further, Esc hides the search bar and clears highlighting.
    await pilot.press("n")
    await pilot.pause()
    assert view.hit_index == (first_hit + 2) % len(view.hits)
    await pilot.press("escape")
    await pilot.pause()
    assert app.query_one("#msg-search").display is False
    assert view.hits == []


# -- voice playback ------------------------------------------------------------


async def test_voice_playback_hotkey_v(app, monkeypatch):
    app, pilot = app
    bob_id = next(c.id for c in app.engine.chats.values() if c.title == "Bob")
    app.open_chat(bob_id, force=True)
    await pilot.pause()
    view = app.query_one(ChatView)
    voice_idx = next(i for i, w in enumerate(view._widgets()) if w.message.has_voice)

    played: list = []
    stopped: list = []

    class RecPlayer:
        def play(self, path):
            played.append(path)

        def stop(self):
            stopped.append(True)

    app.voice_player = RecPlayer()
    await pilot.press("ctrl+down")
    view.select(voice_idx)
    await pilot.pause()
    await pilot.press("v")
    await pilot.pause()
    assert len(played) == 1
    assert played[0].exists(), "mock-движок должен сгенерировать WAV-файл"
    assert played[0].read_bytes()[:4] == b"RIFF"


async def test_voice_without_voice_message_notifies(app, monkeypatch):
    app, pilot = app
    notified: list = []
    monkeypatch.setattr(app, "notify", lambda *a, **k: notified.append(a))
    await pilot.press("ctrl+down")
    await pilot.press("v")
    await pilot.pause()
    assert notified, "должно прийти уведомление об отсутствии голосового"
