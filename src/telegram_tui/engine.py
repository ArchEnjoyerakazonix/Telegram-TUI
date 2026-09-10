"""Mock engine: a full simulation of account activity.

Generates chats (private / groups / channels), seeded history with code
blocks and replies, live incoming traffic on ``tick()`` and auto-replies
to messages sent by the user. No real Telegram connection required.
"""

from __future__ import annotations

import datetime as dt
import random
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

from .backend import BaseBackend
from .media import write_mock_photo, write_mock_voice
from .models import Chat, ChatType, Message, User, utcnow

TICK_INCOMING_PROBABILITY = 0.55
AUTO_REPLY_PROBABILITY = 0.8
AUTO_REPLY_DELAY_RANGE = (2.0, 5.0)

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
    "Кто-нибудь смотрел новый релиз Textual?",
    "Го созвон в 18:00?",
    "Скинь, пожалуйста, конфиг ещё раз 🙏",
    "У меня снова упал CI, смотрю логи.",
    "Кстати, SIGWINCH больше не теряется после апдейта ядра 👍",
    "Подтверждаю: после перезапуска всё работает.",
    "Кто последний трогал compositor.py?",
    "Нашёл классный канал про embedded Linux, кину позже.",
    "Тестирую клиент в tmux — рендер ровный, ресайз ловится.",
    "Плюсую, у меня то же самое на Arch.",
    "Не забудьте про миграцию схемы в пятницу.",
    "Отправил PR, ревью приветствуется.",
]


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
        chat.preview = _one_line(text or f"[{media_type}]")
        return msg

    def _snippet_msg(self, chat_id: int, sender_id: int, minutes_ago: int) -> Message:
        lang, code = self._rng.choice(CODE_SNIPPETS)
        return self._msg(chat_id, sender_id, f"```{lang}\n{code}\n```", minutes_ago)

    def _build_fixture(self) -> None:
        me = self._user("You")
        self.me = me

        devs = self._chat("Textual Devs", ChatType.GROUP, ["Alice", "Bob", "Kate"], pinned=True)
        devs.members_count = "12 members · 4 online"
        a = next(u.id for u in self.users.values() if u.name == "Alice")
        b = next(u.id for u in self.users.values() if u.name == "Bob")
        k = next(u.id for u in self.users.values() if u.name == "Kate")
        m1 = self._msg(devs.id, a, "Всем привет! Кто-нибудь пробовал новый compositor?", 240, reactions=[("🔥", 3), ("👀", 2)])
        self._msg(devs.id, b, "Да, лагов меньше стало. И ресайз наконец ровный.", 236, reply_to=m1.id, reactions=[("👍", 4)])
        self._snippet_msg(devs.id, a, 230)
        self._msg(devs.id, k, "Забираю в проект, спасибо!", 228, reactions=[("💚", 5)])
        devs.unread = 2
        devs.preview = "Забираю в проект, спасибо!"

        alice = self._chat("Alice", ChatType.PRIVATE, ["Alice"], pinned=True)
        alice.members_count = "online"
        self._msg(alice.id, a, "Ты сегодня на созвоне будешь?", 180)
        self._msg(alice.id, me.id, "Буду. Начинаем в 18:00?", 175)
        self._msg(alice.id, a, "Да, скинула приглашение в календарь 📅", 170)
        self._msg(alice.id, a, "Смотри, какой закат был вчера 🌇", 168, has_photo=True, media_type="photo", reactions=[("❤️", 3), ("✨", 2)])
        self._msg(alice.id, a, "", 165, media_type="sticker", sticker_emoji="✌️")
        self._msg(alice.id, me.id, "", 160, media_type="video_note", duration=10, reactions=[("🔥", 1)])

        pychat = self._chat("Python Chat", ChatType.GROUP, ["Dave", "Eve", "Frank"])
        pychat.members_count = "248 members · 32 online"
        d = next(u.id for u in self.users.values() if u.name == "Dave")
        e = next(u.id for u in self.users.values() if u.name == "Eve")
        f = next(u.id for u in self.users.values() if u.name == "Frank")
        self._msg(pychat.id, e, "dataclass vs pydantic — что берёте в 2026?", 300)
        self._msg(pychat.id, d, "pydantic v2, без вариантов. Быстрее в разы.", 295, reply_to=self.messages[pychat.id][-1].id, reactions=[("🚀", 4)])
        self._snippet_msg(pychat.id, f, 290)
        self._msg(pychat.id, e, "О, с model_validate даже проще, чем ждал.", 45)
        self._msg(pychat.id, f, "Кто-нибудь юзал Textual с pytest-pilot? Как тесты?", 30)
        self._msg(pychat.id, d, "Да, pilot.press работает отлично. Скинул пример ниже.", 12)
        self._snippet_msg(pychat.id, d, 11)
        pychat.unread = 5

        arch = self._chat("Arch Linux News", ChatType.CHANNEL, ["archbot"])
        arch.is_read_only = True
        arch.members_count = "8,302 subscribers"
        ab = self.members[arch.id][0]
        self._msg(arch.id, ab, "📢 Вышел linux 7.1.9: обновления драйверов и фиксы планировщика.", 600, reactions=[("🎉", 42), ("🔥", 18)])
        self._msg(arch.id, ab, "⚠️ Внимание: requires reinstall of virtualbox-modules before reboot.", 480)
        self._snippet_msg(arch.id, ab, 120)
        arch.unread = 12

        bob = self._chat("Bob", ChatType.PRIVATE, ["Bob"])
        bob.members_count = "last seen 15 min ago"
        bo = next(u.id for u in self.users.values() if u.name == "Bob")
        self._msg(bob.id, bo, "Слушай, а ты видел PR #42?", 95, has_voice=True, media_type="voice", duration=21, reactions=[("👍", 2)])
        bob.unread = 1

        work = self._chat("Work · Deploy Squad", ChatType.GROUP, ["PM Olga", "SRE Max"])
        self._msg(work.id, next(u.id for u in self.users.values() if u.name == "SRE Max"), "Deploy прошёл, error rate 0.01%.", 200)
        self._snippet_msg(work.id, next(u.id for u in self.users.values() if u.name == "PM Olga"), 190)

        mom = self._chat("Mom", ChatType.PRIVATE, ["Mom"])
        mo = next(u.id for u in self.users.values() if u.name == "Mom")
        self._msg(mom.id, mo, "Позвони, как сможешь ❤️", 700)

        docker = self._chat("Docker Club", ChatType.GROUP, ["Grace", "Linus"])
        self._snippet_msg(docker.id, next(u.id for u in self.users.values() if u.name == "Grace"), 400)
        self._msg(
            docker.id,
            next(u.id for u in self.users.values() if u.name == "Linus"),
            "Скриншот мониторинга после чистки docker system prune 📉",
            395,
            has_photo=True,
        )

        books = self._chat("Sci-Fi Books", ChatType.CHANNEL, ["bookbot"])
        self._msg(books.id, self.members[books.id][0], "Книга недели: «Ложная слепота» Питера Уоттса.", 900)

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

    async def start(self) -> bool:
        return True

    # -- media (generated offline so mpv/chafa work in mock mode) -------------

    async def fetch_voice(self, message: Message) -> Path | None:
        if not message.has_voice:
            return None
        path = self._media_dir / f"voice-{message.id}.wav"
        if not path.exists():
            write_mock_voice(path)
        return path

    async def fetch_photo(self, message: Message) -> Path | None:
        if not message.has_photo:
            return None
        path = self._media_dir / f"photo-{message.id}.png"
        if not path.exists():
            write_mock_photo(path)
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
                    "Ок, понял, отвечу чуть позже 👌",
                    "Ха, я как раз про это думал!",
                    "Принято. Добавил в таску.",
                    "Согласен, давай так и сделаем.",
                    "А можно подробнее? Что-то не воспроизвёл.",
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
        """Generate older historical messages preceding offset_id."""
        if chat_id not in self.messages or not self.messages[chat_id]:
            return []
        oldest = self.messages[chat_id][0]
        older_msgs: list[Message] = []
        texts = [
            "Ранее обсуждали архитектуру очередей сообщений и ресайз.",
            "Проверил производительность парсера: x3 прирост скорости.",
            "Подготовил PR с новыми контрастными стилями сайдбара.",
            "Отлично, интеграционные тесты прошли успешно.",
            "Двигаемся дальше по бэклогу релиза.",
        ]
        members = [uid for uid in self.members.get(chat_id, [])] or [self.me.id]
        for i in range(min(5, limit)):
            msg_id = oldest.id - 100 + i
            dt_past = oldest.timestamp - dt.timedelta(minutes=60 - i * 10)
            sender_id = members[i % len(members)]
            m = Message(
                id=msg_id,
                chat_id=chat_id,
                sender_id=sender_id,
                text=texts[i % len(texts)],
                timestamp=dt_past,
            )
            older_msgs.append(m)
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
