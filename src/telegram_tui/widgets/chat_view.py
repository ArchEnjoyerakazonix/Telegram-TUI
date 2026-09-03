"""Center panel: scrollable message history with code highlighting and replies.

Vim-style navigation: j/k moves the selection, G/g g jump to the end/start,
'r' replies to the selected message, 'v' plays its voice, '/' searches.
"""

from __future__ import annotations

import datetime as dt
import re

from rich.markup import escape
from rich.syntax import Syntax as RichSyntax
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.widgets import Static

from ..models import Chat, Message
from .photo import PhotoWidget

_FENCE_RE = re.compile(r"```(\w*)\n(.*?)```", re.DOTALL)

_SENDER_STYLES = [
    "bold cyan",
    "bold green",
    "bold yellow",
    "bold magenta",
    "bold blue",
    "bold red",
    "bold orange3",
    "bold violet",
]


def sender_style(sender_id: int) -> str:
    return _SENDER_STYLES[sender_id % len(_SENDER_STYLES)]


def _time_label(ts: dt.datetime) -> str:
    return ts.astimezone().strftime("%H:%M")


class CodeBlock(Static):
    """Code snippet with syntax highlighting (rich/pygments), re-wrapped on resize."""

    DEFAULT_CSS = """
    CodeBlock {
        width: 1fr;
        background: $panel;
        border: round $secondary 20%;
        padding: 0 1;
        margin: 0 0 0 0;
    }
    """

    def __init__(self, code: str, lang: str) -> None:
        super().__init__(markup=False, expand=True)
        self._code = code
        self._lang = lang

    def render(self) -> RichSyntax:
        return RichSyntax(
            self._code,
            lexer=self._lang or "text",
            theme="monokai",
            word_wrap=True,
            padding=(0, 0),
        )


class MessageWidget(Vertical):
    """A single message: header, optional reply quote, text, code, media."""

    DEFAULT_CSS = """
    MessageWidget { height: auto; margin: 0 1 1 0; }
    MessageWidget.-selected { background: $boost; }
    MessageWidget.-selected Static.msg-header { text-style: bold; }
    MessageWidget.-hit { background: $warning 15%; }
    MessageWidget.-miss { opacity: 0.35; }
    MessageWidget .msg-reply {
        border-left: thick $accent;
        padding-left: 1;
        text-style: italic;
    }
    MessageWidget .msg-voice { color: $warning; text-style: italic; }
    MessageWidget CodeBlock { margin: 0; }
    """

    def __init__(
        self,
        message: Message,
        sender_name: str,
        reply_to: Message | None = None,
        reply_to_name: str | None = None,
    ) -> None:
        super().__init__(classes="message")
        self.message = message
        self._sender_name = sender_name
        self._reply_to = reply_to
        self._reply_to_name = reply_to_name or ""

    def compose(self) -> ComposeResult:
        yield Static(
            f"[{sender_style(self.message.sender_id)}]"
            f"{escape(self._sender_name)}[/] [dim]{_time_label(self.message.timestamp)}[/]",
            classes="msg-header",
        )

        if self._reply_to is not None:
            first = self._reply_to.text.splitlines()[0] if self._reply_to.text else "…"
            if len(first) > 60:
                first = first[:57] + "…"
            quote = Text()
            quote.append("↱ ", style="dim")
            quote.append(self._reply_to_name, style=sender_style(self._reply_to.sender_id))
            quote.append(f": {first}", style="dim")
            yield Static(quote, classes="msg-reply", markup=False)

        if self.message.has_voice:
            yield Static("🎙 голосовое сообщение — нажмите v, чтобы прослушать",
                         classes="msg-voice", markup=False)

        for part in self._split_text(self.message.text):
            if part["kind"] == "code":
                yield CodeBlock(part["text"].rstrip("\n"), part["lang"])
            else:
                yield Static(Text(part["text"]), markup=False)

        if self.message.has_photo:
            yield PhotoWidget(self.message, self.app.engine)

    def set_selected(self, selected: bool) -> None:
        self.set_class(selected, "-selected")

    @staticmethod
    def _split_text(text: str) -> list[dict]:
        parts: list[dict] = []
        pos = 0
        for match in _FENCE_RE.finditer(text):
            before = text[pos : match.start()]
            if before.strip():
                parts.append({"kind": "text", "text": before})
            parts.append({"kind": "code", "lang": match.group(1), "text": match.group(2)})
            pos = match.end()
        tail = text[pos:]
        if tail.strip():
            parts.append({"kind": "text", "text": tail})
        return parts


