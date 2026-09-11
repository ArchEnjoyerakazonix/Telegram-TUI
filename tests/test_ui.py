"""UI tests through textual.pilot: focus, navigation, hotkeys, resize."""

import asyncio

import pytest

from telegram_tui.app import TelegramTUI
from telegram_tui.engine import MockEngine
from telegram_tui.widgets.chat_list import ChatItem, ChatList
from telegram_tui.widgets.chat_view import QUICK_REACTIONS, ChatView
from telegram_tui.widgets.composer import Composer
from telegram_tui.widgets.photo import PhotoWidget

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
    view.focus()
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


# -- feed scrolling ---------------------------------------------------------


async def _open_chat_with_history(app, pilot):
    """Open a chat whose history is taller than the viewport."""
    target = max(app.engine.chats, key=lambda cid: len(app.engine.history(cid)))
    app.open_chat(target, force=True)
    await pilot.pause()
    await pilot.pause()
    return app.query_one(ChatView)


async def test_opening_a_chat_lands_on_the_newest_message(app):
    app, pilot = app
    view = await _open_chat_with_history(app, pilot)
    assert view.max_scroll_y > 0, "test needs a chat taller than the viewport"
    assert view.scroll_y == view.max_scroll_y
    assert view.selected_message() is app.engine.history(view.chat_id)[-1]


async def test_incoming_message_keeps_the_feed_at_the_bottom(app):
    app, pilot = app
    view = await _open_chat_with_history(app, pilot)

    app._ingest(app.engine.inject_incoming(view.chat_id))
    await pilot.pause()
    await pilot.pause()

    assert view.scroll_y == view.max_scroll_y


async def test_incoming_message_does_not_yank_a_reader_of_scrollback(app):
    app, pilot = app
    view = await _open_chat_with_history(app, pilot)
    view.scroll_to(y=0, animate=False)
    await pilot.pause()
    assert view.scroll_y == 0

    app._ingest(app.engine.inject_incoming(view.chat_id))
    await pilot.pause()
    await pilot.pause()

    assert view.scroll_y == 0, "reading history must not be interrupted"


# -- quick reactions --------------------------------------------------------


async def _focus_feed_on(app, pilot, predicate):
    """Focus the feed with the first message matching predicate selected."""
    view = app.query_one(ChatView)
    view.focus()
    await pilot.pause()
    for index, widget in enumerate(view._widgets()):
        if predicate(widget.message):
            view.select(index)
            await pilot.pause()
            return view, widget
    raise AssertionError("no matching message in the opened chat")


async def test_number_key_posts_a_reaction(app):
    app, pilot = app
    view, widget = await _focus_feed_on(app, pilot, lambda m: not m.reactions)

    await pilot.press("3")
    await pilot.pause()

    assert widget.message.reactions == [("🔥", 1)]
    assert widget._reaction_row.display is True


async def test_repeated_reaction_increments_the_count(app):
    app, pilot = app
    view, widget = await _focus_feed_on(app, pilot, lambda m: not m.reactions)

    await pilot.press("1")
    await pilot.press("1")
    await pilot.pause()

    assert widget.message.reactions == [("👍", 2)]


async def test_reaction_keys_cover_the_documented_set(app):
    app, pilot = app
    view, widget = await _focus_feed_on(app, pilot, lambda m: not m.reactions)

    for key in QUICK_REACTIONS:
        await pilot.press(key)
    await pilot.pause()

    assert [emoji for emoji, _count in widget.message.reactions] == list(
        QUICK_REACTIONS.values()
    )


async def test_reaction_on_empty_selection_is_a_no_op(app):
    app, pilot = app
    view = app.query_one(ChatView)
    view.focus()
    await pilot.pause()
    view._selected = -1

    await pilot.press("2")
    await pilot.pause()  # must not raise


# -- photo previews ---------------------------------------------------------


async def _photo_widget(size):
    """Open the chat holding a photo and return (feed, photo widget) at ``size``."""
    app = TelegramTUI(engine=MockEngine(seed=42), live_traffic=False)
    async with app.run_test(size=size) as pilot:
        await pilot.pause()
        target = next(
            cid
            for cid in app.engine.chats
            if any(m.has_photo for m in app.engine.history(cid))
        )
        app.open_chat(target, force=True)
        for _ in range(4):
            await pilot.pause()
        yield app.query_one(ChatView), app.query(PhotoWidget).first()


