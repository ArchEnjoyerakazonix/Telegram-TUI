"""Mock engine: a full simulation of account activity.

Generates chats (private / groups / channels), seeded history with code
blocks and replies, live incoming traffic on ``tick()`` and auto-replies
to messages sent by the user. No real Telegram connection required.
"""

from __future__ import annotations

import datetime as dt
import mimetypes
import random
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

from .backend import BaseBackend
from .media import write_mock_photo, write_mock_voice
from .models import Chat, ChatType, Message, User, media_label, utcnow

TICK_INCOMING_PROBABILITY = 0.55
AUTO_REPLY_PROBABILITY = 0.8
AUTO_REPLY_DELAY_RANGE = (2.0, 5.0)

#: Older messages each mock chat can still produce before the history ends.
BACKLOG_PER_CHAT = 60

CODE_SNIPPETS = [
    (
        "python",
        "def fib(n: int) -> int:\n    a, b = 0, 1\n    for _ in range(n):\n        a, b = b, a + b\n    return a\n\nprint(fib(10))  # 55",
    ),
    (
        "python",
        "from textual.app import App, ComposeResult\nfrom textual.widgets import Header, Footer\n\nclass T(App):\n    def compose(self) -> ComposeResult:\n        yield Header()\n        yield Footer()",
    ),
    (
        "bash",
        "sudo pacman -Syu --noconfirm\nsystemctl --user restart tg-tui.service\njournalctl --user -u tg-tui -f",
    ),
    (
        "json",
        '{\n  "status": "ok",\n  "job": "nightly-build",\n  "duration_sec": 412,\n  "artifacts": ["app.tar.gz"]\n}',
    ),
    (
        "sql",
        "SELECT chat_id, count(*) AS unread\nFROM messages\nWHERE is_read = false\nGROUP BY chat_id\nORDER BY unread DESC\nLIMIT 5;",
    ),
]

INCOMING_TEXTS = [
    "Has anyone checked out the latest Textual release?",
    "Quick sync at 18:00?",
    "Could you share your config once again please? 🙏",
    "CI failed again, inspecting logs...",
    "By the way, SIGWINCH is no longer lost after the kernel update 👍",
    "Confirmed: everything works smoothly after restart.",
    "Who touched compositor.py last?",
    "Found a great channel about embedded Linux, will share later.",
    "Testing client in tmux — clean render and smooth resize.",
    "Same here on Arch Linux, works great.",
    "Don't forget the schema migration this Friday.",
    "Submitted the PR, reviews are welcome.",
]


#: Extension groups used to guess what an uploaded file should be sent as.
_EXT_MEDIA = {
    "photo": {".png", ".jpg", ".jpeg", ".webp", ".bmp"},
    "gif": {".gif"},
    "video": {".mp4", ".mkv", ".webm", ".mov", ".avi"},
    "audio": {".mp3", ".flac", ".ogg", ".m4a", ".wav"},
}


def _guess_media_type(path: Path) -> str:
    """What Telegram would turn this file into if not forced to a document."""
    suffix = path.suffix.lower()
    for media_type, extensions in _EXT_MEDIA.items():
        if suffix in extensions:
            return media_type
    return "document"


def _one_line(text: str) -> str:
    """First meaningful line of a message, for the chat list preview."""
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("```"):
            lang = stripped[3:].strip() or "code"
            return f"⌨ {lang}"
        return stripped
    return "…"


class PlannedReply(NamedTuple):
    """An auto-reply the engine has decided will happen after ``delay`` seconds."""

    delay: float
    factory: Callable[[], Message]


