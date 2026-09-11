"""Comprehensive adversarial test suite for Telegram TUI.

Tests malformed configs, boundary credentials, corrupted waveforms,
external media launcher resilience, edge-case UI messages, and Telethon errors.
"""

from __future__ import annotations

import datetime as dt
import os
import subprocess
import tomllib
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from telegram_tui.app import TelegramTUI
from telegram_tui.auth import ApiCredentialsScreen, LoginScreen
from telegram_tui.backend import BaseBackend
from telegram_tui.config import Config
from telegram_tui.media import (
    decode_telegram_waveform,
    format_waveform,
    open_external_media,
    render_photo,
)
from telegram_tui.models import Chat, ChatType, Message
from telegram_tui.telethon_backend import _display_name
from telegram_tui.widgets.chat_view import (
    ChatView,
    MessageWidget,
    _time_label,
    sender_style,
)


# ============================================================================
# 1. Config adversarial & boundary tests
# ============================================================================


def test_config_corrupt_toml_raises(tmp_path: Path):
    corrupt = tmp_path / "corrupt.toml"
    corrupt.write_text("[[[invalid toml == ??", encoding="utf-8")
    with pytest.raises(tomllib.TOMLDecodeError):
        Config.load(path=corrupt, environ={})


def test_config_binary_garbage_raises(tmp_path: Path):
    garbage = tmp_path / "garbage.toml"
    garbage.write_bytes(b"\x00\xff\xfe\x12\x34\xab\xcd")
    with pytest.raises((tomllib.TOMLDecodeError, UnicodeDecodeError)):
        Config.load(path=garbage, environ={})


def test_config_nonexistent_file_raises(tmp_path: Path):
    missing = tmp_path / "does_not_exist.toml"
    with pytest.raises(FileNotFoundError):
        Config.load(path=missing, environ={})


