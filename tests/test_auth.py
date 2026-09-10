"""Tests for the in-terminal authorization flow (LoginScreen, mock live backend)."""

import time

import pytest

from telegram_tui.app import TelegramTUI
from telegram_tui.auth import LoginScreen
from telegram_tui.backend import BaseBackend
from telegram_tui.models import Chat, ChatType, Message
from telegram_tui.widgets.chat_list import ChatList


class FakeLiveBackend(BaseBackend):
    """Live-like backend: start() requires terminal login; records calls."""

    is_mock = False

    class PasswordNeeded(BaseException):  # backend-specific 2FA signal
        pass

    PasswordNeededError = PasswordNeeded

    def __init__(self, two_fa: bool = False) -> None:
        self.calls: list[tuple] = []
        self.two_fa = two_fa
        self.authorized = False
        self.loaded = False
        self._chat = Chat(id=1, title="Live Chat", chat_type=ChatType.PRIVATE)
        self.chats = {1: self._chat}
        self._history = [
            Message(id=1, chat_id=1, sender_id=2, text="привет из live"),
        ]

    async def start(self) -> bool:
        return False  # always needs login for the test

    async def request_code(self, phone: str) -> None:
        self.calls.append(("phone", phone))
        if phone != "89990001122":
            raise ValueError("номер не принят")

    async def submit_code(self, code: str) -> None:
        self.calls.append(("code", code))
        if code == "00000":
            raise ValueError("неверный код")
        if self.two_fa:
            raise self.PasswordNeededError()
        self.authorized = True

    async def submit_password(self, password: str) -> None:
        self.calls.append(("password", password))
        if password != "hunter2":
            raise ValueError("неверный пароль")
        self.authorized = True

    async def load(self) -> None:
        self.loaded = True

    def sorted_chats(self, query: str = ""):
        return [self._chat]

    def history(self, chat_id: int):
        return list(self._history)

    def get_message(self, chat_id: int, message_id: int):
        return next((m for m in self._history if m.id == message_id), None)

    def sender_name(self, sender_id: int) -> str:
        return {0: "You", 2: "Remote Peer"}.get(sender_id, "?")

    def mark_read(self, chat_id: int) -> None: ...

    def toggle_pin(self, chat_id: int) -> Chat:
        self._chat.pinned = not self._chat.pinned
        return self._chat

    def send(self, chat_id: int, text: str, reply_to=None):
        msg = Message(id=len(self._history) + 10, chat_id=chat_id, sender_id=0, text=text)
        self._history.append(msg)
        return msg


def make_app(backend: FakeLiveBackend):
    return TelegramTUI(engine=backend, live_traffic=False)


async def wait_until(pilot, cond, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return True
        await pilot.pause(0.05)
    return bool(cond())


@pytest.fixture
async def live_app():
    backend = FakeLiveBackend()
    app = make_app(backend)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        yield app, pilot, backend


async def test_login_screen_appears_for_live_backend(live_app):
    app, _pilot, _backend = live_app
    assert isinstance(app.screen, LoginScreen)
    assert len(app.query_one(ChatList).children) == 0


async def test_full_login_without_2fa(live_app):
    app, pilot, backend = live_app
    await pilot.press(*"89990001122")
    await pilot.press("enter")
    assert await wait_until(pilot, lambda: any(c[0] == "phone" for c in backend.calls))
    assert await wait_until(pilot, lambda: app.screen.step == "code")
    await pilot.press(*"12345")
    await pilot.press("enter")
    assert await wait_until(pilot, lambda: backend.loaded)
    assert await wait_until(pilot, lambda: app.current_chat_id == 1)
    assert len(app.query_one(ChatList).children) > 0, "чаты должны появиться после входа"
    assert backend.calls == [("phone", "89990001122"), ("code", "12345")]


async def test_login_with_2fa_password_step(live_app):
    app, pilot, backend = live_app
    backend.two_fa = True
    await pilot.press(*"89990001122")
    await pilot.press("enter")
    assert await wait_until(pilot, lambda: any(c[0] == "phone" for c in backend.calls))
    assert await wait_until(pilot, lambda: app.screen.step == "code")
    await pilot.press(*"12345")
    await pilot.press("enter")
    assert await wait_until(pilot, lambda: app.screen.step == "password")
    inp = app.screen.query_one("#auth-input")
    assert inp.password is True, "пароль должен вводиться скрыто"
    await pilot.press(*"hunter2")
    await pilot.press("enter")
    assert await wait_until(pilot, lambda: backend.loaded)
    assert await wait_until(pilot, lambda: app.current_chat_id == 1)
    assert ("password", "hunter2") in backend.calls


async def test_wrong_code_shows_error_and_allows_retry(live_app):
    app, pilot, backend = live_app
    await pilot.press(*"89990001122")
    await pilot.press("enter")
    assert await wait_until(pilot, lambda: any(c[0] == "phone" for c in backend.calls))
    assert await wait_until(pilot, lambda: app.screen.step == "code")
    await pilot.press(*"00000")
    await pilot.press("enter")
    assert await wait_until(
        pilot, lambda: "Error" in str(app.screen.query_one("#auth-error").content)
    )
    # Input is editable again and a good code completes the login.
    assert app.screen.query_one("#auth-input").disabled is False
    await pilot.press(*"12345")
    await pilot.press("enter")
    assert await wait_until(pilot, lambda: backend.loaded)


async def test_escape_cancels_login_and_exits(live_app):
    app, pilot, _backend = live_app
    assert isinstance(app.screen, LoginScreen)
    await pilot.press("escape")
    assert await wait_until(pilot, lambda: not app.is_running)


def test_backend_incoming_event():
    from datetime import datetime
    from telegram_tui.app import BackendIncoming
    from telegram_tui.models import Message as ModelMessage
    from textual.message import Message as TextualMessage

    msg = ModelMessage(
        id=999,
        chat_id=1,
        sender_id=42,
        text="Hello live",
        timestamp=datetime.now(),
    )
    event = BackendIncoming(msg)
    assert isinstance(event, TextualMessage)
    assert event.message.text == "Hello live"