class ChatView(VerticalScroll):
    """Scrollable history of the currently open chat, with vim navigation."""

    can_focus = True

    BINDINGS = [
        Binding("j", "sel_next", "↓ msg", show=False),
        Binding("k", "sel_prev", "↑ msg", show=False),
        Binding("G", "sel_last", "Last", show=False),
        Binding("g,g", "sel_first", "First", show=False),
        Binding("r", "app_reply", "Reply"),
        Binding("v", "app_voice", "Play voice"),
        Binding("/", "app_find", "Find in chat"),
        Binding("n", "next_hit", show=False),
        Binding("N", "prev_hit", show=False),
    ]

    DEFAULT_CSS = """
    ChatView { height: 1fr; padding: 0 1; }
    """

    def __init__(self, engine) -> None:  # noqa: ANN001 - avoids circular import
        super().__init__(id="messages")
        self.engine = engine
        self.chat_id: int | None = None
        self._selected: int = -1
        self.hits: list[MessageWidget] = []
        self.hit_index: int = -1

    # -- content ---------------------------------------------------------------

    def show_chat(self, chat: Chat) -> None:
        self.chat_id = chat.id
        self.remove_children()
        self.hits = []
        self.hit_index = -1
        for message in self.engine.history(chat.id):
            self.mount(self._make_message_widget(message))
        self.scroll_end(animate=False, force=True)
        self.select(len(self._widgets()) - 1)

    def append_message(self, message: Message, scroll: bool = True) -> MessageWidget:
        was_last_selected = self._selected >= len(self._widgets()) - 1
        widget = self._make_message_widget(message)
        self.mount(widget)
        if scroll or was_last_selected:
            self.scroll_end(animate=False, force=True)
        if was_last_selected:
            self.select(len(self._widgets()) - 1)
        return widget

    def _make_message_widget(self, message: Message) -> MessageWidget:
        reply_to = (
            self.engine.get_message(message.chat_id, message.reply_to)
            if message.reply_to
            else None
        )
        return MessageWidget(
            message,
            sender_name=self.engine.sender_name(message.sender_id),
            reply_to=reply_to,
            reply_to_name=self.engine.sender_name(reply_to.sender_id) if reply_to else None,
        )

    def _widgets(self) -> list[MessageWidget]:
        return [w for w in self.children if isinstance(w, MessageWidget)]

    # -- selection -----------------------------------------------------------

    def select(self, index: int) -> None:
        widgets = self._widgets()
        if not widgets:
            self._selected = -1
            return
        index = max(0, min(index, len(widgets) - 1))
        for i, w in enumerate(widgets):
            w.set_selected(i == index)
        self._selected = index
        self.scroll_to_widget(widgets[index], animate=False)

    def action_sel_next(self) -> None:
        self.select(self._selected + 1)

    def action_sel_prev(self) -> None:
        self.select(self._selected - 1)

    def action_sel_last(self) -> None:
        self.select(len(self._widgets()) - 1)

    def action_sel_first(self) -> None:
        self.select(0)

    def selected_message(self) -> Message | None:
        widgets = self._widgets()
        if 0 <= self._selected < len(widgets):
            return widgets[self._selected].message
        return None

    def action_app_reply(self) -> None:
        self.app.reply_selected()

    async def action_app_voice(self) -> None:
        await self.app.play_selected_voice()

    def action_app_find(self) -> None:
        self.app.action_search_in_chat()

    # -- in-chat search --------------------------------------------------------

    def update_hits(self, query: str) -> None:
        self.hits = []
        self.hit_index = -1
        q = query.strip().lower()
        for widget in self._widgets():
            widget.remove_class("-hit")
            widget.remove_class("-miss")
            if not q:
                continue
            if q in widget.message.text.lower():
                widget.add_class("-hit")
                self.hits.append(widget)
            else:
                widget.add_class("-miss")
        if self.hits:
            self._scroll_to_hit(0)

    def _scroll_to_hit(self, index: int) -> None:
        self.hit_index = index % len(self.hits)
        self.scroll_to_widget(self.hits[self.hit_index], animate=False, center=True)

    def action_next_hit(self) -> None:
        if self.hits:
            self._scroll_to_hit((self.hit_index + 1) % len(self.hits))

    def action_prev_hit(self) -> None:
        if self.hits:
            self._scroll_to_hit((self.hit_index - 1) % len(self.hits))