def test_config_env_api_id_non_integer_raises(tmp_path: Path):
    cfg_file = tmp_path / "cfg.toml"
    cfg_file.write_text('mode = "live"\napi_hash = "abc"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="TG_TUI_API_ID must be an integer"):
        Config.load(path=cfg_file, environ={"TG_TUI_API_ID": "not-an-int"})


def test_config_env_api_id_special_chars_raises(tmp_path: Path):
    with pytest.raises(ValueError, match="TG_TUI_API_ID must be an integer"):
        Config.load(path=None, environ={"TG_TUI_API_ID": "!@#$%^&*"})


def test_config_live_mode_missing_credentials():
    with pytest.raises(ValueError, match="api_id"):
        Config(mode="live", api_id=None, api_hash="abc")

    with pytest.raises(ValueError, match="api_hash"):
        Config(mode="live", api_id=12345, api_hash="")


def test_config_traffic_interval_boundary():
    with pytest.raises(ValidationError):
        Config(traffic_interval=0)
    with pytest.raises(ValidationError):
        Config(traffic_interval=-1.5)


def test_config_save_credentials_invalid_api_id(tmp_path: Path):
    with pytest.raises(ValueError, match="api_id must be a positive integer"):
        Config.save_credentials(api_id=-1, api_hash="validhash", path=tmp_path / "c.toml")
    with pytest.raises(ValueError, match="api_id must be a positive integer"):
        Config.save_credentials(api_id=0, api_hash="validhash", path=tmp_path / "c.toml")


def test_config_save_credentials_injection_prevented(tmp_path: Path):
    with pytest.raises(ValueError, match="api_hash"):
        Config.save_credentials(
            api_id=123,
            api_hash='injected"\nmode = "mock"\n',
            path=tmp_path / "c.toml",
        )
    with pytest.raises(ValueError, match="session"):
        Config.save_credentials(
            api_id=123,
            api_hash="validhash",
            session='sess"\ncorrupted = true\n',
            path=tmp_path / "c.toml",
        )


def test_config_save_credentials_permissions(tmp_path: Path):
    target = tmp_path / "sub" / "secure_config.toml"
    saved = Config.save_credentials(
        api_id=98765,
        api_hash="0123456789abcdef0123456789abcdef",
        path=target,
    )
    assert saved.exists()
    mode = target.stat().st_mode & 0o777
    assert mode == 0o600
    data = tomllib.loads(saved.read_text(encoding="utf-8"))
    assert data["api_id"] == 98765
    assert data["api_hash"] == "0123456789abcdef0123456789abcdef"


# ============================================================================
# 2. ApiCredentialsScreen adversarial validation tests
# ============================================================================


@pytest.mark.asyncio
async def test_api_credentials_screen_empty_validation():
    screen = ApiCredentialsScreen()
    dismissed_result = []
    screen.dismiss = lambda res=None: dismissed_result.append(res)

    class DummyInput:
        def __init__(self, val=""):
            self.value = val
            self.focused = False

        def focus(self):
            self.focused = True

    class DummyStatic:
        def __init__(self):
            self.text = ""

        def update(self, t):
            self.text = t

    inp_id = DummyInput("")
    inp_hash = DummyInput("")
    err = DummyStatic()

    def dummy_query_one(selector, *args):
        if "id" in selector:
            return inp_id
        if "hash" in selector:
            return inp_hash
        return err

    screen.query_one = dummy_query_one

    # 1. Empty api_id
    screen._submit()
    assert err.text == "Please enter api_id"
    assert not dismissed_result

    # 2. Non-digit api_id
    inp_id.value = "not_digits"
    screen._submit()
    assert err.text == "api_id must be an integer"
    assert not dismissed_result

    # 3. Negative api_id
    inp_id.value = "-100"
    screen._submit()
    assert err.text == "api_id must be a positive integer"
    assert not dismissed_result

    # 4. Zero api_id
    inp_id.value = "0"
    screen._submit()
    assert err.text == "api_id must be a positive integer"
    assert not dismissed_result

    # 5. Empty api_hash
    inp_id.value = "123456"
    inp_hash.value = ""
    screen._submit()
    assert err.text == "Please enter api_hash"
    assert not dismissed_result

    # 6. Malformed api_hash (too short or newlines)
    inp_hash.value = "short"
    screen._submit()
    assert err.text == "Invalid api_hash format"
    assert not dismissed_result

    inp_hash.value = 'hash_with\nnewline"'
    screen._submit()
    assert err.text == "Invalid api_hash format"
    assert not dismissed_result

    # 7. Valid credentials
    inp_hash.value = "abcdef0123456789abcdef0123456789"
    screen._submit()
    assert dismissed_result == [(123456, "abcdef0123456789abcdef0123456789")]

    # 8. Cancel action
    screen.action_cancel()
    assert dismissed_result[-1] is None


@pytest.mark.asyncio
async def test_login_screen_error_rich_markup_safety():
    backend = MagicMock(spec=BaseBackend)
    backend.request_code = AsyncMock(side_effect=ValueError("[420 FLOOD_WAIT_60: [tag] unclosed"))
    screen = LoginScreen(backend)

    class FakeInput:
        id = "auth-input"
        disabled = False
        value = "+79991234567"

        def focus(self):
            pass

    event = MagicMock()
    event.input = FakeInput()
    event.value = "+79991234567"

    err = MagicMock()
    screen.query_one = MagicMock(return_value=err)

    await screen.on_input_submitted(event)
    err.update.assert_called()


# ============================================================================
# 3. Waveform and media adversarial tests
# ============================================================================


def test_waveform_zero_target_len():
    assert decode_telegram_waveform(b"\x01\x02\x03", target_len=0) == []
    assert decode_telegram_waveform(b"\x01\x02\x03", target_len=-5) == []


def test_waveform_empty_bytes():
    assert decode_telegram_waveform(b"") == []
    assert decode_telegram_waveform(b"", target_len=10) == []


def test_waveform_fuzz_random_bytes():
    for seed in range(50):
        data = os.urandom(seed % 32 + 1)
        res = decode_telegram_waveform(data, target_len=16)
        assert isinstance(res, list)
        assert len(res) <= 16
        for sample in res:
            assert 0 <= sample <= 31


def test_format_waveform_boundary_width():
    assert format_waveform(b"\x01\x02", width=0) == ""
    assert format_waveform(b"\x01\x02", width=-3) == ""


def test_format_waveform_extreme_values():
    bizarre = [None, float("nan"), float("inf"), -100, "corrupted", 999999]
    res = format_waveform(bizarre, width=10)
    assert isinstance(res, str)
    assert len(res) <= 10

    all_zeros = format_waveform([0, 0, 0, 0], width=4)
    assert isinstance(all_zeros, str)

    all_neg = format_waveform([-5, -10, -20], width=3)
    assert isinstance(all_neg, str)


def test_open_external_media_nonexistent_file(tmp_path: Path):
    nonexistent = tmp_path / "does_not_exist.mp4"
    assert open_external_media(nonexistent) is None


def test_open_external_media_directory(tmp_path: Path):
    assert open_external_media(tmp_path) is None


def test_open_external_media_popen_failure(tmp_path: Path, monkeypatch):
    valid_file = tmp_path / "video.mp4"
    valid_file.write_bytes(b"data")

    monkeypatch.setattr("shutil.which", lambda cmd: "/usr/bin/" + cmd)

    def failing_popen(*args, **kwargs):
        raise OSError("Permission denied")

    monkeypatch.setattr(subprocess, "Popen", failing_popen)
    assert open_external_media(valid_file) is None


def test_render_photo_nonexistent_file(tmp_path: Path):
    nonexistent = tmp_path / "photo.png"
    assert render_photo(nonexistent) is None


def test_render_photo_subprocess_failure(tmp_path: Path, monkeypatch):
    photo = tmp_path / "img.png"
    photo.write_bytes(b"data")

    monkeypatch.setattr("shutil.which", lambda cmd: "/usr/bin/chafa")

    def failing_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="chafa", timeout=30)

    monkeypatch.setattr(subprocess, "run", failing_run)
    assert render_photo(photo) is None


