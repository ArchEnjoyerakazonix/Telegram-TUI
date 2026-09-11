"""Live Telegram backend on top of Telethon.

Telethon is an optional dependency: ``pip install telegram-tui[live]``.
The import is lazy so mock mode works without it installed.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import tempfile
from pathlib import Path

from .backend import BaseBackend
from .models import Chat, ChatType, Message, media_label, utcnow

DIALOG_LIMIT = 50
MESSAGES_PER_DIALOG = 30

#: How many raw Telethon messages to keep around for media downloads. They are
#: only needed to re-download attachments, so the oldest are dropped first
#: rather than letting a long-running session grow without bound.
TMSG_CACHE_LIMIT = 2000

_log = logging.getLogger(__name__)


def _resolve_session_path(session: str) -> str:
    """Anchor session file inside ~/.config/telegram-tui/ unless it's already
    an absolute path.  Returns the path *without* the .session suffix
    (Telethon appends it automatically)."""
    p = Path(session)
    if p.is_absolute():
        return session
    config_dir = Path.home() / ".config" / "telegram-tui"
    config_dir.mkdir(parents=True, exist_ok=True)
    return str(config_dir / p)


def _members_label(entity, chat_type: ChatType) -> str:
    """Chat subtitle text; Telethon reports a raw count, the model holds a label."""
    count = getattr(entity, "participants_count", None)
    if not isinstance(count, int) or isinstance(count, bool) or count <= 0:
        return ""
    noun = "subscriber" if chat_type is ChatType.CHANNEL else "member"
    return f"{count:,} {noun}" if count == 1 else f"{count:,} {noun}s"


def _preview(text: str) -> str:
    for line in (text or "").splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return "…"


class TelethonBackend(BaseBackend):
    """Bridges the BaseBackend interface to a real Telegram account."""

    def __init__(self, api_id: int, api_hash: str, session: str = "telegram-tui") -> None:
        try:
            from telethon import TelegramClient, errors
        except ImportError as exc:  # pragma: no cover - environment-specific
            raise RuntimeError(
                "To use live mode, install Telethon: pip install 'telegram-tui[live]'"
            ) from exc

        self._errors = errors
        self._api_id = api_id
        self._api_hash = api_hash
        self.PasswordNeededError = errors.SessionPasswordNeededError
        self._session_path = _resolve_session_path(session)
        self._client = TelegramClient(self._session_path, api_id, api_hash)
        self._tmsg: dict[tuple[int, int], object] = {}
        self._entities: dict[int, object] = {}
        self._media_dir = Path(tempfile.gettempdir()) / "telegram-tui-media"
        self._media_dir.mkdir(exist_ok=True)
        self._ready: dict[int, bool] = {}
        self._pin_overrides: dict[int, bool] = {}

        # Populated by load()
        self.chats: dict[int, Chat] = {}
        self.messages: dict[int, list[Message]] = {}
        self.users: dict[int, str] = {}

    # -- lifecycle -----------------------------------------------------------

    async def start(self) -> bool:
        """Connect and check authorization.

        Only Telegram itself rejecting the stored auth key justifies throwing
        the session away; a transient connection failure propagates so the app
        can report it, because deleting the session there would force a full
        re-login every time the network is down.
        """
        try:
            await self._client.connect()
            return await self._client.is_user_authorized()
        except (
            self._errors.AuthKeyUnregisteredError,
            self._errors.AuthKeyInvalidError,
        ):
            _log.warning("Session auth key rejected by Telegram — resetting session")
            await self._reset_session()
            return False

    async def _reset_session(self) -> None:
        """Delete a corrupt .session file and create a fresh client."""
        from telethon import TelegramClient

        try:
            await self._client.disconnect()
        except Exception:
            pass
        for suffix in (".session", ".session-journal"):
            p = Path(self._session_path + suffix)
            p.unlink(missing_ok=True)
        self._client = TelegramClient(self._session_path, self._api_id, self._api_hash)
        await self._client.connect()

    async def request_code(self, phone: str) -> None:
        await self._client.sign_in(phone=phone)

    async def submit_code(self, code: str) -> None:
        await self._client.sign_in(code=code)

    async def submit_password(self, password: str) -> None:
        await self._client.sign_in(password=password)

    async def load(self) -> None:
        from telethon import events

        me = await self._client.get_me()
        if me is None:
            raise RuntimeError("Failed to fetch user profile (get_me returned None)")
        self.users[me.id] = _display_name(me)
        self.me_id = me.id

        self._client.add_event_handler(self._on_new_message, events.NewMessage)

        async for dialog in self._client.iter_dialogs(limit=DIALOG_LIMIT):
            entity = dialog.entity
            self._entities[dialog.id] = entity
            if dialog.is_channel:
                chat_type = ChatType.CHANNEL
            elif dialog.is_group:
                chat_type = ChatType.GROUP
            else:
                chat_type = ChatType.PRIVATE

            is_admin = bool(getattr(entity, "admin_rights", None) or getattr(entity, "creator", False))
            is_read_only = bool(getattr(entity, "broadcast", False) and not is_admin)

            chat = Chat(
                id=dialog.id,
                title=dialog.name or _display_name(entity),
                chat_type=chat_type,
                pinned=bool(dialog.pinned),
                unread=dialog.unread_count or 0,
                last_activity=dialog.date or utcnow(),
                is_read_only=is_read_only,
                members_count=_members_label(entity, chat_type),
            )
            self.chats[chat.id] = chat
            self.messages[chat.id] = []
            self._load_history(chat.id, entity)

    def _load_history(self, chat_id: int, entity) -> None:
        """Fetch recent history in the background; UI renders what's cached."""

        async def job() -> None:
            try:
                mapped: list[Message] = []
                tmsgs = []
                async for tm in self._client.iter_messages(entity, limit=MESSAGES_PER_DIALOG):
                    tmsgs.append(tm)
                for tm in reversed(tmsgs):
                    mapped.append(await self._map_message(tm, chat_id))
                self.messages[chat_id] = mapped
                chat = self.chats.get(chat_id)
                if chat and mapped:
                    chat.preview = _preview(mapped[-1].text)
                    chat.last_activity = mapped[-1].timestamp
            except Exception:
                _log.warning("History fetch failed for chat %s", chat_id, exc_info=True)
            finally:
                # Mark ready and tell the UI either way, otherwise a feed that
                # is showing "Loading history…" would sit there forever.
                self._ready[chat_id] = True
                if self.on_history is not None:
                    self.on_history(chat_id)

        asyncio.get_running_loop().create_task(job())

    def ensure_history(self, chat_id: int) -> bool:
        if self._ready.get(chat_id) or self.messages.get(chat_id):
            return True
        entity = self._entities.get(chat_id)
        if entity is not None:
            self._load_history(chat_id, entity)
        return False

    # -- mapping -------------------------------------------------------------

    async def _map_message(self, tm, chat_id: int) -> Message:
        sender_id = tm.sender_id or 0
        if sender_id and sender_id not in self.users:
            try:
                sender = await tm.get_sender()
                self.users[sender_id] = _display_name(sender) if sender else str(sender_id)
            except Exception:
                self.users[sender_id] = str(sender_id)
        timestamp: dt.datetime = tm.date or utcnow()

        media_type = "text"
        sticker_emoji = None
        duration = None

        if getattr(tm, "voice", None):
            media_type = "voice"
            duration = getattr(tm.voice, "duration", None)
        elif getattr(tm, "video_note", None):
            media_type = "video_note"
            duration = getattr(tm.video_note, "duration", None)
        elif getattr(tm, "sticker", None):
            media_type = "sticker"
            attrs = getattr(tm.sticker, "attributes", [])
            for attr in attrs:
                alt = getattr(attr, "alt", None)
                if alt:
                    sticker_emoji = alt
                    break
        elif getattr(tm, "photo", None):
            media_type = "photo"

        # Reactions
        reactions: list[tuple[str, int]] = []
        tm_reactions = getattr(tm, "reactions", None)
        if tm_reactions and hasattr(tm_reactions, "results"):
            for r in tm_reactions.results:
                reaction_obj = getattr(r, "reaction", None)
                emoji = getattr(reaction_obj, "emoticon", None) or "👍"
                count = getattr(r, "count", 1)
                reactions.append((str(emoji), int(count)))

        fallback_text = tm.message or ""
        if not fallback_text and (media_type != "text" or getattr(tm, "media", None)):
            fallback_text = media_label(media_type, sticker_emoji)

        # Waveform for audio/voice
        waveform = None
        if getattr(tm, "voice", None) and hasattr(tm, "document") and tm.document:
            attrs = getattr(tm.document, "attributes", [])
            for attr in attrs:
                raw_wave = getattr(attr, "waveform", None)
                if raw_wave:
                    waveform = list(raw_wave)
                    break

        msg = Message(
            id=tm.id,
            chat_id=chat_id,
            sender_id=sender_id,
            text=fallback_text,
            timestamp=timestamp,
            reply_to=tm.reply_to_msg_id if tm.reply_to else None,
            has_voice=bool(media_type == "voice"),
            has_photo=bool(media_type == "photo"),
            media_type=media_type,
            duration=duration,
            sticker_emoji=sticker_emoji,
            reactions=reactions,
            waveform=waveform,
        )
        self._remember_raw(chat_id, tm)
        return msg

    def _remember_raw(self, chat_id: int, tm) -> None:
        """Cache the raw message for later media downloads, oldest evicted first."""
        key = (chat_id, tm.id)
        self._tmsg.pop(key, None)
        self._tmsg[key] = tm
        while len(self._tmsg) > TMSG_CACHE_LIMIT:
            self._tmsg.pop(next(iter(self._tmsg)))

    async def _on_new_message(self, event) -> None:
        """Handle a NewMessage update.

        The event fires for our own messages too, so anything ``send()`` has
        already cached must not be added a second time — but a message typed on
        another device has no local copy and does belong in the feed.
        """
        chat_id = event.chat_id
        if chat_id not in self.chats:
            return
        if any(m.id == event.message.id for m in self.messages.get(chat_id, [])):
            return
        msg = await self._map_message(event.message, chat_id)
        self.messages.setdefault(chat_id, []).append(msg)
        chat = self.chats[chat_id]
        chat.last_activity = msg.timestamp
        chat.preview = _preview(msg.text)
        if not getattr(event.message, "out", False):
            chat.unread += 1
        if self.on_incoming is not None:
            self.on_incoming(msg)

    # -- queries (cache-backed) ----------------------------------------------

    def sorted_chats(self, query: str = "") -> list[Chat]:
        q = query.strip().lower()
        chats = [c for c in self.chats.values() if q in c.title.lower()]
        for chat in chats:
            if chat.id in self._pin_overrides:
                chat.pinned = self._pin_overrides[chat.id]
        return sorted(chats, key=lambda c: (not c.pinned, -c.last_activity.timestamp()))

    def history(self, chat_id: int) -> list[Message]:
        return list(self.messages.get(chat_id, []))

    def get_message(self, chat_id: int, message_id: int) -> Message | None:
        for msg in self.messages.get(chat_id, []):
            if msg.id == message_id:
                return msg
        return None

    def sender_name(self, sender_id: int) -> str:
        return self.users.get(sender_id) or str(sender_id)

    def mark_read(self, chat_id: int) -> None:
        chat = self.chats.get(chat_id)
        if chat is not None:
            chat.unread = 0
        entity = self._entities.get(chat_id)

        async def job() -> None:
            try:
                await self._client.send_read_acknowledge(entity)
            except Exception:
                pass

        if entity is not None:
            asyncio.get_running_loop().create_task(job())

    def toggle_pin(self, chat_id: int) -> Chat:
        chat = self.chats[chat_id]
        current = self._pin_overrides.get(chat_id, chat.pinned)
        self._pin_overrides[chat_id] = not current
        chat.pinned = not current
        return chat

    # -- actions -------------------------------------------------------------

    async def send(self, chat_id: int, text: str, reply_to: int | None = None) -> Message:
        entity = self._entities[chat_id]
        tm = await self._client.send_message(entity, text, reply_to=reply_to)
        msg = await self._map_message(tm, chat_id)
        self.messages.setdefault(chat_id, []).append(msg)
        chat = self.chats[chat_id]
        chat.last_activity = msg.timestamp
        chat.preview = _preview(msg.text)
        return msg

    async def fetch_more_history(
        self, chat_id: int, offset_id: int = 0, limit: int = 20
    ) -> list[Message]:
        entity = self._entities.get(chat_id)
        if entity is None:
            return []
        try:
            tmsgs = []
            async for tm in self._client.iter_messages(entity, limit=limit, offset_id=offset_id):
                tmsgs.append(tm)
            mapped: list[Message] = []
            for tm in tmsgs:
                mapped.append(await self._map_message(tm, chat_id))
            existing_ids = {m.id for m in self.messages.get(chat_id, [])}
            new_msgs = [m for m in mapped if m.id not in existing_ids]
            if new_msgs:
                # Prepend older messages to the beginning of the list
                self.messages[chat_id] = list(reversed(new_msgs)) + self.messages.get(chat_id, [])
            return new_msgs
        except Exception:
            return []

    async def add_reaction(self, chat_id: int, message_id: int, emoji: str) -> None:
        entity = self._entities.get(chat_id)
        if entity is None:
            return
        try:
            from telethon.tl.functions.messages import SendReactionRequest
            from telethon.tl.types import ReactionEmoji

            await self._client(
                SendReactionRequest(
                    peer=entity,
                    msg_id=message_id,
                    reaction=[ReactionEmoji(emoticon=emoji)],
                )
            )
            # Update cached message reaction
            msg = self.get_message(chat_id, message_id)
            if msg:
                curr = dict(msg.reactions)
                curr[emoji] = curr.get(emoji, 0) + 1
                msg.reactions = list(curr.items())
        except Exception:
            pass

    # -- media ---------------------------------------------------------------

    async def _download(self, message: Message, attr: str) -> Path | None:
        tm = self._tmsg.get((message.chat_id, message.id))
        if tm is None or getattr(tm, attr, None) is None:
            return None
        try:
            result = await tm.download_media(file=str(self._media_dir))
            return Path(result) if result else None
        except Exception:
            return None

    async def fetch_voice(self, message: Message) -> Path | None:
        res = await self._download(message, "voice")
        if res is None:
            res = await self._download(message, "video_note")
        return res

    async def fetch_photo(self, message: Message) -> Path | None:
        return await self._download(message, "photo")


def _display_name(entity) -> str:
    first = getattr(entity, "first_name", None)
    last = getattr(entity, "last_name", None)
    title = getattr(entity, "title", None)
    username = getattr(entity, "username", None)
    name = " ".join(p for p in (first, last) if p)
    return name or title or (f"@{username}" if username else "Unknown")
