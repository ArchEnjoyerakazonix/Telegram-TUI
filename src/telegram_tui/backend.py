"""Backend abstraction: the UI talks to this interface only.

Two implementations exist:
  * MockEngine (engine.py)  — offline simulation, default;
  * TelethonBackend (telethon_backend.py) — real Telegram account.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from pathlib import Path

from .models import Chat, Message


class BaseBackend(ABC):
    """Contract used by the TUI. Sync query methods read from a local cache
    filled by ``start()``/``load()``; ``send`` and media fetching are async."""

    is_mock: bool = False

    #: Set by the app; called with each new incoming Message.
    on_incoming: Callable[[Message], None] | None = None

    #: Raised by ``submit_code`` when the account has 2FA enabled.
    PasswordNeededError = Exception

    # -- lifecycle -----------------------------------------------------------

    @abstractmethod
    async def start(self) -> bool:
        """Connect; return True if already authorized."""

    async def load(self) -> None:
        """Fetch chats and recent history after successful authorization."""

    def ensure_history(self, chat_id: int) -> bool:
        """Make sure ``history()`` is ready; False means 'still loading'."""
        return True

    # -- queries (sync, cache-backed) ----------------------------------------

    @abstractmethod
    def sorted_chats(self, query: str = "") -> list[Chat]: ...

    @abstractmethod
    def history(self, chat_id: int) -> list[Message]: ...

    @abstractmethod
    def get_message(self, chat_id: int, message_id: int) -> Message | None: ...

    @abstractmethod
    def sender_name(self, sender_id: int) -> str: ...

    @abstractmethod
    def mark_read(self, chat_id: int) -> None: ...

    @abstractmethod
    def toggle_pin(self, chat_id: int) -> Chat: ...

    # -- actions -------------------------------------------------------------

    @abstractmethod
    def send(self, chat_id: int, text: str, reply_to: int | None = None):
        """Send a message; returns Message (mock: sync, live: coroutine)."""

    # -- media ---------------------------------------------------------------

    async def fetch_voice(self, message: Message) -> Path | None:
        return None

    async def fetch_photo(self, message: Message) -> Path | None:
        return None