async def test_photo_preview_fits_inside_the_feed():
    async for feed, photo in _photo_widget((120, 40)):
        cols, rows = photo._preview_box()
        assert cols <= feed.size.width, "a preview must not overflow sideways"
        assert rows <= feed.size.height, "a preview must not be taller than the feed"


async def test_photo_preview_never_grows_on_a_smaller_terminal():
    async for _feed, photo in _photo_widget((120, 40)):
        roomy = photo._preview_box()
    async for _feed, photo in _photo_widget((60, 16)):
        cramped = photo._preview_box()

    assert cramped[0] <= roomy[0] and cramped[1] <= roomy[1]
    assert cramped != roomy, "a much smaller terminal must clamp the box"


async def test_z_expands_and_collapses_a_photo(app):
    app, pilot = app
    target = next(
        cid for cid in app.engine.chats if any(m.has_photo for m in app.engine.history(cid))
    )
    app.open_chat(target, force=True)
    for _ in range(4):
        await pilot.pause()

    view = app.query_one(ChatView)
    view.focus()
    photo = app.query(PhotoWidget).first()
    index = next(
        i for i, w in enumerate(view._widgets()) if w.query(PhotoWidget)
    )
    view.select(index)
    await pilot.pause()

    compact_rows = photo._preview_box()[1]
    assert photo.expanded is False

    await pilot.press("z")
    await pilot.pause()
    assert photo.expanded is True
    assert photo._preview_box()[1] > compact_rows

    await pilot.press("z")
    await pilot.pause()
    assert photo.expanded is False
    assert photo._preview_box()[1] == compact_rows


# -- sidebar refresh cost ---------------------------------------------------


async def test_sidebar_updates_rows_in_place(app):
    """Rebuilding the list clears it first, so a busy chat blanked the sidebar."""
    app, pilot = app
    chat_list = app.query_one(ChatList)
    before = list(chat_list.query(ChatItem))
    chat_id = app.current_chat_id

    app.engine.chats[chat_id].unread = 7
    app.refresh_chat_list()
    await pilot.pause()

    after = list(chat_list.query(ChatItem))
    assert [id(w) for w in before] == [id(w) for w in after], "rows must be reused"
    row = next(w for w in after if w.chat_id == chat_id)
    assert row._signature[2] == 7, "the badge still has to update"


async def test_sidebar_rebuilds_when_the_order_changes(app):
    app, pilot = app
    chat_list = app.query_one(ChatList)
    before = [w.chat_id for w in chat_list.query(ChatItem)]

    # Filtering changes which chats are listed, so reuse is impossible.
    app._search_query = "mom"
    app.refresh_chat_list()
    await pilot.pause()

    after = [w.chat_id for w in chat_list.query(ChatItem)]
    assert after != before
    assert len(after) == 1


async def test_unchanged_rows_are_not_redrawn(app):
    app, pilot = app
    row = app.query_one(ChatList).query(ChatItem).first()
    chat = app.engine.chats[row.chat_id]

    assert row.update_chat(chat) is False, "nothing changed, nothing to redraw"
    chat.unread += 1
    assert row.update_chat(chat) is True


# -- poster frames for video and GIF ----------------------------------------


@pytest.mark.parametrize("media_type", ["video", "gif", "video_note"])
async def test_video_like_media_shows_a_poster_frame(media_type):
    """"GIF doesn't render anything" — it needs the still frame Telegram keeps."""
    engine = MockEngine(seed=5)
    chat_id = next(iter(engine.chats))
    engine._msg(chat_id, engine.members[chat_id][0], "", media_type=media_type, duration=11)

    app = TelegramTUI(engine=engine, live_traffic=False)
    async with app.run_test(size=(120, 40)) as pilot:
        app.open_chat(chat_id, force=True)
        for _ in range(8):
            await pilot.pause(0.05)

        frames = [w for w in app.query(PhotoWidget) if w._thumbnail]
        assert frames, f"{media_type} should show a poster frame"
        assert frames[-1]._path is not None
        assert frames[-1].size.height > 1


async def test_a_frameless_video_hides_the_widget_rather_than_apologising():
    engine = MockEngine(seed=5)
    chat_id = next(iter(engine.chats))
    engine._msg(chat_id, engine.members[chat_id][0], "", media_type="video", duration=5)

    async def no_thumbnail(message):
        return None

    engine.fetch_thumbnail = no_thumbnail
    app = TelegramTUI(engine=engine, live_traffic=False)
    async with app.run_test(size=(120, 40)) as pilot:
        app.open_chat(chat_id, force=True)
        for _ in range(8):
            await pilot.pause(0.05)

        frames = [w for w in app.query(PhotoWidget) if w._thumbnail]
        assert frames and frames[-1].display is False