# ============================================================================
# 4. ChatView & MessageWidget edge-case tests
# ============================================================================


def test_sender_style_none_and_negative():
    assert sender_style(None) == "bold white"
    assert sender_style(-100123456789) in [
        "bold cyan", "bold green", "bold yellow", "bold magenta",
        "bold blue", "bold red", "bold orange3", "bold violet",
    ]


def test_time_label_none():
    assert _time_label(None) == ""


def test_message_widget_compose_edge_cases():
    msg = Message(
        id=1,
        chat_id=10,
        sender_id=None,
        text="",
        timestamp=None,
        media_type="unknown_type",
        reactions=[("👍", 2), ("🔥", None), "invalid_item", (None, 5)],
    )
    widget = MessageWidget(msg, sender_name=None)
    items = list(widget.compose())
    assert len(items) > 0


def test_message_widget_huge_text_payload():
    huge_text = "Hello world!\n" * 1000 + "```python\nprint('code')\n```\n" + "Tail\n" * 500
    msg = Message(
        id=2,
        chat_id=10,
        sender_id=1,
        text=huge_text,
    )
    widget = MessageWidget(msg, sender_name="Tester")
    items = list(widget.compose())
    assert len(items) >= 3


@pytest.mark.asyncio
async def test_chat_view_empty_history():
    engine = MagicMock(spec=BaseBackend)
    chat = Chat(id=1, title="Empty Chat", chat_type=ChatType.PRIVATE)
    engine.chats = {1: chat}
    engine.sorted_chats = lambda q="": [chat]
    engine.history = lambda cid: []
    engine.sender_name = lambda sid: "User"
    engine.ensure_history = lambda cid: True
    engine.mark_read = lambda cid: None

    app = TelegramTUI(engine=engine, live_traffic=False)
    async with app.run_test() as pilot:
        view = app.query_one(ChatView)
        view.show_chat(chat)
        assert view.chat_id == 1
        assert view.selected_message() is None


def test_chat_view_update_hits_none_text():
    engine = MagicMock(spec=BaseBackend)
    view = ChatView(engine)
    msg = Message(id=1, chat_id=1, sender_id=1, text="")
    msg.text = None  # type: ignore
    widget = MessageWidget(msg, sender_name="Bob")
    view._widgets = lambda: [widget]
    view.update_hits("search")
    assert len(view.hits) == 0


@pytest.mark.asyncio
async def test_chat_view_load_older_history_backend_error():
    engine = MagicMock(spec=BaseBackend)
    engine.fetch_more_history = AsyncMock(side_effect=ConnectionError("Disconnected"))
    engine.chats = {1: Chat(id=1, title="Test", chat_type=ChatType.PRIVATE)}
    engine.sorted_chats = lambda q="": list(engine.chats.values())
    engine.history = lambda cid: [Message(id=100, chat_id=1, sender_id=1, text="Hello")]
    engine.sender_name = lambda sid: "User"
    engine.ensure_history = lambda cid: True
    engine.mark_read = lambda cid: None

    notified = []
    app = TelegramTUI(engine=engine, live_traffic=False)
    app.notify = lambda msg, *args, **kwargs: notified.append(msg)
    async with app.run_test() as pilot:
        view = app.query_one(ChatView)
        await view.action_load_older()
        assert any("Failed" in str(msg) for msg in notified)