class MockEngine(BaseBackend):
    """In-memory simulation of the Telegram account the client is bound to."""

    is_mock = True

    def __init__(self, seed: int | None = None) -> None:
        self._rng = random.Random(seed)
        self.users: dict[int, User] = {}
        self.members: dict[int, list[int]] = {}
        self.chats: dict[int, Chat] = {}
        self.messages: dict[int, list[Message]] = {}
        self._next_id = 1
        self._media_dir = Path(tempfile.gettempdir()) / "telegram-tui-media"
        self._media_dir.mkdir(exist_ok=True)
        #: How much older history each chat still has left to hand out.
        self._backlog: dict[int, int] = {}
        self._build_fixture()

    # -- id helpers ---------------------------------------------------------

    def _id(self) -> int:
        self._next_id += 1
        return self._next_id - 1

    # -- fixture ------------------------------------------------------------

    def _user(self, name: str) -> User:
        uid = self._id()
        self.users[uid] = User(id=uid, name=name)
        return self.users[uid]

    def _chat(
        self,
        title: str,
        chat_type: ChatType,
        member_names: list[str],
        pinned: bool = False,
    ) -> Chat:
        users = [self._user(n) for n in member_names]
        chat = Chat(id=self._id(), title=title, chat_type=chat_type, pinned=pinned)
        self.chats[chat.id] = chat
        self.members[chat.id] = [u.id for u in users]
        self.messages[chat.id] = []
        return chat

    def _msg(
        self,
        chat_id: int,
        sender_id: int,
        text: str = "",
        minutes_ago: int = 0,
        reply_to: int | None = None,
        has_voice: bool = False,
        has_photo: bool = False,
        media_type: str = "text",
        duration: int | None = None,
        sticker_emoji: str | None = None,
        reactions: list[tuple[str, int]] | None = None,
        waveform: list[int] | None = None,
    ) -> Message:
        if (has_voice or media_type == "voice") and waveform is None:
            import math

            waveform = [int(12 + 10 * math.sin(i * 0.6) + 4 * math.cos(i * 1.5)) for i in range(20)]

        msg = Message(
            id=self._id(),
            chat_id=chat_id,
            sender_id=sender_id,
            text=text,
            timestamp=utcnow() - dt.timedelta(minutes=minutes_ago),
            reply_to=reply_to,
            has_voice=has_voice,
            has_photo=has_photo,
            media_type=media_type,
            duration=duration,
            sticker_emoji=sticker_emoji,
            reactions=reactions or [],
            waveform=waveform,
        )
        self.messages[chat_id].append(msg)
        chat = self.chats[chat_id]
        chat.last_activity = msg.timestamp
        chat.preview = _one_line(text or media_label(media_type, sticker_emoji))
        return msg

    def _snippet_msg(self, chat_id: int, sender_id: int, minutes_ago: int) -> Message:
        lang, code = self._rng.choice(CODE_SNIPPETS)
        return self._msg(chat_id, sender_id, f"```{lang}\n{code}\n```", minutes_ago)

    def _build_fixture(self) -> None:
        me = self._user("You")
        self.me = me
        self.me_id = me.id

        devs = self._chat("Textual Devs", ChatType.GROUP, ["Alice", "Bob", "Kate"], pinned=True)
        devs.members_count = "12 members · 4 online"
        a = next(u.id for u in self.users.values() if u.name == "Alice")
        b = next(u.id for u in self.users.values() if u.name == "Bob")
        k = next(u.id for u in self.users.values() if u.name == "Kate")
        m1 = self._msg(devs.id, a, "Hey everyone! Has anyone tried the new compositor?", 240, reactions=[("🔥", 3), ("👀", 2)])
        self._msg(devs.id, b, "Yes, noticeably smoother and resize is pixel-perfect now.", 236, reply_to=m1.id, reactions=[("👍", 4)])
        self._snippet_msg(devs.id, a, 230)
        self._msg(devs.id, k, "Pulling it into the project, thanks!", 228, reactions=[("💚", 5)])
        devs.unread = 2
        devs.preview = "Pulling it into the project, thanks!"

        alice = self._chat("Alice", ChatType.PRIVATE, ["Alice"], pinned=True)
        alice.members_count = "online"
        self._msg(alice.id, a, "Will you be on the sync call today?", 180)
        self._msg(alice.id, me.id, "Yes. Starting at 18:00?", 175)
        self._msg(alice.id, a, "Yes, sent a calendar invite 📅", 170)
        self._msg(alice.id, a, "Check out yesterday's sunset 🌇", 168, has_photo=True, media_type="photo", reactions=[("❤️", 3), ("✨", 2)])
        self._msg(alice.id, a, "", 165, media_type="sticker", sticker_emoji="✌️")
        self._msg(alice.id, me.id, "", 160, media_type="video_note", duration=10, reactions=[("🔥", 1)])

        pychat = self._chat("Python Chat", ChatType.GROUP, ["Dave", "Eve", "Frank"])
        pychat.members_count = "248 members · 32 online"
        d = next(u.id for u in self.users.values() if u.name == "Dave")
        e = next(u.id for u in self.users.values() if u.name == "Eve")
        f = next(u.id for u in self.users.values() if u.name == "Frank")
        self._msg(pychat.id, e, "dataclass vs pydantic — what are you using in 2026?", 300)
        self._msg(pychat.id, d, "pydantic v2 hands down. Order of magnitude faster.", 295, reply_to=self.messages[pychat.id][-1].id, reactions=[("🚀", 4)])
        self._snippet_msg(pychat.id, f, 290)
        self._msg(pychat.id, e, "model_validate makes parsing so much cleaner.", 45)
        self._msg(pychat.id, f, "Anyone testing Textual with pytest-pilot?", 30)
        self._msg(pychat.id, d, "Yes, pilot.press works great. Posted a snippet below.", 12)
        self._snippet_msg(pychat.id, d, 11)
        pychat.unread = 5

        arch = self._chat("Arch Linux News", ChatType.CHANNEL, ["archbot"])
        arch.is_read_only = True
        arch.members_count = "8,302 subscribers"
        ab = self.members[arch.id][0]
        self._msg(arch.id, ab, "📢 Linux 7.1.9 released: updated drivers and scheduler patches.", 600, reactions=[("🎉", 42), ("🔥", 18)])
        self._msg(arch.id, ab, "⚠️ Notice: requires reinstall of virtualbox-modules before reboot.", 480)
        self._snippet_msg(arch.id, ab, 120)
        arch.unread = 12

        bob = self._chat("Bob", ChatType.PRIVATE, ["Bob"])
        bob.members_count = "last seen 15 min ago"
        bo = next(u.id for u in self.users.values() if u.name == "Bob")
        self._msg(bob.id, bo, "Hey, have you seen PR #42?", 95, has_voice=True, media_type="voice", duration=21, reactions=[("👍", 2)])
        bob.unread = 1

        work = self._chat("Work · Deploy Squad", ChatType.GROUP, ["PM Olga", "SRE Max"])
        self._msg(work.id, next(u.id for u in self.users.values() if u.name == "SRE Max"), "Deployment succeeded, error rate 0.01%.", 200)
        self._snippet_msg(work.id, next(u.id for u in self.users.values() if u.name == "PM Olga"), 190)

        mom = self._chat("Mom", ChatType.PRIVATE, ["Mom"])
        mo = next(u.id for u in self.users.values() if u.name == "Mom")
        self._msg(mom.id, mo, "Call me whenever you can ❤️", 700)

        docker = self._chat("Docker Club", ChatType.GROUP, ["Grace", "Linus"])
        self._snippet_msg(docker.id, next(u.id for u in self.users.values() if u.name == "Grace"), 400)
        self._msg(
            docker.id,
            next(u.id for u in self.users.values() if u.name == "Linus"),
            "System monitoring graph after docker system prune 📉",
            395,
            has_photo=True,
        )

        books = self._chat("Sci-Fi Books", ChatType.CHANNEL, ["bookbot"])
        self._msg(books.id, self.members[books.id][0], "Book of the week: 'Blindsight' by Peter Watts.", 900)

        cibot = self._chat("CI Bot", ChatType.PRIVATE, ["cibot"])
        self._snippet_msg(cibot.id, self.members[cibot.id][0], 60)

    # -- queries ------------------------------------------------------------

    def sorted_chats(self, query: str = "") -> list[Chat]:
        """Pinned chats first, then by recent activity; filtered by substring."""
        q = query.strip().lower()
        chats = [c for c in self.chats.values() if q in c.title.lower()]
        return sorted(chats, key=lambda c: (not c.pinned, -c.last_activity.timestamp()))

    def history(self, chat_id: int) -> list[Message]:
        return list(self.messages.get(chat_id, []))

    def get_message(self, chat_id: int, message_id: int) -> Message | None:
        for msg in self.messages.get(chat_id, []):
            if msg.id == message_id:
                return msg
        return None

    def sender_name(self, sender_id: int) -> str:
        if sender_id in self.users:
            return self.users[sender_id].name
        if sender_id in self.chats:
            return self.chats[sender_id].title
        return str(sender_id)

    # -- actions ------------------------------------------------------------

    def mark_read(self, chat_id: int) -> None:
        self.chats[chat_id].unread = 0

    def toggle_pin(self, chat_id: int) -> Chat:
        chat = self.chats[chat_id]
        chat.pinned = not chat.pinned
        return chat

    def send(self, chat_id: int, text: str, reply_to: int | None = None) -> Message:
        msg = self._msg(chat_id, self.me.id, text, reply_to=reply_to)
        return msg

    def send_file(
        self,
        chat_id: int,
        path: Path,
        caption: str = "",
        force_document: bool = False,
        reply_to: int | None = None,
        progress=None,
    ) -> Message:
        """Offline equivalent: record the upload as a message with real metadata."""
        path = Path(path)
        size = path.stat().st_size if path.exists() else None
        media_type = "document" if force_document else _guess_media_type(path)
        msg = self._msg(
            chat_id,
            self.me.id,
            caption,
            reply_to=reply_to,
            media_type=media_type,
            has_photo=media_type == "photo",
            has_voice=media_type in ("voice", "audio"),
        )
        msg.file_name = path.name
        msg.file_size = size
        msg.mime_type = mimetypes.guess_type(path.name)[0]
        chat = self.chats[chat_id]
        chat.preview = _one_line(caption) if caption else msg.media_summary()
        if progress is not None and size:
            progress(size, size)
        return msg

    async def start(self) -> bool:
        return True

    # -- media (generated offline so mpv/chafa work in mock mode) -------------

    async def fetch_file(self, message: Message, progress=None) -> Path | None:
        """Offline stand-in so every attachment can actually be opened.

        Audio-ish media gets a real playable wav, documents a text file under
        their own name, and anything visual a generated image.
        """
        if message.media_type in ("voice", "video_note", "audio"):
            path = await self.fetch_voice(message)
        elif message.media_type == "photo":
            path = await self.fetch_photo(message)
        elif message.media_type == "document":
            name = Path(message.file_name or f"file-{message.id}.txt").name
            path = self._media_dir / f"{message.id}-{name}"
            if not path.exists():
                path.write_text(f"Mock attachment for message {message.id}\n")
        else:
            path = self._media_dir / f"file-{message.id}.png"
            if not path.exists():
                write_mock_photo(path)
        if path is not None and progress is not None:
            size = path.stat().st_size
            progress(size, size)
        return path

    async def fetch_voice(self, message: Message) -> Path | None:
        if not message.has_voice and message.media_type not in ("voice", "video_note", "audio"):
            return None
        path = self._media_dir / f"voice-{message.id}.wav"
        if not path.exists():
            write_mock_voice(path)
        return path

    async def fetch_photo(self, message: Message) -> Path | None:
        if not message.has_photo and message.media_type != "photo":
            return None
        path = self._media_dir / f"photo-{message.id}.png"
        if not path.exists():
            write_mock_photo(path)
        return path

    async def fetch_thumbnail(self, message: Message) -> Path | None:
        if message.media_type not in ("video", "gif", "video_note"):
            return None
        path = self._media_dir / f"thumb-{message.id}.png"
        if not path.exists():
            write_mock_photo(path, 320, 180)
        return path

    def plan_auto_reply(self, chat_id: int) -> PlannedReply | None:
        """Decide whether an interlocutor will reply to the user's last message."""
        history = self.messages.get(chat_id, [])
        if not history or history[-1].sender_id != self.me.id:
            return None
        if self._rng.random() > AUTO_REPLY_PROBABILITY:
            return None
        members = [uid for uid in self.members.get(chat_id, []) if uid != self.me.id]
        if not members:
            return None
        sender_id = self._rng.choice(members)
        delay = self._rng.uniform(*AUTO_REPLY_DELAY_RANGE)

        def factory() -> Message:
            text = self._rng.choice(
                [
                    "Got it, will reply shortly 👌",
                    "Ha, I was just thinking about that!",
                    "Acknowledged. Added to the backlog.",
                    "Agreed, let's go with that approach.",
                    "Could you elaborate a bit? Couldn't reproduce.",
                ]
            )
            return self._incoming(chat_id, sender_id, text, deliver=False)

        return PlannedReply(delay=delay, factory=factory)

    # -- live traffic ---------------------------------------------------------

    def _incoming(
        self, chat_id: int, sender_id: int, text: str, deliver: bool = True
    ) -> Message:
        if self._rng.random() < 0.15:
            lang, code = self._rng.choice(CODE_SNIPPETS)
            text = f"```{lang}\n{code}\n```"
        msg = Message(
            id=self._id(),
            chat_id=chat_id,
            sender_id=sender_id,
            text=text,
            timestamp=utcnow(),
            reply_to=None,
        )
        self.messages[chat_id].append(msg)
        chat = self.chats[chat_id]
        chat.last_activity = msg.timestamp
        chat.preview = _one_line(text)
        if deliver:
            chat.unread += 1
        return msg

    def tick(self) -> list[Message]:
        """Simulate a round of live activity; returns newly created messages."""
        produced: list[Message] = []
        if self._rng.random() > TICK_INCOMING_PROBABILITY:
            return produced
        chat_id = self._rng.choice(list(self.chats))
        members = [uid for uid in self.members.get(chat_id, []) if uid != self.me.id]
        if not members:
            return produced
        sender_id = self._rng.choice(members)
        text = self._rng.choice(INCOMING_TEXTS)
        produced.append(self._incoming(chat_id, sender_id, text))
        return produced

    def inject_incoming(self, chat_id: int | None = None) -> Message:
        """Immediately inject one incoming message (demo button / tests)."""
        if chat_id is None:
            chat_id = self._rng.choice(list(self.chats))
        members = [uid for uid in self.members.get(chat_id, []) if uid != self.me.id]
        sender_id = self._rng.choice(members)
        return self._incoming(chat_id, sender_id, self._rng.choice(INCOMING_TEXTS))

    async def fetch_more_history(self, chat_id: int, offset_id: int, limit: int = 30) -> list[Message]:
        """Older messages preceding offset_id, from a finite backlog.

        The backlog runs out, the way a real conversation does, so reaching the
        beginning is something the client can actually be shown doing.
        """
        if chat_id not in self.messages or not self.messages[chat_id]:
            return []
        remaining = self._backlog.get(chat_id, BACKLOG_PER_CHAT)
        if remaining <= 0:
            return []

        oldest = self.messages[chat_id][0]
        texts = [
            "Earlier we discussed the message queue architecture and terminal resize.",
            "Benchmarked parser throughput: 3x speed improvement.",
            "Prepared a PR with high-contrast sidebar theme adjustments.",
            "Integration test suite passed smoothly.",
            "Continuing with the release roadmap items.",
        ]
        members = [uid for uid in self.members.get(chat_id, [])] or [self.me.id]
        count = max(1, min(limit, remaining))
        older_msgs: list[Message] = []
        for i in range(count):
            # Ids and timestamps descend away from the oldest message we have.
            step = count - i
            older_msgs.append(
                Message(
                    id=oldest.id - step,
                    chat_id=chat_id,
                    sender_id=members[i % len(members)],
                    text=texts[i % len(texts)],
                    timestamp=oldest.timestamp - dt.timedelta(minutes=step),
                )
            )
        self._backlog[chat_id] = remaining - count
        self.messages[chat_id] = older_msgs + self.messages[chat_id]
        return older_msgs

    async def add_reaction(self, chat_id: int, message_id: int, emoji: str) -> None:
        msg = self.get_message(chat_id, message_id)
        if not msg:
            return
        new_reactions: list[tuple[str, int]] = []
        found = False
        for e, count in msg.reactions:
            if e == emoji:
                new_reactions.append((e, count + 1))
                found = True
            else:
                new_reactions.append((e, count))
        if not found:
            new_reactions.append((emoji, 1))
        msg.reactions = new_reactions