@pytest.mark.parametrize(
    "media_type", ["photo", "video", "gif", "audio", "document", "video_note", "voice"]
)
async def test_pressing_o_hands_every_media_kind_to_a_program(media_type):
    """Nothing openable may be a dead end in the feed."""
    from unittest.mock import MagicMock, patch

    engine = MockEngine(seed=5)
    chat_id = next(iter(engine.chats))
    engine.messages[chat_id].clear()
    message = engine._msg(
        chat_id,
        engine.members[chat_id][0],
        "",
        media_type=media_type,
        duration=11,
        has_photo=media_type == "photo",
        has_voice=media_type == "voice",
    )
    message.file_name = "report.pdf" if media_type == "document" else None

    app = TelegramTUI(engine=engine, live_traffic=False)
    app.notify = lambda *a, **k: None
    with patch("subprocess.Popen") as popen:
        popen.return_value = MagicMock()
        async with app.run_test(size=(120, 40)) as pilot:
            app.open_chat(chat_id, force=True)
            for _ in range(6):
                await pilot.pause(0.05)
            view = app.query_one(ChatView)
            view.focus()
            view.select(0)
            await pilot.pause()
            await pilot.press("o")
            for _ in range(6):
                await pilot.pause(0.05)

    assert popen.called, f"{media_type} was not handed to any program"


# -- cancelling a download --------------------------------------------------


async def _app_with_a_slow_download():
    """An app whose next download never finishes on its own."""
    engine = MockEngine(seed=5)
    chat_id = next(iter(engine.chats))
    engine.messages[chat_id].clear()
    engine._msg(chat_id, engine.members[chat_id][0], "", media_type="video", duration=30)

    started = asyncio.Event()
    calls: list[int] = []

    async def slow_fetch(message, progress=None):
        calls.append(1)
        started.set()
        await asyncio.sleep(60)

    engine.fetch_file = slow_fetch
    notices: list[str] = []
    app = TelegramTUI(engine=engine, live_traffic=False)
    app.notify = lambda msg, *a, **k: notices.append(str(msg))
    return app, chat_id, started, calls, notices


async def _select_the_video(app, pilot, chat_id):
    app.open_chat(chat_id, force=True)
    for _ in range(6):
        await pilot.pause(0.05)
    view = app.query_one(ChatView)
    view.focus()
    view.select(0)
    await pilot.pause()


async def test_escape_cancels_a_download_in_flight():
    """A large file must not hold the client hostage.

    Note this drives the actions directly rather than pressing keys: pilot waits
    for the app to go idle, which for a running download means waiting for it.
    """
    app, chat_id, started, _calls, notices = await _app_with_a_slow_download()
    async with app.run_test(size=(120, 40)) as pilot:
        await _select_the_video(app, pilot, chat_id)

        app.action_open_media()
        await asyncio.wait_for(started.wait(), timeout=5)
        assert app._download is not None and not app._download.done()

        app.action_back_to_list()  # what Esc is bound to
        await asyncio.sleep(0)
        assert app._download.cancelled() or app._download.done()

    assert any("cancelled" in n.lower() for n in notices), notices


async def test_a_second_open_does_not_start_a_parallel_download():
    app, chat_id, started, calls, notices = await _app_with_a_slow_download()
    async with app.run_test(size=(120, 40)) as pilot:
        await _select_the_video(app, pilot, chat_id)

        app.action_open_media()
        await asyncio.wait_for(started.wait(), timeout=5)
        app.action_open_media()
        await asyncio.sleep(0)

        assert len(calls) == 1, "one download at a time"
        assert any("already running" in n.lower() for n in notices), notices
        app.cancel_download()
        await asyncio.sleep(0)


async def test_escape_still_leaves_the_chat_when_nothing_is_downloading():
    """Cancelling must not swallow Esc's normal job."""
    app, chat_id, _started, _calls, _notices = await _app_with_a_slow_download()
    async with app.run_test(size=(120, 40)) as pilot:
        await _select_the_video(app, pilot, chat_id)
        app.query_one(Composer).focus()
        await pilot.pause()

        assert app.cancel_download() is False
        app.action_back_to_list()
        await pilot.pause()

        assert isinstance(app.focused, ChatList)