# ============================================================================
# 5. TelethonBackend error resilience tests
# ============================================================================


@pytest.mark.asyncio
async def test_telethon_backend_start_connection_error(make_backend):
    backend = make_backend()
    backend._client.connect = AsyncMock(side_effect=ConnectionError("No internet connection"))
    # A dead network is the app's problem to report, not a reason to sign out.
    with pytest.raises(ConnectionError):
        await backend.start()


@pytest.mark.asyncio
async def test_telethon_backend_connection_error_keeps_session_file(make_backend):
    """Being offline must never cost the user their login."""
    backend = make_backend()
    session_file = Path(backend._session_path + ".session")
    session_file.write_text("existing-session", encoding="utf-8")

    backend._client.connect = AsyncMock(side_effect=ConnectionError("No internet connection"))
    with pytest.raises(ConnectionError):
        await backend.start()

    assert session_file.exists()
    assert session_file.read_text(encoding="utf-8") == "existing-session"


@pytest.mark.asyncio
async def test_telethon_backend_resets_session_on_rejected_auth_key(make_backend):
    """A key Telegram has revoked is worthless, so that one does get cleared."""
    from telethon import errors

    backend = make_backend()
    session_file = Path(backend._session_path + ".session")
    session_file.write_text("stale-session", encoding="utf-8")

    backend._client.connect = AsyncMock(side_effect=errors.AuthKeyUnregisteredError(None))
    assert await backend.start() is False
    # The client rebuilds an empty session file; what matters is the stale one is gone.
    assert not session_file.exists() or session_file.read_bytes() != b"stale-session"


class _FakeDialog:
    """Shaped like the telethon Dialog objects load() iterates over."""

    def __init__(self, dialog_id, name, *, is_channel=False, is_group=False,
                 participants=None, broadcast=False, pinned=False, unread=0):
        self.id = dialog_id
        self.name = name
        self.is_channel = is_channel
        self.is_group = is_group
        self.pinned = pinned
        self.unread_count = unread
        self.date = dt.datetime.now(dt.timezone.utc)
        self.entity = MagicMock()
        self.entity.participants_count = participants
        self.entity.admin_rights = None
        self.entity.creator = False
        self.entity.broadcast = broadcast


def _stub_client_for_load(backend, dialogs):
    me = MagicMock()
    me.id, me.first_name, me.last_name = 1, "Me", None
    backend._client.get_me = AsyncMock(return_value=me)
    backend._client.add_event_handler = MagicMock()

    async def iter_dialogs(limit=None):
        for dialog in dialogs:
            yield dialog

    async def iter_messages(*args, **kwargs):
        return
        yield  # pragma: no cover - makes this an async generator

    backend._client.iter_dialogs = iter_dialogs
    backend._client.iter_messages = iter_messages


@pytest.mark.asyncio
async def test_telethon_backend_load_maps_real_dialog_shapes(make_backend):
    """Telethon hands back int / None participant counts; load() must survive both."""
    backend = make_backend()
    _stub_client_for_load(
        backend,
        [
            _FakeDialog(-100, "Arch News", is_channel=True, participants=8302, broadcast=True),
            _FakeDialog(-200, "Dev Team", is_group=True, participants=12),
            _FakeDialog(555, "A Friend", participants=None),
        ],
    )

    await backend.load()

    assert set(backend.chats) == {-100, -200, 555}
    assert backend.chats[-100].members_count == "8,302 subscribers"
    assert backend.chats[-200].members_count == "12 members"
    assert backend.chats[555].members_count == ""
    assert backend.chats[-100].is_read_only is True
    assert backend.chats[-200].is_read_only is False


@pytest.mark.asyncio
async def test_telethon_backend_load_handles_single_member_and_zero(make_backend):
    backend = make_backend()
    _stub_client_for_load(
        backend,
        [
            _FakeDialog(-300, "Just Me", is_group=True, participants=1),
            _FakeDialog(-400, "Empty", is_group=True, participants=0),
        ],
    )

    await backend.load()

    assert backend.chats[-300].members_count == "1 member"
    assert backend.chats[-400].members_count == ""


