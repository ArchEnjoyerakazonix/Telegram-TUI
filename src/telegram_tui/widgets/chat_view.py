"""Center panel: scrollable message history with code highlighting and replies."""

from __future__ import annotations

import datetime as dt
import re

from rich.syntax import Syntax as RichSyntax
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.widgets import Static

from ..models import Chat, Message

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
    """A single message: header, optional reply quote, text and code blocks."""

    DEFAULT_CSS = """
    MessageWidget { height: auto; margin: 0 1 1 0; }
    MessageWidget .msg-reply {
        border-left: thick $accent;
        padding-left: 1;
        text-style: italic;
    }
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
        from rich.markup import escape

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

        for part in self._split_text(self.message.text):
            if part["kind"] == "code":
                yield CodeBlock(part["text"].rstrip("\n"), part["lang"])
            else:
                yield Static(Text(part["text"]), markup=False)

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
    """Scrollable history of the currently open chat."""

    DEFAULT_CSS = """
    ChatView { height: 1fr; padding: 0 1; }
    """

    def __init__(self, engine) -> None:  # noqa: ANN001 - avoids circular import
        super().__init__(id="messages")
        self.engine = engine
        self.chat_id: int | None = None

    def show_chat(self, chat: Chat) -> None:
        self.chat_id = chat.id
        self.remove_children()
        for message in self.engine.history(chat.id):
            self.mount(self._make_message_widget(message))
        self.scroll_end(animate=False, force=True)

    def append_message(self, message: Message, scroll: bool = True) -> MessageWidget:
        widget = self._make_message_widget(message)
        self.mount(widget)
        if scroll:
            self.scroll_end(animate=False, force=True)
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