@pytest.mark.asyncio
async def test_telethon_backend_load_get_me_none(make_backend):
    backend = make_backend()
    backend._client.get_me = AsyncMock(return_value=None)
    with pytest.raises(RuntimeError, match="get_me returned None"):
        await backend.load()


@pytest.mark.asyncio
async def test_telethon_backend_download_media_error(make_backend):
    backend = make_backend()
    msg = Message(id=10, chat_id=20, sender_id=1, has_photo=True, media_type="photo")
    fake_tm = MagicMock()
    fake_tm.photo = MagicMock()
    fake_tm.download_media = AsyncMock(side_effect=RuntimeError("RPC error during download"))
    backend._tmsg[(20, 10)] = fake_tm

    result = await backend.fetch_photo(msg)
    assert result is None


def test_telethon_display_name_fallback():
    assert _display_name(None) == "Unknown"
    dummy = MagicMock()
    dummy.first_name = None
    dummy.last_name = None
    dummy.title = None
    dummy.username = None
    assert _display_name(dummy) == "Unknown"


# ============================================================================
# 6. App UI lifecycle & error resilience tests
# ============================================================================


@pytest.mark.asyncio
async def test_app_open_chat_invalid_chat_id():
    app = TelegramTUI(engine=MagicMock(spec=BaseBackend), live_traffic=False)
    app.engine.chats = {}
    app.open_chat(999999)
    assert app.current_chat_id != 999999


@pytest.mark.asyncio
async def test_app_ingest_unknown_chat():
    app = TelegramTUI(engine=MagicMock(spec=BaseBackend), live_traffic=False)
    app.engine.chats = {}
    msg = Message(id=1, chat_id=8888, sender_id=1, text="Unknown chat msg")
    app._ingest(msg)


@pytest.mark.asyncio
async def test_app_modal_dismiss_back_to_list():
    app = TelegramTUI(live_traffic=False)
    async with app.run_test() as pilot:
        modal = ApiCredentialsScreen()
        app.push_screen(modal)
        await pilot.pause()
        assert len(app.screen_stack) > 1
        await pilot.press("escape")
        await pilot.pause()
        assert len(app.screen_stack) == 1


@pytest.mark.asyncio
async def test_app_message_sent_backend_exception():
    engine = MagicMock(spec=BaseBackend)
    engine.chats = {1: Chat(id=1, title="Test", chat_type=ChatType.PRIVATE)}
    engine.sorted_chats = lambda q="": list(engine.chats.values())
    engine.history = lambda cid: []
    engine.sender_name = lambda sid: "User"
    engine.ensure_history = lambda cid: True
    engine.mark_read = lambda cid: None
    engine.send = MagicMock(side_effect=RuntimeError("[420 FLOOD_WAIT_300]"))

    notified = []
    app = TelegramTUI(engine=engine, live_traffic=False)
    app.notify = lambda msg, *args, **kwargs: notified.append(msg)
    async with app.run_test() as pilot:
        event = MagicMock()
        event.text = "Attempting to send during flood wait"
        await app.message_sent(event)
        assert any("Failed" in str(msg) for msg in notified)


@pytest.mark.asyncio
async def test_app_play_voice_exceptions():
    engine = MagicMock(spec=BaseBackend)
    msg = Message(id=1, chat_id=1, sender_id=1, text="voice", has_voice=True, media_type="voice")
    engine.chats = {1: Chat(id=1, title="Test", chat_type=ChatType.PRIVATE)}
    engine.sorted_chats = lambda q="": list(engine.chats.values())
    engine.history = lambda cid: [msg]
    engine.sender_name = lambda sid: "User"
    engine.ensure_history = lambda cid: True
    engine.mark_read = lambda cid: None
    engine.fetch_voice = AsyncMock(side_effect=ConnectionError("Voice download failed"))

    notified = []
    app = TelegramTUI(engine=engine, live_traffic=False)
    app.notify = lambda msg, *args, **kwargs: notified.append(msg)
    async with app.run_test() as pilot:
        await pilot.pause()  # the initial selection settles on the next refresh
        await app.play_selected_voice()
        assert any("Failed" in str(m) for m in notified)


@pytest.mark.asyncio
async def test_app_open_media_photo_exceptions():
    engine = MagicMock(spec=BaseBackend)
    msg = Message(id=2, chat_id=1, sender_id=1, text="photo", has_photo=True, media_type="photo")
    engine.chats = {1: Chat(id=1, title="Test", chat_type=ChatType.PRIVATE)}
    engine.sorted_chats = lambda q="": list(engine.chats.values())
    engine.history = lambda cid: [msg]
    engine.sender_name = lambda sid: "User"
    engine.ensure_history = lambda cid: True
    engine.mark_read = lambda cid: None
    engine.fetch_photo = AsyncMock(side_effect=RuntimeError("Photo decrypt failed"))

    notified = []
    app = TelegramTUI(engine=engine, live_traffic=False)
    app.notify = lambda msg, *args, **kwargs: notified.append(msg)
    async with app.run_test() as pilot:
        await pilot.pause()  # the initial selection settles on the next refresh
        await app.open_selected_media()
        assert any("Failed" in str(m) for m in notified)


@pytest.mark.asyncio
async def test_telethon_backend_add_reaction_exception_handled(make_backend):
    backend = make_backend()
    backend._entities[1] = MagicMock()
    backend._client = MagicMock(side_effect=RuntimeError("Reaction RPC forbidden"))
    # Must not raise an unhandled exception
    await backend.add_reaction(1, 100, "🔥")


def _new_message_event(msg_id, *, chat_id=42, sender_id=7, out=False, text="Hello live"):
    event = MagicMock()
    event.chat_id = chat_id
    event.message = MagicMock()
    event.message.id = msg_id
    event.message.sender_id = sender_id
    event.message.message = text
    event.message.out = out
    event.message.date = dt.datetime.now(dt.timezone.utc)
    event.message.voice = None
    event.message.video_note = None
    event.message.sticker = None
    event.message.photo = None
    event.message.reactions = None
    event.message.reply_to = None
    return event


@pytest.mark.asyncio
async def test_telethon_backend_new_message_does_not_duplicate_sent_message(make_backend):
    """send() caches the message; the NewMessage echo must not add it again."""
    backend = make_backend()
    backend.chats[42] = Chat(id=42, title="Friend", chat_type=ChatType.PRIVATE)
    backend._entities[42] = MagicMock()

    sent_tm = _new_message_event(999, out=True, text="typed here").message
    backend._client.send_message = AsyncMock(return_value=sent_tm)
    await backend.send(42, "typed here")
    assert len(backend.messages[42]) == 1

    await backend._on_new_message(_new_message_event(999, out=True, text="typed here"))

    assert len(backend.messages[42]) == 1
    assert backend.chats[42].unread == 0


@pytest.mark.asyncio
async def test_telethon_backend_outgoing_from_other_device_is_kept_unread_free(make_backend):
    """A message typed on the phone has no local copy, so it belongs in the feed."""
    backend = make_backend()
    backend.chats[42] = Chat(id=42, title="Friend", chat_type=ChatType.PRIVATE)

    await backend._on_new_message(_new_message_event(1000, out=True, text="from phone"))

    assert [m.id for m in backend.messages[42]] == [1000]
    assert backend.chats[42].unread == 0  # our own message is not unread


@pytest.mark.asyncio
async def test_telethon_backend_incoming_message_increments_unread(make_backend):
    backend = make_backend()
    backend.chats[42] = Chat(id=42, title="Friend", chat_type=ChatType.PRIVATE)

    await backend._on_new_message(_new_message_event(1001, out=False))

    assert backend.chats[42].unread == 1


@pytest.mark.asyncio
async def test_telethon_backend_on_new_message_caches_in_history(make_backend):
    backend = make_backend()
    chat = Chat(id=42, title="Active Chat", chat_type=ChatType.PRIVATE)
    backend.chats[42] = chat

    event = MagicMock()
    event.chat_id = 42
    event.message = MagicMock()
    event.message.id = 999
    event.message.sender_id = 7
    event.message.message = "Hello live"
    event.message.date = dt.datetime.now(dt.timezone.utc)
    event.message.voice = None
    event.message.video_note = None
    event.message.sticker = None
    event.message.photo = None
    event.message.reactions = None
    event.message.reply_to = None

    await backend._on_new_message(event)

    assert 42 in backend.messages
    assert any(m.id == 999 for m in backend.messages[42])
    assert backend.history(42)[0].text == "Hello live"

